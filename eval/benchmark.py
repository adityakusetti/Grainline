"""Benchmark: planted bugs (code, data, security) plus clean changes.
Compares an LLM-only reviewer with Grainline (LLM + deterministic checks).
  python -m eval.benchmark --offline   deterministic layer only (no API key needed)
  GROQ_API_KEY=... python -m eval.benchmark"""
import os
import sys

from grainline import config, data_lint, review, security, threats
from grainline.diffs import code_to_diff

CASES = [
    {"name": "off_by_one", "expect": {"bug", "testing"}, "file": "pipeline/window.py",
     "patch": "@@ -1,2 +1,2 @@\n def last_n(rows, n):\n-    return rows[-n:]\n+    return rows[-n - 1:]"},
    {"name": "divide_by_zero", "expect": {"bug"}, "file": "metrics/rates.py",
     "patch": "@@ -1,2 +1,2 @@\n def fill_rate(bikes, docks):\n-    return bikes / docks if docks else 0.0\n+    return bikes / docks"},
    {"name": "mutable_default", "expect": {"bug"}, "file": "pipeline/batch.py",
     "patch": "@@ -1,3 +1,3 @@\n-def add_row(row, batch=None):\n-    batch = batch or []\n+def add_row(row, batch=[]):\n     batch.append(row)\n     return batch"},
    {"name": "sql_injection", "expect": {"security"}, "file": "db/query.py",
     "patch": "@@ -1,2 +1,2 @@\n def station(cur, name):\n-    cur.execute(\"SELECT * FROM stations WHERE name = %s\", (name,))\n"
              "+    cur.execute(f\"SELECT * FROM stations WHERE name = '{name}'\")"},
    {"name": "hardcoded_secret", "expect": {"security"}, "file": "config.py",
     "patch": "@@ -1,1 +1,2 @@\n import os\n+GROQ_API_KEY = \"gsk_abcdefghijklmnopqrstuvwxyz123456\""},
    {"name": "left_join_where", "expect": {"data", "bug"}, "file": "models/active_sellers.sql",
     "patch": code_to_diff("SELECT s.seller_id, COUNT(o.order_id) AS orders\nFROM sellers s\nLEFT JOIN orders o ON s.seller_id = o.seller_id\n"
                           "WHERE o.status = 'completed'\nGROUP BY s.seller_id")},
    {"name": "count_after_join", "expect": {"data", "bug"}, "file": "models/order_counts.sql",
     "patch": code_to_diff("SELECT o.seller_id, COUNT(*) AS orders\nFROM orders o\nJOIN refunds r ON o.order_id = r.order_id\nGROUP BY o.seller_id")},
    {"name": "not_in_null", "expect": {"data", "bug"}, "file": "models/no_refunds.sql",
     "patch": code_to_diff("SELECT order_id FROM orders\nWHERE order_id NOT IN (SELECT order_id FROM refunds)")},
    {"name": "merge_fanout", "expect": {"data", "bug"}, "file": "pipeline/enrich.py",
     "patch": "@@ -1,2 +1,2 @@\n def enrich(trips, stations):\n-    return trips.merge(stations, on='station_id', validate='many_to_one')\n"
              "+    return trips.merge(stations, on='station_id')"},
    {"name": "obfuscated_exec", "expect": {"security"}, "file": "pipeline/loader.py",
     "patch": code_to_diff("import base64\npayload = load_config()['blob']\nexec(base64.b64decode(payload))")},
    {"name": "phishing_link", "expect": {"security"}, "file": "docs/setup.md",
     "patch": code_to_diff("To get access, sign in at https://github-account-verify.xyz/login with your company password.")},
    {"name": "pii_in_fixture", "expect": {"privacy"}, "file": "fixtures/customers.csv",
     "patch": code_to_diff("customer_id,email,ssn\n1,jane.doe@gmail.com,123-45-6789")},
    {"name": "clean_python", "expect": set(), "file": "utils/names.py",
     "patch": "@@ -1,2 +1,2 @@\n def norm(name):\n-    return name.lower()\n+    return name.strip().lower()"},
    {"name": "clean_docs", "expect": set(), "file": "docs/links.md",
     "patch": code_to_diff("Docs: https://docs.python.org/3/ and https://github.com/adityakusetti/grainline")},
    {"name": "clean_sql", "expect": set(), "file": "models/daily_trips.sql",
     "patch": code_to_diff("SELECT trip_date, COUNT(trip_id) AS trips\nFROM trips\nGROUP BY trip_date")},
]


