from tutor_agent.core import (
    handle_message,
    get_phase,
    set_phase,
    get_latest_code,
    get_latest_output,
    get_selected_problem,
    set_selected_problem,
    get_random_problem,
    get_cached_similar_problems
)

__all__ = [
    "handle_message",
    "get_phase",
    "set_phase",
    "get_latest_code",
    "get_latest_output",
    "get_selected_problem",
    "set_selected_problem",
    "get_random_problem",
    "get_cached_similar_problems"
]

if __name__ == "__main__":
    user_id = "demo-user"
    print("Metacognitive Tutor started. Type 'exit' to quit.")

    problem = get_random_problem()
    set_selected_problem(user_id, problem)

    system_kickoff = (
        "The student is about to work on this problem:\n"
        f"{problem.get('text','').strip()}\n"
        "Begin Step 1 by asking the student to restate the task in their own words."
    )

    reply = handle_message(user_id, system_kickoff)
    print("Tutor:", reply)

    while True:
        user_msg = input("You: ")
        if user_msg.strip().lower() in {"exit", "quit"}:
            print("Bye!")
            break
        reply = handle_message(user_id, user_msg)
        print("Tutor:", reply)
