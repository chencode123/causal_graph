from __future__ import annotations
import os

from pathlib import Path
import json
import time
from typing import Any, Dict, List, Optional, Tuple
import hashlib

from tqdm import tqdm
from openai import OpenAI

import utils.prompt_manager as prompt_manager
import winsound

# 你现有的本地后处理
from causal_graphviz.plot_conditions import draw_causal_graph as draw_causal_graph_png
from utils.causal_graph_interactive_pkg.causal_graph_interactive import (
    draw_causal_graph_interactive as draw_causal_graph_html,
)
import utils.incident_card_to_word as incident_card_to_word
from utils.combined_text_preprocess import build_prep_final_check_vars

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).with_name(".env_openai"), override=True)

BASE_DIR = Path(r"runs\batch_api_test\batch_1")  # 你的 runs 目录
MODEL_NAME = "gpt-5.2" #gpt-5.2-2025-12-11
ENDPOINT = "/v1/responses"

REASONING_EFFORT = "high"
VERBOSITY = "medium"
SAVE_RAW_RESPONSE = True  # True 时保存 <step_key>_response_raw.json

# 这些是你工程里用的 taxonomy 文件（建议用正斜杠避免转义）
HAZARDS_JSON_PATH = Path("prompt/hazards_consequence.json")
CONDITIONS_JSON_PATH = Path("prompt/conditions.json")

# -----------------------------
# 通用工具函数
# -----------------------------
def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")


def resolve_var_value(v: Any) -> str:
    """
    将变量值统一转换为“可注入 prompt 的字符串”：
    - Path -> 读文件内容
    - 其他 -> 转 str
    """
    if isinstance(v, Path):
        return read_text(v)
    return str(v)


def render_prompt(template: str, variables: Dict[str, Any]) -> str:
    """
    将 prompt 模板渲染为最终文本。

    ⚠️ 关键：这里假设你的模板是 Python 的 str.format 占位符。
       如果你 prompt_manager 里用的是 Jinja2 / 其他语法，
       把这函数改成你实际的渲染方式即可（其余代码不用动）。
    """
    materialized = {k: resolve_var_value(v) for k, v in variables.items()}
    try:
        return template.format(**materialized)
    except KeyError as e:
        missing = str(e)
        raise KeyError(
            f"Prompt template missing variable: {missing}. "
            f"Available vars: {sorted(materialized.keys())}"
        )


