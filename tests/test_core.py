"""Unit tests for Grainline. Test names reference acceptance criteria where they apply (AC-n)."""
import json

from grainline import config, data_lint, data_proof, docs_check, readiness, requirements_ai, security, traceability
from grainline.diffs import added_lines, code_to_diff, new_text
from grainline.github_api import find_marker, linked_issue
from grainline.llm import extract_json
from grainline.report import findings_table, to_markdown
from grainline.review import apply_noise_budget
from grainline.schemas import Finding, Review, requirements_from, review_from

FIX = "examples/fixtures"
GOOD = open("examples/models/net_sales.sql").read()
BAD = open("examples/models/net_sales_buggy.sql").read()


def test_added_lines_track_new_line_numbers():
    patch = "@@ -1,3 +10,4 @@\n a\n-b\n+c\n+d\n e"
    assert added_lines(patch) == [(11, "c"), (12, "d")]
    assert new_text(patch) == "a\nc\nd\ne"


def test_code_to_diff_round_trip():
    d = code_to_diff("x = 1\ny = 2")
    assert d.startswith("@@ -0,0 +1,2 @@") and new_text(d) == "x = 1\ny = 2"


def test_extract_json_tolerates_extra_text():
    assert extract_json('ok {"a": 1} done') == {"a": 1} and extract_json("nope") is None


def test_review_validation_drops_bad_findings():
    r = review_from({"summary": "s", "findings": [
        {"file": "a.py", "severity": "critical", "category": "bug", "message": "m"},
        {"file": "b.py", "severity": "low", "category": "data", "message": "ok", "line": "7"}]})
    assert len(r.findings) == 1 and r.findings[0].line is None
    assert review_from(None).findings == []


def test_noise_budget_keeps_most_severe():
    fs = [Finding("a.py", s, "bug", "m") for s in ("low", "high", "medium", "low", "high")]
    kept = apply_noise_budget(Review("s", fs), 3).findings
    assert [f.severity for f in kept] == ["high", "high", "medium"]


def test_ac_1_requirements_are_renumbered_and_linked():
    req = requirements_from({"summary": "s", "user_stories": [{"id": "x", "i_want": "a report"}],
                             "acceptance_criteria": [{"id": "c9", "story": "x", "given": "g", "when": "w", "then": "t"}],
                             "tasks": [{"title": "build", "ac": "c9"}], "test_ideas": [{"ac": "c9", "test": "check"}]})
    assert req.user_stories[0]["id"] == "US-1" and req.acceptance_criteria[0]["id"] == "AC-1"
    assert req.acceptance_criteria[0]["story"] == "US-1" and req.tasks[0]["ac"] == "AC-1"


def test_ac_2_requirements_survive_the_comment_round_trip():
    req = requirements_from({"summary": "s", "acceptance_criteria": [{"given": "g", "when": "w", "then": "t"}]})
    body = requirements_ai.to_markdown(req) + "\n" + requirements_ai.embed(req)
    back = requirements_ai.extract(["unrelated", body])
    assert back.acceptance_criteria[0]["id"] == "AC-1"


def test_data_proof_catches_fanout_and_changed_values():
    res = data_proof.compare(GOOD, BAD, FIX)
    checks = {c["check"]: c for c in res["checks"]}
    assert res["status"] == "review" and checks["changed_values"]["examples"][0]["new"] == 17000
    assert checks["row_count"]["old"] == 3 and checks["row_count"]["new"] == 2


def test_data_proof_blocks_duplicate_grain_keys():
    order_grain = "-- grain: order_id\nSELECT o.order_id, r.refund_cents FROM orders o LEFT JOIN refunds r ON o.order_id = r.order_id"
    base = "-- grain: order_id\nSELECT order_id FROM orders"
    res = data_proof.compare(base, order_grain, FIX)
    assert res["status"] == "block"
    assert any(f.severity == "high" and "Fan-out" in f.message for f in data_proof.to_findings("m.sql", res))


def test_data_proof_blocks_broken_query():
    assert data_proof.compare(GOOD, "SELECT nope FROM missing_table", FIX)["status"] == "block"


