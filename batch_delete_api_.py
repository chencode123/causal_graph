from __future__ import annotations
import os
from pathlib import Path
import json
import time
from typing import Any, Dict, List
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

BASE_DIR = Path(r"runs\batch_api_test\batch_1")  # ✅ 按你第二段代码
MODEL_NAME = "gpt-5.2" # gpt-5.2-2025-12-11
ENDPOINT = "/v1/responses"
COMPLETION_WINDOW = "24h"

REASONING_EFFORT = "high"
VERBOSITY = "medium"

# taxonomy
HAZARDS_JSON_PATH = Path("prompt/hazards_consequence.json")
CONDITIONS_JSON_PATH = Path("prompt/conditions.json")


# -----------------------------
# 通用工具函数
# -----------------------------
def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
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
    假设模板为 Python str.format 语法。
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


def _mask(k: str | None) -> str:
    if not k:
        return "<None>"
    return k[:8] + "..." + k[-4:]


def truncate_text(s: str, limit: int = 80000) -> str:
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
    truncate_limit: int = 80000,
) -> None:
    """
    Batch/Sync 都能用的输入快照：
    folder/_debug_inputs 下保存 vars/materialized + prompt(template/rendered) + messages
    """
    dbg_dir = folder / "_debug_inputs"
    dbg_dir.mkdir(parents=True, exist_ok=True)

    materialized = {k: resolve_var_value(v) for k, v in vars_dict.items()}
    materialized_trunc = {k: truncate_text(str(v), truncate_limit) for k, v in materialized.items()}

    write_text(
        dbg_dir / f"{step_key}_vars_materialized.json",
        json.dumps(materialized_trunc, ensure_ascii=False, indent=2),
    )
    write_text(dbg_dir / f"{step_key}_prompt_template.txt", truncate_text(template, truncate_limit))
    write_text(dbg_dir / f"{step_key}_prompt_rendered.txt", truncate_text(prompt_text, truncate_limit))
    write_text(
        dbg_dir / f"{step_key}_messages.json",
        json.dumps(messages, ensure_ascii=False, indent=2),
    )


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
            key="identify_hazard_consequence",
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
        # ✅ 按 batch_2：identify_relationship 用 chain_events + identify_incident
        Step(
            key="identify_relationship",
            output_filename="identify_relationship_output.txt",
            build_vars=lambda folder: {
                "chain_events_output": folder / "chain_events_output.txt",
                "identify_incident_output": folder / "identify_incident_output.txt",
                "conditions_json": conditions_json,
            },
        ),
        # ✅ 按 batch_2：chain_conditions_events 用 chain_events（不再用 update_chain_events）
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
        # ✅ 按 batch_2：chain_scenario 用 chain_events（不再用 update_chain_events）
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

        # ✅ local-only prep_final_check（按你第二段 build_prep_final_check_vars 参数）
        Step(
            key="prep_final_check",
            output_filename="prep_final_check_output.txt",
            build_vars=lambda folder: build_prep_final_check_vars(
                folder=folder,
                chain_scenario=folder / "chain_scenario_output.txt",
                chain_hazards=folder / "chain_hazards_output.txt",
                chain_conditions_events=folder / "chain_conditions_events_output.txt",
                hazards_json=hazards_json,
                conditions_json=conditions_json,
                step_key="prep_final_check",
            ),
        ),
    ]


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
    # local-only step (no LLM call)
    # -------------------------
    if step.key == "prep_final_check":
        ok = 0
        for folder in folders:
            try:
                step.build_vars(folder)
                # ✅ 关键：为了兼容你原来的 postprocess / docx，
                # 把 prep_final_check_output.txt 同步写一份到 final_check_output.txt
                prep_path = folder / "prep_final_check_output.txt"
                if prep_path.exists():
                    write_text(folder / "final_check_output.txt", read_text(prep_path))
                ok += 1
            except Exception as e:
                write_text(folder / f"{step.key}_error.txt", f"{e}\n")
        print(f"[{step.key}] Local preprocessing done for {ok}/{len(folders)} folders.")
        return

    template = all_prompts[step.key]
    batch_input_path = batch_workdir / f"{step.key}_batchinput.jsonl"

    id_to_folder: Dict[str, Path] = {}
    lines: List[str] = []

    for folder in folders:
        try:
            vars_dict = step.build_vars(folder)
            prompt_text = render_prompt(template, vars_dict)
        except Exception:
            continue

        custom_id = f"{folder.name}__{step.key}"
        id_to_folder[custom_id] = folder

        messages = [
            {"role": "system", "content": "You are a professional process safety analyst."},
            {"role": "user", "content": prompt_text},
        ]

        # ✅ 按你 sync 版：每个 folder 保存输入快照（对 batch 也启用）
        try:
            save_step_input_snapshot(
                folder=folder,
                step_key=step.key,
                template=template,
                vars_dict=vars_dict,
                prompt_text=prompt_text,
                messages=messages,
                truncate_limit=80000,
            )
        except Exception as e:
            write_text(folder / f"{step.key}_snapshot_error.txt", f"{e}\n")

        body: Dict[str, Any] = {
            "model": MODEL_NAME,
            "input": messages,
            "max_output_tokens": 160000,
            "reasoning": {"effort": REASONING_EFFORT},
            "text": {"verbosity": VERBOSITY},
        }

        # 额外：你原来的 batch_workdir/prompts 保存也保留（更利于复现）
        short_hash = hashlib.sha1(custom_id.encode("utf-8")).hexdigest()[:12]
        safe_prefix = folder.name[:40]
        prompt_dump_path = batch_workdir / "prompts" / step.key / f"{safe_prefix}_{short_hash}.json"
        prompt_dump_path.parent.mkdir(parents=True, exist_ok=True)
        write_text(
            prompt_dump_path,
            json.dumps(
                {
                    "custom_id": custom_id,
                    "step": step.key,
                    "folder": folder.name,
                    "messages": messages,
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

    uploaded = client.files.create(file=open(batch_input_path, "rb"), purpose="batch")
    input_file_id = uploaded.id

    batch = client.batches.create(
        input_file_id=input_file_id,
        endpoint=ENDPOINT,
        completion_window=COMPLETION_WINDOW,
        metadata={"step": step.key},
    )
    batch_id = batch.id
    print(f"[{step.key}] Created batch: {batch_id}")

    final = poll_batch_until_done(client, batch_id=batch_id, poll_seconds=15)
    status = final.get("status")
    print(f"[{step.key}] Final status: {status}")

    write_text(
        batch_workdir / f"{step.key}_batch_object.json",
        json.dumps(final, ensure_ascii=False, indent=2),
    )

    if status == "completed":
        err_file_id = final.get("error_file_id")
        if err_file_id:
            err_text = download_file_text(client, err_file_id)
            write_text(batch_workdir / f"{step.key}_errors.jsonl", err_text)
            print(f"[{step.key}] Error file saved: {batch_workdir / f'{step.key}_errors.jsonl'}")
        else:
            print(f"[{step.key}] error_file_id is None")

        output_file_id = final.get("output_file_id")
        if not output_file_id:
            print(f"[{step.key}] output_file_id is None -> no successful requests. See batch_object + errors.")
            return

        out_text = download_file_text(client, output_file_id)
        raw_out_path = batch_workdir / f"{step.key}_output_raw.jsonl"
        write_text(raw_out_path, out_text)

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
        write_text(
            batch_workdir / f"{step.key}_batch_failed.json",
            json.dumps(final, ensure_ascii=False, indent=2),
        )


def run_local_postprocess(all_prompts: Dict[str, str], folder: Path) -> None:
    # ✅ 按 batch_2：图用 prep_final_check_output
    chain_text = read_text(folder / "prep_final_check_output.txt")

    draw_causal_graph_png(
        chain_lines=chain_text,
        conditions=str(CONDITIONS_JSON_PATH),
        hazards=str(HAZARDS_JSON_PATH),
        save_path=folder / "causal_graph.png",
    )

    draw_causal_graph_html(
        chain_lines=chain_text,
        conditions=str(CONDITIONS_JSON_PATH),
        hazards=str(HAZARDS_JSON_PATH),
        save_path=folder / "causal_graph.html",
    )

    # ✅ docx：你原函数需要 final_check_output.txt，这里我们在 prep_final_check 已经复制生成了
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
# Batch pipeline
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

    for folder in tqdm(folders, desc="Local postprocess", unit="folder"):
        try:
            run_local_postprocess(all_prompts, folder)
        except Exception as e:
            print(f"⚠️ Postprocess skipped for {folder.name}: {e}")


if __name__ == "__main__":
    run_batch_pipeline(BASE_DIR)
    print("✅ Done.")
    winsound.Beep(1000, 500)
