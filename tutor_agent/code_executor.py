import re
import subprocess
import sys
from textwrap import dedent


def extract_python_block(text: str) -> str:
    """
    Extract the first Python fenced code block from a string.
    Returns the code as a string, or "" if none found.
    """
    # ```python ... ``` or ``` ... ```
    pattern = re.compile(
        r"```(?:python)?\s*(.*?)```",
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return ""
    code = match.group(1)
    return dedent(code).strip()


def run_python_snippet(code: str) -> tuple[str, str | None]:
    """
    Run a Python code snippet in a separate process and capture stdout and stderr.

    Returns:
        (stdout, error)
        - stdout: captured standard output as a string (may be "").
        - error:  None if the process exited with code 0,
                  otherwise a short string describing the error.
    """
    if not code.strip():
        return "", "No code to execute."

    try:
        # Run code in a separate Python process so that any top-level code
        # (including tests not guarded by if __name__ == '__main__') is executed.
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.strip() or f"Process exited with code {proc.returncode}"
            return stdout, err_msg

        return stdout, None
    except Exception as e:
        return "", f"Execution error: {e!r}"
