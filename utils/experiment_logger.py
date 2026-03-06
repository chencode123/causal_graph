
import os, json, datetime, subprocess, sys

def save_json(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return path

def make_spec(
    task_name:str,
    version:str,
    purpose:str,
    task_type:str,
    dataset_desc:str,
    eval_desc:str,
    system_prompt:str,
    user_prompt:str,
    params:dict,
    expected_criteria:str,
    actual_outputs:list,
    meets_expectation:str,
    issues:str,
    next_steps:str,
    tools_or_schema:str=""
) -> dict:
    return {
        "task_name": task_name,
        "version": version,
        "purpose": purpose,
        "task_type": task_type,
        "dataset": dataset_desc,
        "evaluation": eval_desc,
        "prompt": {
            "system": system_prompt,
            "user": user_prompt
        },
        "tools_or_schema": tools_or_schema,
        "params": params,
        "expected": expected_criteria,
        "actual_outputs": actual_outputs,
        "analysis": {
            "meets_expectation": meets_expectation,
            "issues": issues
        },
        "next_steps": next_steps,
        "date": datetime.date.today().isoformat()
    }

def generate_card_from_spec(spec_path:str, outdir:str, gen_script:str):
    # call the generator script created earlier
    os.makedirs(outdir, exist_ok=True)
    cmd = [sys.executable, gen_script, "--spec", spec_path, "--outdir", outdir]
    return subprocess.check_output(cmd).decode("utf-8").strip()
