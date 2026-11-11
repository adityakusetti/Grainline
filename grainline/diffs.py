"""Read unified diffs: which lines were added, and at which line number in the new file."""
import re

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_lines(patch):
    """Return [(new_line_number, text)] for every added line in a unified diff patch."""
    out, line_no = [], None
    for raw in (patch or "").splitlines():
        m = HUNK.match(raw)
        if m:
            line_no = int(m.group(1))
            continue
        if line_no is None or raw.startswith(("+++", "---")):
            continue
        if raw.startswith("+"):
            out.append((line_no, raw[1:]))
            line_no += 1
        elif raw.startswith("-"):
            continue
        else:
            line_no += 1
    return out


def new_text(patch):
    """Rebuild the new version of the changed region (context and added lines)."""
    lines = []
    for raw in (patch or "").splitlines():
        if HUNK.match(raw) or raw.startswith(("+++", "---", "-")):
            continue
        lines.append(raw[1:] if raw[:1] in ("+", " ") else raw)
    return "\n".join(lines)


def looks_like_diff(text):
    return any(l.startswith(("@@", "+++", "---")) for l in text.splitlines()[:20])


def code_to_diff(text):
    """Treat pasted plain code as a newly added file."""
    if looks_like_diff(text):
        return text
    lines = text.splitlines() or [""]
    return f"@@ -0,0 +1,{len(lines)} @@\n" + "\n".join("+" + l for l in lines)
