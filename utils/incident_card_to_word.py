from datetime import datetime
from pathlib import Path
import docx
from docx.shared import Pt
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.oxml.ns import qn
from docx.enum.style import WD_STYLE_TYPE

def clean_for_xml(s: str) -> str:
    """
    Remove characters that are illegal in XML (W3C spec).
    python-docx will crash if these appear.
    """
    if not s:
        return s

    return "".join(
        ch for ch in s
        if (
            ch == '\t' or ch == '\n' or ch == '\r' or
            (0x20 <= ord(ch) <= 0xD7FF) or
            (0xE000 <= ord(ch) <= 0xFFFD) or
            (0x10000 <= ord(ch) <= 0x10FFFF)
        )
    )


def incident_card_to_word(
    # Prompts
    identify_incident_prompt=None,
    identify_hazard_consequence_prompt=None,
    identify_accident_scenario_prompt=None,
    causal_edge_linking_prompt=None,

    # Outputs (file paths or strings)
    identify_incident_output=None,
    identify_hazard_consequence_output=None,
    identify_accident_scenario_output=None,
    causal_edge_linking_output=None,

    # Appendix content (file path or string)
    hazard_consequence_json=None,
    accident_scenario_schema_json=None,

    output_docx_path="incident_card_report.docx"
):
    """Generate a clean academic-style Word report (.docx). Robust with XML-cleaning."""

    # ----------------------------------------
    # Safe text reader w/ XML cleanup
    # ----------------------------------------
    def read_text(x):
        """Read file content if path; otherwise return input string. Auto-clean invalid XML chars."""
        if x and isinstance(x, (str, Path)) and Path(x).exists():
            raw = Path(x).read_text(encoding="utf-8", errors="replace")
        else:
            raw = x if isinstance(x, str) else ""
        return clean_for_xml(raw)

    # ----------------------------------------
    # Create document
    # ----------------------------------------
    doc = docx.Document()

    # ----------------------------------------
    # Normal style
    # ----------------------------------------
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal._element.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')

    # ----------------------------------------
    # Academic headings
    # ----------------------------------------
    def create_academic_heading(doc_, name, size, bold=True):
        # Avoid duplicate style name if caller runs multiple times in same process
        if name in [s.name for s in doc_.styles]:
            return doc_.styles[name]

        style = doc_.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        font = style.font
        font.name = "Times New Roman"
        font.size = Pt(size)
        font.bold = bold
        style._element.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')

        pf = style.paragraph_format
        pf.space_before = Pt(12)
        pf.space_after = Pt(6)
        pf.line_spacing = 1.15
        return style

    create_academic_heading(doc, "H1_Aca", 16, bold=True)
    create_academic_heading(doc, "H2_Aca", 14, bold=True)
    create_academic_heading(doc, "H3_Aca", 12, bold=True)

    # ----------------------------------------
    # Title
    # ----------------------------------------
    p = doc.add_paragraph("Incident Card Summary", style="H1_Aca")
    p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

    # Optional timestamp line (comment out if you don't want it)
    # ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    # p2 = doc.add_paragraph(f"Generated: {ts}", style="Normal")
    # p2.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

    doc.add_paragraph("")

    # ----------------------------------------
    # Add justified text block (SAFE)
    # ----------------------------------------
    def add_justified_block(text: str):
        if not text:
            return

        text = clean_for_xml(text)
        lines = text.split("\n")

        for i, line in enumerate(lines):
            line = clean_for_xml(line.rstrip("\r").strip())
            if not line:
                continue

            p_ = doc.add_paragraph()
            pf = p_.paragraph_format
            pf.left_indent = Pt(12)
            pf.right_indent = Pt(12)
            pf.space_before = Pt(0)
            pf.space_after = Pt(0)

            run = p_.add_run(line)
            run.font.name = "Times New Roman"
            run.font.size = Pt(11)

            if len(lines) > 1 and i < len(lines) - 1:
                pf.alignment = WD_PARAGRAPH_ALIGNMENT.JUSTIFY
            else:
                pf.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT

    # ----------------------------------------
    # Section writer
    # ----------------------------------------
    def write_section(header: str, prompt, output):
        if not prompt and not output:
            return

        doc.add_paragraph(header, style="H2_Aca")

        if prompt:
            label1 = doc.add_paragraph()
            r = label1.add_run("Prompt:")
            r.bold = True
            add_justified_block(read_text(prompt))
            doc.add_paragraph("")

        if output:
            label2 = doc.add_paragraph()
            r = label2.add_run("Model Output:")
            r.bold = True
            add_justified_block(read_text(output))
            doc.add_paragraph("")

    def write_appendix_section(header: str, body_text):
        if not body_text:
            return

        doc.add_paragraph(header, style="H2_Aca")

        label = doc.add_paragraph()
        r = label.add_run("Appendix Content:")
        r.bold = True
        doc.add_paragraph("")

        add_justified_block(read_text(body_text))
        doc.add_paragraph("")

    # ----------------------------------------
    # All sections (按你现在 pipeline 的顺序)
    # ----------------------------------------
    sec = 1

    def add_sec(title, prompt, *outputs):
        nonlocal sec

        # 关键：把 Path/文件内容都先转成字符串，再 join
        combined_output = "\n\n".join(
            read_text(o) for o in outputs if o
        )

        write_section(f"{sec}. {title}", prompt, combined_output)

        if (prompt or combined_output):
            sec += 1



    add_sec("Identify Incident", identify_incident_prompt, identify_incident_output)
    add_sec(
        "Identify Hazard Consequence",
        identify_hazard_consequence_prompt,
        identify_hazard_consequence_output,
    )
    add_sec(
        "Identify Accident Scenarios",
        identify_accident_scenario_prompt,
        identify_accident_scenario_output,
    )
    add_sec(
        "Causal Edge Linking",
        causal_edge_linking_prompt,
        causal_edge_linking_output,
    )

    # ----------------------------------------
    # Appendix
    # ----------------------------------------
    write_appendix_section("Appendix - hazard consequence list", hazard_consequence_json)
    write_appendix_section(
        "Appendix - accident scenarios schema",
        accident_scenario_schema_json,
    )

    # ----------------------------------------
    # Save file
    # ----------------------------------------
    doc.save(output_docx_path)
