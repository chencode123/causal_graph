
from graphviz import Digraph
import textwrap, re, json, os
from collections import OrderedDict
from typing import Iterable, Union, List
from datetime import datetime

__all__ = ["draw_causal_graph"]

# ===================================================================
# Color table for hazard-specific condition colors
# ===================================================================
HAZARD_COLORS = {
    "confined explosion": "#FF7EB6",
    "vce": "#FF8A3D",
    "bleve": "#FF6F61",
    "dust explosion": "#FFD966",
    "pool fire": "#D78BFF",
    "jet fire": "#63A0FF",
    "fire ball": "#9D8CFF",
    "flash fire": "#C8C6A7",
    "toxicity dispersion": "#00C2CB",
    "asphyxiation": "#4CC9A1",
}

# ===================================================================
# Helper functions
# ===================================================================

import unicodedata

def _sanitize_name(name: str) -> str:
    """
    Replace ALL Unicode dash-like characters (category Pd)
    with underscore '_', but do NOT touch '->'.
    """
    result = []
    for ch in name:
        # keep arrow operator unchanged
        if ch == "-" and "->" in name:
            result.append(ch)
            continue

        # replace any dash-like character (Pd = punctuation, dash)
        if unicodedata.category(ch) == "Pd":
            result.append("_")
        else:
            result.append(ch)
    return "".join(result)

def _is_hazard_consequence_name(name: str) -> bool:
    """
    Return True if name looks like a hazard consequence
    (e.g. 'Flash fire 1', 'Jet fire-2', 'Pool fire').
    """
    norm = _normalize_hazard_consequence_name(name.lower())
    return norm in HAZARD_COLORS


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
    if isinstance(data, str):
        data = _normalize_text_block(data)
        lines = _split_into_lines(data)
    else:
        lines = list(data)

    def _norm_line(s: str) -> str:
        # 1) 统一常见不可见空白
        s = (s.replace("\u00A0", " ")   # NBSP
               .replace("\u2009", " ")
               .replace("\u202F", " ")
               .replace("\u200B", "")   # zero-width space
               .replace("\ufeff", ""))  # BOM

        # 2) 统一各种箭头符号为 ASCII ->
        #    注意：先处理 Unicode 箭头，再处理全角/Unicode dash
        s = s.replace("→", "->").replace("➜", "->").replace("⇒", "->").replace("⟶", "->")

        # 3) 统一各种“dash-like”字符为 ASCII '-'
        #    （很多 PDF 会把 '-' 变成 '‐','-','–','—' 等）
        s = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212\uFE63\uFF0D]", "-", s)

        return s.strip()

    # 4) 严格：整行必须是 “src -> dst”
    pat = re.compile(r"^\s*(.*?)\s*->\s*(.*?)\s*$")

    out: List[str] = []
    for raw in lines:
        line = _norm_line(raw)
        if not line:
            continue

        m = pat.match(line)
        if not m:
            continue

        src = re.sub(r"\s+", " ", m.group(1).rstrip(".").strip())
        dst = re.sub(r"\s+", " ", m.group(2).rstrip(".").strip())
        if not src or not dst:
            continue

        out.append(f"{src} -> {dst}")

    return list(OrderedDict.fromkeys(out))

def _collect_nodes_from_arrow_lines(lines: List[str]) -> List[str]:
    nodes = []
    for line in lines:
        if "->" in line:
            src, dst = line.split("->", 1)
            src_s = _sanitize_name(src.strip())
            dst_s = _sanitize_name(dst.strip())
            nodes.extend([src_s, dst_s])

    seen_lower, ordered = set(), []
    for n in nodes:
        key = n.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            ordered.append(n)
    return ordered

def _load_highlight_nodes(source: Union[str, Iterable[str], None]) -> set[str]:
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

def _extract_hazard_tag(name: str) -> str | None:
    """
    Extract hazard tag from angle brackets, e.g. "X <Pool fire 1>" -> "pool fire".
    Supports optional numeric suffix: "pool fire 1", "pool fire-2", "pool fire_3".
    """
    if "<" not in name or ">" not in name:
        return None

    tag = name.split("<", 1)[1].split(">", 1)[0].strip().lower()

    # Remove trailing numeric suffix: "pool fire 1" / "pool fire-2" / "pool fire_3"
    tag = re.sub(r"[\s\-_]*\d+$", "", tag)

    # Normalize whitespace
    tag = re.sub(r"\s+", " ", tag).strip()

    return tag or None

def _normalize_hazard_consequence_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)

    s = s.replace("\u00A0", " ").replace("\u2009", " ").replace("\u202F", " ")

    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s).strip()

    s = re.sub(r"\s*[\-_]?\s*\(?\s*\d+\s*\)?\s*$", "", s).strip()

    s = re.sub(r"\s+", " ", s).strip()
    return s


