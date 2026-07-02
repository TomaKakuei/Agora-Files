#!/usr/bin/env python3
"""Build Phaser-ready agent sprite atlases from Agora_UI scenario data (Modularized CLI entrypoint)."""

from __future__ import annotations

import sys
from pathlib import Path

# Locate and add Agora_UI package root to sys.path for direct command line execution
package_root = Path(__file__).resolve().parent.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

# Re-exports to maintain 100% backward compatibility with automated unit tests
from asset_pipeline.agent_assets.core import main, parse_args, run_pipeline
from asset_pipeline.agent_assets.prompts import _build_prompt_bundle
from asset_pipeline.sprite_qa import run_combined_qa

if __name__ == "__main__":
    main()
