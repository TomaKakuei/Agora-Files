#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CASES = (
    (
        "Cartographer Lung Exchange",
        "creator_20260727_233333_efa8235f_r001",
        "#e9c46a",
    ),
    (
        "Archive of Borrowed Gravity",
        "creator_20260728_002605_dd9ffc0c_r001",
        "#d95d39",
    ),
    (
        "Intertidal Embassy for Extinct Rivers",
        "creator_20260728_020032_6f7b670a_r001",
        "#2a9d8f",
    ),
    (
        "Night Market of Unfinished Weather",
        "creator_20260728_220950_e2278e2f_r001",
        "#f4d35e",
    ),
    (
        "Museum of Future Debts",
        "creator_20260728_223205_1924f12f_r001",
        "#ef233c",
    ),
)


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / filename
    if path.is_file():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _fit_contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    copy = image.convert("RGB")
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    return copy


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the five-world qualitative map figure.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/optimized_worlds_20260728/five_world_maps.png"),
    )
    args = parser.parse_args()

    root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    cell_width = 620
    image_height = 430
    label_height = 86
    gap = 28
    margin = 44
    header_height = 132
    canvas_width = margin * 2 + cell_width * 2 + gap
    canvas_height = header_height + margin + (image_height + label_height) * 3 + gap * 2
    canvas = Image.new("RGB", (canvas_width, canvas_height), "#121817")
    draw = ImageDraw.Draw(canvas)

    draw.text(
        (margin, 38),
        "Five Strict Multimodal Worlds",
        fill="#f5f7f2",
        font=_font(36, bold=True),
    )
    draw.text(
        (margin, 88),
        "World-authored visual canon | semantic FLUX props | compiler + live Pixel validation",
        fill="#a9b7b2",
        font=_font(19),
    )

    for index, (name, revision, accent) in enumerate(CASES):
        row, col = divmod(index, 2)
        if index == 4:
            col = 0
        x = margin + col * (cell_width + gap)
        y = header_height + margin + row * (image_height + label_height + gap)
        if index == 4:
            x = (canvas_width - cell_width) // 2

        source = (
            root
            / "frontend"
            / "assets"
            / "generated"
            / "world_asset_sets"
            / revision
            / "world_map_source.png"
        )
        if not source.is_file():
            raise FileNotFoundError(source)
        fitted = _fit_contain(Image.open(source), (cell_width - 16, image_height - 16))
        image_x = x + (cell_width - fitted.width) // 2
        image_y = y + (image_height - fitted.height) // 2

        draw.rounded_rectangle(
            (x, y, x + cell_width, y + image_height + label_height),
            radius=8,
            fill="#1b2321",
            outline="#34413e",
            width=2,
        )
        draw.rectangle((x, y, x + 8, y + image_height + label_height), fill=accent)
        canvas.paste(fitted, (image_x, image_y))
        draw.line(
            (x + 24, y + image_height, x + cell_width - 24, y + image_height),
            fill="#34413e",
            width=2,
        )
        draw.text(
            (x + 28, y + image_height + 20),
            name,
            fill="#f5f7f2",
            font=_font(23, bold=True),
        )
        draw.text(
            (x + 28, y + image_height + 53),
            "6 rooms | 12 agents | strict publish gate passed",
            fill="#a9b7b2",
            font=_font(16),
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, optimize=True)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
