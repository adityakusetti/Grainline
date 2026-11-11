"""Data proof: run the old and new version of a changed SQL model on fixture data and compare the outputs.

A finding only blocks a release when the data shows it: new duplicate keys (fan-out), a query that no longer runs,
or removed columns. Changed values and row counts are reported for review, with examples.
"""
import csv
import glob
import os
import re
import sqlite3

from .schemas import Finding

GRAIN = re.compile(r"--[ \t]*grain:[ \t]*([\w, \t]+)", re.I)


def grain_of(sql):
    m = GRAIN.search(sql or "")
    return [c.strip() for c in m.group(1).split(",") if c.strip()] if m else []


def _convert(v):
    if v == "":
        return None
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def load_fixtures(conn, fixtures_dir):
    """Every CSV in fixtures_dir becomes a table named after the file."""
    names = []
    for path in sorted(glob.glob(os.path.join(fixtures_dir, "*.csv"))):
        table = os.path.splitext(os.path.basename(path))[0]
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            continue
        cols = list(rows[0].keys())
        conn.execute(f'CREATE TABLE "{table}" ({", ".join(f"{c!r}" for c in cols)})'.replace("'", '"'))
        conn.executemany(f'INSERT INTO "{table}" VALUES ({", ".join("?" for _ in cols)})',
                         [[_convert(r[c]) for c in cols] for r in rows])
        names.append(table)
    return names


def run_query(sql, fixtures_dir):
    conn = sqlite3.connect(":memory:")
    try:
        load_fixtures(conn, fixtures_dir)
        cur = conn.execute(sql.strip().rstrip(";"))
        cols = [d[0] for d in cur.description]
        return cols, [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def _dup_keys(rows, grain):
    seen, dups = {}, 0
    for r in rows:
        k = tuple(r.get(g) for g in grain)
        seen[k] = seen.get(k, 0) + 1
    return sum(1 for c in seen.values() if c > 1)


def _null_rate(rows, col):
    return 100.0 * sum(r.get(col) is None for r in rows) / len(rows) if rows else 0.0


def compare(old_sql, new_sql, fixtures_dir):
    """Return a dict describing how the model's output changed on the fixtures."""
    grain = grain_of(new_sql) or grain_of(old_sql)
    result = {"grain": grain, "status": "ok", "checks": []}
    try:
        new_cols, new_rows = run_query(new_sql, fixtures_dir)
    except sqlite3.Error as e:
        result.update(status="block", checks=[{"check": "runs", "verdict": "block", "detail": f"New query fails on fixtures: {e}"}])
        return result
    old_cols, old_rows = ([], [])
    if old_sql:
        try:
            old_cols, old_rows = run_query(old_sql, fixtures_dir)
        except sqlite3.Error:
            old_sql = None
    checks = result["checks"]
    checks.append({"check": "row_count", "old": len(old_rows) if old_sql else None, "new": len(new_rows),
                   "verdict": "review" if old_sql and len(old_rows) != len(new_rows) else "ok"})
    if grain:
        missing = [g for g in grain if g not in new_cols]
        if missing:
            checks.append({"check": "grain_columns", "verdict": "block", "detail": f"Grain columns missing from output: {missing}"})
        else:
            new_d = _dup_keys(new_rows, grain)
            old_d = _dup_keys(old_rows, grain) if old_sql else 0
            checks.append({"check": "duplicate_keys", "old": old_d if old_sql else None, "new": new_d,
                           "verdict": "block" if new_d > old_d else "ok"})
    if old_sql:
        removed = [c for c in old_cols if c not in new_cols]
        checks.append({"check": "columns", "removed": removed, "added": [c for c in new_cols if c not in old_cols],
                       "verdict": "block" if removed else "ok"})
        for c in [c for c in new_cols if c in old_cols]:
            o, n = _null_rate(old_rows, c), _null_rate(new_rows, c)
            if n - o >= 10:
                checks.append({"check": "null_rate", "column": c, "old": round(o, 1), "new": round(n, 1), "verdict": "review"})
        if grain and all(g in old_cols for g in grain) and all(g in new_cols for g in grain):
            old_by = {tuple(r[g] for g in grain): r for r in old_rows}
            changed = []
            for r in new_rows:
                k = tuple(r[g] for g in grain)
                if k in old_by:
                    for c in new_cols:
                        if c in old_by[k] and c not in grain and old_by[k][c] != r[c]:
                            changed.append({"key": list(k), "column": c, "old": old_by[k][c], "new": r[c]})
            if changed:
                checks.append({"check": "changed_values", "count": len(changed), "examples": changed[:5], "verdict": "review"})
    verdicts = [c["verdict"] for c in checks]
    result["status"] = "block" if "block" in verdicts else "review" if "review" in verdicts else "ok"
    return result


def to_findings(path, proof):
    """Turn data-proof results into findings with evidence."""
    out = []
    for c in proof["checks"]:
        if c["verdict"] == "ok":
            continue
        sev = "high" if c["verdict"] == "block" else "medium"
        if c["check"] == "duplicate_keys":
            msg = f"Fan-out: {c['new']} duplicate grain key(s) on {proof['grain']} in the new output (was {c['old']})."
            fix = "Aggregate the joined table to one row per key before joining."
        elif c["check"] == "changed_values":
            ex = c["examples"][0]
            msg = f"{c['count']} value(s) changed on fixtures, e.g. {ex['column']} for key {ex['key']}: {ex['old']} -> {ex['new']}."
            fix = "Confirm the change is intended; if not, check joins and filters."
        elif c["check"] == "row_count":
            msg = f"Row count changed on fixtures: {c['old']} -> {c['new']}."
            fix = "Confirm rows were meant to be added or dropped."
        elif c["check"] == "columns":
            msg = f"Columns removed from the output: {c['removed']}; downstream users may break."
            fix = "Keep the columns or update downstream models."
        elif c["check"] == "null_rate":
            msg = f"NULL rate of {c['column']} rose from {c['old']}% to {c['new']}%."
            fix = "Check joins and COALESCE defaults."
        else:
            msg, fix = c.get("detail", c["check"]), "Fix the query so it runs on the fixtures."
        out.append(Finding(file=path, severity=sev, category="data", message=msg, suggestion=fix,
                           source=f"data-proof:{c['check']}", evidence="before/after run on fixture data"))
    return out
