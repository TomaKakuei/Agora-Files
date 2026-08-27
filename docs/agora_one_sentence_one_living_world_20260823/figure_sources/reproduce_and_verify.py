#!/usr/bin/env python3
"""Rebuild every paper figure and verify the publication PNGs exactly."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parent
PAPER_DIR = SOURCE_DIR.parent
OUTPUT_DIR = PAPER_DIR / "reproduced_figures"
PUBLICATION_DIR = PAPER_DIR / "figures"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    commands = (
        [sys.executable, str(SOURCE_DIR / "make_generation_figures.py")],
        [sys.executable, str(SOURCE_DIR / "make_social_figures.py")],
    )
    for command in commands:
        subprocess.run(command, cwd=PAPER_DIR, check=True)

    publication_pngs = sorted(PUBLICATION_DIR.glob("*.png"))
    if len(publication_pngs) != 11:
        raise RuntimeError(f"Expected 11 publication PNGs, found {len(publication_pngs)}")

    mismatches: list[str] = []
    for publication in publication_pngs:
        reproduced = OUTPUT_DIR / publication.name
        if not reproduced.is_file() or sha256(publication) != sha256(reproduced):
            mismatches.append(publication.name)

    if mismatches:
        print("PNG verification failed: " + ", ".join(mismatches), file=sys.stderr)
        return 1
    print("Verified 11/11 publication PNGs against freshly rendered outputs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
