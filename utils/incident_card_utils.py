from datetime import datetime
from pathlib import Path
import os

def incident_card_utils(
    identify_incident_prompt=None,
    identify_condition_prompt=None,
    identify_hazard_consequence_prompt=None,
    identify_evidence_prompt=None,
    identify_relationship_prompt=None,
    chain_events_prompt=None,
    chain_conditions_events_prompt=None,
    chain_scenario_prompt=None,
    chain_hazards_prompt=None,

    identify_incident_output=None,
    identify_condition_output=None,
    identify_hazard_consequence_output=None,
    identify_evidence_output=None,
    identify_relationship_output=None,
    chain_events_output=None,
    chain_conditions_events_output=None,
    chain_scenario_output=None,
    chain_hazards_output=None,

    hazard_consequence_json = None,
    conditions_json = None,

    graph_png=None,

    md_path=None,
    file_name=None
):
    """
    Write all prompt + output pairs into a Markdown summary file for one incident card.
    """

    def read_if_path(x):
        """If x is a file path, read its content."""
        if x and isinstance(x, (str, Path)) and Path(x).exists():
            try:
                return Path(x).read_text(encoding="utf-8")
            except Exception as e:
                return f"[⚠️ Error reading file: {e}]"
        return x

    output_md = Path(md_path) / file_name
    output_md.parent.mkdir(parents=True, exist_ok=True)

    with open(output_md, "w", encoding="utf-8") as f:
        f.write(f"# Incident Card Summary\nGenerated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        def write_section(title, prompt_file, output_text):
            """统一写入 prompt + output"""
            if not prompt_file:
                return

            f.write(f"## {title}_prompt\n")

            if isinstance(prompt_file, (str, Path)) and Path(prompt_file).exists():
                f.write(f"**File:** `{prompt_file}`\n\n")
                try:
                    with open(prompt_file, "r", encoding="utf-8") as p:
                        f.write("```text\n" + p.read().strip() + "\n```\n\n")
                except Exception as e:
                    f.write(f"_⚠️ Cannot read prompt file: {e}_\n\n")
            else:
                f.write("```text\n" + str(prompt_file).strip() + "\n```\n\n")
                
            output_text = read_if_path(output_text)
            if output_text:
                f.write(f"**Model Output ({title}_output):**\n")
                f.write("```text\n" + str(output_text).strip() + "\n```\n\n")

        def write_appendix_section(header, body_text):
                    """
                    Writes an appendix section in Markdown to the file handle 'f'.
                    """
                    if not body_text:
                        return

                    # Read the body content, which might be a file path
                    text = read_if_path(body_text)
                    
                    if not text:
                        return
                    
                    # Header (Markdown H2)
                    f.write(f"\n## {header}\n\n")

                    # Body label (Bold Markdown text)
                    f.write("**Appendix Content:**\n\n")

                    # Insert body content in a Markdown code block for easy viewing (like JSON/large text)
                    # This replaces the need for 'add_justified_block' with a clear formatting convention.
                    f.write("```json\n" if header.endswith("json") else "```text\n")
                    f.write(text.strip())
                    f.write("\n```\n\n")

        # === 按顺序写入每一步 ===
        write_section("1. Identify Incident", identify_incident_prompt, identify_incident_output)
        write_section("2. Identify Hazard Consequence", identify_hazard_consequence_prompt, identify_hazard_consequence_output)
        write_section("3. Identify Conditions", identify_condition_prompt, identify_condition_output)
        write_section("4. Identify Evidence", identify_evidence_prompt, identify_evidence_output)
        write_section("5. identify relationship", identify_relationship_prompt, identify_relationship_output)
        write_section("6. Chain Events", chain_events_prompt, chain_events_output)
        write_section("7. Chain Conditions and Events", chain_conditions_events_prompt, chain_conditions_events_output)
        write_section("8. Chain Scenario ", chain_scenario_prompt, chain_scenario_output)
        write_section("9. Chain Hazard Consequence ", chain_hazards_prompt, chain_hazards_output)


        # === 图像部分 ===
        if graph_png and Path(graph_png).exists():
            md_dir = Path(f.name).parent
            rel_path = os.path.relpath(graph_png, start=md_dir)
            rel_path = Path(rel_path).as_posix()
            f.write("**Graph (final visualization):**\n\n")
            f.write(f"![final_graph]({rel_path})\n\n")

        f.write("---\n")
        
        write_appendix_section("Appendix - hazard consequence list", hazard_consequence_json)
        write_appendix_section("Appendix - conditions list", conditions_json)