# ===================================================================
# Main function
# ===================================================================

def draw_causal_graph(
    chain_lines: Union[str, Iterable[str]],
    rankdir: str = "LR",
    width: int = 28,
    conditions: Union[None, str, Iterable[str]] = None,
    hazards: Union[None, str, Iterable[str]] = None,
    condition_color: str = "#f9f9f9",
    hazard_color: str = "#ffcccc",
    neutral_color: str = "#f9f9f9",
    *,
    save_path: str | None = None,
    fmt: str = "png",
    dpi: int = 200,
):

    lines = _to_arrow_lines(chain_lines)

    # Apply sanitize to all node names
    san_lines = []
    for ln in lines:
        if "->" not in ln:
            continue
        src, dst = ln.split("->", 1)
        src_s = _sanitize_name(src.strip())
        dst_s = _sanitize_name(dst.strip())
        san_lines.append(f"{src_s} -> {dst_s}")

    lines = san_lines
    nodes = [ _sanitize_name(n) for n in _collect_nodes_from_arrow_lines(lines) ]

    condition_nodes = _load_highlight_nodes(conditions)
    hazard_nodes = _load_highlight_nodes(hazards)

    auto_condition_nodes = {n.lower() for n in nodes if "<" in n and ">" in n}
    condition_nodes |= auto_condition_nodes
    hazard_nodes -= auto_condition_nodes

    # === Build Graph ===
    dot = Digraph(format=fmt)
    dot.attr(
        rankdir=rankdir,
        dpi=str(dpi),
        bgcolor="white",
        splines="true",
        ranksep="1.2",
        nodesep="0.5",
        pad="0.3",
        concentrate="false"
    )

    dot.attr(
        "node",
        shape="box",
        style="rounded,filled",
        color="#aaaaaa",
        fontname="Helvetica",
        fontsize="10",
        penwidth="0.8"
    )
    dot.attr("edge", color="#55555580", penwidth="1", arrowsize="0.7")

    # === Unique IDs ===
    id_map = {}
    for name in nodes:
        key = name.lower()
        if key not in id_map:
            id_map[key] = f"n{len(id_map)}"

    # === Add nodes ===
    for name in nodes:
        safe_name = _sanitize_name(name)
        label = "\n".join(textwrap.wrap(safe_name, width=width))
        node_id = id_map[safe_name.lower()]
        lower = safe_name.lower()

        hazard_tag = _extract_hazard_tag(safe_name)

        if hazard_tag:
            # Condition <Hazard> → hazard-specific condition color
            fill = HAZARD_COLORS.get(hazard_tag, condition_color)

        elif _is_hazard_consequence_name(safe_name):
            # Flash fire 1 / Jet fire 2 → hazard consequence (red)
            fill = hazard_color

        elif lower in hazard_nodes:
            fill = hazard_color

        elif lower in condition_nodes:
            fill = condition_color
        else:
            fill = neutral_color

        dot.node(node_id, label=label, fillcolor=fill)


    # === Add edges ===
    for line in lines:
        if "->" not in line:
            continue
        src, dst = [part.strip() for part in line.split("->", 1)]
        src = _sanitize_name(src)
        dst = _sanitize_name(dst)
        dot.edge(id_map[src.lower()], id_map[dst.lower()])

    # === Legend ===
    with dot.subgraph(name="cluster_legend") as legend:
        legend.attr(
            label="Legend",
            fontsize="10",
            fontname="Helvetica",
            style="dashed",
            color="#aaaaaa",
            rank="same",
            margin="12"
        )

        # row 1: generic types (remove generic Condition)
        legend.node("event_l", "Event", style="rounded,filled", fillcolor=neutral_color)
        legend.node("haz_l", "Hazard consequence", style="rounded,filled", fillcolor=hazard_color)

        # row 2: hazard-specific colors
        hazard_nodes = []
        for hname, hcolor in HAZARD_COLORS.items():
            nid = f"cond_{hname}"
            hazard_nodes.append(nid)
            legend.node(nid, f"Condition <{hname}>",
                        style="rounded,filled", fillcolor=hcolor)

        # force horizontal layout
        all_nodes = ["event_l", "haz_l"] + hazard_nodes
        for a, b in zip(all_nodes[:-1], all_nodes[1:]):
            legend.edge(a, b, style="invis")

    legend.attr(rankdir="LR")

    if save_path:
        base, ext = os.path.splitext(save_path)
        out_fmt = (ext.lstrip(".") or fmt).lower()
        dot.format = out_fmt
        out = dot.render(base, cleanup=True)
        if os.path.exists(out) and out.endswith(f".{out_fmt}.{out_fmt}"):
            fixed = out[: -(len(out_fmt) + 1)]
            os.replace(out, fixed)
            out = fixed
        return out

    return dot
