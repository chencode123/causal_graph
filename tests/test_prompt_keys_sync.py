from pipeline.step_registry import STEP_REGISTRY
from utils.prompt_validator import collect_prompt_step_validation_errors


def test_prompt_keys_sync() -> None:
    errors = collect_prompt_step_validation_errors(step_registry=STEP_REGISTRY)
    key_errors = [
        e
        for e in errors
        if e.startswith("[Missing key]") or e.startswith("[Missing file]") or e.startswith("[Bad manifest]")
    ]
    assert not key_errors, "\n".join(key_errors)
