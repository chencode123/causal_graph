from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


class PromptPaths:
    def __init__(self, base: str = "prompt", manifest_file: str = "manifest.json"):
        self.base = Path(base)
        self.manifest_path = self.base / manifest_file
        self.manifest = self._load_manifest()
        self.prompts = {
            key: self.base / entry["template_file"] for key, entry in self.manifest.items()
        }

    def _load_manifest(self) -> Dict[str, Dict[str, object]]:
        if not self.manifest_path.exists():
            raise FileNotFoundError(
                f"Prompt manifest not found: {self.manifest_path}. "
                "Expected prompt/manifest.json."
            )

        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(
                f"Prompt manifest must be a JSON object keyed by prompt key: {self.manifest_path}"
            )
        return data

    def __getitem__(self, key: str) -> Path:
        return self.prompts[key]

    def __getattr__(self, key: str) -> Path:
        return self.prompts[key]

    def load_all(self) -> Dict[str, str]:
        return {name: path.read_text(encoding="utf-8") for name, path in self.prompts.items()}


prompts = PromptPaths()
