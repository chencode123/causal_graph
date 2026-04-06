from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


ANALYST_PROMPT_PATH = Path("prompt/prompt_optimizer_round_analyst.txt")


@dataclass
class RoundAnalysis:
    improvement_analysis: str
    regression_analysis: str
    next_round_strategy: str


def _require_dspy():
    try:
        import dspy
    except ImportError as exc:
        raise ImportError(
            "DSPy is required for prompt optimization analysis. Install it before running this workflow."
        ) from exc
    return dspy


def _build_signature(dspy):
    class AnalyzeRoundHistory(dspy.Signature):
        """Analyze why the latest optimization round improved or regressed and propose the next strategy."""

        analyst_instruction = dspy.InputField()
        case_context = dspy.InputField()
        history_window = dspy.InputField()

        improvement_analysis = dspy.OutputField(desc="Why the latest round improved, if it improved.")
        regression_analysis = dspy.OutputField(desc="Why the latest round regressed or still failed.")
        next_round_strategy = dspy.OutputField(desc="Concrete strategy for the next optimization round.")

    return AnalyzeRoundHistory


def analyze_round_history(
    *,
    case_context: Dict[str, Any],
    history_window: List[Dict[str, Any]],
    model_name: str,
    reasoning_effort: str,
    verbosity: str,
) -> RoundAnalysis:
    dspy = _require_dspy()
    AnalyzeRoundHistory = _build_signature(dspy)
    lm = dspy.LM(
        model=model_name,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
    )
    dspy.settings.configure(lm=lm)
    predictor = dspy.Predict(AnalyzeRoundHistory)
    result = predictor(
        analyst_instruction=ANALYST_PROMPT_PATH.read_text(encoding="utf-8"),
        case_context=json.dumps(case_context, ensure_ascii=False, indent=2),
        history_window=json.dumps(history_window, ensure_ascii=False, indent=2),
    )
    return RoundAnalysis(
        improvement_analysis=str(result.improvement_analysis).strip(),
        regression_analysis=str(result.regression_analysis).strip(),
        next_round_strategy=str(result.next_round_strategy).strip(),
    )
