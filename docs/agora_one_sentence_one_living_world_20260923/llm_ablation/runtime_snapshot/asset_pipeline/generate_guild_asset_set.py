#!/usr/bin/env python3
"""Compatibility entrypoint for the world-neutral asset-set pipeline."""

from __future__ import annotations

from asset_pipeline.generate_world_asset_set_full import _generate_ai_map, main

__all__ = ["_generate_ai_map", "main"]


if __name__ == "__main__":
    main()
