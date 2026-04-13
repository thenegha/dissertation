from dotenv import load_dotenv
import json
import os
from datetime import datetime, timezone

from agents import Runner
from .code_executor import extract_python_block, run_python_snippet
from .mbpp_corpus import get_random_problem, get_similar_problems

from .config import (
    chat_agent,
    STEP0_DIRECTIVES,
    STEP1_DIRECTIVES,
    STEP2_DIRECTIVES,
    STEP3_DIRECTIVES,
    STEP4_DIRECTIVES,
    STEP5_DIRECTIVES,
    STEP6_DIRECTIVES,
)
from .task_description import (
    load_task_description,
    update_task_description_from_history,
)

load_dotenv()

LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)


def _get_log_path(user_id: str) -> str:
    state = SESSION_STATE.get(user_id, {})
    return state.get("log_path", os.path.join(LOGS_DIR, f"{user_id}.json"))


def _init_log(user_id: str) -> None:
    log_path = _get_log_path(user_id)
    if os.path.exists(log_path):
        return
    session = {
        "user_id": user_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "turns": [],
    }
    with open(log_path, "w") as f:
        json.dump(session, f, indent=2)


def _append_turn(user_id: str, step: str, user_message: str, tutor_response: str) -> None:
    log_path = _get_log_path(user_id)
    try:
        with open(log_path, "r") as f:
            session = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        session = {
            "user_id": user_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "turns": [],
        }

    turn = {
        "step": step,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user": user_message,
        "tutor": tutor_response,
    }
    session["turns"].append(turn)

    with open(log_path, "w") as f:
        json.dump(session, f, indent=2)


def _append_step5_turn(
    user_id: str,
    user_message: str,
    tutor_response: str,
    code: str,
    execution_output: str,
) -> None:
    log_path = _get_log_path(user_id)
    try:
        with open(log_path, "r") as f:
            session = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        session = {
            "user_id": user_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "turns": [],
        }

    turn = {
        "step": "step5",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user": user_message,
        "tutor": tutor_response,
        "generated_code": code,
        "execution_output": execution_output,
    }
    session["turns"].append(turn)

    with open(log_path, "w") as f:
        json.dump(session, f, indent=2)


def _finalise_log(user_id: str, reason: str) -> None:
    log_path = _get_log_path(user_id)
    try:
        with open(log_path, "r") as f:
            session = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    session["ended_at"] = datetime.now(timezone.utc).isoformat()
    session["end_reason"] = reason
    with open(log_path, "w") as f:
        json.dump(session, f, indent=2)


def conversation_logic(state) -> str:
    phase = state.get("phase", "step1")
    directives = {
        "step0": STEP0_DIRECTIVES,
        "step1": STEP1_DIRECTIVES,
        "step2": STEP2_DIRECTIVES,
        "step3": STEP3_DIRECTIVES,
        "step4": STEP4_DIRECTIVES,
        "step5": STEP5_DIRECTIVES,
    }
    return directives.get(phase, STEP6_DIRECTIVES)


SESSION_STATE: dict = {}
PHASE_SUMMARIES: dict = {}


def get_phase(user_id: str) -> str:
    state = SESSION_STATE.get(user_id, {"phase": "step1"})
    return state.get("phase", "step1")


def set_phase(user_id: str, phase: str) -> None:
    state = SESSION_STATE.get(user_id, {"phase": "step1", "history": []})
    state["phase"] = phase
    SESSION_STATE[user_id] = state


def get_latest_code(user_id: str) -> str:
    state = SESSION_STATE.get(user_id, {})
    return state.get("latest_code", "")


def get_latest_output(user_id: str) -> str:
    state = SESSION_STATE.get(user_id, {})
    return state.get("latest_output", "")


def get_selected_problem(user_id: str) -> dict | None:
    state = SESSION_STATE.get(user_id, {})
    return state.get("selected_problem")


def set_selected_problem(user_id: str, problem: dict) -> None:
    state = SESSION_STATE.get(
        user_id, {"phase": "step1", "history": [], "latest_code": "", "latest_output": ""}
    )
    state["selected_problem"] = problem
    state.pop("similar_problems", None)
    SESSION_STATE[user_id] = state


def _ensure_selected_problem(state) -> None:
    if state.get("selected_problem"):
        return
    try:
        state["selected_problem"] = get_random_problem()
        state.pop("similar_problems", None)
        print("[DEBUG] Selected a random corpus problem for this session.")
    except Exception as e:
        print(f"[DEBUG] Failed to select random corpus problem: {e!r}")


