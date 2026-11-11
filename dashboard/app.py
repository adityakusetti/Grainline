"""Grainline web app: try the reviewer, analyze requirements, run a data proof, and view release history."""
import glob
import json
import os
import sys

import pandas as pd
import streamlit as st

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from grainline import config, data_lint, data_proof, docs_check, requirements_ai, review, security  # noqa: E402
from grainline.diffs import code_to_diff, new_text  # noqa: E402
from grainline.schemas import Review  # noqa: E402

st.set_page_config(page_title="Grainline", page_icon="🌾", layout="wide")
if not os.environ.get("GROQ_API_KEY"):
    try:
        os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
    except Exception:
        pass
CFG = config.load(os.path.join(ROOT, "grainline.toml"))
EX_DIR = os.path.join(ROOT, "examples")
FIXTURES = os.path.join(EX_DIR, "fixtures")
MAX_AI_CALLS, MAX_CHARS = 10, 8000
ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}
st.session_state.setdefault("ai_calls", 0)


def ai_allowed():
    if not os.environ.get("GROQ_API_KEY"):
        st.info("No GROQ_API_KEY set, so only the deterministic checks run. Add it in Streamlit secrets for the AI review.")
        return False
    if st.session_state.ai_calls >= MAX_AI_CALLS:
        st.warning("AI limit for this session reached; deterministic checks still run.")
        return False
    st.session_state.ai_calls += 1
    return True


def findings_df(findings):
    return pd.DataFrame([{"severity": f"{ICON[f.severity]} {f.severity}", "category": f.category, "line": f.line,
                          "finding": f.message, "suggestion": f.suggestion,
                          "source": "AI" if f.source == "ai" else f.source} for f in findings])


st.title("🌾 Grainline")
st.caption("AI-assisted SDLC for data pipelines: requirements → review → data proof → tests → release readiness. "
           "Only tools and data can block a release; the AI explains and suggests.")
tab_review, tab_req, tab_proof, tab_hist = st.tabs(["Review code", "Requirements", "Data proof", "Release history"])

with tab_review:
    examples = {"(paste your own)": ("", "my_change.py")}
    from eval.benchmark import CASES
    examples.update({c["name"].replace("_", " "): (c["patch"], c["file"]) for c in CASES})
    choice = st.selectbox("Example", list(examples), key="ex")
    filename = st.text_input("File name", value=examples[choice][1])
    text = st.text_area("Python or SQL code, or a diff", value=examples[choice][0], height=240)
    if st.button("Review", type="primary"):
        if not text.strip() or len(text) > MAX_CHARS:
            st.warning(f"Paste between 1 and {MAX_CHARS:,} characters.")
        else:
            patch = code_to_diff(text)
            det = data_lint.lint(filename, patch) + security.scan(filename, patch) + \
                docs_check.missing_docstrings(filename, new_text(patch), patch)
            rv = review.review_diff([{"filename": filename, "status": "modified", "patch": patch}], CFG.model,
                                    CFG.max_ai_findings) if ai_allowed() else Review(summary="")
            if rv.summary:
                st.subheader("Summary")
                st.write(rv.summary)
            allf = rv.findings + det
            st.subheader(f"Findings ({len(allf)})")
            st.dataframe(findings_df(allf), hide_index=True, use_container_width=True) if allf else st.success("No issues found.")
            if rv.suggested_tests.strip():
                with st.expander("Suggested tests"):
                    st.code(rv.suggested_tests, language="python")

with tab_req:
    st.write("Turn a plain-English request into user stories, acceptance criteria, tasks, and open questions.")
    title = st.text_input("Title", value="Net sales report by seller")
    body = st.text_area("Request", height=160, value="Finance needs monthly net sales per seller: completed orders "
                        "minus refunds. Sellers with fully refunded orders should still appear.")
    if st.button("Analyze requirements", type="primary"):
        if ai_allowed():
            req = requirements_ai.analyze(title, body, CFG.model)
            st.markdown(requirements_ai.to_markdown(req))

with tab_proof:
    st.write("Run the old and new version of a SQL model on fixture data and compare the outputs. "
             "Declare the output grain with a comment like `-- grain: seller_id`.")
    good = open(os.path.join(EX_DIR, "models", "net_sales.sql")).read()
    bad = open(os.path.join(EX_DIR, "models", "net_sales_buggy.sql")).read()
    c1, c2 = st.columns(2)
    old_sql = c1.text_area("Old SQL", value=good, height=300)
    new_sql = c2.text_area("New SQL", value=bad, height=300)
    with st.expander("Fixture tables"):
        for p in sorted(glob.glob(os.path.join(FIXTURES, "*.csv"))):
            st.caption(os.path.basename(p))
            st.dataframe(pd.read_csv(p), hide_index=True)
    if st.button("Run data proof", type="primary"):
        proof = data_proof.compare(old_sql, new_sql, FIXTURES)
        st.metric("Result", proof["status"].upper())
        st.dataframe(pd.DataFrame([{k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in c.items()}
                                   for c in proof["checks"]]), hide_index=True, use_container_width=True)
        fs = data_proof.to_findings("model.sql", proof) + data_lint.lint("model.sql", code_to_diff(new_sql))
        if fs:
            st.dataframe(findings_df(fs), hide_index=True, use_container_width=True)
        try:
            o, n = data_proof.run_query(old_sql, FIXTURES), data_proof.run_query(new_sql, FIXTURES)
            a, b = st.columns(2)
            a.caption("Old output")
            a.dataframe(pd.DataFrame(o[1]), hide_index=True)
            b.caption("New output")
            b.dataframe(pd.DataFrame(n[1]), hide_index=True)
        except Exception as e:
            st.error(f"Query error: {e}")

with tab_hist:
    recs = []
    for p in sorted(glob.glob(os.path.join(ROOT, CFG.reports_dir, "pr-*.json"))):
        with open(p) as fh:
            recs.append(json.load(fh))
    if not recs:
        st.info("No PR records yet. Download the grainline-records artifact from GitHub Actions into reports/.")
    else:
        df = pd.DataFrame([{"pr": r["pr"], "reviewed_at": r["reviewed_at"][:16], "verdict": r["readiness"]["verdict"],
                            "score": r["readiness"]["score"], "findings": len(r["findings"]),
                            "tests_passed": r["tests"].get("passed"), "coverage": r["tests"].get("coverage"),
                            "minutes_since_opened": r.get("minutes_since_opened")} for r in recs])
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("PRs reviewed", len(df))
        k2.metric("Ready", int((df.verdict == "Ready").sum()))
        k3.metric("Blocked", int((df.verdict == "Blocked").sum()))
        k4.metric("Average score", round(df.score.mean(), 1))
        st.subheader("Verdicts")
        st.bar_chart(df.verdict.value_counts())
        allf = pd.DataFrame([dict(f, pr=r["pr"]) for r in recs for f in r["findings"]])
        if len(allf):
            st.subheader("Findings by source")
            st.bar_chart(allf.source.str.split(":").str[0].value_counts())
        st.subheader("Pull requests")
        st.dataframe(df, hide_index=True, use_container_width=True)
