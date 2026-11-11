"""Testing assistant: run the AI's suggested tests in a throwaway file, and explain failures in plain language."""
import os
import subprocess
import tempfile

from . import llm
from .checks import parse_pytest_summary

EXPLAIN = """Explain each failing test in one or two plain sentences: what it checked and the most likely cause.
Respond with JSON only: {"explanations": [{"test": str, "explanation": str}]}"""


def run_suggested(test_code, repo_root=".", timeout=300):
    """Run AI-suggested tests without committing them. Returns counts, or ran=False if there is nothing to run."""
    if not test_code or "def test" not in test_code:
        return {"ran": False}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test_grainline_suggested.py")
        with open(path, "w") as fh:
            fh.write(test_code)
        env = dict(os.environ, PYTHONPATH=os.path.abspath(repo_root) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        try:
            p = subprocess.run(["pytest", "-q", "--tb=line", "-p", "no:cacheprovider", path], capture_output=True,
                               text=True, timeout=timeout, cwd=repo_root, env=env)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"ran": False, "error": str(e)}
    summary, counts = parse_pytest_summary(p.stdout)
    return {"ran": True, "summary": summary, "counts": counts, "all_passed": p.returncode == 0}


def explain_failures(failing, output_tail, model):
    if not failing:
        return []
    data = llm.chat_json(EXPLAIN, "Failing tests:\n" + "\n".join(failing) + "\n\nOutput:\n" + output_tail[-4000:], model) or {}
    return [e for e in data.get("explanations") or [] if isinstance(e, dict) and e.get("test") and e.get("explanation")]