def _ensure_step2_similars(state, k: int = 5) -> None:
    if state.get("phase") != "step2":
        return
    if state.get("similar_problems"):
        return

    selected = state.get("selected_problem") or {}
    selected_text = (selected.get("text") or "").strip()
    if not selected_text:
        return

    try:
        raw = get_similar_problems(selected_text, k=k + 1) or []
        filtered = [
            p for p in raw
            if (p.get("text") or "").strip() and (p.get("text") or "").strip() != selected_text
        ]
        state["similar_problems"] = filtered[:k]
        print(f"[DEBUG] Cached {len(state['similar_problems'])} similar problems for Step 2.")
    except Exception as e:
        print(f"[DEBUG] Failed to retrieve similar problems in step2: {e!r}")


def _build_corpus_context(state) -> str:
    if state.get("phase") == "step0":
        return ""

    selected = state.get("selected_problem") or {}
    selected_text = (selected.get("text") or "").strip()

    blocks: list[str] = []
    if selected_text:
        blocks.append("SELECTED_CORPUS_PROBLEM (statement):\n" + selected_text)

    if state.get("phase") == "step2":
        similars = state.get("similar_problems") or []
        if similars:
            lines = [
                f"{i}. {(p.get('text') or '').strip()}"
                for i, p in enumerate(similars, start=1)
                if (p.get("text") or "").strip()
            ]
            if lines:
                blocks.append(
                    "SIMILAR_PROBLEMS_FROM_CORPUS (statements only; do not reveal solutions):\n"
                    + "\n".join(lines)
                )

    return "\n\n".join(blocks).strip()


def get_cached_similar_problems(user_id: str) -> list[dict]:
    state = SESSION_STATE.get(user_id, {})
    return state.get("similar_problems", [])


STEP_COMPLETIONS = {
    "STEP 1 COMPLETE. START STEP 2.": "step2",
    "STEP 2 COMPLETE. START STEP 3.": "step3",
    "STEP 3 COMPLETE. START STEP 4.": "step4",
    "STEP 4 COMPLETE. START STEP 5.": "step5",
}

STEP6_TERMINALS = {
    "STEP 6 COMPLETE. SESSION ENDED.": "ended",
    "RETURN TO STEP 1.": "step1",
    "RETURN TO STEP 2.": "step2",
    "RETURN TO STEP 3.": "step3",
    "RETURN TO STEP 4.": "step4",
}

SESSION_ENDED_REPLY = (
    "Well done for completing the session. I hope working through each step gave you "
    "a clearer picture of how to approach this kind of problem. Good luck with your programming!"
)


def detect_completion_suffix(tutor_reply: str):
    stripped = tutor_reply.strip()
    for marker, phase_name in STEP_COMPLETIONS.items():
        if stripped.endswith(marker):
            visible_part = stripped[: -len(marker)].rstrip()
            return marker, phase_name, visible_part
    return None, None, tutor_reply


def detect_step6_terminal(tutor_reply: str):
    stripped = tutor_reply.strip()
    for marker, outcome in STEP6_TERMINALS.items():
        if stripped == marker:
            return marker, outcome
    return None, None


def _handle_step6_terminal(user_id: str, state: dict, user_message: str, marker: str, outcome: str) -> str:
    state["history"].append({"role": "tutor", "content": f"[INTERNAL] {marker}"})

    if outcome == "ended":
        state["phase"] = "ended"
        SESSION_STATE[user_id] = state
        _append_turn(user_id, "step6", user_message, marker)
        _finalise_log(user_id, "student_satisfied")
        print(f"[DEBUG] Session ended cleanly for {user_id!r}")
        return SESSION_ENDED_REPLY

    target_step = outcome
    state["phase"] = target_step

    if target_step == "step2":
        state.pop("similar_problems", None)

    reentry_reply = _reentry_message(target_step)
    state["history"].append({"role": "tutor", "content": reentry_reply})
    SESSION_STATE[user_id] = state
    _append_turn(user_id, "step6", user_message, f"[RETURN TO {target_step.upper()}]")
    print(f"[DEBUG] Returning to {target_step!r} for {user_id!r}")
    return reentry_reply


