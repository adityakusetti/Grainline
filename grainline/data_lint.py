"""Deterministic data-correctness rules for SQL and pandas: the bugs generic reviewers miss."""
import re

from .diffs import added_lines, new_text
from .schemas import Finding


def _f(path, line, sev, msg, fix, rule):
    return Finding(file=path, line=line, severity=sev, category="data", message=msg, suggestion=fix,
                   source=f"data-lint:{rule}", evidence=f"rule {rule}")


def lint_sql(path, patch):
    findings, added = [], added_lines(patch)
    text = new_text(patch)
    low = text.lower()
    has_join = re.search(r"\bjoin\b", low) is not None
    for n, line in added:
        l = line.lower()
        if re.search(r"select\s+\*", l):
            findings.append(_f(path, n, "low", "SELECT * pulls every column, so upstream schema changes leak into this model.",
                               "List the columns you need.", "select-star"))
        if re.search(r"count\(\s*\*\s*\)", l) and has_join:
            findings.append(_f(path, n, "medium", "COUNT(*) after a join counts duplicated rows if the join fans out.",
                               "Use COUNT(DISTINCT <key>) or aggregate before joining.", "count-after-join"))
        if re.search(r"not\s+in\s*\(\s*select", l):
            findings.append(_f(path, n, "medium", "NOT IN (SELECT ...) returns no rows if the subquery yields any NULL.",
                               "Use NOT EXISTS, or filter NULLs in the subquery.", "not-in-null"))
        if re.search(r"[\w\)]\s*/\s*(?!nullif)[a-z_\(]", l) and "nullif" not in l:
            findings.append(_f(path, n, "medium", "Division with no zero guard can fail or return NULL when the denominator is 0.",
                               "Wrap the denominator in NULLIF(x, 0).", "divide-no-guard"))
    # LEFT JOIN whose right-hand table is filtered in WHERE: silently becomes an INNER JOIN
    for alias in re.findall(r"left\s+join\s+\w+(?:\s+as)?\s+(\w+)", low):
        where = low.split("where", 1)[1] if "where" in low else ""
        where = re.split(r"\bgroup\s+by\b|\border\s+by\b", where)[0]
        if re.search(rf"\b{re.escape(alias)}\.\w+\s*(=|<|>|like|in\b)", where) and "is null" not in where:
            line = next((n for n, l in added if "where" in l.lower()), None)
            findings.append(_f(path, line, "high",
                               f"WHERE filters on the LEFT JOINed table '{alias}', which drops unmatched rows (it acts like an INNER JOIN).",
                               "Move that condition into the ON clause.", "left-join-where"))
    return findings


def lint_python(path, patch):
    findings = []
    for n, line in added_lines(patch):
        if re.search(r"def \w+\([^)]*=\s*(\[\]|\{\}|set\(\))", line):
            findings.append(Finding(file=path, line=n, severity="medium", category="bug",
                                    message="Mutable default argument is shared between calls.",
                                    suggestion="Default to None and create the list or dict inside the function.",
                                    source="py-lint:mutable-default", evidence="rule mutable-default"))
        if re.search(r"\.execute\(\s*f[\"']", line) or re.search(r"\.execute\([^)]*(%\s*\(|\.format\()", line):
            findings.append(Finding(file=path, line=n, severity="high", category="security",
                                    message="SQL built with string formatting can allow SQL injection.",
                                    suggestion="Pass values as query parameters, for example execute(sql, (value,)).",
                                    source="py-lint:sql-string-format", evidence="rule sql-string-format"))
        if re.search(r"\.merge\(", line) and "validate=" not in line:
            findings.append(_f(path, n, "low", "pandas merge without validate= can silently duplicate rows (fan-out).",
                               "Add validate='one_to_one' or 'many_to_one'.", "merge-no-validate"))
        if re.search(r"\.drop_duplicates\(\s*\)", line):
            findings.append(_f(path, n, "low", "drop_duplicates() with no subset only drops rows identical in every column.",
                               "Pass subset=[...] with the real key columns.", "dedupe-no-subset"))
        if re.search(r"pd\.to_datetime\([^)]*\)", line) and "utc" not in line and "format=" not in line:
            findings.append(_f(path, n, "low", "to_datetime without format= or utc= can parse dates inconsistently.",
                               "Pass format= and utc=True where it applies.", "datetime-no-format"))
    return findings


def lint(path, patch):
    if path.endswith(".sql"):
        return lint_sql(path, patch)
    if path.endswith(".py"):
        return lint_python(path, patch)
    return []
