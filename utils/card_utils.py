# utils/card_utils.py
import os
import json
import datetime
from typing import Dict, Any, Tuple, List

import tiktoken
from openai import OpenAI
from causal_graphviz.plot import draw_causal_graph


# utils/card_utils.py
import os
import datetime
from typing import Dict, Any

def build_spec(
    task_name: str,
    version: str,
    model: str,
    token_count: int,
    result_text: str,
    graph_png: str,
    max_output_tokens: int,
    reasoning_effort: str,
    text_verbosity: str,
    timestamp: str,
    prompt_file: str | None = None,
    rules_file: str | None = None,
) -> Dict[str, Any]:
    """构建实验卡（模型调用参数由外部传入并记录）"""
    prompt_filename = os.path.basename(prompt_file) if prompt_file else None
    rules_filename  = os.path.basename(rules_file) if rules_file else None

    return {
        "task_name": task_name,
        "version": version,
        "date": timestamp,

        "prompt": {
            "prompt_file": prompt_filename,
            "rules_file": rules_filename,
        },

        "params": {
            "model": model,
            "max_output_tokens": max_output_tokens,
            "reasoning.effort": reasoning_effort,
            "text.verbosity": text_verbosity,
            "input_token_count": token_count,
        },

        "expected": (
            "- The hazard scenario should be expanded based on:\n"
            "   - Defined rules\n"
            "   - Process system structure\n"
            "   - Thermodynamic properties\n"
        ),

        "actual_outputs": [
            {
                "gpt_output_preview": result_text[:1000] + ("..." if len(result_text) > 1000 else ""),
                "artifacts": {"graph_png": graph_png},
            }
        ],

        "artifacts": [graph_png],
    }


def render_card_md(spec: Dict[str, Any]) -> str:
    """把 spec 渲染为 Markdown 文本（只显示 prompt/rules 文件名；图片自动内联）"""
    def _params_to_lines(p: Dict[str, Any]) -> str:
        keys = ["model","temperature","top_p","max_tokens","stop","n","presence_penalty","frequency_penalty",
                "reasoning.effort","text.verbosity","STRICT_JSON","input_token_count"]
        lines = [f"{k}: {p[k]}" for k in keys if k in p]
        for k, v in p.items():
            if k not in keys:
                lines.append(f"{k}: {v}")
        return "\n".join(lines)

    header = (
        f"# Experiment card：{spec.get('task_name','untitled')}  {spec.get('version','v001')}\n"
        f"- Date：{spec.get('date','')}\n"
    )

    p = spec.get("prompt", {})
    prompt_block = "## Prompt version\n"
    prompt_block += "```\n" \
                    f"prompt_file: {p.get('prompt_file')}\n" \
                    f"rules_file:  {p.get('rules_file')}\n" \
                    "```\n\n"

    params_block = "## Parameters\n```\n" + _params_to_lines(spec.get("params", {})) + "\n```\n\n"

    expected_block = "## Expected output\n" + (spec.get("expected", "- （填入你的标准）")) + "\n\n"

    outputs = spec.get("actual_outputs", [])
    outputs_block = "## Textual output\n"
    if not outputs:
        outputs_block += "（还未填写）\n\n"
    else:
        for i, out in enumerate(outputs, 1):
            outputs_block += f"List#{i}：\n"

            if "gpt_output_preview" in out:
                preview = out["gpt_output_preview"].strip()
                outputs_block += "GPT preview：\n```\n" + preview + "\n```\n\n"

    artifacts = spec.get("artifacts", [])
    artifacts_block = ""
    if artifacts:
        artifacts_block = "## Visualized output\n"
        for a in artifacts:
            name = os.path.basename(str(a))
            if name.lower().endswith(".png"):
                artifacts_block += f"![{name}](../artifacts/{name})\n"
            else:
                artifacts_block += f"- {a}\n"

    return "\n".join([header, prompt_block, params_block, expected_block, outputs_block, artifacts_block])


def save_card(md: str, timestamp: str, outdir: str = "./runs/cards", stem: str = "causal_graph_extraction") -> str:
    """
    保存 Markdown 文件，使用时间戳命名（不覆盖）。
    文件命名示例：
        causal_graph_extraction_2025-10-07T21-45-32.md
    """
    os.makedirs(outdir, exist_ok=True)

    # 当前时间（精确到秒，替换冒号为“-”以兼容文件名）
    timestamp = timestamp
    filename = f"{stem}_{timestamp}.md"

    path = os.path.join(outdir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"✅ Saved card: {filename}")
    return path