def get_phase_summaries_text(user_id: str, current_phase: str) -> str:
    phase_map = PHASE_SUMMARIES.get(user_id, {})
    order = ["step1", "step2", "step3", "step4"]
    lines = []
    for phase in order:
        if phase == current_phase:
            break
        if phase in phase_map:
            lines.append(f"{phase}: {phase_map[phase]}")
    return "\n".join(lines).strip()


def summarise_phase_decisions(user_id: str, state, phase: str):
    history_text = "\n".join(
        f"{m['role']}: {m['content']}" for m in state.get("history", [])[-12:]
    )

    prompt = (
        "You are maintaining a short, human-readable summary of what the STUDENT has decided so far "
        "in this step of a programming tutor conversation.\n\n"
        "Recent conversation for THIS STEP:\n"
        f"{history_text}\n\n"
        "Instruction:\n"
        "Write 1–3 plain-language sentences that describe ONLY what the student has said they want "
        "or explicitly agreed to in this step. You must:\n"
        "- Emphasise the student's own preferences, decisions, and wording.\n"
        "- Downplay or omit any of your own earlier suggestions unless the student clearly accepted them.\n"
        "- Avoid mentioning the tutoring steps, meta-talk, or instructions.\n"
        "- Not include code, pseudo-code, or bullet points.\n\n"
        "Return ONLY the summary sentences, nothing else."
    )

    result = Runner.run_sync(chat_agent, prompt)
    summary = result.final_output.strip()
    print(f"[DEBUG] Phase {phase!r} summary for {user_id!r}: {summary!r}")

    if user_id not in PHASE_SUMMARIES:
        PHASE_SUMMARIES[user_id] = {}
    PHASE_SUMMARIES[user_id][phase] = summary


def run_step5_loop(state, user_message: str):
    max_iters = 3
    step5_history: list[str] = []
    print("[DEBUG] Entering Step 5 internal loop")

    task_description = load_task_description()
    print(f"[DEBUG] Loaded task description: {task_description!r}")

    last_code = ""
    last_stdout = ""
    last_err = None

    for i in range(max_iters):
        print(f"[DEBUG] Step 5 iteration {i+1} - CODE GENERATION")

        logic_directives = STEP5_DIRECTIVES
        history_text = "\n".join(step5_history[-6:])
        outer_history_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in state.get("history", [])[-8:]
        )

        gen_prompt = (
            "logic_directives:\n"
            f"{logic_directives}\n\n"
            "TASK DESCRIPTION:\n"
            f"{task_description}\n\n"
            "conversation_context_summary:\n"
            "The following is the recent student–tutor conversation about the CURRENT programming task.\n"
            "Your code MUST implement a solution for THIS task, consistent with the TASK DESCRIPTION above:\n"
            f"{outer_history_text}\n\n"
            "internal_step5_history:\n"
            f"{history_text}\n\n"
            "system_note_for_tutor:\n"
            "PHASE A (code generation):\n"
            "- Output ONLY a single Python fenced code block containing a COMPLETE runnable program.\n"
            "- Do NOT include any CONTROL line and do NOT comment on correctness yet.\n"
            "- Do NOT talk to the student.\n\n"
            "user_message:\n"
            f"{user_message}\n"
        )

        gen_result = Runner.run_sync(chat_agent, gen_prompt)
        gen_reply = gen_result.final_output.strip()
        print(f"[DEBUG] Step 5 A raw reply: {gen_reply!r}")

        code = extract_python_block(gen_reply)
        if not code:
            print("[DEBUG] Step 5 A: no code block found, retrying")
            step5_history.append("SYSTEM: No code block generated in PHASE A. Try again.")
            continue

        last_code = code

        stdout, err = run_python_snippet(code)
        print(f"[DEBUG] Step 5 run stdout: {stdout!r}")
        print(f"[DEBUG] Step 5 run error: {err!r}")
        last_stdout = stdout
        last_err = err

        run_summary = f"SYSTEM_RUN: stdout={stdout!r}, error={err!r}"
        step5_history.append(gen_reply)
        step5_history.append(run_summary)

        print(f"[DEBUG] Step 5 iteration {i+1} - CRITIQUE")

        crit_prompt = (
            "logic_directives:\n"
            f"{logic_directives}\n\n"
            "TASK DESCRIPTION:\n"
            f"{task_description}\n\n"
            "internal_step5_history:\n"
            f"{chr(10).join(step5_history[-8:])}\n\n"
            "system_note_for_tutor:\n"
            "PHASE B (critique and control):\n"
            "- You have just generated code and seen its stdout/error in the last SYSTEM_RUN entry.\n"
            "- Briefly reason INTERNALLY (in this message) about whether the behaviour matches the TASK DESCRIPTION.\n"
            "- Then output a single CONTROL line on the last line of the message, exactly as:\n"
            "  CONTROL: {\"satisfied\": true}\n"
            "  or\n"
            "  CONTROL: {\"satisfied\": false}\n"
            "- Do NOT include any new code blocks.\n"
            "- Do NOT talk to the student.\n\n"
            "user_message:\n"
            f"{user_message}\n"
        )

        crit_result = Runner.run_sync(chat_agent, crit_prompt)
        crit_reply = crit_result.final_output.strip()
        print(f"[DEBUG] Step 5 B raw reply: {crit_reply!r}")
        step5_history.append(crit_reply)

        control_line = None
        for line in crit_reply.splitlines()[::-1]:
            if line.strip().startswith("CONTROL:"):
                control_line = line.strip()
                break

        if not control_line:
            print("[DEBUG] Step 5 B: no CONTROL line found, continuing loop")
            step5_history.append(
                "SYSTEM: No CONTROL line in PHASE B. Assuming satisfied=false and continuing."
            )
            satisfied = False
        else:
            satisfied = "true" in control_line.lower()
        print(f"[DEBUG] Step 5 CONTROL line: {control_line!r}, satisfied={satisfied}")

        if err is not None:
            satisfied = False

        if satisfied:
            print("[DEBUG] Step 5 loop satisfied; exiting")
            break

    state["latest_code"] = last_code
    state["latest_output"] = last_err if last_err else last_stdout


