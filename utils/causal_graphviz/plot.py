from graphviz import Digraph
import textwrap, re, json, os
from collections import OrderedDict
from typing import Iterable, Union, List, Set
from datetime import datetime

__all__ = ["draw_causal_graph"]

_CAUSE_VERBS = r"(causes|cause)"  # 可扩展

def _normalize_text_block(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    return s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")

def _split_into_lines(s: str) -> List[str]:
    if "\n" in s:
        return s.splitlines()
    return re.split(r"(?<=[\.!?])\s+", s)

def _to_cause_lines(data: Union[str, Iterable[str]]) -> List[str]:
    if isinstance(data, str):
        data = _normalize_text_block(data)
        lines = _split_into_lines(data)
    else:
        lines = list(data)

    pat = re.compile(rf"(.+?)\s+{_CAUSE_VERBS}\s+(.+)", re.I)
    out: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = pat.search(line)
        if not m:
            continue
        src = re.sub(r"\s+", " ", m.group(1).rstrip(".").strip())
        dst = re.sub(r"\s+", " ", m.group(3).rstrip(".").strip())  # group(2) 是动词
        out.append(f"{src} causes {dst}")  # 归一化动词
    return list(OrderedDict.fromkeys(out))  # 去重保序

def _collect_nodes_from_cause_lines(lines: List[str]) -> List[str]:
    nodes = []
    for line in lines:
        if "causes" in line:
            src, dst = line.split("causes", 1)
            nodes.extend([src.strip(), dst.strip()])
    # 去重保序
    seen, ordered = set(), []
    for n in nodes:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered

def _load_rules_nodes(rules: Union[None, str, Iterable[str]]) -> Set[str]:
    """
    读取 rules 并返回需要高亮的节点集合（既包含 A 也包含 B）。
    支持：文件路径（json）、字符串、或可迭代的字符串列表。
    """
    if rules is None:
        return set()

    # 1) 路径：尝试解析 json（[{Hazard:..., Scenarios:[...]}, ...] 或 {"Scenarios":[...]} 均可）
    if isinstance(rules, str) and os.path.exists(rules):
        with open(rules, "r", encoding="utf-8") as f:
            data = json.load(f)
        scenario_lines = []
        if isinstance(data, dict) and "Scenarios" in data:
            scenario_lines.extend(data["Scenarios"])
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "Scenarios" in item:
                    scenario_lines.extend(item["Scenarios"])
        # 归一化
        norm = _to_cause_lines(scenario_lines)
        return set(_collect_nodes_from_cause_lines(norm))

    # 2) 一段长字符串或 3) 可迭代的字符串
    if isinstance(rules, str):
        norm = _to_cause_lines(rules)
    else:
        norm = _to_cause_lines(list(rules))
    return set(_collect_nodes_from_cause_lines(norm))

def draw_causal_graph(
    chain_lines: Union[str, Iterable[str]],
    rankdir: str = "LR",
    width: int = 28,
    rules: Union[None, str, Iterable[str]] = None,
    highlight_color: str = "#cfe8ff",  # 浅蓝色
    *,
    save_path: str | None = None,      # ← 新增：指定文件名保存（含目录和扩展名）
    fmt: str = "png",                  # ← 新增：输出格式（png/svg/pdf等）；可被 save_path 扩展名覆盖
    dpi: int = 180,
):
    """
    chain_lines: 待画的因果链（字符串或字符串列表）
    rules:      用于高亮的规则来源（文件路径/字符串/字符串列表）
    save_path:  若提供，则保存到该文件（返回保存后的最终路径）；否则返回 Digraph 对象
    fmt:        输出格式（默认 png），若 save_path 带扩展名则以扩展名为准
    """
    lines = _to_cause_lines(chain_lines)
    nodes = _collect_nodes_from_cause_lines(lines)

    highlight_nodes = _load_rules_nodes(rules)

    dot = Digraph(format="svg")
    dot.attr(rankdir=rankdir)
    dot.attr("graph", dpi=str(dpi))   # ← 应用分辨率
    dot.attr("node", shape="box", style="rounded", fontsize="10", fontname="sans-serif")

    # 稳定 id，避免换行导致重复节点
    id_map = {name: f"n{idx}" for idx, name in enumerate(nodes)}
    for name in nodes:
        label = "\n".join(textwrap.wrap(name, width=width))
        if name in highlight_nodes:
            dot.node(id_map[name], label=label, style="rounded,filled", fillcolor=highlight_color)
        else:
            dot.node(id_map[name], label=label)

    for line in lines:
        src, dst = [part.strip() for part in line.split("causes", 1)]
        dot.edge(id_map[src], id_map[dst])

    # ===== 保存逻辑（可选）=====
    if save_path:
        base, ext = os.path.splitext(save_path)
        out_fmt = (ext.lstrip(".") or fmt).lower()
        dot.format = out_fmt
        # Graphviz 的 render 需要“无扩展名”的基名
        out = dot.render(base, cleanup=True)
        if os.path.exists(out) and out.endswith(f".{out_fmt}.{out_fmt}"):
            fixed = out[: -(len(out_fmt) + 1)]
            os.replace(out, fixed)
            out = fixed
        return out

    return dot