def test_data_proof_correct_model_output():
    cols, rows = data_proof.run_query(GOOD, FIX)
    assert [(r["seller_id"], r["net_cents"]) for r in rows] == [("A", 12000), ("B", 8000), ("C", 0)]


def test_sql_lint_rules():
    rules = {f.source for f in data_lint.lint("m.sql", code_to_diff(BAD))}
    assert {"data-lint:left-join-where", "data-lint:count-after-join"} <= rules
    assert not data_lint.lint("m.sql", code_to_diff(GOOD))


def test_python_lint_rules():
    p = code_to_diff("def f(x=[]):\n    cur.execute(f\"SELECT * FROM t WHERE a = '{x}'\")\n    return df.merge(o, on='k')")
    rules = {f.source for f in data_lint.lint("a.py", p)}
    assert {"py-lint:mutable-default", "py-lint:sql-string-format", "data-lint:merge-no-validate"} <= rules


def test_secret_scan():
    assert security.scan("c.py", code_to_diff('TOKEN = "ghp_' + "a" * 36 + '"'))
    assert not security.scan("c.py", code_to_diff("TOKEN = os.environ['TOKEN']"))


def test_docstring_check():
    src = "def public():\n    return 1\n\ndef _private():\n    return 2\n"
    out = docs_check.missing_docstrings("a.py", src, code_to_diff(src))
    assert [f.message for f in out] == ["New public function 'public' has no docstring."]


def test_ac_3_traceability(tmp_path):
    (tmp_path / "test_x.py").write_text("def test_ac_1_ok():\n    pass\n")
    req = requirements_from({"summary": "s", "acceptance_criteria": [{"then": "a"}, {"then": "b"}]})
    cov = traceability.coverage(req, traceability.ac_mentions(str(tmp_path)))
    assert cov["covered"] == ["AC-1"] and cov["missing"] == ["AC-2"]


def test_readiness_rules():
    cfg = config.Config()
    tests_ok = {"ran": True, "passed": True, "coverage": 90.0, "summary": "5 passed"}
    clean = {"ran": True, "high": 0, "medium": 0, "low": 0}
    none = {"linked": False, "missing": []}
    assert readiness.evaluate([], tests_ok, clean, {"issues": 0}, none, cfg)["verdict"] == "Ready"
    secret = Finding("c.py", "high", "security", "m", source="secrets:github-token")
    assert readiness.evaluate([secret], tests_ok, clean, {"issues": 0}, none, cfg)["verdict"] == "Blocked"
    ai_high = Finding("a.py", "high", "bug", "m")
    r = readiness.evaluate([ai_high], tests_ok, clean, {"issues": 0}, none, cfg)
    assert r["verdict"] == "Needs Review" and not r["blockers"]          # AI alone never blocks
    failing = dict(tests_ok, passed=False, summary="1 failed")
    assert readiness.evaluate([], failing, clean, {"issues": 0}, none, cfg)["verdict"] == "Blocked"


def test_report_markdown_and_table_escape():
    f = Finding("a.py", "medium", "data", "uses | pipe", suggestion="fix\nit", source="data-lint:x")
    assert "uses \\| pipe" in "\n".join(findings_table([f]))
    md = to_markdown(Review("s", changelog="Adds X"), [f], {"ran": True, "passed": True, "summary": "1 passed", "coverage": 80.0},
                     {"ran": True, "high": 0, "medium": 0, "low": 0}, {"ran": True, "issues": 0}, {}, {"ran": False}, [],
                     {"linked": False}, {"verdict": "Needs Review", "score": 76, "blockers": [], "notes": []})
    assert "Needs Review (score 76/100)" in md and "coverage 80.0%" in md and "Adds X" in md


def test_github_helpers():
    assert linked_issue("This PR closes #12 and more") == 12 and linked_issue("no link") is None
    assert find_marker([{"id": 1, "body": "x"}, {"id": 2, "body": "<!-- m -->\nhi"}], "<!-- m -->")["id"] == 2


def test_config_reads_toml(tmp_path):
    p = tmp_path / "grainline.toml"
    p.write_text('[grainline]\nmax_ai_findings = 3\nreview_extensions = [".sql"]\n')
    cfg = config.load(str(p))
    assert cfg.max_ai_findings == 3 and cfg.review_extensions == (".sql",)
