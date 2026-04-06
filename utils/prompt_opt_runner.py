from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable
from tqdm import tqdm

from .prompt_opt_data import TARGET_PROMPT_FILES, load_step_optimization_input
from .prompt_opt_diff import summarize_edge_diff, summarize_scenario_diff
from .prompt_opt_dspy import PromptSuggestion, suggest_prompt_patch
from .prompt_opt_analyst import analyze_round_history
from .prompt_opt_eval import RoundScore, score_case, write_score
from .prompt_opt_patch import write_candidate_prompts
from .prompt_opt_rerun import SingleStepRerunConfig, copy_case_tree, rerun_single_step
from .prompt_opt_summary import (
    build_case_context,
    compress_diff_summary,
    summarize_edge_output,
    summarize_scenario_output,
)


@dataclass(frozen=True)
class PromptOptimizationConfig:
    source_runs: Path
    target_batch: str
    target_case: str
    target_steps: Iterable[str]
    dspy_model: str
    reasoning_effort: str
    verbosity: str
    max_output_tokens: int
    hazards_json_path: Path
    conditions_json_path: Path
    prompt_output_dir: Path
    experiment_name: str
    max_rounds: int = 1
    top_k: int = 3
    analysis_window_size: int = 3
    analysis_rounds: tuple[int, ...] | None = None
    resume_from_existing: bool = True


@dataclass
class CandidateState:
    round_index: int
    case_dir: Path
    prompt_by_step: Dict[str, str]
    score: RoundScore
    summary_path: Path


def _round_score_from_dict(payload: Dict[str, object]) -> RoundScore:
    return RoundScore(
        round_index=int(payload.get("round_index", 0)),
        node_precision=float(payload.get("node_precision", 0.0)),
        node_recall=float(payload.get("node_recall", 0.0)),
        node_f1=float(payload.get("node_f1", 0.0)),
        edge_precision=float(payload.get("edge_precision", 0.0)),
        edge_recall=float(payload.get("edge_recall", 0.0)),
        edge_f1=float(payload.get("edge_f1", 0.0)),
        overall_score=float(payload.get("overall_score", 0.0)),
        structural_similarity=(
            float(payload["structural_similarity"])
            if payload.get("structural_similarity") is not None
            else None
        ),
        graph_edit_distance=(
            float(payload["graph_edit_distance"])
            if payload.get("graph_edit_distance") is not None
            else None
        ),
        normalized_graph_edit_distance=(
            float(payload["normalized_graph_edit_distance"])
            if payload.get("normalized_graph_edit_distance") is not None
            else None
        ),
        graph_edit_similarity=(
            float(payload["graph_edit_similarity"])
            if payload.get("graph_edit_similarity") is not None
            else None
        ),
    )


def _case_dir(config: PromptOptimizationConfig) -> Path:
    return config.source_runs / config.target_batch / config.target_case


def _round_dir(config: PromptOptimizationConfig, round_index: int) -> Path:
    return config.prompt_output_dir / config.experiment_name / f"round_{round_index:02d}"