def deterministic(case):
    return (data_lint.lint(case["file"], case["patch"]) + security.scan(case["file"], case["patch"])
            + threats.scan(case["file"], case["patch"]))


def categories(findings, min_sev=("high", "medium", "low")):
    return {f.category for f in findings if f.severity in min_sev}


def ai_categories(case, cfg):
    files = [{"filename": case["file"], "status": "modified", "patch": case["patch"]}]
    return categories(review.review_diff(files, cfg.model, cfg.max_ai_findings).findings, ("high", "medium"))


def score(rows, key):
    """rows: dicts with 'expect' and per-config category sets. Returns caught, planted, false alarms, clean."""
    planted = [r for r in rows if r["expect"]]
    clean = [r for r in rows if not r["expect"]]
    caught = sum(bool(r["expect"] & r[key]) for r in planted)
    alarms = sum(bool(r[key]) for r in clean)
    return caught, len(planted), alarms, len(clean)


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


def main(offline, runs=1):
    cfg = config.load()
    totals = {"det": [0, 0, 0, 0], "ai": [0, 0, 0, 0], "both": [0, 0, 0, 0]}
    per_case = []
    for run in range(runs):
        rows = []
        for c in CASES:
            det = categories(deterministic(c))
            ai = set() if offline else ai_categories(c, cfg)
            rows.append({"name": c["name"], "expect": c["expect"], "det": det, "ai": ai, "both": det | ai})
        for key in totals:
            for i, v in enumerate(score(rows, key)):
                totals[key][i] += v
        per_case = rows
    print(f"Per-case results (last run of {runs}):")
    print(f"{'case':18s} {'expected':16s} {'deterministic':14s} {'LLM only':12s} Grainline")
    for r in per_case:
        def mark(key):
            if offline and key == "ai":
                return "-"
            if r["expect"]:
                return "caught" if r["expect"] & r[key] else "missed"
            return "false alarm" if r[key] else "ok"
        print(f"{r['name']:18s} {','.join(sorted(r['expect'])) or 'clean':16s} {mark('det'):14s} {mark('ai'):12s} {mark('both')}")
    table = ["| Configuration | Planted bugs caught | Detection rate | False alarms on clean changes | False-positive rate |",
             "|---|---|---|---|---|"]
    labels = {"det": "Deterministic checks only", "ai": "LLM only", "both": "Grainline (LLM + deterministic)"}
    for key, label in labels.items():
        if offline and key != "det":
            table.append(f"| {label} | not run | | | |")
            continue
        caught, planted, alarms, clean = totals[key]
        table.append(f"| {label} | {caught} / {planted} | {pct(caught, planted)} | {alarms} / {clean} | {pct(alarms, clean)} |")
    note = f" over {runs} runs" if runs > 1 else ""
    footer = f"Model: {cfg.model}{note}; {len(CASES) - sum(1 for c in CASES if not c['expect'])} planted bugs and " \
             f"{sum(1 for c in CASES if not c['expect'])} clean changes per run. Counts are summed across runs."
    print("\nMarkdown table for the README:\n")
    print("\n".join(table))
    print("\n" + footer)
    return table, footer, per_case


if __name__ == "__main__":
    args = sys.argv[1:]
    runs = int(args[args.index("--runs") + 1]) if "--runs" in args else 1
    table, footer, per_case = main("--offline" in args or not os.environ.get("GROQ_API_KEY"), runs)
    if "--markdown-out" in args:
        with open(args[args.index("--markdown-out") + 1], "w") as fh:
            fh.write("## Grainline benchmark\n\n" + "\n".join(table) + "\n\n" + footer + "\n")
