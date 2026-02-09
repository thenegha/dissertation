import streamlit as st
from agent import (
    handle_message,
    get_phase,
    set_phase,
    get_latest_code,
    get_latest_output,
)

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
# Session state
# -------------------------
if "user_id" not in st.session_state:
    st.session_state.user_id = "streamlit-user"

if "history" not in st.session_state:
    st.session_state.history = []

if "initialized" not in st.session_state:
    st.session_state.initialized = False

if "problem_text" not in st.session_state:
    # Fixed reference problem (read-only)
    st.session_state.problem_text = (
        "A robot moves on a grid with commands U, D, L, R "
        "and we must output its final position."
    )

# -------------------------
# Kickoff tutor message (once)
# -------------------------
if not st.session_state.initialized:
    kickoff_message = (
        "The student is about to work on this problem:\n"
        f"{st.session_state.problem_text}\n"
        "Begin Step 1 by asking the student to restate the task in their own words."
    )

    first_reply = handle_message(st.session_state.user_id, kickoff_message)

    st.session_state.history.append(
        {"role": "tutor", "content": first_reply}
    )

    st.session_state.initialized = True

# -------------------------
# Sidebar info + debug
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
    st.subheader("Debug: Stage")

    current_phase = get_phase(st.session_state.user_id)
    st.markdown(f"**Current phase:** `{current_phase}`")

    phase_options = ["step1", "step2", "step3", "step4", "step5", "step6"]
    selected_phase = st.selectbox(
        "Set phase (debug):",
        options=phase_options,
        index=phase_options.index(current_phase)
        if current_phase in phase_options
        else 0,
        key="phase_select",
    )

    if st.button("Apply phase (debug)"):
        set_phase(st.session_state.user_id, selected_phase)
        st.success(f"Phase set to {selected_phase}")
        st.rerun()

# -------------------------
# Main layout: left / right
# -------------------------
left_col, right_col = st.columns(2)

# ----- LEFT: split vertically (problem top, code bottom) -----
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
            st.markdown("**Latest code (read-only):**")
            st.code(code, language="python")
        else:
            st.info("No generated code yet. This panel will fill during Step 5.")

        if output:
            st.markdown("**Console output:**")
            st.code(output)
        else:
            st.info("No console output yet.")

# ----- RIGHT: Conversation / chat -----
with right_col:
    st.subheader("Conversation")

    for message in st.session_state.history:
        role = message["role"]
        content = message["content"]

        if role == "user":
            st.markdown(f"**You:** {content}")
        else:
            st.markdown(f"**Tutor:** {content}")

    st.markdown("---")

    # User input (Enter to send)
    user_input = st.chat_input("Type your message and press Enter...")

    if user_input:
        text = user_input.strip()
        if text:
            # Add user message
            st.session_state.history.append(
                {"role": "user", "content": text}
            )

            # Send to backend
            reply = handle_message(st.session_state.user_id, text)

            # Add tutor reply
            st.session_state.history.append(
                {"role": "tutor", "content": reply}
            )

            # Rerun so new messages and updated code/output appear
            st.rerun()
