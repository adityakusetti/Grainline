"""Benchmark: planted bugs (code, data, security) plus clean changes.
Compares an LLM-only reviewer with Grainline (LLM + deterministic checks).
  python -m eval.benchmark --offline   deterministic layer only (no API key needed)
  GROQ_API_KEY=... python -m eval.benchmark"""
import os
import sys

from grainline import config, data_lint, review, security
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
    {"name": "clean_python", "expect": set(), "file": "utils/names.py",
     "patch": "@@ -1,2 +1,2 @@\n def norm(name):\n-    return name.lower()\n+    return name.strip().lower()"},
    {"name": "clean_sql", "expect": set(), "file": "models/daily_trips.sql",
     "patch": code_to_diff("SELECT trip_date, COUNT(trip_id) AS trips\nFROM trips\nGROUP BY trip_date")},
]


def deterministic(case):
    return data_lint.lint(case["file"], case["patch"]) + security.scan(case["file"], case["patch"])


def categories(findings, min_sev=("high", "medium", "low")):
    return {f.category for f in findings if f.severity in min_sev}


def main(offline):
    cfg = config.load()
    rows = []
    for c in CASES:
        det = categories(deterministic(c))
        ai = set() if offline else categories(review.review_diff(
            [{"filename": c["file"], "status": "modified", "patch": c["patch"]}], cfg.model, cfg.max_ai_findings).findings,
            ("high", "medium"))
        rows.append((c["name"], c["expect"], ai, det | ai))
    planted = [r for r in rows if r[1]]
    clean = [r for r in rows if not r[1]]
    hit = lambda exp, got: bool(exp & got)
    print(f"{'case':18s} {'expected':16s} {'LLM only':10s} Grainline")
    for name, exp, ai, both in rows:
        e = ",".join(sorted(exp)) or "clean"
        a = "-" if offline else ("caught" if hit(exp, ai) else "missed") if exp else ("false alarm" if ai else "ok")
        g = ("caught" if hit(exp, both) else "missed") if exp else ("false alarm" if both else "ok")
        print(f"{name:18s} {e:16s} {a:10s} {g}")
    g_caught = sum(hit(r[1], r[3]) for r in planted)
    g_fa = sum(bool(r[3]) for r in clean)
    print(f"\nGrainline: {g_caught}/{len(planted)} planted bugs caught, {g_fa}/{len(clean)} false alarms on clean changes")
    if not offline:
        a_caught = sum(hit(r[1], r[2]) for r in planted)
        a_fa = sum(bool(r[2]) for r in clean)
        print(f"LLM only:  {a_caught}/{len(planted)} planted bugs caught, {a_fa}/{len(clean)} false alarms on clean changes")
    else:
        print("(offline: deterministic checks only; run with GROQ_API_KEY to compare against the LLM)")


if __name__ == "__main__":
    main("--offline" in sys.argv or not os.environ.get("GROQ_API_KEY"))
