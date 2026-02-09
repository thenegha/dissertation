from dotenv import load_dotenv

from agents import Runner
from .code_executor import extract_python_block, run_python_snippet

from .config import (
    chat_agent,
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


def conversation_logic(state) -> str:
    phase = state.get("phase", "step1")
    if phase == "step1":
        return STEP1_DIRECTIVES
    elif phase == "step2":
        return STEP2_DIRECTIVES
    elif phase == "step3":
        return STEP3_DIRECTIVES
    elif phase == "step4":
        return STEP4_DIRECTIVES
    elif phase == "step5":
        return STEP5_DIRECTIVES
    else:
        return STEP6_DIRECTIVES


SESSION_STATE: dict = {}
PHASE_SUMMARIES: dict = {}  # key: user_id, value: dict[phase_name, summary_text]


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


STEP_COMPLETIONS = {
    "STEP 1 COMPLETE. START STEP 2.": "step2",
    "STEP 2 COMPLETE. START STEP 3.": "step3",
    "STEP 3 COMPLETE. START STEP 4.": "step4",
    "STEP 4 COMPLETE. START STEP 5.": "step5",
}


def detect_completion_suffix(tutor_reply: str):
    stripped = tutor_reply.strip()
    for marker, phase_name in STEP_COMPLETIONS.items():
        if stripped.endswith(marker):
            visible_part = stripped[: -len(marker)].rstrip()
            return marker, phase_name, visible_part
    return None, None, tutor_reply


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
            f"{'\n'.join(step5_history[-8:])}\n\n"
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
    if last_err:
        state["latest_output"] = last_err
    else:
        state["latest_output"] = last_stdout


def handle_message(user_id: str, user_message: str) -> str:
    state = SESSION_STATE.get(
        user_id, {"phase": "step1", "history": [], "latest_code": "", "latest_output": ""}
    )
    print(f"[DEBUG] handle_message start: phase={state['phase']!r}, user_id={user_id!r}")
    state["history"].append({"role": "user", "content": user_message})

    logic_directives = conversation_logic(state)
    summaries_text = get_phase_summaries_text(user_id, state["phase"])

    prompt = (
        "logic_directives:\n"
        f"{logic_directives}\n\n"
        "conversation_state:\n"
        f"phase={state['phase']}\n\n"
        "previous_step_summaries:\n"
        f"{summaries_text}\n\n"
        "user_message:\n"
        f"{user_message}\n"
    )

    result = Runner.run_sync(chat_agent, prompt)
    raw_reply = result.final_output.strip()
    print(f"[DEBUG] Raw tutor reply: {raw_reply!r}")

    marker, completion_phase, visible_part = detect_completion_suffix(raw_reply)
    print(
        f"[DEBUG] marker={marker!r}, completion_phase={completion_phase!r}, "
        f"visible_part={visible_part!r}"
    )

    if completion_phase is not None:
        print(f"[DEBUG] Completion for phase={state['phase']!r} -> {completion_phase!r}")

        if visible_part:
            state["history"].append({"role": "tutor", "content": visible_part})

        old_phase = state["phase"]

        if old_phase in {"step1", "step2", "step3", "step4"}:
            summarise_phase_decisions(user_id, state, old_phase)
            update_task_description_from_history(state, user_message)

        state["phase"] = completion_phase
        state["history"].append({"role": "tutor", "content": f"[INTERNAL] {marker}"})

        if completion_phase == "step5":
            print("[DEBUG] Entering Step 5 + Step 6 flow")
            run_step5_loop(state, user_message)
            state["phase"] = "step6"
            print("[DEBUG] Step 5 loop complete, phase set to 'step6'")

            new_directives2 = conversation_logic(state)
            summaries_text2 = get_phase_summaries_text(user_id, state["phase"])

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
                "Here is a brief factual summary of that run:\n"
                f"- Code status: {code_hint}\n"
                f"- Output summary:\n{output_hint}\n\n"
                "You now need to:\n"
                "1) Summarize, in plain language, what the FINAL program does, consistent with this summary.\n"
                "2) Briefly describe what the test output showed (do NOT invent different output).\n"
                "3) Ask the student to reflect on whether the behaviour matches their expectations.\n"
                "Do NOT show the raw code; the interface will display it separately.\n"
            )

            followup_prompt2 = (
                "logic_directives:\n"
                f"{new_directives2}\n\n"
                "conversation_state:\n"
                f"phase={state['phase']}\n\n"
                "previous_step_summaries:\n"
                f"{summaries_text2}\n\n"
                "system_note_for_tutor:\n"
                f"{system_note}\n\n"
                "user_message:\n"
                f"{user_message}\n"
            )

            followup_result2 = Runner.run_sync(chat_agent, followup_prompt2)
            followup_reply2 = followup_result2.final_output.strip()
            print(f"[DEBUG] Step 6 explanation reply: {followup_reply2!r}")

            state["history"].append({"role": "tutor", "content": followup_reply2})
            SESSION_STATE[user_id] = state
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
            "system_note_for_tutor:\n"
            "The previous message completed the last step. You are now in the new step.\n"
            "Begin this step with a brief explanation of what you will focus on next,\n"
            "then continue the conversation with the student.\n\n"
            "user_message:\n"
            f"{user_message}\n"
        )

        followup_result = Runner.run_sync(chat_agent, followup_prompt)
        followup_reply = followup_result.final_output.strip()
        print(f"[DEBUG] Followup reply after completion: {followup_reply!r}")

        state["history"].append({"role": "tutor", "content": followup_reply})
        SESSION_STATE[user_id] = state
        print(f"[DEBUG] handle_message end (normal completion): phase={state['phase']!r}")
        return followup_reply

    state["history"].append({"role": "tutor", "content": raw_reply})
    SESSION_STATE[user_id] = state
    print(f"[DEBUG] handle_message end (no completion): phase={state['phase']!r}")
    return raw_reply
