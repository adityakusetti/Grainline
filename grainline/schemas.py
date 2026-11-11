"""Validated data structures for everything the LLM returns. Anything malformed is dropped, never trusted."""
from dataclasses import asdict, dataclass, field

SEVERITIES = ("high", "medium", "low")
CATEGORIES = ("bug", "security", "privacy", "data", "testing", "performance", "style", "docs")


@dataclass
class Finding:
    file: str
    severity: str
    category: str
    message: str
    line: int | None = None
    suggestion: str = ""
    source: str = "ai"          # "ai" or the deterministic check that produced it
    evidence: str = ""          # for deterministic findings: what proves it

    def to_dict(self):
        return asdict(self)


@dataclass
class Review:
    summary: str
    findings: list = field(default_factory=list)
    suggested_tests: str = ""
    changelog: str = ""


@dataclass
class Requirements:
    summary: str
    user_stories: list = field(default_factory=list)          # {id, as_a, i_want, so_that}
    acceptance_criteria: list = field(default_factory=list)   # {id, story, given, when, then}
    tasks: list = field(default_factory=list)                 # {id, title, ac}
    open_questions: list = field(default_factory=list)
    test_ideas: list = field(default_factory=list)            # {ac, test}

    def to_dict(self):
        return asdict(self)


def _int_or_none(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def finding_from(d, source="ai"):
    if not isinstance(d, dict):
        return None
    if d.get("severity") not in SEVERITIES or d.get("category") not in CATEGORIES:
        return None
    if not isinstance(d.get("file"), str) or not isinstance(d.get("message"), str) or not d["message"].strip():
        return None
    return Finding(file=d["file"], severity=d["severity"], category=d["category"], message=d["message"].strip(),
                   line=_int_or_none(d.get("line")), suggestion=str(d.get("suggestion") or "").strip(), source=source)


def review_from(data):
    if not isinstance(data, dict):
        return Review(summary="The AI review could not be parsed; the automated checks below still apply.")
    findings = [f for f in (finding_from(x) for x in data.get("findings") or []) if f]
    return Review(summary=str(data.get("summary") or "").strip() or "Review complete.", findings=findings,
                  suggested_tests=str(data.get("suggested_tests") or ""), changelog=str(data.get("changelog") or "").strip())


def _strs(xs):
    return [str(x).strip() for x in (xs or []) if isinstance(x, (str, int, float)) and str(x).strip()]


def requirements_from(data):
    """Validate and renumber IDs (US-1, AC-1, T-1) so references stay consistent no matter what the model returns."""
    if not isinstance(data, dict):
        return Requirements(summary="The requirements could not be parsed.")
    stories, id_map = [], {}
    for i, s in enumerate([s for s in data.get("user_stories") or [] if isinstance(s, dict) and s.get("i_want")], 1):
        id_map[str(s.get("id", ""))] = f"US-{i}"
        stories.append({"id": f"US-{i}", "as_a": str(s.get("as_a", "user")), "i_want": str(s["i_want"]),
                        "so_that": str(s.get("so_that", ""))})
    acs, ac_map = [], {}
    for i, a in enumerate([a for a in data.get("acceptance_criteria") or [] if isinstance(a, dict) and a.get("then")], 1):
        ac_map[str(a.get("id", ""))] = f"AC-{i}"
        acs.append({"id": f"AC-{i}", "story": id_map.get(str(a.get("story", "")), stories[0]["id"] if stories else ""),
                    "given": str(a.get("given", "")), "when": str(a.get("when", "")), "then": str(a["then"])})
    tasks = [{"id": f"T-{i}", "title": str(t.get("title")), "ac": ac_map.get(str(t.get("ac", "")), "")}
             for i, t in enumerate([t for t in data.get("tasks") or [] if isinstance(t, dict) and t.get("title")], 1)]
    ideas = [{"ac": ac_map.get(str(t.get("ac", "")), ""), "test": str(t.get("test"))}
             for t in data.get("test_ideas") or [] if isinstance(t, dict) and t.get("test")]
    return Requirements(summary=str(data.get("summary") or "").strip(), user_stories=stories, acceptance_criteria=acs,
                        tasks=tasks, open_questions=_strs(data.get("open_questions")), test_ideas=ideas)