def _reentry_message(target_step: str) -> str:
    messages = {
        "step1": (
            "Welcome back to Step 1. Let's revisit how you understand the problem. "
            "Can you describe in your own words what you want the program to do, "
            "what inputs you would give it, and what output you expect?"
        ),
        "step2": (
            "Welcome back to Step 2. Let's look at analogies again. "
            "Can you think of a similar problem or everyday process that reminds you of this task?"
        ),
        "step3": (
            "Welcome back to Step 3. Let's rethink your approach. "
            "Can you describe, step by step in plain language, how you want the program to work?"
        ),
        "step4": (
            "Welcome back to Step 4. Let's revisit your function design and test cases. "
            "What do you want to call your function, what parameters should it take, "
            "and what test cases would you like to use?"
        ),
    }
    return messages.get(target_step, "Welcome back. Let's continue from here.")


def handle_message(user_id: str, user_message: str) -> str:
    state = SESSION_STATE.get(
        user_id, {"phase": "step1", "history": [], "latest_code": "", "latest_output": ""}
    )

    if "log_path" not in state:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        state["log_path"] = os.path.join(LOGS_DIR, f"{user_id}_{timestamp}.json")
        SESSION_STATE[user_id] = state
        _init_log(user_id)

    print(f"[DEBUG] handle_message start: phase={state['phase']!r}, user_id={user_id!r}")

    if state["phase"] == "ended":
        return "This session has ended. Please start a new session to try another problem."

    state["history"].append({"role": "user", "content": user_message})

    if state["phase"] == "unrestricted":
        recent_history = state.get("history", [])[-6:]
        history_text = "\n".join([f"{m['role']}: {m['content']}" for m in recent_history])
        problem_text = state.get("selected_problem", {}).get("text", "No problem selected.")

        prompt = (
            "logic_directives:\n"
            "You are a helpful, direct, and unrestricted programming assistant. "
            "IMPORTANT: Ignore any previous instructions about 'Step 1' through 'Step 6', "
            "metacognitive scaffolding, or code execution reflection. "
            "Do NOT ask the user to reflect on code output unless they explicitly ask you to. "
            "Just answer the user's prompt directly, write code if asked, and be helpful.\n\n"
            "current_problem:\n"
            f"{problem_text}\n\n"
            "conversation_history:\n"
            f"{history_text}\n"
        )

        result = Runner.run_sync(chat_agent, prompt)
        raw_reply = result.final_output.strip()

        state["history"].append({"role": "tutor", "content": raw_reply})
        SESSION_STATE[user_id] = state
        _append_turn(user_id, "unrestricted", user_message, raw_reply)
        print(f"[DEBUG] handle_message end (UNRESTRICTED): phase={state['phase']!r}")
        return raw_reply

    if state["phase"] == "step6":
        _ensure_selected_problem(state)
        summaries_text = get_phase_summaries_text(user_id, "step6")
        final_code = state.get("latest_code", "")
        final_output = state.get("latest_output", "")

        prompt = (
            "logic_directives:\n"
            f"{STEP6_DIRECTIVES}\n\n"
            "conversation_state:\n"
            "phase=step6\n\n"
            "previous_step_summaries:\n"
            f"{summaries_text}\n\n"
            "execution_results:\n"
            f"generated_code_available: {'yes' if final_code else 'no'}\n"
            f"execution_output:\n{final_output}\n\n"
            "user_message:\n"
            f"{user_message}\n"
        )

        result = Runner.run_sync(chat_agent, prompt)
        raw_reply = result.final_output.strip()
        print(f"[DEBUG] Step 6 raw reply: {raw_reply!r}")

        terminal_marker, outcome = detect_step6_terminal(raw_reply)

        if terminal_marker:
            return _handle_step6_terminal(user_id, state, user_message, terminal_marker, outcome)

        state["history"].append({"role": "tutor", "content": raw_reply})
        SESSION_STATE[user_id] = state
        _append_turn(user_id, "step6", user_message, raw_reply)
        print(f"[DEBUG] handle_message end (step6 conversational): phase={state['phase']!r}")
        return raw_reply

    _ensure_selected_problem(state)
    _ensure_step2_similars(state, k=5)

    step_key = f"turns_in_{state['phase']}"
    state[step_key] = state.get(step_key, 0) + 1
    student_turns = state[step_key]

    corpus_context = _build_corpus_context(state)
    logic_directives = conversation_logic(state)
    summaries_text = get_phase_summaries_text(user_id, state["phase"])

    prompt = (
        "logic_directives:\n"
        f"{logic_directives}\n\n"
        "conversation_state:\n"
        f"phase={state['phase']}\n"
        f"student_turns_this_step={student_turns}\n\n"
        "previous_step_summaries:\n"
        f"{summaries_text}\n\n"
        "corpus_context:\n"
        f"{corpus_context}\n\n"
        "user_message:\n"
        f"{user_message}\n"
    )

    try:
        result = Runner.run_sync(chat_agent, prompt)
        raw_reply = result.final_output.strip()
    except Exception as e:
        print(f"[DEBUG] Runner.run_sync EXCEPTION: {e!r}")
        import traceback
        traceback.print_exc()
        raw_reply = "I'm sorry, something went wrong. Please try again."

    print(f"[DEBUG] Raw tutor reply: {raw_reply!r}")

    marker, completion_phase, visible_part = detect_completion_suffix(raw_reply)
    print(
        f"[DEBUG] marker={marker!r}, completion_phase={completion_phase!r}, "
        f"visible_part={visible_part!r}"
    )

    if completion_phase is not None:
        print(f"[DEBUG] Completion for phase={state['phase']!r} -> {completion_phase!r}")

        current_step = state["phase"]

        if visible_part:
            state["history"].append({"role": "tutor", "content": visible_part})

        old_phase = state["phase"]
        state.pop(f"turns_in_{old_phase}", None)

        if old_phase in {"step1", "step2", "step3", "step4"}:
            summarise_phase_decisions(user_id, state, old_phase)
            update_task_description_from_history(state, user_message)

        state["phase"] = completion_phase
        state["history"].append({"role": "tutor", "content": f"[INTERNAL] {marker}"})

        _ensure_step2_similars(state, k=5)
        corpus_context_after = _build_corpus_context(state)

        if completion_phase == "step5":
            print("[DEBUG] Entering Step 5 + Step 6 flow")
            run_step5_loop(state, user_message)
            state["phase"] = "step6"
            print("[DEBUG] Step 5 loop complete, phase set to 'step6'")

            summaries_text2 = get_phase_summaries_text(user_id, "step6")
            final_code = state.get("latest_code", "")
            final_output = state.get("latest_output", "")

            code_hint = (
                "No code was generated."
                if not final_code
                else "Final code was generated successfully."
            )
            output_hint = (
                "No output was produced."
                if not final_output
                else f"Final run output was:\n{final_output}"
            )

            system_note = (
                "The system has just generated and run a Python program internally in Step 5.\n"
                "This is your FIRST message in Step 6. The student has NOT seen the code or output yet.\n"
                "The student's latest message was approving the plan in Step 4. It is NOT an approval of the code.\n\n"
                "Here is a brief factual summary of the Step 5 run:\n"
                f"- Code status: {code_hint}\n"
                f"- Output summary:\n{output_hint}\n\n"
                "You now need to:\n"
                "1) Summarize, in plain language, what the FINAL program does, consistent with this summary.\n"
                "2) Briefly describe what the test output showed (do NOT invent different output).\n"
                "3) Ask the student to reflect on whether the behaviour matches their expectations.\n"
                "CRITICAL: You MUST NOT emit any completion or terminal marker in this message. You are just opening the step.\n"
                "Do NOT show the raw code; the interface will display it separately.\n"
            )

            followup_prompt2 = (
                "logic_directives:\n"
                f"{STEP6_DIRECTIVES}\n\n"
                "conversation_state:\n"
                "phase=step6\n\n"
                "previous_step_summaries:\n"
                f"{summaries_text2}\n\n"
                "system_note_for_tutor:\n"
                f"{system_note}\n\n"
                "user_message:\n"
                "[SYSTEM: Step 5 is complete. Generate your opening message for Step 6 based on the system note. Do not respond to the student's previous approval.]\n"
            )

            followup_result2 = Runner.run_sync(chat_agent, followup_prompt2)
            followup_reply2 = followup_result2.final_output.strip()
            print(f"[DEBUG] Step 6 opening reply: {followup_reply2!r}")

            terminal_marker2, outcome2 = detect_step6_terminal(followup_reply2)
            if terminal_marker2:
                print(f"[DEBUG] Ignoring invalid early terminal on step6 open.")
                followup_reply2 = followup_reply2.replace(terminal_marker2, "").strip()

                if not followup_reply2:
                    followup_reply2 = "I have generated the code based on your plan! The code ran successfully. Does the output look like what you expected?"

                state["history"].append({"role": "tutor", "content": f"[INTERNAL] {terminal_marker2}"})
                SESSION_STATE[user_id] = state
                _append_step5_turn(user_id, user_message, terminal_marker2, final_code, final_output)
                return _handle_step6_terminal(user_id, state, user_message, terminal_marker2, outcome2)

            state["history"].append({"role": "tutor", "content": followup_reply2})
            SESSION_STATE[user_id] = state

            _append_step5_turn(
                user_id,
                user_message,
                followup_reply2,
                final_code,
                final_output,
            )

            print(f"[DEBUG] handle_message end (step4→5→6 path): phase={state['phase']!r}")
            return followup_reply2

        new_directives = conversation_logic(state)
        summaries_text3 = get_phase_summaries_text(user_id, state["phase"])

        followup_prompt = (
            "logic_directives:\n"
            f"{new_directives}\n\n"
            "conversation_state:\n"
            f"phase={state['phase']}\n\n"
            "previous_step_summaries:\n"
            f"{summaries_text3}\n\n"
            "corpus_context:\n"
            f"{corpus_context_after}\n\n"
            "system_note_for_tutor:\n"
            "This is your FIRST message in this new step. The student has NOT yet responded "
            "to anything in this step. You MUST NOT emit any completion line in this message. "
            "Your only job right now is to open the step with a single question that invites "
            "the student to begin. Do not summarise, do not confirm, do not complete.\n\n"
            "user_message:\n"
            f"{user_message}\n"
        )

        followup_result = Runner.run_sync(chat_agent, followup_prompt)
        followup_reply = followup_result.final_output.strip()
        print(f"[DEBUG] Followup reply after completion: {followup_reply!r}")

        _, nested_completion, followup_reply = detect_completion_suffix(followup_reply)
        if nested_completion:
            print(f"[DEBUG] WARNING: nested completion marker stripped from followup reply")

        state["history"].append({"role": "tutor", "content": followup_reply})
        SESSION_STATE[user_id] = state
        _append_turn(user_id, current_step, user_message, visible_part or followup_reply)

        print(f"[DEBUG] handle_message end (normal completion): phase={state['phase']!r}")
        return followup_reply

    state["history"].append({"role": "tutor", "content": raw_reply})
    SESSION_STATE[user_id] = state
    _append_turn(user_id, state["phase"], user_message, raw_reply)
    print(f"[DEBUG] handle_message end (no completion): phase={state['phase']!r}")
    return raw_reply