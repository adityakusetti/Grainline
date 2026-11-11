"""Defensive scans of added lines: suspicious code (malware-style patterns), phishing-style links, and privacy leaks.
These are heuristics that flag changes for a human to look at; they are not an antivirus."""
import ipaddress
import re
from urllib.parse import urlparse

from .diffs import added_lines
from .schemas import Finding

# ---------- suspicious code ----------
SUSPICIOUS = [
    ("download-and-run", "high", re.compile(r"(curl|wget)\b[^|\n]*\|\s*(ba|z)?sh\b", re.I),
     "Downloads a script and pipes it straight into a shell."),
    ("obfuscated-exec", "high", re.compile(r"\b(exec|eval)\s*\(\s*(base64\.b64decode|codecs\.decode|bytes\.fromhex|zlib\.decompress|marshal\.loads)", re.I),
     "Executes decoded or decompressed data, a common way to hide malicious code."),
    ("dynamic-exec", "medium", re.compile(r"(?<![\w.])(exec|eval)\s*\(\s*(?![\"'])", re.I),
     "Runs code built at runtime with exec or eval."),
    ("reverse-shell", "high", re.compile(r"(socket\.socket\(.*\)|\.connect\(\().*(subprocess|os\.dup2|/bin/(ba)?sh)", re.I),
     "Network socket combined with a shell, a typical reverse-shell pattern."),
    ("shell-injection", "medium", re.compile(r"(os\.system|subprocess\.(run|call|Popen|check_output))\([^)]*(f[\"']|\+|\.format\()", re.I),
     "Shell command built from variables can allow command injection."),
    ("shell-true", "low", re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True", re.I),
     "shell=True runs the command through a shell."),
    ("crypto-miner", "high", re.compile(r"\b(xmrig|stratum\+tcp://|coinhive|cryptonight)\b", re.I),
     "References a cryptocurrency miner or mining pool."),
    ("go-exec-shell", "medium", re.compile(r'exec\.Command\(\s*"(ba|z)?sh"\s*,\s*"-c"', re.I),
     "Go code runs a shell command string, which can allow command injection."),
    ("unsafe-deserialize", "medium", re.compile(r"\b(pickle\.loads?|yaml\.load)\s*\((?![^)]*SafeLoader)", re.I),
     "Deserializing untrusted data with pickle or yaml.load can run arbitrary code."),
]

# GitHub Actions risks, checked only in workflow files
WORKFLOW = [
    ("pr-target-checkout", "high", re.compile(r"pull_request_target", re.I),
     "pull_request_target runs with repository secrets; combined with checking out PR code it can leak them."),
    ("unpinned-action", "low", re.compile(r"uses:\s*[\w.-]+/[\w.-]+@(main|master|latest)\b", re.I),
     "Action pinned to a moving branch; pin to a release tag or commit SHA."),
]

# ---------- phishing-style links ----------
URL = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "ow.ly", "cutt.ly", "rebrand.ly", "shorturl.at"}
BRANDS = ["paypal", "github", "google", "microsoft", "apple", "amazon", "netflix", "facebook", "instagram", "bankofamerica", "chase", "wellsfargo"]
OFFICIAL = {"paypal.com", "github.com", "githubusercontent.com", "google.com", "microsoft.com", "apple.com", "amazon.com",
            "netflix.com", "facebook.com", "instagram.com", "bankofamerica.com", "chase.com", "wellsfargo.com"}
RISKY_TLDS = {".zip", ".mov", ".xyz", ".top", ".click", ".country", ".gq", ".tk", ".ml", ".cf"}
SAFE_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}


def url_risk(url):
    """Return (rule, reason) if a URL looks like phishing or a hidden destination, else None."""
    try:
        p = urlparse(url)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    if not host or host in SAFE_HOSTS:
        return None
    if "@" in (p.netloc or ""):
        return "userinfo-trick", "URL hides the real host after an @ sign."
    try:
        ip = ipaddress.ip_address(host)
        if not (ip.is_private or ip.is_loopback):
            return "raw-ip-link", "Link points to a raw public IP address instead of a domain."
        return None
    except ValueError:
        pass
    if host.startswith("xn--") or ".xn--" in host:
        return "punycode-domain", "Punycode domain can imitate a real brand with look-alike characters."
    if host in SHORTENERS:
        return "url-shortener", "Link shortener hides the real destination."
    if any(host.endswith(t) for t in RISKY_TLDS):
        return "risky-tld", f"Domain uses a top-level domain often seen in phishing ({host})."
    base = ".".join(host.split(".")[-2:])
    for brand in BRANDS:
        if brand in host.replace("-", "") and base not in OFFICIAL:
            return "brand-lookalike", f"'{host}' mentions {brand} but is not an official {brand} domain."
    if p.scheme == "http" and any(w in (p.path or "").lower() for w in ("login", "signin", "verify", "account", "password")):
        return "insecure-login", "Login or account page served over plain http."
    return None


