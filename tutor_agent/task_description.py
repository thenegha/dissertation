from agents import Runner
from .config import chat_agent


def load_task_description(path: str = "task_description.txt") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"[DEBUG] task_description.txt not found at {path}")
        return ""
    except Exception as e:
        print(f"[DEBUG] Error reading task_description.txt: {e!r}")
        return ""


def save_task_description(text: str, path: str = "task_description.txt", mode: str = "w") -> None:
    try:
        with open(path, mode, encoding="utf-8") as f:
            f.write(text.strip() + "\n")
        print(f"[DEBUG] task_description.txt updated with mode={mode!r}.")
    except Exception as e:
        print(f"[DEBUG] Error writing task_description.txt: {e!r}")


def update_task_description_from_history(state, user_message: str):
    history_text = "\n".join(
        f"{m['role']}: {m['content']}" for m in state.get("history", [])[-12:]
    )

    phase = state.get("phase", "step1")

    prompt = (
        "You are maintaining an internal TASK DESCRIPTION that must reflect ONLY what the student has "
        "asked for or explicitly agreed to so far.\n\n"
        "Recent conversation:\n"
        f"{history_text}\n\n"
        "Instruction:\n"
        "Write 1–3 plain-language sentences that describe the programming task using ONLY:\n"
        "- What the student has said about the overall goal of the program.\n"
        "- What inputs they want to provide.\n"
        "- What outputs they expect to see.\n"
        "You MUST NOT:\n"
        "- Introduce or name any functions, parameters, or helper components that the student has not named.\n"
        "- Add edge cases or behaviours the student has not mentioned.\n"
        "- Mention code, implementation details, or specific Python constructs.\n\n"
        "If the current phase is Step 1, limit yourself to a basic description of inputs and outputs.\n"
        "If the current phase is later (Step 2–4), you may add only new details that the student has "
        "explicitly agreed to in those phases.\n\n"
        "Return ONLY the sentences that should be added to the TASK DESCRIPTION file, nothing else."
    )

    result = Runner.run_sync(chat_agent, prompt)
    desc_fragment = result.final_output.strip()
    print(f"[DEBUG] New task description fragment: {desc_fragment!r}")

    if phase == "step1":
        save_task_description(desc_fragment, mode="w")
    else:
        save_task_description(desc_fragment, mode="a")
