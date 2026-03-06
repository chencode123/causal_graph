from __future__ import annotations

import os
import json
import asyncio
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from tqdm import tqdm
from dotenv import load_dotenv

import utils.prompt_manager as prompt_manager
import winsound

# 你现有的本地后处理
from causal_graphviz.plot_conditions import draw_causal_graph as draw_causal_graph_png
from utils.causal_graph_interactive_pkg.causal_graph_interactive import (
    draw_causal_graph_interactive as draw_causal_graph_html,
)
from utils.combined_text_preprocess import build_prep_final_check_vars
import utils.incident_card_to_word as incident_card_to_word


# -----------------------------
# ENV / CONFIG
# -----------------------------
load_dotenv(dotenv_path=Path(__file__).with_name(".env_tamu"), override=True)

BASE_DIR = Path(r"runs\batch_api_test\o3")

# ✅ 用 TAMU Chat API 的 model 名称（以 /api/models 返回为准）
MODEL_NAME = "protected.o3"

# ✅ TAMU Chat API endpoint
TAMUS_ENDPOINT = os.getenv("TAMUS_AI_CHAT_API_ENDPOINT", "https://chat-api.tamu.ai").rstrip("/")
TAMUS_KEY = os.getenv("TAMUS_AI_CHAT_API_KEY")

# 并发控制
MAX_CONCURRENCY = int(os.getenv("TAMUS_MAX_CONCURRENCY", "8"))
REQUEST_TIMEOUT = float(os.getenv("TAMUS_TIMEOUT_SEC", "120"))
MAX_RETRIES = int(os.getenv("TAMUS_MAX_RETRIES", "3"))

HAZARDS_JSON_PATH = Path("prompt/hazards_consequence.json")
CONDITIONS_JSON_PATH = Path("prompt/conditions.json")

# -----------------------------
# Utils
# -----------------------------
def _mask(k: str | None) -> str:
    if not k:
        return "<None>"
    if len(k) <= 12:
        return k
    return k[:8] + "..." + k[-4:]


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def resolve_var_value(v: Any) -> str:
    if isinstance(v, Path):
        return read_text(v)
    return str(v)


def render_prompt(template: str, variables: Dict[str, Any]) -> str:
    materialized = {k: resolve_var_value(v) for k, v in variables.items()}
    return template.format(**materialized)


def extract_text_from_tamus_chat_response(data: Dict[str, Any]) -> str:
    """
    兼容 TAMU 返回（OpenAI ChatCompletions 风格）
    """
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {})
        content = msg.get("content")
        if isinstance(content, str):
            return content
    return json.dumps(data, ensure_ascii=False, indent=2)


# -----------------------------
# Pipeline Step
# -----------------------------
class Step:
    def __init__(
        self,
        key: str,
        output_filename: str,
        build_vars: callable,  # (folder: Path) -> Dict[str, Any]
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
        # 本地预处理（不打模型）
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
        # final_check
        Step(
            key="final_check",
            output_filename="final_check_output.txt",
            build_vars=lambda folder: {
                "combined_text_output": read_text(folder / "prep_final_check_output.txt"),
                "hazards_consequence_json": hazards_json,
                "conditions_json": conditions_json,
            },
        ),
    ]


# -----------------------------
# TAMU Chat API Call (async)
# -----------------------------
async def _call_tamus_chat(
    client: httpx.AsyncClient,
    prompt_text: str,
    *,
    model: str,
) -> str:
    url = f"{TAMUS_ENDPOINT}/openai/chat/completions"
    headers = {
        "Authorization": f"Bearer {TAMUS_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You are a professional process safety analyst."},
            {"role": "user", "content": prompt_text},
        ],
    }

    last_err: Optional[str] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                last_err = f"HTTP {r.status_code}: {r.text}"
                if r.status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(min(2 ** (attempt - 1), 8))
                    continue
                raise RuntimeError(last_err)

            data = r.json()
            return extract_text_from_tamus_chat_response(data)

        except Exception as e:
            last_err = str(e)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
                continue
            raise RuntimeError(f"Chat call failed after {MAX_RETRIES} retries: {last_err}") from e

    raise RuntimeError(f"Chat call failed: {last_err}")