# ---------- privacy ----------
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<!\d)(\+1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
PII_COLS = re.compile(r"\b(ssn|social_security|date_of_birth|dob|passport|credit_card|card_number|email|phone|home_address)\b", re.I)
LOGGING = re.compile(r"\b(print|logging\.\w+|logger\.\w+|log\.\w+)\s*\(", re.I)
EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net", "test.com", "noreply", "users.noreply.github.com")


def luhn_ok(digits):
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n > 4 else n * 2
        total, alt = total + n, not alt
    return total % 10 == 0


def _f(path, line, sev, cat, msg, fix, rule):
    return Finding(file=path, line=line, severity=sev, category=cat, message=msg, suggestion=fix,
                   source=f"{cat}:{rule}", evidence=f"rule {rule} on an added line")


def scan_suspicious(path, patch):
    out = []
    is_workflow = path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
    rules = SUSPICIOUS + (WORKFLOW if is_workflow else [])
    for n, line in added_lines(patch):
        if line.lstrip().startswith(("#", "--", "//")):
            continue
        for rule, sev, rx, why in rules:
            if rx.search(line):
                out.append(_f(path, n, sev, "security", f"Suspicious code: {why}",
                              "Confirm this is intended; remove it or replace it with a safer alternative.", rule))
                break
    return out


def scan_links(path, patch):
    out = []
    for n, line in added_lines(patch):
        for url in URL.findall(line):
            risk = url_risk(url.rstrip(".,;"))
            if risk:
                rule, why = risk
                out.append(_f(path, n, "medium", "security", f"Phishing-style link: {why}",
                              "Use the official domain, or remove the link.", rule))
    return out


def scan_privacy(path, patch):
    out = []
    data_file = path.endswith((".csv", ".json", ".jsonl", ".txt", ".tsv"))
    for n, line in added_lines(patch):
        for m in CARD.finditer(line):
            digits = re.sub(r"\D", "", m.group())
            if 13 <= len(digits) <= 19 and luhn_ok(digits) and len(set(digits)) > 2:
                out.append(_f(path, n, "high", "privacy", "Looks like a real payment card number (passes the Luhn check).",
                              "Remove it and use masked or synthetic test data.", "card-number"))
                break
        if SSN.search(line):
            out.append(_f(path, n, "high", "privacy", "Looks like a U.S. Social Security number.",
                          "Remove it and use synthetic data.", "ssn"))
        emails = [e for e in EMAIL.findall(line) if not e.lower().endswith(EXAMPLE_DOMAINS)]
        if emails and (data_file or LOGGING.search(line)):
            out.append(_f(path, n, "medium", "privacy",
                          "Personal email address in " + ("data committed to the repo." if data_file else "a log or print statement."),
                          "Use example.com addresses in fixtures, and mask emails before logging.", "email"))
        if PHONE.search(line) and data_file:
            out.append(_f(path, n, "low", "privacy", "Phone number in committed data.", "Use synthetic numbers.", "phone"))
        if path.endswith(".sql") and PII_COLS.search(line) and re.search(r"\bselect\b|^\s*[\w.]+\s*,?\s*$", line, re.I):
            out.append(_f(path, n, "low", "privacy", f"Query exposes a personal-data column ({PII_COLS.search(line).group(0)}).",
                          "Select it only if the output needs it, and mask or hash it otherwise.", "pii-column"))
        if path.endswith(".py") and LOGGING.search(line) and PII_COLS.search(line):
            out.append(_f(path, n, "medium", "privacy", "Personal data may be written to logs.",
                          "Mask or remove personal fields before logging.", "pii-in-logs"))
    return out


def scan(path, patch):
    return scan_suspicious(path, patch) + scan_links(path, patch) + scan_privacy(path, patch)
