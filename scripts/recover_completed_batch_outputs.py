from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.batch_runner import download_file_text
from pipeline.io_utils import extract_text_from_responses_body, get_response_dir, write_text
from pipeline.step_registry import STEP_REGISTRY


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover local outputs from an already completed OpenAI Batch."
    )
    parser.add_argument("batch_id")
    parser.add_argument("round_dir", type=Path)
    parser.add_argument("step_key", choices=tuple(STEP_REGISTRY))
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env_openai", override=True)
    round_dir = args.round_dir.resolve()
    if not round_dir.is_dir():
        raise FileNotFoundError(f"Round directory does not exist: {round_dir}")

    client = OpenAI()
    batch = client.batches.retrieve(args.batch_id)
    batch_data = batch.model_dump()
    if batch.status != "completed" or not batch.output_file_id:
        raise RuntimeError(
            f"Batch is not recoverable yet: status={batch.status}, "
            f"output_file_id={batch.output_file_id}"
        )
    metadata_step = (batch.metadata or {}).get("step")
    if metadata_step and metadata_step != args.step_key:
        raise ValueError(
            f"Batch metadata step {metadata_step!r} does not match {args.step_key!r}."
        )

    workdir = round_dir / "_batch_pipeline_all"
    workdir.mkdir(parents=True, exist_ok=True)
    write_text(
        workdir / f"{args.step_key}_batch_object.json",
        json.dumps(batch_data, ensure_ascii=False, indent=2),
    )
    output_text = download_file_text(client, batch.output_file_id)
    write_text(workdir / f"{args.step_key}_output_raw.jsonl", output_text)

    output_name = STEP_REGISTRY[args.step_key]["output_file"]
    ok = 0
    failed = 0
    unknown = 0
    for line in output_text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        custom_id = str(obj.get("custom_id") or "")
        folder = round_dir.joinpath(*custom_id.split("__")).resolve()
        if folder.parent.parent != round_dir or not folder.is_dir():
            unknown += 1
            continue
        if obj.get("error"):
            failed += 1
            write_text(
                folder / f"{args.step_key}_error.txt",
                json.dumps(obj["error"], ensure_ascii=False, indent=2),
            )
            continue
        response = obj.get("response")
        if not response or response.get("status_code") != 200:
            failed += 1
            write_text(
                folder / f"{args.step_key}_error.txt",
                json.dumps(obj, ensure_ascii=False, indent=2),
            )
            continue
        body = response.get("body", {})
        write_text(folder / output_name, extract_text_from_responses_body(body))
        response_dir = get_response_dir(folder)
        write_text(
            response_dir / f"{args.step_key}_response_raw.json",
            json.dumps(body, ensure_ascii=False, indent=2),
        )
        ok += 1

    print(f"Recovered {args.step_key}: ok={ok}, failed={failed}, unknown={unknown}")
    if failed or unknown:
        raise RuntimeError("Batch recovery was incomplete. Inspect the saved raw output.")


if __name__ == "__main__":
    main()
