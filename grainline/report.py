"""PR comment markdown and the JSON audit record."""
from datetime import datetime, timezone

ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}
VERDICT_ICON = {"Ready": "✅", "Needs Review": "🟠", "Blocked": "⛔"}
ORDER = {"high": 0, "medium": 1, "low": 2}


def _cell(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def findings_table(findings):
    if not findings:
        return ["No issues found."]
    rows = ["| Severity | Category | Where | Finding | Suggestion | Source |", "|---|---|---|---|---|---|"]
    for f in sorted(findings, key=lambda f: (ORDER[f.severity], f.source == "ai")):
        where = f"`{f.file}`" + (f":{f.line}" if f.line else "")
        src = "AI" if f.source == "ai" else f"`{f.source}`"
        rows.append(f"| {ICON[f.severity]} {f.severity} | {f.category} | {where} | {_cell(f.message)} | {_cell(f.suggestion)} | {src} |")
    return rows


def to_markdown(review, findings, tests, bandit, ruff, proofs, suggested_run, explanations, trace, readiness):
    v = readiness["verdict"]
    md = [f"## {VERDICT_ICON[v]} Grainline: {v} (score {readiness['score']}/100)", "", review.summary, ""]
    if readiness["blockers"]:
        md += ["**Blockers**"] + [f"- ⛔ {b}" for b in readiness["blockers"]] + [""]
    if readiness["notes"]:
        md += ["**Notes**"] + [f"- {n}" for n in readiness["notes"]] + [""]
    md += ["### Findings"] + findings_table(findings) + [""]
    if proofs:
        md += ["### Data proof (old vs new SQL on fixture data)"]
        for path, p in proofs.items():
            md.append(f"- `{path}`: **{p['status'].upper()}**" + (f" · grain {p['grain']}" if p["grain"] else " · no `-- grain:` declared"))
        md.append("")
    md += ["### Automated checks",
           (f"- **pytest:** {'✅' if tests.get('passed') else '❌'} {tests.get('summary', '')}" +
            (f" · coverage {tests['coverage']}%" if tests.get("coverage") is not None else "")) if tests.get("ran") else "- **pytest:** not run",
           f"- **Bandit:** {bandit['high']} high, {bandit['medium']} medium, {bandit['low']} low" if bandit.get("ran") else "- **Bandit:** not run",
           f"- **Ruff:** {ruff['issues']} lint issues" if ruff.get("ran") else "- **Ruff:** not run"]
    for e in explanations:
        md.append(f"  - `{e['test']}`: {e['explanation']}")
    if trace.get("linked"):
        md += ["", "### Requirement traceability"]
        md += [f"- {ac}: " + (", ".join(f"`{t}`" for t in tests_) if tests_ else "❌ no test yet") for ac, tests_ in trace["map"].items()]
    if review.suggested_tests.strip():
        status = ""
        if suggested_run.get("ran"):
            status = f" · ran in a sandbox: {suggested_run['summary']}"
        md += ["", f"<details><summary>Suggested tests{status}</summary>", "", "```python", review.suggested_tests.strip(), "```", "</details>"]
    if review.changelog:
        md += ["", f"**Changelog:** {review.changelog}"]
    md += ["", "_Only tools and data can block a release. AI findings are suggestions to review._"]
    return "\n".join(md)


def to_record(repo, pr, files, review, findings, tests, bandit, ruff, proofs, trace, readiness, opened_at=None):
    now = datetime.now(timezone.utc)
    minutes_open = None
    if opened_at:
        try:
            minutes_open = round((now - datetime.fromisoformat(opened_at.replace("Z", "+00:00"))).total_seconds() / 60, 1)
        except ValueError:
            minutes_open = None
    return {"repo": repo, "pr": pr, "reviewed_at": now.isoformat(), "minutes_since_opened": minutes_open,
            "files_reviewed": [f["filename"] for f in files], "changelog": review.changelog,
            "findings": [f.to_dict() for f in findings], "tests": tests, "bandit": bandit, "ruff": ruff,
            "data_proofs": proofs, "traceability": trace, "readiness": readiness}
