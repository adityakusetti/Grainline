"""Settings, read from grainline.toml in the repository root if present."""
import os
import tomllib
from dataclasses import dataclass, field


@dataclass
class Config:
    model: str = "openai/gpt-oss-120b"
    max_ai_findings: int = 5            # noise budget: at most this many AI comments per PR
    review_extensions: tuple = (".py", ".sql")
    models_dir: str = "models"          # SQL models checked by the data proof
    fixtures_dir: str = "fixtures"      # CSV files loaded as tables for the data proof
    tests_dir: str = "tests"
    coverage_threshold: float = 70.0
    ready_score: int = 80
    reports_dir: str = "reports"
    extra: dict = field(default_factory=dict)


def load(path="grainline.toml"):
    """Accepts keys at the top level or under a [grainline] table."""
    cfg = Config()
    if os.path.exists(path):
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        data = data.get("grainline", data)
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, tuple(v) if k == "review_extensions" else v)
    if os.environ.get("REVIEW_MODEL"):
        cfg.model = os.environ["REVIEW_MODEL"]
    for key in ("models_dir", "fixtures_dir", "tests_dir"):
        if os.environ.get(f"GRAINLINE_{key.upper()}"):
            setattr(cfg, key, os.environ[f"GRAINLINE_{key.upper()}"])
    return cfg
