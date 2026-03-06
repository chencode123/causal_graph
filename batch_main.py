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
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).with_name(".env_openai"), override=True)

BASE_DIR = Path(r"runs\batch_api_test\batch_1")  # 你的 runs 目录
MODEL_NAME = "gpt-5.2"
ENDPOINT = "/v1/responses"
COMPLETION_WINDOW = "24h"

REASONING_EFFORT = "high"
VERBOSITY = "medium"

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


def poll_batch_until_done(client: OpenAI, batch_id: str, poll_seconds: int = 15) -> Dict[str, Any]:
    while True:
        b = client.batches.retrieve(batch_id)
        status = b.status
        if status in ("completed", "failed", "expired", "cancelled"):
            return b.model_dump() if hasattr(b, "model_dump") else dict(b)
        time.sleep(poll_seconds)


def download_file_text(client: OpenAI, file_id: str) -> str:
    resp = client.files.content(file_id)
    return resp.text if hasattr(resp, "text") else str(resp)


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
            key="delete_repetitive_events",
            output_filename="delete_repetitive_events_output.txt",
            build_vars=lambda folder: {
                "chain_events_output": folder / "chain_events_output.txt",
                "conditions_json": conditions_json,
            },
        ),
        Step(
            key="update_chain_events",
            output_filename="update_chain_events_output.txt",
            build_vars=lambda folder: {
                "chain_events_output": folder / "chain_events_output.txt",
                "delete_repetitive_events_output": folder / "delete_repetitive_events_output.txt",
            },
        ),
        Step(
            key="identify_relationship",
            output_filename="identify_relationship_output.txt",
            build_vars=lambda folder: {
                "update_chain_events_output": folder / "update_chain_events_output.txt",
                "identify_condition_output": folder / "identify_condition_output.txt",
                "conditions_json": conditions_json,
            },
        ),
        Step(
            key="chain_conditions_events",
            output_filename="chain_conditions_events_output.txt",
            build_vars=lambda folder: {
                "identify_relationship_output": folder / "identify_relationship_output.txt",
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
                "conditions_json": conditions_json,
            },
        ),
        Step(
            key="chain_scenario",
            output_filename="chain_scenario_output.txt",
            build_vars=lambda folder: {
                "identify_hazard_consequence_output": folder / "identify_hazard_consequence_output.txt",
                "update_chain_events_output": folder / "update_chain_events_output.txt",
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
                hazards_json=hazards_json,
                conditions_json=conditions_json,
                step_key="prep_final_check",  
            ),
        ),

        Step(
            key="final_check",
            output_filename="final_check_output.txt",   
            build_vars=lambda folder: {
                # 注意：这个变量是你代码里动态拼的 combined_text
                "combined_text_output":  read_text(folder / "prep_final_check_output.txt"),
                "hazards_consequence_json": hazards_json,
                "conditions_json": conditions_json,
            },
        ),
    ]


def _mask(k: str | None) -> str:
    if not k:
        return "<None>"
    return k[:8] + "..." + k[-4:]


