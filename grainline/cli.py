"""GitHub Actions entry points.
  python -m grainline.cli pr      review a pull request
  python -m grainline.cli issue   analyze an issue (and draft code when labeled grainline-suggest)"""
import json
import os
import pathlib
import sys

from . import codegen, config, github_api, pipeline, report, requirements_ai

PR_MARKER = "<!-- grainline-pr -->"
REQ_COMMENT = "<!-- grainline-req-comment -->"
CODE_COMMENT = "<!-- grainline-code-comment -->"
SUGGEST_LABEL = "grainline-suggest"


def _event():
    return json.loads(pathlib.Path(os.environ["GITHUB_EVENT_PATH"]).read_text())


def _save(cfg, name, record):
    out = pathlib.Path(cfg.reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(record, indent=2, default=str))


def cmd_pr(cfg):
    repo, ev = os.environ["GITHUB_REPOSITORY"], _event()
    pr = ev["pull_request"]
    files = github_api.get_changed_files(repo, pr["number"])
    req, issue = None, github_api.linked_issue(pr.get("body"))
    if issue:
        req = requirements_ai.extract(github_api.comment_bodies(repo, issue))
    base = pr["base"]["sha"]
    result = pipeline.run(files, cfg, old_text=lambda p: github_api.file_at(repo, p, base), req=req)
    body = report.to_markdown(result["review"], result["findings"], result["tests"], result["bandit"], result["ruff"],
                              result["proofs"], result["suggested"], result["explanations"], result["trace"], result["readiness"])
    github_api.upsert_comment(repo, pr["number"], body, PR_MARKER)
    _save(cfg, f"pr-{pr['number']}.json", report.to_record(
        repo, pr["number"], result["files"], result["review"], result["findings"], result["tests"], result["bandit"],
        result["ruff"], result["proofs"], result["trace"], result["readiness"], pr.get("created_at")))
    print(f"Grainline verdict: {result['readiness']['verdict']} ({result['readiness']['score']}/100)")
    if os.environ.get("GRAINLINE_FAIL_ON_BLOCK") == "1" and result["readiness"]["verdict"] == "Blocked":
        sys.exit(1)


def cmd_issue(cfg):
    repo, ev = os.environ["GITHUB_REPOSITORY"], _event()
    issue = ev["issue"]
    if "pull_request" in issue:
        return
    req = requirements_ai.analyze(issue["title"], issue.get("body"), cfg.model)
    github_api.upsert_comment(repo, issue["number"], requirements_ai.to_markdown(req) + "\n" + requirements_ai.embed(req), REQ_COMMENT)
    record = {"repo": repo, "issue": issue["number"], "requirements": req.to_dict()}
    labels = [l["name"] for l in issue.get("labels", [])]
    if SUGGEST_LABEL in labels:
        draft = codegen.draft(req, cfg.model)
        github_api.upsert_comment(repo, issue["number"], codegen.to_markdown(draft), CODE_COMMENT)
        record["draft_files"] = [f["path"] for f in draft["files"]]
    _save(cfg, f"issue-{issue['number']}.json", record)
    print(f"Requirements: {len(req.acceptance_criteria)} acceptance criteria, {len(req.tasks)} tasks")


def main():
    cfg = config.load()
    {"pr": cmd_pr, "issue": cmd_issue}[sys.argv[1] if len(sys.argv) > 1 else "pr"](cfg)


if __name__ == "__main__":
    main()
