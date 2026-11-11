"""Deterministic secret detection on added lines."""
import re

from .diffs import added_lines
from .schemas import Finding

PATTERNS = [
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("groq-key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("hardcoded-credential", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
]


def scan(path, patch):
    found = []
    for n, line in added_lines(patch):
        for rule, rx in PATTERNS:
            if rx.search(line):
                found.append(Finding(file=path, line=n, severity="high", category="security",
                                     message=f"Possible secret committed ({rule}).",
                                     suggestion="Remove it, rotate the credential, and load it from an environment variable or secret store.",
                                     source=f"secrets:{rule}", evidence="matched a secret pattern on an added line"))
                break
    return found
