from __future__ import annotations

from pathlib import Path
import json
import time
from typing import Dict, Any, Optional

from openai import OpenAI

import utils.prompt_manager as prompt_manager


# -----------------------------
# Config
# -----------------------------
MODEL_NAME = "gpt-5.2"
ENDPOINT = "/v1/responses"
COMPLETION_WINDOW = "24h"

OUTPUT_FILENAME = "identify_hazard_consequence_output.txt"
ERROR_FILENAME = "identify_hazard_consequence_error.txt"
INCIDENT_INPUT_FILENAME = "identify_incident_output.txt"


# -----------------------------
# Helpers
# -----------------------------
def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def extract_text_from_responses_body(body: Dict[str, Any]) -> str:
    """
    Try hard to extract the assistant text from a Responses API response body.
    The exact schema can vary by SDK/version/model output shape, so we handle common cases.

    If you enforce JSON output via response_format/json_schema, you can instead dump JSON.
    """
    # Common convenience field in some SDKs
    if isinstance(body, dict) and isinstance(body.get("output_text"), str):
        return body["output_text"]

    # Common raw structure: body["output"] is a list of items, each has "content"
    output = body.get("output")
    if isinstance(output, list):
        chunks = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and isinstance(c.get("text"), str):
                        chunks.append(c["text"])
                    # sometimes nested like {"type":"output_text","text":"..."}
                    elif isinstance(c, dict) and isinstance(c.get("content"), str):
                        chunks.append(c["content"])
        if chunks:
            return "\n".join(chunks)

    # Fallback: dump the whole body
    return json.dumps(body, ensure_ascii=False, indent=2)


def build_instructions(
    prompt_template: str,
    incident_text: str,
    hazards_consequence_json_text: str,
) -> str:
    """
    Render your identify_hazard_consequence prompt.
    Adjust variable names to match your template placeholders.

    Example placeholders you might have in your prompt:
      {identify_incident_output}
      {hazards_consequence_json}
    """
    return prompt_template.format(
        identify_incident_output=incident_text,
        hazards_consequence_json=hazards_consequence_json_text,
    )


def make_batch_jsonl(
    base_dir: Path,
    subfolders: list[Path],
    prompt_template: str,
    hazards_consequence_json_path: Path,
    out_jsonl_path: Path,
) -> Dict[str, Path]:
    """
    Create batch input .jsonl. Returns mapping custom_id -> folder path.
    """
    hazards_json_text = read_text(hazards_consequence_json_path)
    id_to_folder: Dict[str, Path] = {}

    lines = []
    for folder in subfolders:
        incident_path = folder / INCIDENT_INPUT_FILENAME
        if not incident_path.exists():
            # skip folders without required input
            continue

        custom_id = folder.name  # 你也可以用 f"{folder.name}__s1"
        id_to_folder[custom_id] = folder

        incident_text = read_text(incident_path)
        instructions = build_instructions(
            prompt_template=prompt_template,
            incident_text=incident_text,
            hazards_consequence_json_text=hazards_json_text,
        )

        # Batch 每行一个 request；body 参数与 /v1/responses 一致
        # 这里用 instructions + input 的最常见组合
        req = {
            "custom_id": custom_id,
            "method": "POST",
            "url": ENDPOINT,
            "body": {
                "model": MODEL_NAME,
                "instructions": instructions,
                "input": "Return the hazard consequence identification result.",  # 可留空或写一个固定 user prompt
                # 可按需要加 max_output_tokens / temperature 等
                # "max_output_tokens": 1200,
                # "temperature": 0,
            },
        }
        lines.append(json.dumps(req, ensure_ascii=False))

    out_jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return id_to_folder


def poll_batch_until_done(client: OpenAI, batch_id: str, poll_seconds: int = 10) -> Dict[str, Any]:
    while True:
        b = client.batches.retrieve(batch_id)
        status = b.status
        print(f"[batch] status={status}")
        if status in ("completed", "failed", "expired", "cancelled"):
            return b.model_dump() if hasattr(b, "model_dump") else dict(b)
        time.sleep(poll_seconds)


def download_file_text(client: OpenAI, file_id: str) -> str:
    # Files content API returns a response-like object in the Python SDK
    resp = client.files.content(file_id)
    return resp.text if hasattr(resp, "text") else str(resp)


def write_back_outputs(
    output_jsonl_text: str,
    id_to_folder: Dict[str, Path],
) -> None:
    for line in output_jsonl_text.splitlines():
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
            (folder / ERROR_FILENAME).write_text(
                json.dumps(error, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            continue

        if not response or response.get("status_code") != 200:
            (folder / ERROR_FILENAME).write_text(
                json.dumps(obj, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            continue

        body = response.get("body", {})
        text = extract_text_from_responses_body(body)
        (folder / OUTPUT_FILENAME).write_text(text, encoding="utf-8")


# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    client = OpenAI()

    all_prompts = prompt_manager.prompts.load_all()
    prompt_template = all_prompts["identify_hazard_consequence"]

    hazards_consequence_json_path = Path("prompt/hazards_consequence.json")

    base_dir = Path(r"runs\batch_test\batch_1_top_5")
    subfolders = [f for f in base_dir.iterdir() if f.is_dir()]
    print(f"Found {len(subfolders)} folders under {base_dir}")

    # 1) Build jsonl
    batch_dir = base_dir / "_batch_step1"
    safe_mkdir(batch_dir)
    batch_input_path = batch_dir / "identify_hazard_consequence_batchinput.jsonl"

    id_to_folder = make_batch_jsonl(
        base_dir=base_dir,
        subfolders=subfolders,
        prompt_template=prompt_template,
        hazards_consequence_json_path=hazards_consequence_json_path,
        out_jsonl_path=batch_input_path,
    )
    print(f"Wrote batch input: {batch_input_path} ({len(id_to_folder)} requests)")

    # 2) Upload file for batch
    uploaded = client.files.create(
        file=open(batch_input_path, "rb"),
        purpose="batch",
    )
    input_file_id = uploaded.id
    print(f"Uploaded batch input file_id={input_file_id}")

    # 3) Create batch
    batch = client.batches.create(
        input_file_id=input_file_id,
        endpoint=ENDPOINT,
        completion_window=COMPLETION_WINDOW,
        metadata={"step": "identify_hazard_consequence"},
    )
    batch_id = batch.id
    print(f"Created batch_id={batch_id}")

    # 4) Poll until done
    final = poll_batch_until_done(client, batch_id=batch_id, poll_seconds=15)
    status = final.get("status")
    print(f"[batch] final status={status}")

    # 5) Download outputs + write back
    if status == "completed":
        output_file_id = final.get("output_file_id")
        if not output_file_id:
            raise RuntimeError("Batch completed but output_file_id is missing.")
        output_text = download_file_text(client, output_file_id)
        write_back_outputs(output_text, id_to_folder)
        print("✅ Wrote identify_hazard_consequence_output.txt to each folder (where successful).")

        # Optional: handle error file too
        err_file_id = final.get("error_file_id")
        if err_file_id:
            err_text = download_file_text(client, err_file_id)
            (batch_dir / "identify_hazard_consequence_errors.jsonl").write_text(err_text, encoding="utf-8")
            print(f"⚠️ Error file saved to: {batch_dir / 'identify_hazard_consequence_errors.jsonl'}")

    else:
        # failed/expired/cancelled
        print("⚠️ Batch did not complete successfully. Inspect batch object & error_file_id if present.")
        print(json.dumps(final, ensure_ascii=False, indent=2))
