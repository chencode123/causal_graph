from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

OPTIMIZER_PROMPT_FILES = {
    "identify_accident_scenario": Path("prompt/prompt_optimizer_identify_accident_scenario.txt"),
    "causal_edge_linking": Path("prompt/prompt_optimizer_causal_edge_linking.txt"),
}


@dataclass
class PromptSuggestion:
    step_key: str
    failure_modes: str
    patch_rules: str
    revised_prompt_suffix: str


def _require_dspy():
    try:
        import dspy
    except ImportError as exc:
        raise ImportError(
            "DSPy is required for prompt optimization. Install it before running this workflow."
        ) from exc
    return dspy


def _build_signatures(dspy):
    class SuggestScenarioPromptPatch(dspy.Signature):
        """Suggest a minimal patch for the identify_accident_scenario prompt."""

        optimizer_instruction = dspy.InputField()
        current_prompt = dspy.InputField()
        step_input = dspy.InputField()
        current_output = dspy.InputField()
        gold_nodes = dspy.InputField()
        diff_summary = dspy.InputField()
        previous_round_feedback = dspy.InputField()

        failure_modes = dspy.OutputField(desc="Concise diagnosis of why the current prompt failed.")
        patch_rules = dspy.OutputField(desc="A short numbered or semicolon-separated list of rules to add.")
        revised_prompt_suffix = dspy.OutputField(
            desc="Minimal prompt suffix to append to the current prompt. Do not rewrite the full prompt."
        )

    class SuggestEdgePromptPatch(dspy.Signature):
        """Suggest a minimal patch for the causal_edge_linking prompt."""

        optimizer_instruction = dspy.InputField()
        current_prompt = dspy.InputField()
        step_input = dspy.InputField()
        current_output = dspy.InputField()
        gold_graph = dspy.InputField()
        diff_summary = dspy.InputField()
        previous_round_feedback = dspy.InputField()

        failure_modes = dspy.OutputField(desc="Concise diagnosis of why the current prompt failed.")
        patch_rules = dspy.OutputField(desc="A short numbered or semicolon-separated list of rules to add.")
        revised_prompt_suffix = dspy.OutputField(
            desc="Minimal prompt suffix to append to the current prompt. Do not rewrite the full prompt."
        )

    return SuggestScenarioPromptPatch, SuggestEdgePromptPatch


def _as_json_text(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _load_optimizer_instruction(step_key: str) -> str:
    path = OPTIMIZER_PROMPT_FILES[step_key]
    return path.read_text(encoding="utf-8")


def suggest_prompt_patch(
    *,
    step_key: str,
    current_prompt: str,
    step_input: Dict[str, Any],
    current_output: Dict[str, Any],
    gold_target: Dict[str, Any],
    diff_summary: Dict[str, Any],
    previous_round_feedback: str,
    model_name: str,
    reasoning_effort: str,
    verbosity: str,
) -> PromptSuggestion:
    dspy = _require_dspy()
    SuggestScenarioPromptPatch, SuggestEdgePromptPatch = _build_signatures(dspy)
    lm = dspy.LM(
        model=model_name,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
    )
    dspy.settings.configure(lm=lm)

    if step_key == "identify_accident_scenario":
        predictor = dspy.Predict(SuggestScenarioPromptPatch)
        result = predictor(
            optimizer_instruction=_load_optimizer_instruction(step_key),
            current_prompt=current_prompt,
            step_input=_as_json_text(step_input),
            current_output=_as_json_text(current_output),
            gold_nodes=_as_json_text(gold_target),
            diff_summary=_as_json_text(diff_summary),
            previous_round_feedback=previous_round_feedback,
        )
    elif step_key == "causal_edge_linking":
        predictor = dspy.Predict(SuggestEdgePromptPatch)
        result = predictor(
            optimizer_instruction=_load_optimizer_instruction(step_key),
            current_prompt=current_prompt,
            step_input=_as_json_text(step_input),
            current_output=_as_json_text(current_output),
            gold_graph=_as_json_text(gold_target),
            diff_summary=_as_json_text(diff_summary),
            previous_round_feedback=previous_round_feedback,
        )
    else:
        raise KeyError(f"Unsupported optimization step: {step_key}")

    return PromptSuggestion(
        step_key=step_key,
        failure_modes=str(result.failure_modes).strip(),
        patch_rules=str(result.patch_rules).strip(),
        revised_prompt_suffix=str(result.revised_prompt_suffix).strip(),
    )