async def run_step_concurrently(
    all_prompts: Dict[str, str],
    folders: List[Path],
    step: Step,
    batch_workdir: Path,
    overall_pbar: Optional[tqdm] = None,   # ✅ 新增：总进度条
) -> None:
    # local-only
    if step.key == "prep_final_check":
        ok = 0
        for folder in folders:
            try:
                step.build_vars(folder)  # build_prep_final_check_vars 内部会写文件
                ok += 1
            except Exception as e:
                write_text(folder / f"{step.key}_error.txt", f"{e}\n")
            finally:
                if overall_pbar:
                    overall_pbar.update(1)
                    overall_pbar.set_postfix(step=step.key, last="ok" if ok else "err", refresh=True)

        print(f"[{step.key}] Local preprocessing done for {ok}/{len(folders)} folders.")
        return

    template = all_prompts.get(step.key)
    if not template:
        # 缺 prompt 模板：对每个 folder 写 error，并推进总进度（不让 overall 卡住）
        for folder in folders:
            write_text(folder / f"{step.key}_error.txt", f"Missing prompt template for step: {step.key}\n")
            if overall_pbar:
                overall_pbar.update(1)
                overall_pbar.set_postfix(step=step.key, last="err", refresh=True)
        return

    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    # 记录每个请求的 prompt（可选，和你原来一致）
    prompts_dir = batch_workdir / "prompts" / step.key
    prompts_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:

        async def one_folder(folder: Path) -> None:
            ok = False
            try:
                vars_dict = step.build_vars(folder)
                prompt_text = render_prompt(template, vars_dict)
            except Exception as e:
                write_text(folder / f"{step.key}_error.txt", f"[build_vars/render_prompt] {e}\n")
            else:
                # dump prompt
                custom_id = f"{folder.name}__{step.key}"
                short_hash = hashlib.sha1(custom_id.encode("utf-8")).hexdigest()[:12]
                safe_prefix = folder.name[:40]
                prompt_dump_path = prompts_dir / f"{safe_prefix}_{short_hash}.json"
                write_text(
                    prompt_dump_path,
                    json.dumps(
                        {
                            "custom_id": custom_id,
                            "step": step.key,
                            "folder": folder.name,
                            "model": MODEL_NAME,
                            "messages": [
                                {"role": "system", "content": "You are a professional process safety analyst."},
                                {"role": "user", "content": prompt_text},
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

                async with sem:
                    try:
                        out_text = await _call_tamus_chat(client, prompt_text, model=MODEL_NAME)
                        write_text(step.output_path(folder), out_text)
                        ok = True
                    except Exception as e:
                        write_text(folder / f"{step.key}_error.txt", f"[api_call] {e}\n")
            finally:
                if overall_pbar:
                    overall_pbar.update(1)
                    overall_pbar.set_postfix(step=step.key, last="ok" if ok else "err", refresh=True)

        tasks = [one_folder(f) for f in folders]
        for fut in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc=f"{step.key}", unit="req", dynamic_ncols=True):
            await fut


# -----------------------------
# Local postprocess (unchanged)
# -----------------------------
def run_local_postprocess(all_prompts: Dict[str, str], folder: Path) -> None:
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

    incident_card_to_word.incident_card_to_word(
        identify_incident_prompt=all_prompts.get("identify_incident", ""),
        identify_hazard_consequence_prompt=all_prompts.get("identify_hazard_consequence", ""),
        identify_condition_prompt=all_prompts.get("identify_condition", ""),
        identify_evidence_prompt=all_prompts.get("identify_evidence", ""),
        chain_events_prompt=all_prompts.get("chain_events", ""),
        delete_repetitive_events_prompt=all_prompts.get("delete_repetitive_events", ""),
        update_chain_events_prompt=all_prompts.get("update_chain_events", ""),
        identify_relationship_prompt=all_prompts.get("identify_relationship", ""),
        chain_conditions_events_prompt=all_prompts.get("chain_conditions_events", ""),
        chain_scenario_prompt=all_prompts.get("chain_scenario", ""),
        chain_hazards_prompt=all_prompts.get("chain_hazards", ""),
        final_check_prompt=all_prompts.get("final_check", ""),
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
# Main
# -----------------------------
async def run_pipeline(base_dir: Path) -> None:
    if not TAMUS_KEY:
        raise RuntimeError("Missing TAMUS_AI_CHAT_API_KEY in environment/.env")
    if not TAMUS_ENDPOINT:
        raise RuntimeError("Missing TAMUS_AI_CHAT_API_ENDPOINT in environment/.env")

    print("[RUNTIME] TAMUS_AI_CHAT_API_ENDPOINT =", TAMUS_ENDPOINT)
    print("[RUNTIME] TAMUS_AI_CHAT_API_KEY =", _mask(TAMUS_KEY))
    print("[RUNTIME] MODEL_NAME =", MODEL_NAME)
    print("[RUNTIME] MAX_CONCURRENCY =", MAX_CONCURRENCY)

    all_prompts = prompt_manager.prompts.load_all()
    folders = [f for f in base_dir.iterdir() if f.is_dir()]
    print(f"Found {len(folders)} folders under {base_dir}")

    pipeline = build_pipeline(all_prompts)
    enabled_steps = [s for s in pipeline if s.enabled]

    workdir = base_dir / "_batch_pipeline"
    workdir.mkdir(parents=True, exist_ok=True)

    total_units = len(folders) * len(enabled_steps)
    overall = tqdm(total=total_units, desc="TOTAL", unit="call", dynamic_ncols=True)

    try:
        for step in enabled_steps:
            await run_step_concurrently(all_prompts, folders, step, workdir, overall_pbar=overall)
    finally:
        overall.close()

    for folder in tqdm(folders, desc="Local postprocess", unit="folder", dynamic_ncols=True):
        try:
            run_local_postprocess(all_prompts, folder)
        except Exception as e:
            print(f"⚠️ Postprocess skipped for {folder.name}: {e}")


if __name__ == "__main__":
    asyncio.run(run_pipeline(BASE_DIR))
    print("✅ Done.")
    winsound.Beep(1000, 500)
