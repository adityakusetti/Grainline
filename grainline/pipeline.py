"""The connected workflow for one pull request, kept free of GitHub calls so it can be tested and reused:
review (AI + data lint + secrets + docs) -> data proof -> tests and scanners -> traceability -> release readiness."""
import os

from . import checks, data_lint, data_proof, docs_check, review, security, testgen, traceability
from .readiness import evaluate
from .schemas import Review


def requirements_context(req):
    if not req or not req.acceptance_criteria:
        return ""
    return "\n".join(f"{a['id']}: Given {a['given']}, when {a['when']}, then {a['then']}" for a in req.acceptance_criteria)


def run(files, cfg, old_text=lambda path: None, new_text=None, req=None, run_tools=True, use_ai=True):
    """files: [{filename, status, patch}]. old_text(path) returns the base version of a file (or None)."""
    new_text = new_text or (lambda p: open(p).read() if os.path.exists(p) else None)
    files = [f for f in files if f["filename"].endswith(cfg.review_extensions) and f["status"] != "removed"]

    ai_review = review.review_diff(files, cfg.model, cfg.max_ai_findings, requirements_context(req)) if use_ai \
        else Review(summary="AI review skipped.")
    findings = list(ai_review.findings)
    proofs = {}
    for f in files:
        path, patch = f["filename"], f["patch"]
        findings += data_lint.lint(path, patch) + security.scan(path, patch)
        src = new_text(path)
        if src:
            findings += docs_check.missing_docstrings(path, src, patch)
        if path.endswith(".sql") and path.startswith(cfg.models_dir.rstrip("/") + "/") and src:
            proof = data_proof.compare(old_text(path), src, cfg.fixtures_dir)
            proofs[path] = proof
            findings += data_proof.to_findings(path, proof)

    paths = [f["filename"] for f in files if os.path.exists(f["filename"])]
    if run_tools:
        tests = checks.run_pytest(cfg.tests_dir)
        bandit, ruff = checks.run_bandit(paths), checks.run_ruff(paths)
        suggested = testgen.run_suggested(ai_review.suggested_tests) if use_ai else {"ran": False}
        explanations = testgen.explain_failures(tests.get("failing", []), tests.get("summary", ""), cfg.model) if use_ai else []
    else:
        tests, bandit, ruff, suggested, explanations = {"ran": False}, {"ran": False, "high": 0, "medium": 0, "low": 0}, \
            {"ran": False, "issues": 0}, {"ran": False}, []
    trace = traceability.coverage(req, traceability.ac_mentions(cfg.tests_dir))
    ready = evaluate(findings, tests, bandit, ruff, trace, cfg)
    return {"files": files, "review": ai_review, "findings": findings, "tests": tests, "bandit": bandit, "ruff": ruff,
            "proofs": proofs, "suggested": suggested, "explanations": explanations, "trace": trace, "readiness": ready}
