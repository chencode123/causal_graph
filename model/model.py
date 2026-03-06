from openai import OpenAI
from pathlib import Path
import os
from utils.input_normalization import normalize_input_var

def run_prompt(
    prompt=None,
    variables=None,
    output_dir="outputs",
    model_name=None,
    api_key=None,
    prompt_key="none",
    prev_prompt=None,
    prev_output=None,
    reasoning_effort=None,   # "none" | "low" | "medium" | "high" | "xhigh"
    verbosity=None,          # "low" | "normal" | "high"
    max_output_tokens=16000,
    preview_only=False,
    print_prompt=False,
):
    """
    Run a formatted prompt through OpenAI Responses API (non-streaming mode).
    """

    # Resolve variables -> JSON literals
    if variables and isinstance(variables, dict):
        resolved_vars = {k: normalize_input_var(v) for k, v in variables.items()}
        prompt = prompt.format(**resolved_vars)

    if print_prompt or preview_only:
        print("========== FINAL PROMPT ==========\n")
        print(prompt)
        print("\n========== END PROMPT ==========")

    if preview_only:
        return prompt  # <-- 不调用 API

    client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    messages = [{"role": "system", "content": "You are a professional process safety analyst. Reason carefully for each tasks."}]

    if prev_prompt and prev_output:
        messages.extend([
            {"role": "user", "content": prev_prompt},
            {"role": "assistant", "content": prev_output},
        ])

    messages.append({"role": "user", "content": prompt})

    request_kwargs = {
        "model": model_name,
        "input": messages,
        "max_output_tokens": max_output_tokens,
    }

    if verbosity is not None:
        request_kwargs["text"] = {"verbosity": verbosity}

    if reasoning_effort is not None:
        request_kwargs["reasoning"] = {"effort": reasoning_effort}

    response = client.responses.create(**request_kwargs)
    output = response.output_text

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        outfile = output_dir / f"{prompt_key}_output.txt"
        outfile.write_text(output, encoding="utf-8")

    return output
