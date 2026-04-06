from __future__ import annotations

import json
from difflib import unified_diff
from datetime import datetime
from pathlib import Path
from typing import Dict

from .prompt_opt_dspy import PromptSuggestion


def _to_markdown(step_key: str, suggestion: PromptSuggestion, diff_summary: dict) -> str:
    lines = [f"# {step_key}", ""]
    lines.append("## Failure Modes")
    lines.append(suggestion.failure_modes or "None")
    lines.append("")
    lines.append("## Patch Rules")
    lines.append(suggestion.patch_rules or "None")
    lines.append("")
    lines.append("## Prompt Suffix")
    lines.append("```text")
    lines.append(suggestion.revised_prompt_suffix or "")
    lines.append("```")
    lines.append("")
    lines.append("## Diff Summary")
    lines.append("```json")
    lines.append(json.dumps(diff_summary, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_candidate_prompts(
    *,
    output_root: Path,
    experiment_name: str,
    prompt_sources: Dict[str, Path],
    suggestions: Dict[str, PromptSuggestion],
    diffs: Dict[str, dict],
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = output_root / f"{experiment_name}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for step_key, suggestion in suggestions.items():
        prompt_path = prompt_sources[step_key]
        original = prompt_path.read_text(encoding="utf-8")
        suffix = suggestion.revised_prompt_suffix.strip()
        candidate_text = original.rstrip() + "\n\n" + suffix + "\n"
        (out_dir / prompt_path.name).write_text(candidate_text, encoding="utf-8")
        diff_text = "\n".join(
            unified_diff(
                original.splitlines(),
                candidate_text.splitlines(),
                fromfile=f"previous/{prompt_path.name}",
                tofile=f"candidate/{prompt_path.name}",
                lineterm="",
            )
        )
        diff_md_lines = [
            f"# {step_key} Prompt Diff",
            "",
            "```diff",
            diff_text,
            "```",
            "",
        ]
        (out_dir / f"{step_key}_prompt_diff.md").write_text(
            "\n".join(diff_md_lines),
            encoding="utf-8",
        )
        (out_dir / f"{step_key}_suggestion.json").write_text(
            json.dumps(
                {
                    "step_key": suggestion.step_key,
                    "failure_modes": suggestion.failure_modes,
                    "patch_rules": suggestion.patch_rules,
                    "revised_prompt_suffix": suggestion.revised_prompt_suffix,
                    "diff_summary": diffs[step_key],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (out_dir / f"{step_key}_suggestion.md").write_text(
            _to_markdown(step_key, suggestion, diffs[step_key]),
            encoding="utf-8",
        )

    summary_lines = ["# Optimization Summary", ""]
    for step_key, suggestion in suggestions.items():
        summary_lines.append(f"## {step_key}")
        summary_lines.append("")
        summary_lines.append("### Failure Modes")
        summary_lines.append(suggestion.failure_modes or "None")
        summary_lines.append("")
        summary_lines.append("### Patch Rules")
        summary_lines.append(suggestion.patch_rules or "None")
        summary_lines.append("")
    (out_dir / "optimization_summary.md").write_text(
        "\n".join(summary_lines),
        encoding="utf-8",
    )

    return out_dir
