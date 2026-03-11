from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, Any


KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _load_manifest(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Manifest must be a JSON object: {path}")
    return data


def _save_manifest(path: Path, manifest: Dict[str, Dict[str, Any]]) -> None:
    sorted_manifest = {k: manifest[k] for k in sorted(manifest.keys())}
    path.write_text(
        json.dumps(sorted_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _touch_prompt_file(prompt_path: Path, key: str) -> bool:
    if prompt_path.exists():
        return False

    prompt_path.write_text(
        "\n".join(
            [
                f"# {key}",
                "",
                "INPUT:",
                "{example_input}",
                "",
                "TASK:",
                "Describe the task here.",
                "",
                "OUTPUT:",
                "Return the expected output format here.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return True


def _update_coverage_instructions(path: Path, key: str) -> bool:
    line = (
        f"- Added step key: `{key}`. Define required vars in manifest and "
        "STEP_REGISTRY (required_vars as var->source mapping)."
    )
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if line in content:
            return False
        path.write_text(content.rstrip() + "\n" + line + "\n", encoding="utf-8")
        return True

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Step Coverage Notes\n\n"
        "When adding a new prompt step, ensure tests still pass:\n"
        "- `tests/test_prompt_keys_sync.py`\n"
        "- `tests/test_prompt_vars_sync.py`\n"
        f"{line}\n",
        encoding="utf-8",
    )
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python scripts/new_step.py <key>")
        return 1

    key = argv[1].strip()
    if not KEY_PATTERN.match(key):
        print("Invalid key. Use snake_case like: identify_new_step")
        return 1

    root = Path(__file__).resolve().parent.parent
    prompt_dir = root / "prompt"
    manifest_path = prompt_dir / "manifest.json"
    prompt_file = prompt_dir / f"{key}.txt"
    coverage_notes = root / "tests" / "step_coverage_instructions.md"

    prompt_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(manifest_path)

    created_prompt = _touch_prompt_file(prompt_file, key)

    updated_manifest = False
    if key not in manifest:
        manifest[key] = {
            "template_file": f"{key}.txt",
            "required_vars": [],
            "optional_vars": [],
        }
        _save_manifest(manifest_path, manifest)
        updated_manifest = True

    updated_notes = _update_coverage_instructions(coverage_notes, key)

    print(f"Step key: {key}")
    print(f"Prompt file: {'created' if created_prompt else 'exists'} -> {prompt_file}")
    print(f"Manifest: {'updated' if updated_manifest else 'unchanged'} -> {manifest_path}")
    print(
        f"Coverage notes: {'updated' if updated_notes else 'unchanged'} -> {coverage_notes}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
