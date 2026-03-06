
import os, json, datetime, hashlib

def slugify(s):
    return "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-").replace("--","-")

def hash_short(text):
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]

def render_card(spec: dict) -> str:
    def get(d,k,default=""):
        return d.get(k, default)
    header = f"# 实验卡：{spec.get('task_name','untitled')}  {spec.get('version','v001')}\n- 日期：{spec.get('date') or datetime.date.today().isoformat()}\n- 目的：{spec.get('purpose','')}\n- 任务类型：{spec.get('task_type','')}\n- 数据源：{spec.get('dataset','')}\n- 评估方式：{spec.get('evaluation','')}\n"
    prompt = spec.get("prompt",{})
    tools = spec.get("tools_or_schema","").strip()
    prompt_block = "## Prompt（system / user / tools）\n"
    prompt_block += "SYSTEM:\n```\n" + prompt.get("system","").strip() + "\n```\n\n"
    prompt_block += "USER:\n```\n" + prompt.get("user","").strip() + "\n```\n\n"
    if tools:
        prompt_block += "TOOLS / JSON schema（如需要）:\n```\n" + tools + "\n```\n\n"
    params = spec.get("params",{})
    keys = ["model","temperature","top_p","max_tokens","stop","n","presence_penalty","frequency_penalty"]
    lines = [f"{k}: {params[k]}" for k in keys if k in params]
    for k,v in params.items():
        if k not in keys:
            lines.append(f"{k}: {v}")
    params_block = "## 参数设置\n```\n" + "\n".join(lines) + "\n```\n\n"
    expected_block = "## 期望输出（定义“好”的标准）\n" + (spec.get("expected","- （填入你的标准）")) + "\n\n"
    outputs = spec.get("actual_outputs",[])
    outputs_block = "## 实际输出\n"
    if not outputs:
        outputs_block += "（还未填写）\n\n"
    else:
        import json
        for i, out in enumerate(outputs, 1):
            outputs_block += f"候选#{i}：\n```json\n{json.dumps(out, ensure_ascii=False, indent=2)}\n```\n\n"
    analysis = spec.get("analysis",{})
    analysis_block = "## 问题分析\n"
    analysis_block += f"- 结果是否达标：{analysis.get('meets_expectation','未评估')}\n"
    if analysis.get("issues",""):
        analysis_block += "- 失败样例/误差类型：\n" + analysis["issues"] + "\n"
    analysis_block += "\n"
    next_block = "## 改进计划（下一步实验假设）\n" + (spec.get("next_steps","- （下一步要改什么，为什么）")) + "\n"
    return "\n".join([header, prompt_block, params_block, expected_block, outputs_block, analysis_block, next_block])

def save_card(spec: dict, content: str, base_dir: str):
    os.makedirs(base_dir, exist_ok=True)
    task = slugify(spec.get("task_name","untitled"))
    version = spec.get("version","v001")
    today = datetime.date.today().isoformat()
    fingerprint = hash_short(json.dumps(spec.get("prompt",{}), ensure_ascii=False))
    filename = f"{task}_{version}_{today}_{fingerprint}.md"
    path = os.path.join(base_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate an experiment card (Markdown) from a JSON spec.")
    parser.add_argument("--spec", required=True, help="Path to JSON spec file")
    parser.add_argument("--outdir", default="./exp_cards", help="Output directory")
    args = parser.parse_args()
    with open(args.spec, "r", encoding="utf-8") as f:
        spec = json.load(f)
    content = render_card(spec)
    out_path = save_card(spec, content, args.outdir)
    print(out_path)
