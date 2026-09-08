from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from utils.evaluation_case_filters import (
    DEFAULT_EXCLUDED_CASES_PATH,
    filter_excluded_case_folders,
    infer_case_key,
    load_excluded_case_keys,
    normalize_case_key,
)


class EvaluationCaseFilterTests(unittest.TestCase):
    def test_default_list_matches_selected_few_shot_sources(self) -> None:
        exclusions = load_excluded_case_keys(DEFAULT_EXCLUDED_CASES_PATH)
        pattern_path = DEFAULT_EXCLUDED_CASES_PATH.parent / (
            "runs/few-shot/review_feedback/case_coverage_12/"
            "review_feedback_analysis_few_shot_balanced_small.json"
        )
        payload = json.loads(pattern_path.read_text(encoding="utf-8"))
        source_cases = {
            normalize_case_key(
                str(source).removesuffix("/review_feedback_analysis_output.json")
            )
            for source in payload["source_files"]
        }
        self.assertTrue(source_cases <= exclusions)
        self.assertEqual(exclusions - source_cases, {"batch_9/1"})
        self.assertEqual(len(exclusions), 12)

    def test_infers_key_from_round_and_suffixed_batch(self) -> None:
        parent = Path("root")
        case = parent / "round_2" / "batch_9_output_round_2" / "6_split_1"
        self.assertEqual(infer_case_key(case, parent), "batch_9/6_split_1")

    def test_filters_every_round_of_an_excluded_case(self) -> None:
        parent = Path("root")
        folders = [
            parent / "round_1" / "batch_6" / "1",
            parent / "round_2" / "batch_6_output_round_2" / "1",
            parent / "round_1" / "batch_6" / "2",
        ]
        retained, excluded = filter_excluded_case_folders(
            folders,
            parent,
            {"batch_6/1"},
        )
        self.assertEqual(retained, [folders[2]])
        self.assertEqual([key for key, _ in excluded], ["batch_6/1", "batch_6/1"])

    def test_rejects_duplicate_normalized_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "excluded.json"
            path.write_text(
                json.dumps(["batch_1/1", "batch_1_output_round_2/1"]),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_excluded_case_keys(path)


if __name__ == "__main__":
    unittest.main()
