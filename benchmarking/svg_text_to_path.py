"""Convert simple publication SVG text nodes to portable glyph paths.

The benchmark figures intentionally use plain SVG.  Some manuscript preview
environments do not load external/system fonts even when the font is installed,
which can turn otherwise valid ASCII labels into missing-glyph boxes.  This
module outlines the text with the open DejaVu fonts bundled in the runner image.
"""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

REGULAR_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
BOLD_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace("px", ""))
    except (TypeError, ValueError):
        return default


def _outline_text(element: ET.Element, *, regular: TTFont, bold: TTFont) -> ET.Element:
    text = "".join(element.itertext())
    font_weight = str(element.attrib.get("font-weight") or "400").lower()
    font = bold if font_weight in {"bold", "600", "700", "800", "900"} else regular
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap() or {}
    units_per_em = float(font["head"].unitsPerEm)
    hmtx = font["hmtx"].metrics
    font_size = _float(element.attrib.get("font-size"), 16.0)
    scale = font_size / units_per_em

    glyphs: list[tuple[str, float]] = []
    total_advance = 0.0
    for character in text:
        glyph_name = cmap.get(ord(character), ".notdef")
        advance = float(hmtx.get(glyph_name, (units_per_em * 0.5, 0))[0])
        glyphs.append((glyph_name, total_advance))
        total_advance += advance

    x = _float(element.attrib.get("x"))
    y = _float(element.attrib.get("y"))
    anchor = element.attrib.get("text-anchor", "start")
    if anchor == "middle":
        x -= total_advance * scale / 2.0
    elif anchor == "end":
        x -= total_advance * scale

    group = ET.Element(f"{{{SVG_NS}}}g")
    for attribute in ("fill", "stroke", "opacity", "class"):
        if attribute in element.attrib:
            group.set(attribute, element.attrib[attribute])
    group.set("aria-label", text)

    for glyph_name, cursor in glyphs:
        if glyph_name == "space":
            continue
        pen = SVGPathPen(glyph_set)
        glyph_set[glyph_name].draw(pen)
        commands = pen.getCommands()
        if not commands:
            continue
        path = ET.SubElement(group, f"{{{SVG_NS}}}path")
        path.set("d", commands)
        path.set(
            "transform",
            f"translate({x + cursor * scale:.6f} {y:.6f}) scale({scale:.9f} {-scale:.9f})",
        )
    return group


def convert_svg_text_to_paths(path: str | Path) -> int:
    """Replace every SVG ``text`` node in *path* and return the count."""

    target = Path(path)
    if not REGULAR_FONT.is_file() or not BOLD_FONT.is_file():
        raise FileNotFoundError("DejaVu font files required for portable SVG outlining")
    tree = ET.parse(target)
    root = tree.getroot()
    regular = TTFont(REGULAR_FONT)
    bold = TTFont(BOLD_FONT)
    converted = 0
    try:
        for parent in root.iter():
            for index, child in enumerate(list(parent)):
                if child.tag != f"{{{SVG_NS}}}text":
                    continue
                parent.remove(child)
                parent.insert(index, _outline_text(child, regular=regular, bold=bold))
                converted += 1
    finally:
        regular.close()
        bold.close()
    tree.write(target, encoding="unicode", xml_declaration=False)
    return converted
