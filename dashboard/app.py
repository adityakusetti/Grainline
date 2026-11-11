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

st.set_page_config(page_title="Grainline: AI-assisted SDLC for data pipelines", page_icon="🌾", layout="wide")

# Edit these to point at your own profiles
LINKS = {"GitHub repo": "https://github.com/adityakusetti/grainline",
         "LinkedIn": "https://www.linkedin.com/in/kusetti-aditya",
         "Portfolio": "https://kusettiaditya.me"}
AUTHOR = "Aditya Sai Kumar Kusetti"

st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1200px;}
  .gl-hero {padding: 1.6rem 1.8rem; border-radius: 14px; background: linear-gradient(120deg, #FBF5E6 0%, #F1F6F2 100%);
            border: 1px solid #ECE3CF; margin-bottom: 1.2rem;}
  .gl-eyebrow {font-size: 0.8rem; letter-spacing: .08em; text-transform: uppercase; color: #8A5A12; font-weight: 600;}
  .gl-hero h1 {font-size: 2.1rem; line-height: 1.2; margin: .35rem 0 .5rem 0;}
  .gl-hero p {font-size: 1.05rem; color: #3E4C59; margin: 0;}
  .gl-card {border: 1px solid #ECE7DC; border-radius: 12px; padding: 1rem 1.1rem; background: #FFFFFF; height: 100%;}
  .gl-card h4 {margin: 0 0 .3rem 0; font-size: 1rem;}
  .gl-card p {margin: 0; color: #52606D; font-size: .92rem;}
  .gl-step {font-size: .75rem; font-weight: 700; color: #B7791F;}
  .gl-stat {text-align: center; padding: .8rem; border-radius: 12px; background: #F6F4EF;}
  .gl-stat b {display: block; font-size: 1.6rem; color: #1F2933;}
  .gl-stat span {font-size: .85rem; color: #52606D;}
  div[data-testid="stMetric"] {background: #F6F4EF; border-radius: 12px; padding: .7rem .9rem;}
  footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)
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


with st.sidebar:
    st.markdown("### 🌾 Grainline")
    st.caption("AI-assisted SDLC for data pipelines")
    st.markdown(f"Built by **{AUTHOR}**")
    for label, url in LINKS.items():
        st.markdown(f"[{label}]({url})")
    st.divider()
    st.markdown("**AI review:** " + ("🟢 connected" if os.environ.get("GROQ_API_KEY") else "⚪ off (deterministic checks still run)"))
    st.caption("Only tools and data can block a release. The AI explains and suggests.")

tab_home, tab_review, tab_req, tab_proof, tab_hist = st.tabs(
    ["Overview", "Review code", "Requirements", "Data proof", "Release history"])

with tab_home:
    st.markdown("""
    <div class="gl-hero">
      <div class="gl-eyebrow">AI-assisted SDLC · data pipelines</div>
      <h1>Catch the data bugs that generic AI reviewers miss, with proof.</h1>
      <p>Grainline turns GitHub issues into acceptance criteria, reviews pull requests, runs the old and new SQL on
      fixture data to prove data bugs, and gives every release a verdict: Ready, Needs Review, or Blocked.</p>
    </div>""", unsafe_allow_html=True)
    stats = [("10", "connected SDLC stages"), ("7 / 9", "planted bugs caught offline"),
             ("0", "false alarms on clean changes"), ("20", "unit tests")]
    for col, (num, label) in zip(st.columns(4), stats):
        col.markdown(f'<div class="gl-stat"><b>{num}</b><span>{label}</span></div>', unsafe_allow_html=True)
    st.caption("Offline numbers use the deterministic checks only, on a small benchmark written with the rules.")

    st.subheader("Try it in one click")
    st.write("A pull request changes a net-sales model to join refunds directly. Grainline runs both versions on fixture data:")
    if st.button("▶ Run the data proof demo", type="primary"):
        good = open(os.path.join(EX_DIR, "models", "net_sales.sql")).read()
        bad = open(os.path.join(EX_DIR, "models", "net_sales_buggy.sql")).read()
        proof = data_proof.compare(good, bad, FIXTURES)
        o, n = data_proof.run_query(good, FIXTURES), data_proof.run_query(bad, FIXTURES)
        a, b = st.columns(2)
        a.markdown("**Before (correct)**")
        a.dataframe(pd.DataFrame(o[1]), hide_index=True, use_container_width=True)
        b.markdown("**After (the PR)**")
        b.dataframe(pd.DataFrame(n[1]), hide_index=True, use_container_width=True)
        fs = data_proof.to_findings("models/net_sales.sql", proof) + data_lint.lint("models/net_sales.sql", code_to_diff(bad))
        st.error(f"Data proof result: {proof['status'].upper()}. Seller A's net sales jump from 12,000 to 17,000 and "
                 "seller B disappears, because an order with two refunds is counted twice and the WHERE clause "
                 "turns the LEFT JOIN into an INNER JOIN.")
        st.dataframe(findings_df(fs), hide_index=True, use_container_width=True)

    st.subheader("How it works")
    steps = [("01", "Requirements", "An issue becomes user stories and Given/When/Then acceptance criteria."),
             ("02", "Review", "AI findings with a noise budget, plus deterministic SQL, pandas, and secret checks."),
             ("03", "Data proof", "Old vs new SQL on fixture data: duplicates, dropped rows, changed values."),
             ("04", "Tests", "pytest with coverage, AI-suggested tests in a sandbox, and traceability to each criterion."),
             ("05", "Release", "A score out of 100 and a verdict. Only tools and data can block.")]
    for col, (num, title, text) in zip(st.columns(5), steps):
        col.markdown(f'<div class="gl-card"><div class="gl-step">{num}</div><h4>{title}</h4><p>{text}</p></div>',
                     unsafe_allow_html=True)

    st.subheader("What makes it different")
    diffs = [("Evidence before opinion", "Blocking needs a tool result or a data proof; AI findings are labeled as suggestions."),
             ("Built for data code", "Catches join fan-out, NULL traps, dropped rows, and unguarded division in SQL and pandas."),
             ("Low noise", "At most 5 AI findings per PR, ranked, with style left to the linter."),
             ("Human in the loop", "Draft code and tests are posted for review and never committed automatically.")]
    cols = st.columns(4)
    for col, (title, text) in zip(cols, diffs):
        col.markdown(f'<div class="gl-card"><h4>{title}</h4><p>{text}</p></div>', unsafe_allow_html=True)
    st.write("")
    st.caption(f"Python · Groq LLM · GitHub Actions · GitHub REST API · pytest · Bandit · Ruff · SQLite · Streamlit · Docker  ·  "
               f"[Source code]({LINKS['GitHub repo']})")

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
