"""Release readiness: a deterministic score and verdict. Only evidence from tools and data can block a release;
AI findings can lower the score and ask for review, but never block on their own."""


def evaluate(findings, tests, bandit, ruff, traceability, cfg):
    blockers, notes, score = [], [], 100

    if tests.get("ran") and not tests.get("passed"):
        blockers.append(f"Tests failing: {tests.get('summary')}")
    elif not tests.get("ran"):
        notes.append("Tests did not run.")
        score -= 10
    elif tests.get("no_tests"):
        notes.append("No tests were collected.")
        score -= 15
    cov = tests.get("coverage")
    if cov is not None and cov < cfg.coverage_threshold:
        notes.append(f"Coverage {cov}% is below the {cfg.coverage_threshold}% target.")
        score -= 15

    if bandit.get("high"):
        blockers.append(f"{bandit['high']} high-severity security issue(s) from Bandit.")
    score -= min(30, 10 * bandit.get("medium", 0))
    score -= min(10, ruff.get("issues", 0))

    for f in findings:
        if f.source.startswith("secrets:"):
            blockers.append(f"Possible secret in {f.file}:{f.line}.")
        elif f.source.startswith("data-proof:") and f.severity == "high":
            blockers.append(f"Data proof: {f.message}")
    det = [f for f in findings if f.source != "ai" and not f.source.startswith(("secrets:", "data-proof:"))]
    proof_review = [f for f in findings if f.source.startswith("data-proof:") and f.severity != "high"]
    ai = [f for f in findings if f.source == "ai"]
    score -= min(20, 10 * sum(f.severity == "high" for f in ai)) + min(15, 3 * sum(f.severity == "medium" for f in ai))
    score -= min(20, 10 * len(proof_review))
    score -= min(15, sum({"high": 8, "medium": 4, "low": 1}[f.severity] for f in det))

    if traceability.get("linked") and traceability["missing"]:
        notes.append(f"Acceptance criteria without tests: {', '.join(traceability['missing'])}.")
        score -= min(20, 5 * len(traceability["missing"]))

    score = max(0, score)
    needs_review = (score < cfg.ready_score or any(f.severity == "high" for f in ai) or bool(proof_review)
                    or bool(traceability.get("missing")) or not tests.get("ran")
                    or any(f.severity == "high" for f in det))
    verdict = "Blocked" if blockers else "Needs Review" if needs_review else "Ready"
    return {"verdict": verdict, "score": score, "blockers": blockers, "notes": notes}
