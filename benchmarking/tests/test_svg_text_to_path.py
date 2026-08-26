from pathlib import Path

from benchmarking.svg_text_to_path import convert_svg_text_to_paths


def test_svg_text_is_converted_to_portable_paths(tmp_path: Path) -> None:
    svg = tmp_path / "figure.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100">'
        '<text x="150" y="50" text-anchor="middle" font-size="20" font-weight="700" fill="#123456">Figure 3 · AKT1</text>'
        '</svg>',
        encoding="utf-8",
    )
    assert convert_svg_text_to_paths(svg) == 1
    rendered = svg.read_text(encoding="utf-8")
    assert "<text" not in rendered
    assert "<path" in rendered
    assert 'aria-label="Figure 3 · AKT1"' in rendered
    assert "#123456" in rendered
