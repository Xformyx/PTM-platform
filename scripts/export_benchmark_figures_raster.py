"""Export benchmark SVG figures to PNG and PDF with a pixel-level non-empty check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cairosvg
from PIL import Image, ImageChops


def _non_empty_png(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        white = Image.new("RGB", rgb.size, "white")
        difference = ImageChops.difference(rgb, white)
        bbox = difference.getbbox()
        nonwhite = sum(1 for pixel in difference.getdata() if pixel != (0, 0, 0))
        total = rgb.width * rgb.height
        return {
            "path": str(path),
            "width_px": rgb.width,
            "height_px": rgb.height,
            "nonwhite_pixel_count": nonwhite,
            "nonwhite_fraction": round(nonwhite / total if total else 0.0, 8),
            "content_bbox": list(bbox) if bbox else None,
            "passed": bool(bbox and nonwhite > 1000),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--scale", type=float, default=2.0)
    args = parser.parse_args()
    source_dir = Path(args.figures_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, object]] = []
    for index in range(1, 5):
        source = source_dir / f"Fig{index}.svg"
        if not source.is_file():
            raise FileNotFoundError(source)
        png = output_dir / f"Fig{index}.png"
        pdf = output_dir / f"Fig{index}.pdf"
        cairosvg.svg2png(url=str(source), write_to=str(png), scale=args.scale, background_color="white")
        cairosvg.svg2pdf(url=str(source), write_to=str(pdf), background_color="white")
        check = _non_empty_png(png)
        check["pdf_path"] = str(pdf)
        check["svg_path"] = str(source)
        checks.append(check)
    payload = {
        "schema_version": "benchmark_figure_raster_qc.v1",
        "scale": args.scale,
        "passed": all(bool(item["passed"]) for item in checks),
        "figures": checks,
    }
    qc_path = output_dir / "figure_raster_qc.json"
    qc_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
