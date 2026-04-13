import streamlit as st

from agent import (
    handle_message,
    get_phase,
    set_phase,
    get_latest_code,
    get_latest_output,
    get_selected_problem,
    set_selected_problem,
    get_cached_similar_problems,
)

from tutor_agent.mbpp_corpus import get_random_problem, get_demo_problem

# -------------------------
# Streamlit page config
# -------------------------
st.set_page_config(
    page_title="Metacognitive Programming Tutor",
    page_icon="🧠",
    layout="wide",
)

st.title("Metacognitive Programming Tutor")
st.caption("Vibe coding + meta-cognitive scaffolding for programming tasks.")

# -------------------------
# Session state guards
# -------------------------
if "user_id" not in st.session_state:
    st.session_state.user_id = "streamlit-user"

if "history" not in st.session_state:
    st.session_state.history = []
    st.session_state._history_init_count = st.session_state.get("_history_init_count", 0) + 1

if "initialized" not in st.session_state:
    st.session_state.initialized = False

if "problem_text" not in st.session_state:
    st.session_state.problem_text = ""

if "session_ended" not in st.session_state:
    st.session_state.session_ended = False

# -------------------------
# Kickoff BEFORE any backend calls
# -------------------------
if not st.session_state.initialized:
    try:
        first_reply = handle_message(
            st.session_state.user_id,
            "Begin Step 1 by asking the student to restate the task in their own words.",
        )
    except Exception as e:
        st.error(f"KICKOFF EXCEPTION: {e!r}")
        import traceback
        st.code(traceback.format_exc())
        first_reply = None

    if first_reply:
        st.session_state.history.append({"role": "tutor", "content": first_reply})

    st.session_state.initialized = True

# -------------------------
# Ensure selected problem exists (backend is source of truth)
# -------------------------
def ensure_problem_selected() -> None:
    backend_problem = get_selected_problem(st.session_state.user_id)

    if not backend_problem:
        problem = get_random_problem()
        set_selected_problem(st.session_state.user_id, problem)
        backend_problem = problem

    st.session_state.problem_text = (backend_problem.get("text") or "").strip()

ensure_problem_selected()

# -------------------------
# Sidebar
# -------------------------
with st.sidebar:
    st.header("About this tutor")
    st.write(
        "This tutor guides you through meta-cognitive steps such as "
        "reinterpreting the problem, searching for analogies, exploring "
        "solutions, implementing code, and reflecting on your process."
    )
    st.write(
        "In Step 5 it can generate Python code and run it; the latest code "
        "and console output appear in the left-bottom panel."
    )

    st.markdown("---")
    st.subheader("Controls & Debug")

    current_phase = get_phase(st.session_state.user_id)
    is_unrestricted = current_phase == "unrestricted"

    unrestricted_mode = st.toggle(
        "Enable Unrestricted AI Chat (Bypass Scaffolding)", value=is_unrestricted
    )

    if unrestricted_mode and not is_unrestricted:
        set_phase(st.session_state.user_id, "unrestricted")
        st.session_state.history = []
        st.session_state.initialized = False
        st.session_state.session_ended = False
        st.rerun()
    elif not unrestricted_mode and is_unrestricted:
        set_phase(st.session_state.user_id, "step1")
        st.session_state.history = []
        st.session_state.initialized = False
        st.session_state.session_ended = False
        st.rerun()

    if unrestricted_mode:
        st.warning(
            "⚠️ **Unrestricted Mode Active:** Metacognitive scaffolding, guardrails, "
            "and automated code execution are disabled. You are talking directly to the raw LLM."
        )

    st.markdown(f"**Current phase:** `{current_phase}`")

    phase_options = ["unrestricted", "step1", "step2", "step3", "step4", "step5", "step6"]
    selected_phase = st.selectbox(
        "Set phase manually:",
        options=phase_options,
        index=phase_options.index(current_phase) if current_phase in phase_options else 1,
        key="phase_select",
    )

    if st.button("Apply phase"):
        set_phase(st.session_state.user_id, selected_phase)
        st.success(f"Phase set to {selected_phase}")
        st.rerun()

    st.markdown("---")
    if st.button("New random problem"):
        problem = get_random_problem()
        set_selected_problem(st.session_state.user_id, problem)
        st.session_state.problem_text = (problem.get("text") or "").strip()
        st.session_state.history = []
        st.session_state.initialized = False
        st.session_state.session_ended = False
        st.rerun()

    if st.button("Demo problem"):
        problem = get_demo_problem()
        set_selected_problem(st.session_state.user_id, problem)
        st.session_state.problem_text = (problem.get("text") or "").strip()
        st.session_state.history = []
        st.session_state.initialized = False
        st.session_state.session_ended = False
        st.rerun()

    st.markdown("---")
    with st.expander("Debug: Similar problems (cached)", expanded=False):
        st.caption(
            "Shows the problems cached in backend session state during Step 2 retrieval."
        )

        selected = get_selected_problem(st.session_state.user_id)
        if not selected or not (selected.get("text") or "").strip():
            st.info("No selected problem found yet.")
        else:
            st.markdown("**Selected problem (statement):**")
            st.write(selected["text"])

        cached = get_cached_similar_problems(st.session_state.user_id) or []

        if not cached:
            st.info(
                "No cached similar problems yet. They are typically cached when you enter Step 2."
            )
        else:
            st.markdown(f"**Cached similar problems:** {len(cached)}")
            for i, p in enumerate(cached, start=1):
                st.markdown(f"{i}. {(p.get('text') or '').strip()}")

            show_raw = st.checkbox(
                "Show raw cached objects (distance/code, etc.)",
                value=False,
                key="show_raw_cached_similars",
            )
            if show_raw:
                st.json(cached, expanded=False)

# -------------------------
# Main layout
# -------------------------
left_col, right_col = st.columns(2)

with left_col:
    top_left, bottom_left = st.container(), st.container()

    with top_left:
        st.subheader("Problem")
        st.write(st.session_state.problem_text)

    with bottom_left:
        st.subheader("Generated code & console output")

        code = get_latest_code(st.session_state.user_id)
        output = get_latest_output(st.session_state.user_id)

        if code:
            with st.expander("View generated code", expanded=False):
                st.code(code, language="python")
        else:
            if unrestricted_mode:
                st.info(
                    "Unrestricted mode active. Code will only appear in the chat window, not here."
                )
            else:
                st.info("No generated code yet. This panel will fill during Step 5.")

        if output:
            st.markdown("**Console output:**")
            st.code(output)
        else:
            st.info("No console output yet.")

with right_col:
    st.subheader("Conversation")

    for message in st.session_state.history:
        role = message.get("role")
        content = message.get("content")

        if not content:
            continue

        if role == "user":
            with st.chat_message("user"):
                st.markdown(content)
        else:
            with st.chat_message("assistant"):
                st.markdown(content)

    st.markdown("---")

    if st.session_state.session_ended:
        st.success("Session complete. Start a new problem from the sidebar whenever you are ready.")
    else:
        user_input = st.chat_input("Type your message and press Enter...")

        if user_input:
            text = user_input.strip()
            if text:
                st.session_state.history.append({"role": "user", "content": text})

                reply = handle_message(st.session_state.user_id, text)

                if reply:
                    st.session_state.history.append({"role": "tutor", "content": reply})

                if get_phase(st.session_state.user_id) == "ended":
                    st.session_state.session_ended = True

                st.rerun()
