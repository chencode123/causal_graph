# Prompt 新建与测试说明

本项目当前以这 4 个文件为核心：

- `prompt/<step_key>.txt`：Prompt 正文（真正写任务指令的地方）
- `prompt/manifest.json`：Prompt 注册与变量声明
- `pipeline/step_registry.py`：Step 元数据 + `required_vars` 映射（变量名 -> 数据来源）
- `pipeline/step_var_resolver.py`：只做变量取值解析与执行顺序（`ACTIVE_STEP_KEYS`）

## 0. 先记住一条

不要在 `step_var_resolver.py` 里写 prompt 内容。  
Prompt 只写在 `prompt/<step_key>.txt`。

## 1. 新增一个 Step 的最简流程

1. 运行脚手架：

```bash
python scripts/new_step.py <step_key>
```

示例：

```bash
python scripts/new_step.py identify_root_cause
```

2. 编辑 Prompt 文件：`prompt/<step_key>.txt`
- 在里面写任务说明和 `{变量占位符}`。

3. 更新 `prompt/manifest.json`
- `template_file`
- `required_vars`
- `optional_vars`

要求：模板里的 `{变量}` 必须与 manifest 中声明一致。

4. 更新 `pipeline/step_registry.py`
- 新增同名 step key
- 填写 `output_file`
- 填写 `required_vars`（注意：这里是“变量 -> 来源地址”）
- 可选：`default_params`

5. 将 step key 加到 `pipeline/step_var_resolver.py` 的 `ACTIVE_STEP_KEYS`（控制执行顺序）

6. 运行测试：

```bash
pytest tests/test_prompt_keys_sync.py tests/test_prompt_vars_sync.py -q -p no:cacheprovider
```

也可以直接使用项目脚本（推荐）：

```powershell
.\scripts\test_prompt.ps1
```

## 2. `required_vars` 正确写法（你现在用的方式）

在 `pipeline/step_registry.py` 中，`required_vars` 直接写成映射：

```python
"required_vars": {
    "identify_incident_output": "folder:identify_incident_output.txt",
    "hazards_consequence_json": "config:hazards_json",
    "identify_hazard_consequence_scheme": "project:scheme/identify_hazard_consequence_scheme.json"
}
```

支持的来源前缀：

- `folder:<文件名或相对路径>`：当前样本目录下文件
- `project:<相对项目根目录路径>`：项目根目录下文件
- `config:hazards_json`：运行配置里的 hazards JSON
- `config:conditions_json`：运行配置里的 conditions JSON

## 3. 什么时候要改 `step_var_resolver.py`

大多数情况不用改。  
只有以下情况才需要改：

- 你新增了新的来源类型（例如 `env:`、`http:`）
- 你想扩展解析规则本身

普通新增 step 时，只改：
- prompt 文件
- manifest
- step_registry
- `ACTIVE_STEP_KEYS`

## 4. 常见错误定位

1. `Missing key`
- 含义：`step_registry` 里有 key，但 `manifest` 没有。

2. `Missing file`
- 含义：manifest 声明的 `template_file` 不存在。

3. `Variable mismatch`
- 含义：模板占位符和 manifest 声明不一致。

4. `Registry mismatch`
- 含义：`step_registry.required_vars`（变量名集合）与 `manifest.required_vars` 不一致。