def _write_round_summary(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_previous_round_feedback(previous_summary: Dict[str, object] | None) -> str:
    if not previous_summary:
        return "No previous round feedback. This is the first optimization round."
    round_score = previous_summary.get("round_score", {})
    baseline_score = previous_summary.get("baseline_score", {})
    if not isinstance(round_score, dict) or not isinstance(baseline_score, dict):
        return "Previous round feedback unavailable."
    metric_keys = [
        "node_precision",
        "node_recall",
        "node_f1",
        "edge_precision",
        "edge_recall",
        "edge_f1",
        "overall_score",
        "structural_similarity",
        "graph_edit_distance",
        "normalized_graph_edit_distance",
        "graph_edit_similarity",
    ]
    lines = [
        f"Previous round index: {previous_summary.get('round_index')}",
        f"Improved: {previous_summary.get('improved')}",
        "Score changes:",
    ]
    for key in metric_keys:
        base_value = baseline_score.get(key)
        round_value = round_score.get(key)
        if base_value is None and round_value is None:
            continue
        delta = None
        if isinstance(base_value, (int, float)) and isinstance(round_value, (int, float)):
            delta = round_value - base_value
        lines.append(
            f"- {key}: baseline={base_value}, round={round_value}, delta={delta}"
        )
    step_payloads = previous_summary.get("steps", {})
    if isinstance(step_payloads, dict) and step_payloads:
        lines.append("Previous round step diagnostics:")
        for step_key, payload in step_payloads.items():
            if not isinstance(payload, dict):
                continue
            lines.append(f"[{step_key}]")
            if "failure_modes" in payload:
                lines.append(f"failure_modes: {payload.get('failure_modes')}")
            if "patch_rules" in payload:
                lines.append(f"patch_rules: {payload.get('patch_rules')}")
            if "round_analysis" in payload:
                lines.append("round_analysis:")
                lines.append(json.dumps(payload.get("round_analysis"), ensure_ascii=False, indent=2))
            if "output_summary" in payload:
                lines.append("output_summary:")
                lines.append(json.dumps(payload.get("output_summary"), ensure_ascii=False, indent=2))
            if "diff_summary_compact" in payload:
                diff_text = json.dumps(payload.get("diff_summary_compact"), ensure_ascii=False, indent=2)
                lines.append("diff_summary_compact:")
                lines.append(diff_text)
    round_analysis = previous_summary.get("round_analysis", {})
    if isinstance(round_analysis, dict) and round_analysis:
        lines.append("Previous round analysis:")
        lines.append(json.dumps(round_analysis, ensure_ascii=False, indent=2))
    if previous_summary.get("improved") is False:
        lines.append(
            "The previous prompt change did not improve the score. Avoid repeating the same correction style."
        )
    return "\n".join(lines)


def _ordered_target_steps(step_keys: Iterable[str]) -> list[str]:
    preferred_order = [
        "identify_accident_scenario",
        "causal_edge_linking",
    ]
    step_set = list(step_keys)
    return [step for step in preferred_order if step in step_set]


def _score_sort_key(score: RoundScore) -> tuple[float, float, float]:
    structural_similarity = (
        float(score.structural_similarity)
        if score.structural_similarity is not None
        else float("-inf")
    )
    if score.normalized_graph_edit_distance is not None:
        graph_edit_similarity = 1.0 - float(score.normalized_graph_edit_distance)
    else:
        graph_edit_similarity = (
            float(score.graph_edit_similarity)
            if score.graph_edit_similarity is not None
            else float("-inf")
        )
    blended_score = 0.5 * structural_similarity + 0.5 * graph_edit_similarity
    return (blended_score, structural_similarity, graph_edit_similarity)


def _is_better_score(candidate: RoundScore, incumbent: RoundScore | None) -> bool:
    if incumbent is None:
        return True
    return _score_sort_key(candidate) > _score_sort_key(incumbent)


def _trim_top_k(states: list[CandidateState], top_k: int) -> list[CandidateState]:
    ordered = sorted(states, key=lambda item: _score_sort_key(item.score), reverse=True)
    return ordered[: max(1, top_k)]


def _resume_experiment_state(
    config: PromptOptimizationConfig,
) -> tuple[list[Dict[str, object]], list[CandidateState], RoundScore | None, Dict[str, object] | None, int]:
    if not config.resume_from_existing:
        return [], [], None, None, 1

    experiment_dir = config.prompt_output_dir / config.experiment_name
    if not experiment_dir.exists():
        return [], [], None, None, 1

    history: list[Dict[str, object]] = []
    candidate_states: list[CandidateState] = []
    round_summary_paths = sorted(experiment_dir.glob("round_*/round_summary.json"))
    for summary_path in round_summary_paths:
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        history.append(payload)
        candidate_dir_raw = payload.get("candidate_dir")
        rerun_case_raw = payload.get("rerun_case_dir")
        round_score_raw = payload.get("round_score")
        round_index = payload.get("round_index")
        if (
            not isinstance(candidate_dir_raw, str)
            or not isinstance(rerun_case_raw, str)
            or not isinstance(round_score_raw, dict)
            or not isinstance(round_index, int)
        ):
            continue
        candidate_dir = Path(candidate_dir_raw)
        prompt_by_step: Dict[str, str] = {}
        prompt_complete = True
        for step_key in config.target_steps:
            prompt_path = candidate_dir / TARGET_PROMPT_FILES[step_key].name
            if not prompt_path.exists():
                prompt_complete = False
                break
            prompt_by_step[step_key] = prompt_path.read_text(encoding="utf-8")
        if not prompt_complete:
            continue
        candidate_states.append(
            CandidateState(
                round_index=round_index,
                case_dir=Path(rerun_case_raw),
                prompt_by_step=prompt_by_step,
                score=_round_score_from_dict(round_score_raw),
                summary_path=summary_path,
            )
        )

    history.sort(key=lambda item: int(item.get("round_index", 0)))
    candidate_states = _trim_top_k(candidate_states, config.top_k)
    best_state = candidate_states[0] if candidate_states else None
    best_score = best_state.score if best_state is not None else None
    previous_round_summary = history[-1] if history else None
    start_round_index = (int(previous_round_summary.get("round_index", 0)) + 1) if previous_round_summary else 1
    return history, candidate_states, best_score, previous_round_summary, start_round_index


def _build_history_window(
    history: list[Dict[str, object]],
    current_summary: Dict[str, object],
    window_size: int,
) -> list[Dict[str, object]]:
    window = history[-(window_size - 1):] + [current_summary]
    return window[-window_size:]


def _build_analyst_history_window(
    history: list[Dict[str, object]],
    current_summary: Dict[str, object],
    window_size: int,
    analysis_rounds: tuple[int, ...] | None = None,
) -> list[Dict[str, object]]:
    raw_window = _build_history_window(history, current_summary, window_size)
    if analysis_rounds:
        round_map: Dict[int, Dict[str, object]] = {}
        for item in history:
            round_index = item.get("round_index")
            if isinstance(round_index, int):
                round_map[round_index] = item
        current_round_index = current_summary.get("round_index")
        if isinstance(current_round_index, int):
            round_map[current_round_index] = current_summary
        selected_window = [
            round_map[round_index]
            for round_index in analysis_rounds
            if round_index in round_map
        ]
        if selected_window:
            raw_window = selected_window
    filtered: list[Dict[str, object]] = []
    for item in raw_window:
        step_payloads = item.get("steps", {})
        steps: Dict[str, object] = {}
        if isinstance(step_payloads, dict):
            for step_key, payload in step_payloads.items():
                if not isinstance(payload, dict):
                    continue
                steps[step_key] = {
                    "current_output": payload.get("current_output", {}),
                    "failure_modes": payload.get("failure_modes", ""),
                    "patch_rules": payload.get("patch_rules", ""),
                    "prompt_diff": payload.get("prompt_diff", ""),
                }
        filtered.append(
            {
                "round_index": item.get("round_index"),
                "base_round_index": item.get("base_round_index"),
                "baseline_score": item.get("baseline_score", {}),
                "round_score": item.get("round_score", {}),
                "improved": item.get("improved"),
                "steps": steps,
            }
        )
    return filtered


def _score_markdown(title: str, score: Dict[str, object]) -> list[str]:
    lines = [f"### {title}", ""]
    for key in (
        "node_precision",
        "node_recall",
        "node_f1",
        "edge_precision",
        "edge_recall",
        "edge_f1",
        "overall_score",
        "structural_similarity",
        "graph_edit_distance",
        "normalized_graph_edit_distance",
        "graph_edit_similarity",
    ):
        if key in score:
            lines.append(f"- {key}: {score[key]}")
    lines.append("")
    return lines


def _write_round_summary_md(path: Path, payload: Dict[str, object]) -> None:
    lines = [f"# Round {payload['round_index']} Summary", ""]
    lines.append(f"- source_case_dir: {payload['source_case_dir']}")
    lines.append(f"- base_round_index: {payload.get('base_round_index')}")
    lines.append(f"- candidate_dir: {payload['candidate_dir']}")
    lines.append(f"- rerun_case_dir: {payload['rerun_case_dir']}")
    lines.append(f"- improved: {payload['improved']}")
    lines.append("")
    lines.extend(_score_markdown("Baseline Score", payload["baseline_score"]))
    lines.extend(_score_markdown("Round Score", payload["round_score"]))
    if "round_analysis" in payload:
        analysis = payload["round_analysis"]
        if isinstance(analysis, dict):
            lines.append("## Round Analysis")
            lines.append("")
            lines.append("Improvement Analysis")
            lines.append(str(analysis.get("improvement_analysis", "")))
            lines.append("")
            lines.append("Regression Analysis")
            lines.append(str(analysis.get("regression_analysis", "")))
            lines.append("")
            lines.append("Next Round Strategy")
            lines.append(str(analysis.get("next_round_strategy", "")))
            lines.append("")
    lines.append("## Step Suggestions")
    lines.append("")
    for step_key, step_payload in payload["steps"].items():
        lines.append(f"### {step_key}")
        lines.append("")
        lines.append("Failure Modes")
        lines.append(str(step_payload.get("failure_modes", "")))
        lines.append("")
        lines.append("Patch Rules")
        lines.append(str(step_payload.get("patch_rules", "")))
        lines.append("")
        if "current_output" in step_payload:
            lines.append("Current Output")
            lines.append("```json")
            lines.append(json.dumps(step_payload.get("current_output", {}), ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
        if "prompt_diff" in step_payload:
            lines.append("Prompt Diff")
            lines.append("```text")
            lines.append(str(step_payload.get("prompt_diff", "")))
            lines.append("```")
            lines.append("")
        if "output_summary" in step_payload:
            lines.append("Output Summary")
            lines.append("```json")
            lines.append(json.dumps(step_payload.get("output_summary", {}), ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
        if "diff_summary_compact" in step_payload:
            lines.append("Diff Summary")
            lines.append("```json")
            lines.append(json.dumps(step_payload.get("diff_summary_compact", {}), ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_experiment_summary_md(path: Path, payload: Dict[str, object]) -> None:
    lines = ["# Experiment Summary", ""]
    lines.append(f"- source_case_dir: {payload['source_case_dir']}")
    lines.append("")
    best_score = payload.get("best_score")
    if isinstance(best_score, dict):
        lines.extend(_score_markdown("Best Score", best_score))
    lines.append("## Round History")
    lines.append("")
    for item in payload.get("history", []):
        lines.append(f"### Round {item['round_index']}")
        lines.append(f"- improved: {item['improved']}")
        lines.append(f"- base_round_index: {item.get('base_round_index', '')}")
        round_score = item.get("round_score", {})
        if isinstance(round_score, dict):
            lines.append(f"- overall_score: {round_score.get('overall_score', '')}")
            lines.append(f"- structural_similarity: {round_score.get('structural_similarity', '')}")
            lines.append(f"- graph_edit_distance: {round_score.get('graph_edit_distance', '')}")
            lines.append(
                f"- normalized_graph_edit_distance: {round_score.get('normalized_graph_edit_distance', '')}"
            )
            lines.append(f"- graph_edit_similarity: {round_score.get('graph_edit_similarity', '')}")
        analysis = item.get("round_analysis", {})
        if isinstance(analysis, dict):
            lines.append(f"- next_round_strategy: {analysis.get('next_round_strategy', '')}")
        lines.append("")
    top_k = payload.get("top_k", [])
    if isinstance(top_k, list) and top_k:
        lines.append("## Top-K Archive")
        lines.append("")
        for item in top_k:
            if not isinstance(item, dict):
                continue
            score = item.get("score", {})
            lines.append(f"### Round {item.get('round_index')}")
            lines.append(f"- case_dir: {item.get('case_dir', '')}")
            if isinstance(score, dict):
                lines.append(f"- structural_similarity: {score.get('structural_similarity', '')}")
                lines.append(f"- graph_edit_distance: {score.get('graph_edit_distance', '')}")
                lines.append(f"- overall_score: {score.get('overall_score', '')}")
            lines.append(f"- summary_path: {item.get('summary_path', '')}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_prompt_optimization(config: PromptOptimizationConfig) -> None:
    source_case_dir = _case_dir(config)
    if not source_case_dir.exists():
        raise FileNotFoundError(f"Case directory does not exist: {source_case_dir}")

    project_root = Path(__file__).resolve().parent.parent
    initial_prompt_by_step = {
        step_key: TARGET_PROMPT_FILES[step_key].read_text(encoding="utf-8")
        for step_key in config.target_steps
    }
    history, candidate_states, best_score, previous_round_summary, start_round_index = _resume_experiment_state(config)
    incident_description = load_step_optimization_input(
        source_case_dir, "identify_accident_scenario"
    ).step_input.get("incident_description", "")
    identify_hazard_consequence_output = (
        source_case_dir / "identify_hazard_consequence_output.json"
    ).read_text(encoding="utf-8")
    gold_graph = load_step_optimization_input(source_case_dir, "causal_edge_linking").gold_target
    case_context = build_case_context(
        incident_description=incident_description,
        identify_hazard_consequence_output=identify_hazard_consequence_output,
        gold_graph=gold_graph,
    )

    if start_round_index > config.max_rounds:
        print(
            f"Experiment already has rounds through {start_round_index - 1}; "
            f"MAX_ROUNDS={config.max_rounds}, so nothing new to run."
        )
        return

    remaining_rounds = config.max_rounds - start_round_index + 1
    with tqdm(total=remaining_rounds, desc="Optimization Rounds", unit="round") as round_bar:
        for round_index in range(start_round_index, config.max_rounds + 1):
            round_dir = _round_dir(config, round_index)
            if round_dir.exists():
                shutil.rmtree(round_dir)
            round_dir.mkdir(parents=True, exist_ok=True)
            if candidate_states:
                base_state = candidate_states[0]
                analysis_case_dir = base_state.case_dir
                current_prompt_by_step = dict(base_state.prompt_by_step)
            else:
                base_state = None
                analysis_case_dir = source_case_dir
                current_prompt_by_step = dict(initial_prompt_by_step)

            if round_index == 1:
                baseline_score = score_case(source_case_dir, 0)
                write_score(round_dir / "baseline_score.json", baseline_score)
            else:
                baseline_score = (
                    base_state.score
                    if base_state is not None
                    else (best_score if best_score is not None else score_case(source_case_dir, round_index - 1))
                )

            suggestions: Dict[str, PromptSuggestion] = {}
            diffs: Dict[str, dict] = {}
            output_summaries: Dict[str, dict] = {}
            step_keys = _ordered_target_steps(config.target_steps)

            with tqdm(total=4, desc=f"Round {round_index} Stages", unit="stage", leave=False) as stage_bar:
                with tqdm(step_keys, desc="Optimize Steps", unit="step", leave=False) as step_bar:
                    for step_key in step_bar:
                        step_bar.set_postfix_str(step_key)
                        step_data = load_step_optimization_input(analysis_case_dir, step_key)
                        step_data = step_data.__class__(
                            step_key=step_data.step_key,
                            prompt_path=step_data.prompt_path,
                            current_prompt=current_prompt_by_step[step_key],
                            step_input=step_data.step_input,
                            current_output=step_data.current_output,
                            gold_target=step_data.gold_target,
                            case_dir=step_data.case_dir,
                        )
                        if step_key == "identify_accident_scenario":
                            diff_summary = summarize_scenario_diff(step_data.current_output, step_data.gold_target)
                            output_summary = summarize_scenario_output(
                                step_data.current_output, step_data.gold_target
                            )
                        elif step_key == "causal_edge_linking":
                            diff_summary = summarize_edge_diff(step_data.current_output, step_data.gold_target)
                            output_summary = summarize_edge_output(
                                step_data.current_output, step_data.gold_target
                            )
                        else:
                            raise KeyError(f"Unsupported optimization step: {step_key}")

                        suggestion = suggest_prompt_patch(
                            step_key=step_key,
                            current_prompt=step_data.current_prompt,
                            step_input=step_data.step_input,
                            current_output=step_data.current_output,
                            gold_target=step_data.gold_target,
                            diff_summary=diff_summary,
                            previous_round_feedback=_build_previous_round_feedback(previous_round_summary),
                            model_name=config.dspy_model,
                            reasoning_effort=config.reasoning_effort,
                            verbosity=config.verbosity,
                        )
                        suggestions[step_key] = suggestion
                        diffs[step_key] = diff_summary
                        output_summaries[step_key] = output_summary
                stage_bar.update(1)

                candidate_dir = write_candidate_prompts(
                    output_root=round_dir,
                    experiment_name="candidate_prompts",
                    prompt_sources=TARGET_PROMPT_FILES,
                    suggestions=suggestions,
                    diffs=diffs,
                )
                stage_bar.update(1)

                rerun_case_dir = round_dir / "rerun_case"
                copy_case_tree(analysis_case_dir, rerun_case_dir)
                for step_key in step_keys:
                    candidate_prompt_path = candidate_dir / TARGET_PROMPT_FILES[step_key].name
                    rerun_single_step(
                        SingleStepRerunConfig(
                            case_dir=rerun_case_dir,
                            prompt_path=candidate_prompt_path,
                            step_key=step_key,
                            model_name=config.dspy_model,
                            reasoning_effort=config.reasoning_effort,
                            verbosity=config.verbosity,
                            max_output_tokens=config.max_output_tokens,
                            hazards_json_path=config.hazards_json_path,
                            conditions_json_path=config.conditions_json_path,
                            project_root=project_root,
                        )
                    )
                stage_bar.update(1)

                round_score = score_case(rerun_case_dir, round_index)
                write_score(round_dir / "round_score.json", round_score)
                stage_bar.update(1)

            improved = _is_better_score(round_score, best_score)
            if improved:
                best_score = round_score
            next_prompt_by_step = dict(current_prompt_by_step)
            rerun_outputs: Dict[str, dict] = {}
            prompt_diffs: Dict[str, str] = {}
            for step_key in config.target_steps:
                next_prompt_by_step[step_key] = (candidate_dir / TARGET_PROMPT_FILES[step_key].name).read_text(
                    encoding="utf-8"
                )
                rerun_outputs[step_key] = load_step_optimization_input(rerun_case_dir, step_key).current_output
                prompt_diffs[step_key] = (
                    candidate_dir / f"{step_key}_prompt_diff.md"
                ).read_text(encoding="utf-8")

            provisional_round_summary = {
                "round_index": round_index,
                "source_case_dir": str(analysis_case_dir),
                "candidate_dir": str(candidate_dir),
                "rerun_case_dir": str(rerun_case_dir),
                "base_round_index": base_state.round_index if base_state is not None else 0,
                "baseline_score": asdict(baseline_score),
                "round_score": asdict(round_score),
                "improved": improved,
                "steps": {
                    step_key: {
                        "current_output": rerun_outputs.get(step_key, {}),
                        "failure_modes": suggestion.failure_modes,
                        "patch_rules": suggestion.patch_rules,
                        "prompt_diff": prompt_diffs.get(step_key, ""),
                        "output_summary": output_summaries.get(step_key, {}),
                        "diff_summary_compact": compress_diff_summary(diffs.get(step_key, {})),
                    }
                    for step_key, suggestion in suggestions.items()
                },
            }
            round_analysis = analyze_round_history(
                case_context=case_context,
                history_window=_build_analyst_history_window(
                    history,
                    provisional_round_summary,
                    config.analysis_window_size,
                    config.analysis_rounds,
                ),
                model_name=config.dspy_model,
                reasoning_effort=config.reasoning_effort,
                verbosity=config.verbosity,
            )
            round_summary = dict(provisional_round_summary)
            round_summary["round_analysis"] = {
                "improvement_analysis": round_analysis.improvement_analysis,
                "regression_analysis": round_analysis.regression_analysis,
                "next_round_strategy": round_analysis.next_round_strategy,
            }
            _write_round_summary(round_dir / "round_summary.json", round_summary)
            _write_round_summary_md(round_dir / "round_summary.md", round_summary)
            history.append(round_summary)
            candidate_states.append(
                CandidateState(
                    round_index=round_index,
                    case_dir=rerun_case_dir,
                    prompt_by_step=next_prompt_by_step,
                    score=round_score,
                    summary_path=round_dir / "round_summary.json",
                )
            )
            candidate_states = _trim_top_k(candidate_states, config.top_k)
            previous_round_summary = round_summary
            round_bar.update(1)

    experiment_dir = config.prompt_output_dir / config.experiment_name
    experiment_summary = {
        "source_case_dir": str(source_case_dir),
        "case_context": case_context,
        "best_score": asdict(best_score) if best_score else None,
        "history": history,
        "top_k": [
            {
                "round_index": state.round_index,
                "case_dir": str(state.case_dir),
                "score": asdict(state.score),
                "summary_path": str(state.summary_path),
            }
            for state in candidate_states
        ],
    }
    _write_round_summary(
        experiment_dir / "experiment_summary.json",
        experiment_summary,
    )
    _write_experiment_summary_md(
        experiment_dir / "experiment_summary.md",
        experiment_summary,
    )
    print(f"Wrote optimization rounds to {experiment_dir}")
