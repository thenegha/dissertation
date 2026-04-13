from __future__ import annotations


import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from dotenv import load_dotenv



load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parent.parent
dotenv_from_root = PROJECT_ROOT / ".env"
if dotenv_from_root.exists():
    load_dotenv(dotenv_from_root, override=False)


import chromadb
from chromadb.utils import embedding_functions
from datasets import load_dataset


PACKAGE_DIR = Path(__file__).resolve().parent
LOCAL_MBPP_PATH = PACKAGE_DIR / "sanitized-mbpp.json"


if not LOCAL_MBPP_PATH.exists():
    raise FileNotFoundError(
        f"Expected MBPP file at {LOCAL_MBPP_PATH} but it was not found."
    )


dataset = load_dataset(
    "json",
    data_files=str(LOCAL_MBPP_PATH),
)

_SPLIT = "train"
ds = dataset[_SPLIT]


def _pick_first_existing_key(example: dict, candidates: List[str]) -> str:
    for k in candidates:
        if k in example and example[k] is not None:
            return k
    raise KeyError(
        f"None of these keys exist in dataset example: {candidates}. "
        f"Available keys: {list(example.keys())}"
    )


def _detect_schema() -> Tuple[str, str, str]:
    """
    Detect common MBPP column names across variants.

    Returns (prompt_key, solution_key, tests_key_or_empty_string).
    """
    ex = dict(ds[0])

    prompt_key = _pick_first_existing_key(
        ex, ["text", "prompt", "question", "instruction", "problem"]
    )
    solution_key = _pick_first_existing_key(
        ex, ["code", "completion", "solution", "canonical_solution"]
    )

    tests_key = ""
    for k in ["test_list", "tests", "assertions"]:
        if k in ex and k in ex and ex[k] is not None:
            tests_key = k
            break

    return prompt_key, solution_key, tests_key


PROMPT_KEY, SOLUTION_KEY, TESTS_KEY = _detect_schema()


def _as_text(x: Any) -> str:
    """Normalize fields that might be str/list/None into a string."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return "\n".join(str(i) for i in x)
    return str(x)


CHROMA_PATH = PROJECT_ROOT / "chroma_db"
client = chromadb.PersistentClient(path=str(CHROMA_PATH))


openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key_env_var="OPENAI_API_KEY",
    model_name="text-embedding-3-large",
)

COLLECTION_NAME = "mbpp_problems_openai_v1"


try:
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=openai_ef,
    )
except Exception as e:
    raise RuntimeError(
        "Failed to get_or_create_collection. If you previously created a collection with a "
        "different embedding function, delete the chroma_db folder or change COLLECTION_NAME.\n"
        f"Underlying error: {e!r}"
    )


def _ensure_indexed() -> None:
    """
    Populate the collection if empty.
    """
    if collection.count() > 0:
        return

    docs: List[str] = []
    metadatas: List[dict] = []
    ids: List[str] = []

    for i, item in enumerate(ds):
        item = dict(item)

        prompt = _as_text(item.get(PROMPT_KEY)).strip()
        solution = _as_text(item.get(SOLUTION_KEY)).strip()

        if not prompt:
            continue

        doc = f"Problem: {prompt}\nSolution: {solution}"
        docs.append(doc)
        metadatas.append({"problem_id": int(i), "prompt": prompt})
        ids.append(f"prob_{i}")

    if not docs:
        raise RuntimeError(
            f"No documents were indexed. Check that {LOCAL_MBPP_PATH} contains a prompt-like field "
            f"(detected PROMPT_KEY={PROMPT_KEY!r})."
        )

    collection.add(documents=docs, metadatas=metadatas, ids=ids)

_ensure_indexed()


# -------------------------
# Public API
# -------------------------
def get_random_problem() -> Dict[str, Any]:
    """
    Returns a normalized dict with:
    - text: problem statement
    - code: reference solution (keep hidden from student UI)
    - tests: tests if present
    """
    idx = random.randint(0, len(ds) - 1)
    item = dict(ds[idx])

    return {
        "text": _as_text(item.get(PROMPT_KEY)).strip(),
        "code": _as_text(item.get(SOLUTION_KEY)).strip(),
        "tests": item.get(TESTS_KEY) if TESTS_KEY else None,
        "_raw": item,
        "_split": _SPLIT,
        "_prompt_key": PROMPT_KEY,
        "_solution_key": SOLUTION_KEY,
        "_path": str(LOCAL_MBPP_PATH),
    }


def get_demo_problem() -> Dict[str, Any]:
    """
    Returns a deterministic 'demo' problem: the first entry in the MBPP dataset.
    Same normalized structure as get_random_problem.
    """
    if len(ds) == 0:
        raise RuntimeError("MBPP dataset is empty; cannot select demo problem.")

    item = dict(ds[0])

    return {
        "text": _as_text(item.get(PROMPT_KEY)).strip(),
        "code": _as_text(item.get(SOLUTION_KEY)).strip(),
        "tests": item.get(TESTS_KEY) if TESTS_KEY else None,
        "_raw": item,
        "_split": _SPLIT,
        "_prompt_key": PROMPT_KEY,
        "_solution_key": SOLUTION_KEY,
        "_path": str(LOCAL_MBPP_PATH),
    }


def get_similar_problems(problem_text: str, k: int = 5) -> List[Dict[str, Any]]:
    """
    Retrieve top-k similar problems (by embedding similarity in Chroma).

    Returns list of:
    {id, text, code, distance}
    """
    q = (problem_text or "").strip()
    if not q:
        return []

    results = collection.query(query_texts=[q], n_results=k)

    ids = results.get("ids", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    out: List[Dict[str, Any]] = []
    for doc_id, meta, dist in zip(ids, metadatas, distances):
        pid = int(meta["problem_id"])
        item = dict(ds[pid])

        out.append(
            {
                "id": doc_id,
                "text": _as_text(item.get(PROMPT_KEY)).strip(),
                "code": _as_text(item.get(SOLUTION_KEY)).strip(),
                "distance": float(dist),
            }
        )

    return out
