from __future__ import annotations

import argparse
import json
from pathlib import Path

from .constants import _read_json
from .compositor import render_map_asset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a readable structured room-part map asset directly from map_grid.json.")
    parser.add_argument("--map-grid", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tile-px", type=int, default=32)
    parser.add_argument("--margin-px", type=int, default=56)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    map_grid = _read_json(Path(args.map_grid).resolve())
    output_path = Path(args.output).resolve()
    render_map_asset(
        map_grid=map_grid,
        output_path=output_path,
        tile_px=args.tile_px,
        margin_px=args.margin_px,
    )
    print(json.dumps({"status": "ok", "output": str(output_path)}, ensure_ascii=False, indent=2))
