from pipeline.step_registry import STEP_REGISTRY
from utils.prompt_validator import collect_prompt_step_validation_errors


def test_prompt_vars_sync() -> None:
    errors = collect_prompt_step_validation_errors(step_registry=STEP_REGISTRY)
    var_errors = [
        e
        for e in errors
        if e.startswith("[Variable mismatch]") or e.startswith("[Registry mismatch]")
    ]
    assert not var_errors, "\n".join(var_errors)
