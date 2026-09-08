from __future__ import annotations

import json
import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.causal_graph_interactive_pkg.causal_graph_interactive import (
    _build_schema_form_options,
)

_REPAIR_SPEC = importlib.util.spec_from_file_location(
    "repair_causal_graph_html_schema_options",
    PROJECT_ROOT / "scripts" / "repair_causal_graph_html_schema_options.py",
)
if _REPAIR_SPEC is None or _REPAIR_SPEC.loader is None:
    raise RuntimeError("Unable to load repair_causal_graph_html_schema_options.py")
_REPAIR_MODULE = importlib.util.module_from_spec(_REPAIR_SPEC)
_REPAIR_SPEC.loader.exec_module(_REPAIR_MODULE)
repair_html_text = _REPAIR_MODULE.repair_html_text


class CausalGraphHtmlSchemaOptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads(
            (PROJECT_ROOT / "scheme" / "accident_scenario_schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.options = _build_schema_form_options(schema)

    def test_pipe_delimited_event_labels_are_individual_options(self) -> None:
        expected = {
            "InitiatingEvent",
            "MechanicalFailure",
            "IgnitionSource",
            "IntermediateEvent",
            "InstantRelease",
            "ContinuousRelease",
            "Dispersion",
        }
        self.assertTrue(expected.issubset(set(self.options["labels"])))
        self.assertFalse(any("|" in label for label in self.options["labels"]))
        for label in expected:
            self.assertEqual(self.options["label_to_type"][label], "event")

    def test_historical_hazard_labels_remain_selectable(self) -> None:
        for label in ("VCE", "BLEVE", "Dust explosion", "Jet fire"):
            self.assertIn(label, self.options["labels"])
            self.assertEqual(
                self.options["label_to_type"][label], "hazardconsequence"
            )

    def test_html_repair_preserves_other_embedded_content(self) -> None:
        old_options = {
            "labels": ["HazardConsequence", "InitiatingEvent | MechanicalFailure"],
            "types": ["hazardconsequence", "event"],
            "label_to_type": {
                "HazardConsequence": "hazardconsequence",
                "InitiatingEvent | MechanicalFailure": "event",
            },
            "relations": ["has", "enables"],
        }
        elements = {
            "nodes": [
                {"data": {"id": "Ev1", "label": "InitiatingEvent", "nodeType": "event"}}
            ],
            "edges": [],
        }
        review = {"keep": "unchanged"}
        html = (
            "before\nconst elements = "
            + json.dumps(elements)
            + ";\nconst schemaForm = "
            + json.dumps(old_options)
            + ";\nconst reviewSuggestions = "
            + json.dumps(review)
            + ";\nafter"
        )

        repaired, audit = repair_html_text(html, self.options)

        self.assertEqual(audit["status"], "changed")
        self.assertEqual(audit["missing_node_labels_after_repair"], [])
        self.assertIn('const reviewSuggestions = {"keep": "unchanged"};', repaired)
        self.assertTrue(repaired.startswith("before\n"))
        self.assertTrue(repaired.endswith(";\nafter"))


if __name__ == "__main__":
    unittest.main()
