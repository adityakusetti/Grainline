"""Grainline web app: try the reviewer, analyze requirements, run a data proof, and view release history."""
import glob
import json
import os
import sys

import pandas as pd
import streamlit as st

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from grainline import config, data_lint, data_proof, docs_check, github_api, pipeline, report, requirements_ai, review, security, threats  # noqa: E402
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


try:
    import plotly.express as px
    import plotly.graph_objects as go
except ImportError:          # charts fall back to Streamlit's built-ins
    px = go = None

VERDICT_COLORS = {"Ready": "#2F855A", "Needs Review": "#B7791F", "Blocked": "#C53030"}


@st.cache_data(show_spinner=False)
def cached_query(sql):
    return data_proof.run_query(sql, FIXTURES)


@st.cache_data(show_spinner=False)
def cached_compare(old_sql, new_sql):
    return data_proof.compare(old_sql, new_sql, FIXTURES)


def score_gauge(score, verdict):
    """Release score as a gauge, colored by verdict."""
    if go is None:
        st.metric("Release score", f"{score}/100", verdict)
        return
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score, number={"suffix": " / 100"},
        title={"text": verdict, "font": {"size": 18, "color": VERDICT_COLORS.get(verdict, "#1F2933")}},
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": VERDICT_COLORS.get(verdict, "#B7791F")},
               "steps": [{"range": [0, 60], "color": "#FDECEC"}, {"range": [60, 80], "color": "#FDF3E1"},
                         {"range": [80, 100], "color": "#E8F5EC"}],
               "threshold": {"line": {"color": "#1F2933", "width": 3}, "value": CFG.ready_score}}))
    fig.update_layout(height=230, margin=dict(l=20, r=20, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def bar(series, title, colors=None):
    """Interactive bar chart with Plotly, or Streamlit's chart if Plotly is missing."""
    if px is None:
        st.bar_chart(series)
        return
    df_ = series.rename_axis("name").reset_index(name="count")
    fig = px.bar(df_, x="name", y="count", title=title, color="name",
                 color_discrete_map=colors or {}, text="count")
    fig.update_layout(height=320, showlegend=False, margin=dict(l=10, r=10, t=50, b=10), xaxis_title=None, yaxis_title=None)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def downloads(md_text, record, key):
    c1, c2 = st.columns(2)
    c1.download_button(":material/description: Download report (Markdown)", md_text, file_name=f"grainline-{key}.md",
                       mime="text/markdown", key=f"md-{key}", use_container_width=True)
    c2.download_button(":material/data_object: Download audit record (JSON)", json.dumps(record, indent=2, default=str),
                       file_name=f"grainline-{key}.json", mime="application/json", key=f"json-{key}", use_container_width=True)


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

tab_home, tab_pr, tab_review, tab_req, tab_proof, tab_hist = st.tabs(
    [":material/home: Overview", ":material/merge: Review a GitHub PR", ":material/code: Review code",
     ":material/checklist: Requirements", ":material/science: Data proof", ":material/history: Release history"])

with tab_pr:
    st.write("Paste a link to any **public** GitHub pull request. Grainline fetches the diff and runs the AI review, "
             "data lint, and secret checks. Tests and the data proof run when Grainline is installed in the repo itself.")
    url = st.text_input("Pull request URL", placeholder="https://github.com/owner/repo/pull/123",
                        help="Any public GitHub pull request. Private repos need Grainline installed as a GitHub Action.")
    if st.button("Review this PR", type="primary"):
        parsed = github_api.parse_pr_url(url)
        if not parsed:
            st.warning("That doesn't look like a GitHub pull request link.")
        else:
            repo, number = parsed
            try:
                with st.spinner(f"Fetching {repo} #{number}..."):
                    pr_info = github_api.get_pr(repo, number)
                    files = github_api.get_changed_files(repo, number)
            except Exception as e:
                files = None
                st.error(f"Couldn't fetch that PR. Is the repository public? ({e})")
            if files is not None:
                st.markdown(f"**[{pr_info.get('title', 'Pull request')}]({url})** · {len(files)} changed file(s)")
                reviewable = [f for f in files if f["status"] != "removed" and
                              f["filename"].endswith(CFG.review_extensions + pipeline.THREAT_SCAN_EXT)]
                if not reviewable:
                    st.info("No code, data, docs, or workflow changes to review in this PR.")
                else:
                    with st.spinner("Reviewing..."):
                        result = pipeline.run(reviewable, CFG, new_text=lambda p: None, run_tools=False,
                                              use_ai=ai_allowed())
                    if result["review"].summary and result["review"].summary != "AI review skipped.":
                        st.write(result["review"].summary)
                    fs = result["findings"]
                    ready = result["readiness"]
                    g, m = st.columns([1, 2])
                    with g:
                        score_gauge(ready["score"], ready["verdict"])
                    with m:
                        k1, k2, k3 = st.columns(3)
                        k1.metric("Files reviewed", len(reviewable))
                        k2.metric("Findings", len(fs))
                        k3.metric("High severity", sum(f.severity == "high" for f in fs),
                                  help="High-severity findings from the AI or deterministic rules.")
                        st.caption("Partial review: tests and the data proof run when Grainline is installed in the repo, "
                                   "so this verdict can be Needs Review at best.")
                    if fs:
                        st.dataframe(findings_df(fs), hide_index=True, use_container_width=True)
                    else:
                        st.success("No issues found.")
                    comment = report.to_markdown(result["review"], fs, result["tests"], result["bandit"], result["ruff"],
                                                 result["proofs"], result["suggested"], result["explanations"],
                                                 result["trace"], result["readiness"])
                    with st.expander("See the PR comment Grainline would post"):
                        st.markdown(comment)
                    record = report.to_record(repo, number, reviewable, result["review"], fs, result["tests"],
                                              result["bandit"], result["ruff"], result["proofs"], result["trace"], ready)
                    downloads(comment, record, f"{repo.replace('/', '-')}-{number}")

with tab_home:
    st.markdown("""
    <div class="gl-hero">
      <div class="gl-eyebrow">AI-assisted SDLC · data pipelines</div>
      <h1>Catch the data bugs that generic AI reviewers miss, with proof.</h1>
      <p>Grainline turns GitHub issues into acceptance criteria, reviews pull requests, runs the old and new SQL on
      fixture data to prove data bugs, and gives every release a verdict: Ready, Needs Review, or Blocked.</p>
    </div>""", unsafe_allow_html=True)
    stats = [("10", "connected SDLC stages"), ("10 / 12", "planted bugs caught offline"),
             ("0", "false alarms on clean changes"), ("26", "unit tests")]
    for col, (num, label) in zip(st.columns(4), stats):
        col.markdown(f'<div class="gl-stat"><b>{num}</b><span>{label}</span></div>', unsafe_allow_html=True)
    st.caption("Offline numbers use the deterministic checks only, on a small benchmark written with the rules.")

    st.subheader("Try it in one click")
    st.write("A pull request changes a net-sales model to join refunds directly. Grainline runs both versions on fixture data:")
    if st.button("▶ Run the data proof demo", type="primary"):
        good = open(os.path.join(EX_DIR, "models", "net_sales.sql")).read()
        bad = open(os.path.join(EX_DIR, "models", "net_sales_buggy.sql")).read()
        proof = cached_compare(good, bad)
        o, n = cached_query(good), cached_query(bad)
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
             ("02", "Review", "AI findings with a noise budget, plus SQL, pandas, security, phishing, and privacy checks."),
             ("03", "Data proof", "Old vs new SQL on fixture data: duplicates, dropped rows, changed values."),
             ("04", "Tests", "pytest with coverage, AI-suggested tests in a sandbox, and traceability to each criterion."),
             ("05", "Release", "A score out of 100 and a verdict. Only tools and data can block.")]
    for col, (num, title, text) in zip(st.columns(5), steps):
        col.markdown(f'<div class="gl-card"><div class="gl-step">{num}</div><h4>{title}</h4><p>{text}</p></div>',
                     unsafe_allow_html=True)

    st.subheader("What makes it different")
    diffs = [("Evidence before opinion", "Blocking needs a tool result or a data proof; AI findings are labeled as suggestions."),
             ("Built for data code", "Catches join fan-out, NULL traps, dropped rows, and unguarded division in SQL and pandas."),
             ("Security and privacy", "Flags malware-style code, phishing links, secrets, and personal data like card or SSN numbers."),
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
    names = list(examples)
    if hasattr(st, "pills"):
        choice = st.pills("Load an example", names, default=names[0], key="ex",
                          help="Each example contains one planted bug, except the clean ones.") or names[0]
    else:
        choice = st.selectbox("Load an example", names, key="ex")
    filename = st.text_input("File name", value=examples[choice][1],
                             help="The extension decides which rules run: .sql for SQL rules, .py for pandas and Python rules.")
    text = st.text_area("Python or SQL code, or a diff", value=examples[choice][0], height=240,
                        help="Plain code is treated as a newly added file. A unified diff is reviewed as a change.")
    if st.button("Review", type="primary"):
        if not text.strip() or len(text) > MAX_CHARS:
            st.warning(f"Paste between 1 and {MAX_CHARS:,} characters.")
        else:
            patch = code_to_diff(text)
            det = data_lint.lint(filename, patch) + security.scan(filename, patch) + threats.scan(filename, patch) + \
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
    title = st.text_input("Title", value="Net sales report by seller", help="Like a GitHub issue title.")
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
    old_sql = c1.text_area("Old SQL", value=good, height=300, help="The model before the pull request.")
    new_sql = c2.text_area("New SQL", value=bad, height=300,
                           help="The model after the pull request. Declare the grain, for example `-- grain: seller_id`, "
                                "so duplicate keys can be detected.")
    with st.expander("Fixture tables"):
        for p in sorted(glob.glob(os.path.join(FIXTURES, "*.csv"))):
            st.caption(os.path.basename(p))
            st.dataframe(pd.read_csv(p), hide_index=True)
    if st.button("Run data proof", type="primary"):
        proof = cached_compare(old_sql, new_sql)
        st.metric("Result", proof["status"].upper())
        st.dataframe(pd.DataFrame([{k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in c.items()}
                                   for c in proof["checks"]]), hide_index=True, use_container_width=True)
        fs = data_proof.to_findings("model.sql", proof) + data_lint.lint("model.sql", code_to_diff(new_sql))
        if fs:
            st.dataframe(findings_df(fs), hide_index=True, use_container_width=True)
        try:
            o, n = cached_query(old_sql), cached_query(new_sql)
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
        bar(df.verdict.value_counts(), "Verdicts", VERDICT_COLORS)
        allf = pd.DataFrame([dict(f, pr=r["pr"]) for r in recs for f in r["findings"]])
        if len(allf):
            bar(allf.source.str.split(":").str[0].value_counts(), "Findings by source")
            if px is not None and len(df) > 1:
                fig = px.line(df.sort_values("reviewed_at"), x="reviewed_at", y="score", markers=True,
                              title="Release score over time", hover_data=["pr", "verdict"])
                fig.add_hline(y=CFG.ready_score, line_dash="dash", annotation_text="Ready threshold")
                fig.update_layout(height=320, margin=dict(l=10, r=10, t=50, b=10), xaxis_title=None, yaxis_title=None)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.subheader("Pull requests")
        st.dataframe(df, hide_index=True, use_container_width=True)
