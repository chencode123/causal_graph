# Prompt-Step Workflow

This repository now uses three sources of truth for prompt-based steps:

- `prompt/manifest.json`: prompt templates and declared variables
- `pipeline/step_registry.py`: pipeline step metadata
- `utils/prompt_validator.py`: startup and test-time validation

## Add a New Prompt Step

1. Run scaffold:
   - `python scripts/new_step.py <new_step_key>`
2. Edit `prompt/<new_step_key>.txt` and add placeholders like `{my_var}`.
3. Update `prompt/manifest.json` entry:
   - `template_file`
   - `required_vars` (var->source mapping)
   - `optional_vars`
4. Add/update `pipeline/step_registry.py` entry for the same key:
   - `output_file`
   - `required_vars` (var->source mapping)
   - `default_params`
5. Wire the step into your pipeline builder (for example `pipeline/step_factory.py`).
6. Run tests:
   - `pytest tests/test_prompt_keys_sync.py tests/test_prompt_vars_sync.py`

## Validation Rules

- Every step key in `STEP_REGISTRY` must exist in `prompt/manifest.json`.
- Every manifest `template_file` for registry steps must exist.
- Prompt placeholders in template text must match the manifest vars.
- `STEP_REGISTRY.required_vars` must match `manifest.required_vars` for each registry step.
