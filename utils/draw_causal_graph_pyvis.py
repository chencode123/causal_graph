from pyvis.network import Network
import re, json, os, textwrap
from collections import OrderedDict
from typing import Iterable, Union, List
from pathlib import Path

__all__ = ["draw_causal_graph_pyvis"]

def _normalize_text_block(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    return s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")

def _split_into_lines(s: str) -> List[str]:
    if "\n" in s:
        return s.splitlines()
    return re.split(r"(?<=[\.!?])\s+", s)

def _to_arrow_lines(data: Union[str, Iterable[str]]) -> List[str]:
    """Extract 'A -> B' lines"""
    if isinstance(data, str):
        data = _normalize_text_block(data)
        lines = _split_into_lines(data)
    else:
        lines = list(data)

    pat = re.compile(r"(.+?)\s*->\s*(.+)")
    out: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = pat.match(line)
        if not m:
            continue
        src = re.sub(r"\s+", " ", m.group(1).rstrip(".").strip())
        dst = re.sub(r"\s+", " ", m.group(2).rstrip(".").strip())
        out.append(f"{src} -> {dst}")
    return list(OrderedDict.fromkeys(out))  # 去重并保留顺序

def _collect_nodes_from_arrow_lines(lines: List[str]) -> List[str]:
    nodes = []
    for line in lines:
        if "->" in line:
            src, dst = line.split("->", 1)
            nodes.extend([src.strip(), dst.strip()])
    seen_lower, ordered = set(), []
    for n in nodes:
        key = n.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            ordered.append(n)
    return ordered

def _load_highlight_nodes(source: Union[str, Iterable[str], None]) -> set[str]:
    """Load highlight nodes from JSON or list"""
    if isinstance(source, str):
        if os.path.exists(source):
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {x.strip().lower() for x in data}
        else:
            return {source.strip().lower()}
    elif isinstance(source, Iterable):
        return {x.strip().lower() for x in source}
    else:
        return set()

def draw_causal_graph_pyvis(
    chain_lines: Union[str, Iterable[str]],
    conditions: Union[None, str, Iterable[str]] = None,
    hazards: Union[None, str, Iterable[str]] = None,
    condition_color: str = "#64b5f6",  # light blue
    hazard_color: str = "#ef9a9a",     # light red
    neutral_color: str = "#eeeeee",
    save_path: str | Path | None = None,
    height: str = "850px",
    width: str = "100%",
):
    """
    Build an interactive causal graph using Pyvis.
    Supports user-specified conditions and hazards files for highlighting.
    """
    # === Parse relations ===
    lines = _to_arrow_lines(chain_lines)
    nodes = _collect_nodes_from_arrow_lines(lines)
    condition_nodes = _load_highlight_nodes(conditions)
    hazard_nodes = _load_highlight_nodes(hazards)

    print(f"✅ Detected {len(nodes)} nodes, {len(lines)} edges.")

    # === Initialize network ===
    net = Network(height=height, width=width, directed=True, bgcolor="white", font_color="black")
    net.show_buttons(filter_=["physics", "layout", "interaction"])

    # === Add nodes ===
    for name in nodes:
        lower = name.lower()
        if lower in condition_nodes:
            color = condition_color
            group = "condition"
        elif lower in hazard_nodes:
            color = hazard_color
            group = "hazard"
        else:
            color = neutral_color
            group = "event"

        wrapped_label = "\n".join(textwrap.wrap(name, width=24))
        net.add_node(
            name,
            label=wrapped_label,
            color=color,
            title=f"Type: {group}",
            shape="box",
            borderWidth=1,
            shadow=True
        )

    # === Add edges ===
    for line in lines:
        if "->" not in line:
            continue
        src, dst = [x.strip() for x in line.split("->", 1)]
        net.add_edge(src, dst, arrows="to", color="#999999", width=1.2)

    # === Legend ===
    net.add_node("Legend: Hazard", color=hazard_color, shape="box", level=6)
    net.add_node("Legend: Condition", color=condition_color, shape="box", level=6)
    net.add_node("Legend: Event", color=neutral_color, shape="box", level=6)
    net.add_edge("Legend: Hazard", "Legend: Condition", color="#ffffff")


    save_path = Path(save_path or "causal_graph.html")
    net.write_html(str(save_path), open_browser=False)
    print(f"✅ Pyvis causal graph saved to {save_path}")
    return save_path
