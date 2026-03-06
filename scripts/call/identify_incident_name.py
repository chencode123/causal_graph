def identify_incident_name(client, model_name, report_text, 
                           prompt_path=None,
                           reasoning_effort="medium",
                           text_verbosity="medium",
                           max_output_tokens=6000):

    # 1. 读取 prompt 模板
    with open(prompt_path, "r", encoding="utf-8") as f:
        identify_name_prompt_template = f.read()

    # 2. 格式化输入
    identify_name_incident_prompt = identify_name_prompt_template.format(
        report_text=report_text[:1000]
    )

    # 3. 调用模型
    r_name = client.responses.create(
        model=model_name,
        input=[
            {"role": "system", "content": "You are a professional process safety analyst."},
            {"role": "user", "content": identify_name_incident_prompt}
        ],
        max_output_tokens=max_output_tokens,
        reasoning={"effort": reasoning_effort},
        text={"verbosity": text_verbosity},
    )

    # 4. 返回结果
    return r_name.output_text
