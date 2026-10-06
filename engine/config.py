"""Load the threshold config so no business rule hardcodes a number."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "thresholds.yaml"


def load_config(path: Path | str = DEFAULT_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)
