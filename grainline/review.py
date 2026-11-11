"""AI review of a PR diff, with a noise budget and a focus on correctness, security, and data bugs."""
from . import llm
from .schemas import Review, review_from

MAX_PATCH_CHARS = 12_000

SYSTEM = """You are a careful senior reviewer for Python, SQL, and Go code in data pipelines and services. Review ONLY the diff given.
Report real problems, most important first: bugs, data correctness (join fan-out, NULL handling, dropped rows,
wrong date filters, grain changes), security issues (including suspicious or obfuscated code and phishing-style links),
privacy risks (personal data in code, fixtures, or logs), and missing tests. Skip style nitpicks; linters handle style.
Do not invent issues. If the change is fine, return an empty findings list.
Respond with JSON only:
{"summary": str,
 "changelog": "one-line changelog entry for this change",
 "findings": [{"file": str, "line": int or null, "severity": "high"|"medium"|"low",
               "category": "bug"|"security"|"privacy"|"data"|"testing"|"performance"|"style"|"docs",
               "message": str, "suggestion": str}],
 "suggested_tests": "pytest code for the most important missing tests, or empty"}"""


def build_prompt(files, context=""):
    parts, used = [], 0
    for f in files:
        patch = f["patch"][: max(0, MAX_PATCH_CHARS - used)]
        if not patch:
            continue
        parts.append(f"### {f['filename']} ({f['status']})\n```diff\n{patch}\n```")
        used += len(patch)
    head = f"Requirements this PR should satisfy:\n{context}\n\n" if context else ""
    return head + "Review this pull request diff.\n\n" + "\n\n".join(parts)


def apply_noise_budget(review, limit):
    """Keep only the most important AI findings, so real problems are not buried."""
    order = {"high": 0, "medium": 1, "low": 2}
    review.findings = sorted(review.findings, key=lambda f: order[f.severity])[:limit]
    return review


def review_diff(files, model, limit=5, context=""):
    if not files:
        return Review(summary="No reviewable changes in this PR.")
    data = llm.chat_json(SYSTEM, build_prompt(files, context), model)
    return apply_noise_budget(review_from(data), limit)
