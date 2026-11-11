"""Deterministic tools: pytest (with coverage when available), Bandit, and Ruff."""
import json
import os
import re
import subprocess
import tempfile


def _run(cmd, timeout=600, cwd=None, env=None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return None, "", f"{cmd[0]} is not installed"
    except subprocess.TimeoutExpired:
        return None, "", f"{cmd[0]} timed out"


def parse_pytest_summary(out):
    """Read counts like '3 passed, 1 failed in 0.5s' from pytest's last line."""
    last = (out.strip().splitlines() or [""])[-1]
    counts = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|errors?|skipped)", last)}
    counts["error"] = counts.pop("errors", 0) + counts.pop("error", 0)
    return last, counts


def failing_tests(out):
    return re.findall(r"^FAILED (\S+)", out, re.M)[:10]


def run_pytest(tests_dir="tests"):
    cov_path = os.path.join(tempfile.gettempdir(), "grainline_coverage.json")
    code, out, err = _run(["pytest", "-q", "--tb=line", "-rf", "--cov=.", f"--cov-report=json:{cov_path}"])
    if code is not None and "unrecognized arguments: --cov" in err:
        code, out, err = _run(["pytest", "-q", "--tb=line", "-rf"])
    if code is None:
        return {"ran": False, "passed": False, "summary": err}
    summary, counts = parse_pytest_summary(out)
    coverage = None
    if os.path.exists(cov_path):
        try:
            with open(cov_path) as fh:
                coverage = round(json.load(fh)["totals"]["percent_covered"], 1)
        except (KeyError, json.JSONDecodeError):
            coverage = None
    return {"ran": True, "passed": code in (0, 5), "no_tests": code == 5, "summary": summary, "counts": counts,
            "failing": failing_tests(out), "coverage": coverage}


def parse_ruff(out):
    try:
        issues = json.loads(out or "[]")
    except json.JSONDecodeError:
        issues = []
    return {"ran": True, "issues": len(issues),
            "examples": [f"{i['filename']}:{i['location']['row']} {i['code']} {i['message']}" for i in issues[:5]]}


def parse_bandit(out):
    try:
        results = json.loads(out or "{}").get("results", [])
    except json.JSONDecodeError:
        results = []
    count = lambda s: sum(r.get("issue_severity") == s for r in results)
    return {"ran": True, "high": count("HIGH"), "medium": count("MEDIUM"), "low": count("LOW"),
            "examples": [f"{r['filename']}:{r['line_number']} {r['test_id']} {r['issue_text']}" for r in results[:5]]}


def run_ruff(paths):
    paths = [p for p in paths if p.endswith(".py")]
    if not paths:
        return {"ran": False, "issues": 0}
    code, out, _ = _run(["ruff", "check", "--output-format", "json", *paths])
    return {"ran": False, "issues": 0} if code is None else parse_ruff(out)


def run_bandit(paths):
    paths = [p for p in paths if p.endswith(".py")]
    if not paths:
        return {"ran": False, "high": 0, "medium": 0, "low": 0}
    code, out, _ = _run(["bandit", "-q", "-f", "json", *paths])
    return {"ran": False, "high": 0, "medium": 0, "low": 0} if code is None else parse_bandit(out)