# -----------------------------
# Batch 执行某一步（跨所有 folders）
# -----------------------------
def run_step_as_batch(
    client: OpenAI,
    all_prompts: Dict[str, str],
    folders: List[Path],
    step: Step,
    batch_workdir: Path,
) -> None:
    
    # -------------------------
    # NEW: local-only step (no LLM call)
    # -------------------------
    if step.key == "prep_final_check":
        ok = 0
        for folder in folders:
            try:
                # 只执行 build_vars 的副作用：写 prep_final_check_output.txt（processed_text）
                step.build_vars(folder)
                ok += 1
            except Exception as e:
                # 这里建议写到单独的 error 文件，别覆盖主产物
                write_text(folder / f"{step.key}_error.txt", f"{e}\n")
        print(f"[{step.key}] Local preprocessing done for {ok}/{len(folders)} folders.")
        return

    """
    对所有 folder 批量运行某个 step，并把输出写回各 folder 的 step.output_filename。
    """
    template = all_prompts[step.key]
    batch_input_path = batch_workdir / f"{step.key}_batchinput.jsonl"

    # 1) 生成 jsonl + 建映射
    id_to_folder: Dict[str, Path] = {}
    lines: List[str] = []

    for folder in folders:
        # 跳过：缺少必需输入的 folder
        try:
            vars_dict = step.build_vars(folder)
            # build_vars 里用了 Path 的会读文件；如果文件缺失会在 read_text 报错
            prompt_text = render_prompt(template, vars_dict)
        except Exception:
            continue

        custom_id = f"{folder.name}__{step.key}"
        id_to_folder[custom_id] = folder

        prompt_text = prompt_text

        messages = [
            {"role": "system", "content": "You are a professional process safety analyst."},
            {"role": "user", "content": prompt_text},
        ]

        body: Dict[str, Any] = {
            "model": MODEL_NAME,
            "input": messages,
            "max_output_tokens": 160000, 
            "reasoning": {"effort": REASONING_EFFORT},
            "text": { "verbosity": VERBOSITY }
        }

        # =========================
        # NEW: 保存每一次 prompt（chat messages）
        # =========================
        short_hash = hashlib.sha1(custom_id.encode("utf-8")).hexdigest()[:12]
        safe_prefix = folder.name[:40]  # 防止 Windows 路径过长

        prompt_dump_path = (
            batch_workdir
            / "prompts"
            / step.key
            / f"{safe_prefix}_{short_hash}.json"
        )

        # 确保目录存在（关键，避免 FileNotFoundError）
        prompt_dump_path.parent.mkdir(parents=True, exist_ok=True)

        write_text(
            prompt_dump_path,
            json.dumps(
                {
                    "custom_id": custom_id,
                    "step": step.key,
                    "folder": folder.name,
                    "messages": messages,          # system + user
                    "model": MODEL_NAME,
                    "max_output_tokens": body["max_output_tokens"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )


        req = {
            "custom_id": custom_id,
            "method": "POST",
            "url": ENDPOINT,
            "body": body,
        }
        lines.append(json.dumps(req, ensure_ascii=False))

    if not lines:
        print(f"[{step.key}] No runnable folders (missing inputs). Skipping.")
        return

    write_text(batch_input_path, "\n".join(lines) + "\n")
    print(f"[{step.key}] Prepared {len(lines)} requests: {batch_input_path}")

    # 2) 上传文件
    uploaded = client.files.create(file=open(batch_input_path, "rb"), purpose="batch")
    input_file_id = uploaded.id

    # 3) 创建 batch
    batch = client.batches.create(
        input_file_id=input_file_id,
        endpoint=ENDPOINT,
        completion_window=COMPLETION_WINDOW,
        metadata={"step": step.key},
    )
    batch_id = batch.id
    print(f"[{step.key}] Created batch: {batch_id}")

    # 4) 轮询
    final = poll_batch_until_done(client, batch_id=batch_id, poll_seconds=15)
    status = final.get("status")
    print(f"[{step.key}] Final status: {status}")

    # ✅ 永远保存 batch object，便于排查（无论成功失败）
    write_text(
        batch_workdir / f"{step.key}_batch_object.json",
        json.dumps(final, ensure_ascii=False, indent=2)
    )

    # 5) 下载 output 并写回
    if status == "completed":
        # ✅ 先保存 error file（如果有），因为很多时候 completed 但全部失败
        err_file_id = final.get("error_file_id")
        if err_file_id:
            err_text = download_file_text(client, err_file_id)
            write_text(batch_workdir / f"{step.key}_errors.jsonl", err_text)
            print(f"[{step.key}] Error file saved: {batch_workdir / f'{step.key}_errors.jsonl'}")
        else:
            print(f"[{step.key}] error_file_id is None")

        # ✅ 再判断 output_file_id 是否存在
        output_file_id = final.get("output_file_id")
        if not output_file_id:
            print(f"[{step.key}] output_file_id is None -> no successful requests. See batch_object + errors.")
            return

        out_text = download_file_text(client, output_file_id)
        raw_out_path = batch_workdir / f"{step.key}_output_raw.jsonl"
        write_text(raw_out_path, out_text)

        # 回填每个 folder
        for line in out_text.splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)

            custom_id = obj.get("custom_id")
            folder = id_to_folder.get(custom_id)
            if folder is None:
                continue

            error = obj.get("error")
            response = obj.get("response")

            if error:
                write_text(folder / f"{step.key}_error.txt", json.dumps(error, ensure_ascii=False, indent=2))
                continue

            if not response or response.get("status_code") != 200:
                write_text(folder / f"{step.key}_error.txt", json.dumps(obj, ensure_ascii=False, indent=2))
                continue

            text = extract_text_from_responses_body(response.get("body", {}))
            write_text(step.output_path(folder), text)

    else:
        # failed/expired/cancelled
        write_text(
            batch_workdir / f"{step.key}_batch_failed.json",
            json.dumps(final, ensure_ascii=False, indent=2)
        )

def run_local_postprocess(all_prompts: Dict[str, str], folder: Path) -> None:

    # # 画 png：用 combined_text（你原逻辑）
    # chain_scenario_text = read_text(folder / "chain_scenario_output.txt")
    # chain_hazards_text = read_text(folder / "chain_hazards_output.txt")
    # chain_conditions_events_text = read_text(folder / "chain_conditions_events_output.txt")

    # combined_text = chain_scenario_text + "\n" + chain_hazards_text + "\n" + chain_conditions_events_text

    chain_text = read_text(folder / "final_check_output.txt")
    # chain_text = read_text(folder / "prep_final_check_output.txt")
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
        identify_incident_prompt=all_prompts["identify_incident"],
        identify_hazard_consequence_prompt=all_prompts["identify_hazard_consequence"],
        identify_condition_prompt=all_prompts["identify_condition"],
        identify_evidence_prompt=all_prompts["identify_evidence"],
        chain_events_prompt=all_prompts["chain_events"],
        delete_repetitive_events_prompt=all_prompts["delete_repetitive_events"],
        update_chain_events_prompt=all_prompts["update_chain_events"],
        identify_relationship_prompt=all_prompts["identify_relationship"],
        chain_conditions_events_prompt=all_prompts["chain_conditions_events"],
        chain_scenario_prompt=all_prompts["chain_scenario"],
        chain_hazards_prompt=all_prompts["chain_hazards"],
        final_check_prompt=all_prompts["final_check"],

        identify_incident_output=folder / "identify_incident_output.txt",
        identify_hazard_consequence_output=folder / "identify_hazard_consequence_output.txt",
        identify_condition_output=folder / "identify_condition_output.txt",
        identify_evidence_output=folder / "identify_evidence_output.txt",
        chain_events_output=folder / "chain_events_output.txt",
        delete_repetitive_events_output=folder / "delete_repetitive_events_output.txt",
        update_chain_events_output=folder / "update_chain_events_output.txt",
        identify_relationship_output=folder / "identify_relationship_output.txt",
        chain_conditions_events_output=folder / "chain_conditions_events_output.txt",
        chain_scenario_output=folder / "chain_scenario_output.txt",
        chain_hazards_output=folder / "chain_hazards_output.txt",
        final_check_output=folder / "final_check_output.txt",

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
    for step in tqdm(pipeline, desc="Batch Steps", unit="step"):
        if not step.enabled:
            continue
        run_step_as_batch(
            client=client,
            all_prompts=all_prompts,
            folders=folders,
            step=step,
            batch_workdir=batch_workdir,
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