def extract_text_from_responses_body(body: Dict[str, Any]) -> str:
    """
    兼容提取 Responses API 输出文本。
    """
    if isinstance(body, dict) and isinstance(body.get("output_text"), str):
        return body["output_text"]

    output = body.get("output")
    if isinstance(output, list):
        parts: List[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and isinstance(c.get("text"), str):
                        parts.append(c["text"])
        if parts:
            return "\n".join(parts)

    # fallback
    return json.dumps(body, ensure_ascii=False, indent=2)

# -----------------------------
# Pipeline Step 定义
# -----------------------------
class Step:
    def __init__(
        self,
        key: str,
        output_filename: str,
        build_vars: callable,   # (folder: Path) -> Dict[str, Any]
        enabled: bool = True,
    ):
        self.key = key
        self.output_filename = output_filename
        self.build_vars = build_vars
        self.enabled = enabled

    def output_path(self, folder: Path) -> Path:
        return folder / self.output_filename

def build_pipeline(all_prompts: Dict[str, str]) -> List[Step]:

    hazards_json = HAZARDS_JSON_PATH
    conditions_json = CONDITIONS_JSON_PATH

    return [
        Step(
            key = "identify_hazard_consequence",
            output_filename="identify_hazard_consequence_output.txt",
            build_vars=lambda folder: {
               "identify_incident_output": (folder / "identify_incident_output.txt"),
               "hazards_consequence_json": hazards_json,
               },
        ),
        Step(
            key="identify_condition",
            output_filename="identify_condition_output.txt",
            build_vars=lambda folder: {
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
                "identify_incident_output": folder / "identify_incident_output.txt",
                "conditions_json": conditions_json,
            },
        ),
        Step(
            key="identify_evidence",
            output_filename="identify_evidence_output.txt",
            build_vars=lambda folder: {
                "identify_condition_output": folder / "identify_condition_output.txt",
                "identify_incident_output": folder / "identify_incident_output.txt",
                "conditions_json": conditions_json,
            },
        ),
        Step(
            key="chain_events",
            output_filename="chain_events_output.txt",
            build_vars=lambda folder: {
                "identify_evidence_output": folder / "identify_evidence_output.txt",
            },
        ),

        Step(
            key="identify_relationship",
            output_filename="identify_relationship_output.txt",
            build_vars=lambda folder: {
                "chain_events_output": folder / "chain_events_output.txt",
                "identify_incident_output": folder / "identify_incident_output.txt",
                "conditions_json": conditions_json,
            },
        ),
        Step(
            key="chain_conditions_events",
            output_filename="chain_conditions_events_output.txt",
            build_vars=lambda folder: {
                "identify_relationship_output": folder / "identify_relationship_output.txt",
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
                "chain_events_output": folder / "chain_events_output.txt",
                "conditions_json": conditions_json,
            },
        ),
        Step(
            key="chain_scenario",
            output_filename="chain_scenario_output.txt",
            build_vars=lambda folder: {
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
                "chain_events_output": folder / "chain_events_output.txt",
                "conditions_json": conditions_json,
            },
        ),
        Step(
            key="chain_hazards",
            output_filename="chain_hazards_output.txt",
            build_vars=lambda folder: {
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
                "identify_incident_output": folder / "identify_incident_output.txt",
                "conditions_json": conditions_json,
                "chain_scenario_output": folder / "chain_scenario_output.txt",
            },
        ),

        # this doesn't call api, this is preparation for final check
        Step(
            key="prep_final_check",
            output_filename="prep_final_check_output.txt",  
            build_vars=lambda folder: build_prep_final_check_vars(
                folder=folder,
                chain_scenario = folder / "chain_scenario_output.txt",
                chain_hazards = folder / "chain_hazards_output.txt",
                chain_conditions_events = folder / "chain_conditions_events_output.txt",
                hazards_json=hazards_json,
                conditions_json=conditions_json, 
                step_key="prep_final_check",  
            ),
        ),
    ]

def _mask(k: str | None) -> str:
    if not k:
        return "<None>"
    return k[:8] + "..." + k[-4:]

def truncate_text(s: str, limit: int = 50000) -> str:
    """Truncate long text for debug snapshots."""
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n\n...[TRUNCATED {len(s) - limit} chars]..."


def save_step_input_snapshot(
    folder: Path,
    step_key: str,
    template: str,
    vars_dict: Dict[str, Any],
    prompt_text: str,
    messages: List[Dict[str, str]],
    *,
    truncate_limit: int = 50000,
) -> None:
    """
    Save a readable snapshot of step inputs for debugging and reproducibility.
    - Materializes Path variables into file contents.
    - Saves rendered prompt and messages payload.
    """
    dbg_dir = folder / "_debug_inputs"
    dbg_dir.mkdir(parents=True, exist_ok=True)

    # Materialize variables (Path -> file content)
    materialized = {k: resolve_var_value(v) for k, v in vars_dict.items()}

    # Truncate huge fields for readability
    materialized_trunc = {k: truncate_text(str(v), truncate_limit) for k, v in materialized.items()}

    # 1) vars
    write_text(
        dbg_dir / f"{step_key}_vars_materialized.json",
        json.dumps(materialized_trunc, ensure_ascii=False, indent=2),
    )

    # 2) prompt
    write_text(dbg_dir / f"{step_key}_prompt_template.txt", truncate_text(template, truncate_limit))
    write_text(dbg_dir / f"{step_key}_prompt_rendered.txt", truncate_text(prompt_text, truncate_limit))

    # 3) messages payload
    write_text(
        dbg_dir / f"{step_key}_messages.json",
        json.dumps(messages, ensure_ascii=False, indent=2),
    )

def run_step_sync(
    client: OpenAI,
    all_prompts: Dict[str, str],
    folders: List[Path],
    step: Step,
    call_sleep_seconds: float = 0.0,  # 可选：每次请求间隔，避免触发速率限制
) -> None:
    """
    非 Batch：逐 folder 立即调用 /v1/responses，结果立刻写回各 folder。
    """
    # local-only step
    if step.key == "prep_final_check":
        ok = 0
        for folder in folders:
            try:
                step.build_vars(folder)
                ok += 1
            except Exception as e:
                write_text(folder / f"{step.key}_error.txt", f"{e}\n")
        print(f"[{step.key}] Local preprocessing done for {ok}/{len(folders)} folders.")
        return

    template = all_prompts[step.key]
    ok, fail = 0, 0

    for folder in folders:
        try:
            vars_dict = step.build_vars(folder)
            prompt_text = render_prompt(template, vars_dict)
        except Exception as e:
            fail += 1
            write_text(folder / f"{step.key}_error.txt", f"Prompt build failed: {e}\n")
            continue

        messages = [
            {"role": "system", "content": "You are a professional process safety analyst."},
            {"role": "user", "content": prompt_text},
        ]

        save_step_input_snapshot(
            folder=folder,
            step_key=step.key,
            template=template,
            vars_dict=vars_dict,
            prompt_text=prompt_text,
            messages=messages,
            truncate_limit=80000,  # 你可以调大/调小
        )

        try:
            # ✅ 即时调用：client.responses.create
            resp = client.responses.create(
                model=MODEL_NAME,
                input=messages,
                max_output_tokens=160000,  # 建议别 160000，调试用 30k~60k 更稳
                reasoning={"effort": REASONING_EFFORT},
                text={"verbosity": VERBOSITY},
            )

            # resp 是对象，转 dict 更通用
            body = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
            out_text = extract_text_from_responses_body(body)

            write_text(step.output_path(folder), out_text)
            ok += 1

            # 可选：保存原始响应，方便排查问题
            if SAVE_RAW_RESPONSE:
                write_text(
                    folder / f"{step.key}_response_raw.json",
                    json.dumps(body, ensure_ascii=False, indent=2),
                )

        except Exception as e:
            fail += 1
            write_text(folder / f"{step.key}_error.txt", f"API call failed: {e}\n")

        if call_sleep_seconds > 0:
            time.sleep(call_sleep_seconds)

    print(f"[{step.key}] Sync done. ok={ok}, fail={fail}")


def run_local_postprocess(all_prompts: Dict[str, str], folder: Path) -> None:

    # chain_scenario_text = read_text(folder / "chain_scenario_output.txt")
    # chain_hazards_text = read_text(folder / "chain_hazards_output.txt")
    # chain_conditions_events_text = read_text(folder / "chain_conditions_events_output.txt")

    # chain_text = chain_scenario_text + "\n" + chain_hazards_text + "\n" + chain_conditions_events_text
    # print(chain_text)
    # chain_text = read_text(folder / "final_check_output.txt")
    chain_text = read_text(folder / "prep_final_check_output.txt")
    draw_causal_graph_png(
        chain_lines=chain_text,
        conditions=str(CONDITIONS_JSON_PATH),
        hazards=str(HAZARDS_JSON_PATH),
        save_path=folder / "causal_graph.png",
    )

    # 画 html：你原逻辑是用 final_check_output.txt

    draw_causal_graph_html(
        chain_lines=chain_text,
        conditions=str(CONDITIONS_JSON_PATH),
        hazards=str(HAZARDS_JSON_PATH),
        save_path=folder / "causal_graph.html",
    )

    # generate docx
    incident_card_to_word.incident_card_to_word(
        identify_incident_prompt=all_prompts.get("identify_incident", ""),
        identify_hazard_consequence_prompt=all_prompts.get("identify_hazard_consequence", ""),
        identify_condition_prompt=all_prompts.get("identify_condition", ""),
        identify_evidence_prompt=all_prompts.get("identify_evidence", ""),
        chain_events_prompt=all_prompts.get("chain_events", ""),
        identify_relationship_prompt=all_prompts.get("identify_relationship", ""),
        chain_conditions_events_prompt=all_prompts.get("chain_conditions_events", ""),
        chain_scenario_prompt=all_prompts.get("chain_scenario", ""),
        chain_hazards_prompt=all_prompts.get("chain_hazards", ""),
        prep_final_check_prompt=all_prompts.get("prep_final_check", ""),  # 仍然可留空/存在

        identify_incident_output=folder / "identify_incident_output.txt",
        identify_hazard_consequence_output=folder / "identify_hazard_consequence_output.txt",
        identify_condition_output=folder / "identify_condition_output.txt",
        identify_evidence_output=folder / "identify_evidence_output.txt",
        chain_events_output=folder / "chain_events_output.txt",
        identify_relationship_output=folder / "identify_relationship_output.txt",
        chain_conditions_events_output=folder / "chain_conditions_events_output.txt",
        chain_scenario_output=folder / "chain_scenario_output.txt",
        chain_hazards_output=folder / "chain_hazards_output.txt",
        prep_final_check_output=folder / "prep_final_check_output.txt",
        prep_final_check_removed_edges_report = folder / "prep_final_check_removed_edges_report.txt",

        hazard_consequence_json=str(HAZARDS_JSON_PATH),
        conditions_json=str(CONDITIONS_JSON_PATH),

        graph_png=folder / "causal_graph.png",
        output_docx_path=folder / "incident_card_report.docx",
    )



# -----------------------------
# Batch processing
# -----------------------------
def run_batch_pipeline(base_dir: Path) -> None:
    client = OpenAI()
    print("[RUNTIME] OPENAI_API_KEY =", _mask(os.getenv("OPENAI_API_KEY")))
    print("[RUNTIME] OPENAI_BASE_URL env =", os.getenv("OPENAI_BASE_URL"))
    print("[RUNTIME] client base_url =", getattr(client, "base_url", None))

    all_prompts = prompt_manager.prompts.load_all()

    folders = [f for f in base_dir.iterdir() if f.is_dir()]
    print(f"Found {len(folders)} folders under {base_dir}")
    
    pipeline = build_pipeline(all_prompts)

    batch_workdir = base_dir / "_batch_pipeline"
    batch_workdir.mkdir(parents=True, exist_ok=True)

    # 逐步 batch：每一步一个 batch（跨 folders）
    for step in tqdm(pipeline, desc="Steps (sync)", unit="step"):
        if not step.enabled:
            continue
        run_step_sync(
            client=client,
            all_prompts=all_prompts,
            folders=folders,
            step=step,
            call_sleep_seconds=0.0,  # 若后续 folder 多可设 0.2~1.0
        )


    # 所有 LLM 步骤完成后，本地后处理（可并行，但先串行最稳）
    for folder in tqdm(folders, desc="Local postprocess", unit="folder"):
        try:
            run_local_postprocess(all_prompts, folder)
        except Exception as e:
            print(f"⚠️ Postprocess skipped for {folder.name}: {e}")


if __name__ == "__main__":
    run_batch_pipeline(BASE_DIR)
    print("✅ Done.")
    winsound.Beep(1000, 500)


def build_update_chain_vars(folder: Path) -> Dict[str, Any]:

    combined_text = "\n\n".join(
        (folder / f).read_text(encoding="utf-8")
        for f in [
            "chain_scenario_output.txt",
            "chain_hazards_output.txt",
            "chain_conditions_events_output.txt",
        ]
    )

    delete_report_path = folder / "delete_repetitive_events_output.txt"
    delete_report = (
        delete_report_path.read_text(encoding="utf-8")
        if delete_report_path.exists()
        else ""
    )

    print(f"[DEBUG] combined_text length = {len(combined_text)}")
    print(f"[DEBUG] delete_report length = {len(delete_report)}")

    return {
        "combined_text": combined_text,
        "delete_repetitive_events_output": delete_report,
    }

