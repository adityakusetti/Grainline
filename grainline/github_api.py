"""GitHub REST API: changed files, file contents at a commit, issues, and single self-updating comments."""
import base64
import os
import re

from . import http

API = "https://api.github.com"


def _h():
    return {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def get_changed_files(repo, pr):
    files, page = [], 1
    while True:
        batch = http.request("GET", f"{API}/repos/{repo}/pulls/{pr}/files", headers=_h(),
                             params={"per_page": 100, "page": page}).json()
        files += [{"filename": f["filename"], "status": f["status"], "patch": f.get("patch", "")} for f in batch]
        if len(batch) < 100:
            return files
        page += 1


def file_at(repo, path, ref):
    """Return the file's text at a commit, or None if it did not exist there."""
    try:
        data = http.request("GET", f"{API}/repos/{repo}/contents/{path}", headers=_h(), params={"ref": ref}, retries=1).json()
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None


def comment_bodies(repo, number):
    return [c.get("body", "") for c in http.request("GET", f"{API}/repos/{repo}/issues/{number}/comments",
                                                     headers=_h(), params={"per_page": 100}).json()]


def linked_issue(pr_body):
    m = re.search(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", pr_body or "", re.I)
    return int(m.group(1)) if m else None


def find_marker(comments, marker):
    return next((c for c in comments if marker in c.get("body", "")), None)


def upsert_comment(repo, number, body, marker):
    body = f"{marker}\n{body}"
    comments = http.request("GET", f"{API}/repos/{repo}/issues/{number}/comments", headers=_h(),
                            params={"per_page": 100}).json()
    existing = find_marker(comments, marker)
    if existing:
        http.request("PATCH", f"{API}/repos/{repo}/issues/comments/{existing['id']}", headers=_h(), json={"body": body})
    else:
        http.request("POST", f"{API}/repos/{repo}/issues/{number}/comments", headers=_h(), json={"body": body})
