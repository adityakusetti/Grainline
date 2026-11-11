"""Requirement-to-test traceability: which acceptance criteria have a test that names them."""
import glob
import os
import re

AC_IN_TEXT = re.compile(r"(?<![a-z])ac[-_ ]?(\d+)(?!\d)", re.I)


def ac_mentions(tests_dir="tests"):
    found = {}
    for path in glob.glob(os.path.join(tests_dir, "**", "test_*.py"), recursive=True):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for n in AC_IN_TEXT.findall(fh.read()):
                found.setdefault(f"AC-{int(n)}", []).append(os.path.relpath(path))
    return found


def coverage(req, mentions):
    """Map each acceptance criterion to the test files that reference it."""
    if not req or not req.acceptance_criteria:
        return {"linked": False, "covered": [], "missing": [], "map": {}}
    m = {a["id"]: sorted(set(mentions.get(a["id"], []))) for a in req.acceptance_criteria}
    return {"linked": True, "map": m, "covered": [k for k, v in m.items() if v], "missing": [k for k, v in m.items() if not v]}
