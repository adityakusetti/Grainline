"""Code assistant: a draft implementation for approved requirements, posted for a human to review. Never applied automatically."""
from . import llm

SYSTEM = """You are a senior Python engineer. Write a minimal, correct draft implementation for the tasks and
acceptance criteria below, plus pytest tests named after the acceptance criteria (test_ac_1_..., test_ac_2_...).
Respond with JSON only: {"files": [{"path": str, "content": str, "explanation": str}], "notes": str}"""


def draft(req, model, max_files=4):
    if not req.acceptance_criteria:
        return {"files": [], "notes": "No acceptance criteria yet, so no draft was generated."}
    spec = "\n".join([f"{a['id']}: Given {a['given']}, when {a['when']}, then {a['then']}" for a in req.acceptance_criteria] +
                     [f"{t['id']}: {t['title']}" for t in req.tasks])
    data = llm.chat_json(SYSTEM, spec, model) or {}
    files = [f for f in data.get("files") or [] if isinstance(f, dict) and isinstance(f.get("path"), str)
             and isinstance(f.get("content"), str) and ".." not in f["path"] and not f["path"].startswith("/")][:max_files]
    return {"files": files, "notes": str(data.get("notes") or "")}


def to_markdown(result):
    md = ["## 🛠️ Grainline draft implementation", "",
          "_Draft for human review. Nothing has been committed; copy what you want into a branch._", ""]
    if not result["files"]:
        md.append(result["notes"] or "No draft was generated.")
    for f in result["files"]:
        lang = "sql" if f["path"].endswith(".sql") else "python"
        md += [f"<details><summary><code>{f['path']}</code></summary>", "", f.get("explanation", ""), "",
               f"```{lang}", f["content"].strip(), "```", "</details>", ""]
    if result["notes"] and result["files"]:
        md += ["", result["notes"]]
    return "\n".join(md)
