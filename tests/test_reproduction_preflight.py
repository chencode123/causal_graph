import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pipeline.reproduction_preflight import preflight
from utils.batch_pipeline_utils import PipelineConfig


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / "source"
    case = source / "batch_1" / "1"
    case.mkdir(parents=True)
    for name in ("identify_incident_output.json", "identify_hazard_consequence_output.json"):
        (case / name).write_text(json.dumps({"text": "prepared input"}))
    template = tmp_path / "prompt.txt"
    template.write_text("{incident}")
    config = PipelineConfig(
        base_dir=source, model_name="unused", reasoning_effort="medium",
        verbosity="medium", force_json_output=True, save_raw_response=True,
        max_output_tokens=32000, call_sleep_seconds=0,
        hazards_json_path=template, conditions_json_path=template,
        active_step_keys=("causal_narrative_extraction",),
    )
    step = SimpleNamespace(key="causal_narrative_extraction", build_vars=lambda _: {"incident": "text"})
    with patch("pipeline.reproduction_preflight.build_pipeline", return_value=[step]), \
         patch("pipeline.reproduction_preflight.prompts", {step.key: template}):
        yield config, case, tmp_path / "output"


def check(config, output, resume=True):
    return preflight(config, output_root=output, rounds=5, start_round=1, resume=resume)


def test_dry_check_does_not_create_outputs(prepared):
    config, _, output = prepared
    assert check(config, output) == 1
    assert not output.exists()


def test_missing_fixed_hazard_input_fails(prepared):
    config, case, output = prepared
    (case / "identify_hazard_consequence_output.json").unlink()
    with pytest.raises(FileNotFoundError, match="Missing prepared input"):
        check(config, output)
    assert not output.exists()


def test_incomplete_existing_round_is_preserved(prepared):
    config, _, output = prepared
    round_dir = output / "round_1"
    round_dir.mkdir(parents=True)
    sentinel = round_dir / "sentinel.txt"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match="incomplete"):
        check(config, output)
    assert sentinel.read_text() == "keep"


def test_overwrite_and_overlapping_trees_are_rejected(prepared):
    config, _, output = prepared
    (output / "round_1").mkdir(parents=True)
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        check(config, output, resume=False)
    with pytest.raises(ValueError, match="separate"):
        check(config, config.base_dir / "outputs")


def test_complete_existing_round_is_accepted(prepared):
    config, _, output = prepared
    round_dir = output / "round_1"
    round_dir.mkdir(parents=True)
    for name in ("causal_narrative_extraction_output.json", "causal_graph.json",
                 "updated_causal_graph_accept_all.json"):
        (round_dir / name).write_text("{}")
    assert check(config, output) == 1
