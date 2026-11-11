"""Requirements analyzer: a GitHub issue or plain-English request becomes stories, acceptance criteria, and tasks."""
import json

from . import llm
from .schemas import requirements_from

MARKER = "<!-- grainline-requirements"

SYSTEM = """You are a precise product engineer. Turn the request into implementable requirements.
Write testable acceptance criteria in Given/When/Then form, and list open questions for anything ambiguous or missing.
Respond with JSON only:
{"summary": str,
 "user_stories": [{"id": "US-1", "as_a": str, "i_want": str, "so_that": str}],
 "acceptance_criteria": [{"id": "AC-1", "story": "US-1", "given": str, "when": str, "then": str}],
 "tasks": [{"id": "T-1", "title": str, "ac": "AC-1"}],
 "open_questions": [str],
 "test_ideas": [{"ac": "AC-1", "test": "short description of a test"}]}"""


def analyze(title, body, model):
    data = llm.chat_json(SYSTEM, f"Title: {title}\n\n{body or ''}", model)
    return requirements_from(data)


def to_markdown(req):
    md = ["## 📋 Grainline requirements", "", req.summary or "", ""]
    if req.user_stories:
        md += ["### User stories"] + [f"- **{s['id']}:** As a {s['as_a']}, I want {s['i_want']}" +
                                      (f", so that {s['so_that']}." if s['so_that'] else ".") for s in req.user_stories] + [""]
    if req.acceptance_criteria:
        md += ["### Acceptance criteria", "| ID | Story | Given | When | Then |", "|---|---|---|---|---|"]
        md += [f"| {a['id']} | {a['story']} | {a['given']} | {a['when']} | {a['then']} |" for a in req.acceptance_criteria] + [""]
    if req.tasks:
        md += ["### Tasks"] + [f"- [ ] **{t['id']}** {t['title']}" + (f" ({t['ac']})" if t['ac'] else "") for t in req.tasks] + [""]
    if req.open_questions:
        md += ["### Open questions"] + [f"- {q}" for q in req.open_questions] + [""]
    if req.test_ideas:
        md += ["### Test ideas"] + [f"- {t['ac'] + ': ' if t['ac'] else ''}{t['test']}" for t in req.test_ideas] + [""]
    md += ["_Name tests after acceptance criteria (for example `test_ac_1_...`) so Grainline can trace them._"]
    return "\n".join(md)


def embed(req):
    """Hidden machine-readable copy inside the comment, read back later for traceability."""
    return f"{MARKER} {json.dumps(req.to_dict())} -->"


def extract(comment_bodies):
    for body in comment_bodies:
        if MARKER in body:
            raw = body.split(MARKER, 1)[1].rsplit("-->", 1)[0].strip()
            try:
                return requirements_from(json.loads(raw))
            except json.JSONDecodeError:
                return None
    return None
