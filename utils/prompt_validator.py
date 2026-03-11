from __future__ import annotations

import json
import string
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


PROMPT_DIR = Path("prompt")
MANIFEST_PATH = PROMPT_DIR / "manifest.json"


def load_prompt_manifest(manifest_path: Path = MANIFEST_PATH) -> Dict[str, Dict[str, Any]]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Prompt manifest not found: {manifest_path}")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Prompt manifest must be a JSON object: {manifest_path}")
    return data


def extract_placeholders(template_text: str) -> Set[str]:
    placeholders: Set[str] = set()
    formatter = string.Formatter()
    for _, field_name, _, _ in formatter.parse(template_text):
        if not field_name:
            continue
        normalized = field_name.split("[", 1)[0].split(".", 1)[0]
        placeholders.add(normalized)
    return placeholders


def _sorted_vars(values: Iterable[str]) -> List[str]:
    return sorted(set(values))


def collect_prompt_step_validation_errors(
    step_registry: Dict[str, Dict[str, Any]],
    manifest_path: Path = MANIFEST_PATH,
    prompt_dir: Path = PROMPT_DIR,
) -> List[str]:
    errors: List[str] = []
    manifest = load_prompt_manifest(manifest_path=manifest_path)

    for step_key in sorted(step_registry.keys()):
        if step_key not in manifest:
            errors.append(
                f"[Missing key] Step '{step_key}' exists in STEP_REGISTRY but not in {manifest_path}."
            )

    for step_key in sorted(step_registry.keys()):
        entry = manifest.get(step_key)
        if not entry:
            continue

        template_file = entry.get("template_file")
        if not isinstance(template_file, str) or not template_file:
            errors.append(
                f"[Bad manifest] Step '{step_key}' has invalid 'template_file' in {manifest_path}."
            )
            continue

        template_path = prompt_dir / template_file
        if not template_path.exists():
            errors.append(
                f"[Missing file] Step '{step_key}' template file not found: {template_path}."
            )
            continue

        required_vars = entry.get("required_vars")
        optional_vars = entry.get("optional_vars")
        if not isinstance(required_vars, list) or not isinstance(optional_vars, list):
            errors.append(
                f"[Bad manifest] Step '{step_key}' must define list fields "
                f"'required_vars' and 'optional_vars' in {manifest_path}."
            )
            continue

        declared_vars = set(_sorted_vars(required_vars + optional_vars))
        registry_required_raw = step_registry[step_key].get("required_vars", {})
        if isinstance(registry_required_raw, dict):
            registry_required_vars = set(_sorted_vars(registry_required_raw.keys()))
        elif isinstance(registry_required_raw, list):
            registry_required_vars = set(_sorted_vars(registry_required_raw))
        else:
            errors.append(
                f"[Registry mismatch] Step '{step_key}' STEP_REGISTRY.required_vars "
                "must be a dict (var->source) or list."
            )
            continue

        try:
            template_text = template_path.read_text(encoding="utf-8")
            placeholders = extract_placeholders(template_text)
        except ValueError as exc:
            errors.append(
                f"[Template parse error] Step '{step_key}' template has invalid format braces: "
                f"{template_path}. Error: {exc}"
            )
            continue

        if placeholders != declared_vars:
            missing_in_manifest = _sorted_vars(placeholders - declared_vars)
            extra_in_manifest = _sorted_vars(declared_vars - placeholders)
            errors.append(
                f"[Variable mismatch] Step '{step_key}' manifest vars do not match template placeholders. "
                f"Missing in manifest: {missing_in_manifest}. Extra in manifest: {extra_in_manifest}."
            )

        if registry_required_vars != set(_sorted_vars(required_vars)):
            missing_in_registry = _sorted_vars(set(required_vars) - registry_required_vars)
            extra_in_registry = _sorted_vars(registry_required_vars - set(required_vars))
            errors.append(
                f"[Registry mismatch] Step '{step_key}' STEP_REGISTRY.required_vars do not match "
                f"manifest.required_vars. Missing in registry: {missing_in_registry}. "
                f"Extra in registry: {extra_in_registry}."
            )

    return errors


def assert_prompt_step_configuration_valid(
    step_registry: Dict[str, Dict[str, Any]],
    manifest_path: Path = MANIFEST_PATH,
    prompt_dir: Path = PROMPT_DIR,
) -> None:
    errors = collect_prompt_step_validation_errors(
        step_registry=step_registry,
        manifest_path=manifest_path,
        prompt_dir=prompt_dir,
    )
    if not errors:
        return

    joined = "\n".join(f"- {line}" for line in errors)
    raise ValueError(
        "Prompt-step configuration validation failed.\n"
        f"Manifest: {manifest_path}\n"
        f"Prompt dir: {prompt_dir}\n"
        f"{joined}"
    )
