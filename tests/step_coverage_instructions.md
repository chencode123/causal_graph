# Step Coverage Notes

When adding a new prompt step, ensure tests still pass:
- `tests/test_prompt_keys_sync.py`
- `tests/test_prompt_vars_sync.py`
- Added step key: `identify_accident_scenario`. Define required vars in manifest and STEP_REGISTRY.
- Added step key: `causal_edge_linking_prompt`. Define required vars in manifest and STEP_REGISTRY (required_vars as var->source mapping).
