from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PipelinePaths:
    package_root: Path
    output_root: Path
    event_root: Path
    asset_dir: Path
    revision: str
