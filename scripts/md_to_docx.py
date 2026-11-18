"""Convert docs/reflection.md to a styled Word document (docs/reflection.docx)."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION  # noqa: F401
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "reflection.md"
DST = ROOT / "docs" / "reflection.docx"

FONT = "Microsoft JhengHei"
MONO = "Consolas"
ACCENT = RGBColor(0x1F, 0x3A, 0x5F)

LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
TOKEN_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def set_run_font(run, name: str, size: float | None = None, bold: bool | None = None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def add_inline(paragraph, text: str, size: float = 10.5):
    text = LINK_RE.sub(r"\1", text)
    for piece in TOKEN_RE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            run = paragraph.add_run(piece[2:-2])
            set_run_font(run, FONT, size, bold=True)
        elif piece.startswith("`") and piece.endswith("`"):
            run = paragraph.add_run(piece[1:-1])
            set_run_font(run, MONO, size - 0.5)
            run.font.color.rgb = RGBColor(0xB0, 0x30, 0x30)
        else:
            run = paragraph.add_run(piece)
            set_run_font(run, FONT, size)


def shade(cell, hex_color: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def add_table(doc: Document, rows: list[list[str]]):
    widths = [0.55, 1.9, 1.25, 1.25, 1.25, 2.6]
    table = doc.add_table(rows=0, cols=len(rows[0]))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for r_idx, row in enumerate(rows):
        cells = table.add_row().cells
        for c_idx, value in enumerate(row):
            cell = cells[c_idx]
            cell.text = ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(2)
            add_inline(para, value, size=9)
            if c_idx < len(widths):
                cell.width = Cm(widths[c_idx])
            if r_idx == 0:
                shade(cell, "E8EEF7")
                for run in para.runs:
                    run.bold = True
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def build():
    lines = SRC.read_text(encoding="utf-8").splitlines()
    doc = Document()

    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    for attr in ("top_margin", "bottom_margin"):
        setattr(section, attr, Cm(2.0))
    for attr in ("left_margin", "right_margin"):
        setattr(section, attr, Cm(2.2))

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.paragraph_format.line_spacing = 1.25
    normal.paragraph_format.space_after = Pt(6)

    for name, size in (("Heading 1", 20), ("Heading 2", 13.5), ("Heading 3", 11.5)):
        style = doc.styles[name]
        style.font.name = FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = ACCENT
        style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        style.paragraph_format.space_before = Pt(12 if name != "Heading 1" else 0)
        style.paragraph_format.space_after = Pt(6)

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue

        if line.startswith("|"):
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                raw = lines[i].strip().strip("|")
                cells = [c.strip() for c in raw.split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells):
                    table_rows.append(cells)
                i += 1
            if table_rows:
                add_table(doc, table_rows)
            continue

        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            para = doc.add_heading(level=level)
            add_inline(para, heading.group(2), size={1: 20, 2: 13.5, 3: 11.5}[level])
            if level == 1:
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in para.runs:
                run.font.color.rgb = ACCENT
            i += 1
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", line)
        numbered = re.match(r"^(\d+)\.\s+(.*)$", line)
        if bullet:
            para = doc.add_paragraph(style="List Bullet")
            add_inline(para, bullet.group(1))
        elif numbered:
            para = doc.add_paragraph(style="List Number")
            add_inline(para, numbered.group(2))
        else:
            para = doc.add_paragraph()
            para.paragraph_format.first_line_indent = Cm(0)
            add_inline(para, line)
        i += 1

    doc.save(DST)
    return DST


if __name__ == "__main__":
    path = build()
    print(f"saved: {path} ({path.stat().st_size} bytes)")
