from __future__ import annotations

import dspy


class SuggestScenarioPromptPatch(dspy.Signature):
    """Suggest a minimal patch for the identify_accident_scenario prompt."""

    current_prompt = dspy.InputField()
    step_input = dspy.InputField()
    current_output = dspy.InputField()
    gold_nodes = dspy.InputField()
    diff_summary = dspy.InputField()

    failure_modes = dspy.OutputField(desc="Concise diagnosis of why the current prompt failed.")
    patch_rules = dspy.OutputField(desc="A short numbered or semicolon-separated list of rules to add.")
    revised_prompt_suffix = dspy.OutputField(
        desc="Minimal prompt suffix to append to the current prompt. Do not rewrite the full prompt."
    )


class SuggestEdgePromptPatch(dspy.Signature):
    """Suggest a minimal patch for the causal_edge_linking prompt."""

    current_prompt = dspy.InputField()
    step_input = dspy.InputField()
    current_output = dspy.InputField()
    gold_graph = dspy.InputField()
    diff_summary = dspy.InputField()

    failure_modes = dspy.OutputField(desc="Concise diagnosis of why the current prompt failed.")
    patch_rules = dspy.OutputField(desc="A short numbered or semicolon-separated list of rules to add.")
    revised_prompt_suffix = dspy.OutputField(
        desc="Minimal prompt suffix to append to the current prompt. Do not rewrite the full prompt."
    )
