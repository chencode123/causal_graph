"""
causal_graph_interactive

Generate:
1) Static causal graphs via Graphviz (PNG/SVG/PDF)
2) Interactive HTML causal graphs via Cytoscape.js + Dagre (CDN)

Primary entrypoint:
    draw_causal_graph_interactive(...)

Behavior:
- If save_path endswith ".html" (or fmt="html"), an interactive HTML file is generated.
- Otherwise, Graphviz renders a static image (requires graphviz + python-graphviz).

Color rules (aligned with your Python implementation):
- Nodes with hazard tags in angle brackets, e.g. "X <Pool fire>", are treated as CONDITION nodes
  and colored by hazard-specific colors (HAZARD_COLORS[tag]) if available; otherwise condition_color.
- Other nodes can be highlighted as:
  - hazards (hazard_color) if listed in hazards JSON/text
  - conditions (condition_color) if listed in conditions JSON/text
  - neutral otherwise
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Union, List, Optional, Dict, Set, Tuple
import json
import os
import re
import textwrap
import unicodedata

# ============================================================
# Color table for hazard-specific condition colors
# ============================================================
HAZARD_COLORS: Dict[str, str] = {
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

__all__ = ["HAZARD_COLORS", "draw_causal_graph_interactive"]


# ============================================================
# Helpers (aligned with your existing code)
# ============================================================

def _sanitize_name(name: str) -> str:
    """
    Replace ALL Unicode dash-like characters (category Pd) with underscore '_'.
    Keep ordinary '-' untouched. This targets punctuation dashes like en/em dashes.
    """
    out = []
    for ch in name:
        if unicodedata.category(ch) == "Pd":
            out.append("_")
        else:
            out.append(ch)
    return "".join(out)

def _normalize_hazard_consequence_name(s: str) -> str:
    """
    Normalize hazard consequence node label for matching HAZARD_COLORS keys.
    Examples:
      "Toxicity dispersion 1" -> "toxicity dispersion"
      "Pool fire number" -> "pool fire"
      "Pool fire (3)" -> "pool fire"
      "Jet fire-2" -> "jet fire"
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00A0", " ").replace("\u2009", " ").replace("\u202F", " ")
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s).strip()

    # drop trailing "... number" / "... number 12"
    s = re.sub(r"(?:\s+number(?:\s*\d+)?)$", "", s).strip()

    # drop trailing "(12)"
    s = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", s).strip()

    # drop trailing digits with optional separators: " 12" / "-12" / "_12"
    s = re.sub(r"[\s\-_]*\d+$", "", s).strip()

    s = re.sub(r"\s+", " ", s).strip()
    return s

def _is_hazard_consequence_node(name: str) -> bool:
    norm = _normalize_hazard_consequence_name(name)
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

    # de-duplicate, preserve order (case-insensitive)
    seen = set()
    dedup = []
    for x in out:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            dedup.append(x)
    return dedup

def _collect_nodes_from_arrow_lines(lines: List[str]) -> List[str]:
    nodes: List[str] = []
    for line in lines:
        if "->" not in line:
            continue
        src, dst = line.split("->", 1)
        nodes.append(_sanitize_name(src.strip()))
        nodes.append(_sanitize_name(dst.strip()))

    seen_lower: Set[str] = set()
    ordered: List[str] = []
    for n in nodes:
        key = n.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            ordered.append(n)
    return ordered

def _load_highlight_nodes(source: Union[str, Iterable[str], None]) -> Set[str]:
    """
    Accept:
      - path to JSON list (["node a", "node b", ...])
      - a single string (one node)
      - iterable of strings
      - None
    Returns a set of lowercase node labels.
    """
    if source is None:
        return set()

    if isinstance(source, (str, os.PathLike)):
        p = Path(source)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # allow {"nodes": [...]}
                data = data.get("nodes", [])
            return {str(x).strip().lower() for x in data}
        else:
            return {str(source).strip().lower()}

    # iterable
    return {str(x).strip().lower() for x in source}
def _normalize_hazard_tag(tag: str) -> str:
    """
    Normalize hazard tag inside <> to match HAZARD_COLORS keys.
    Handles:
      <Pool fire 1>      -> pool fire
      <Pool fire-2>      -> pool fire
      <Pool fire_3>      -> pool fire
      <Pool fire number> -> pool fire
      <Pool fire number 4> -> pool fire
    """
    tag = (tag or "").strip().lower()

    # collapse whitespace first
    tag = re.sub(r"\s+", " ", tag).strip()

    # remove trailing patterns:
    #   " number", " number 12", " 12", "-12", "_12"
    tag = re.sub(r"(?:\s+number(?:\s*\d+)?)$", "", tag)   # ... number / number 12
    tag = re.sub(r"[\s\-_]*\d+$", "", tag)                # ... 12 / -12 / _12

    # collapse whitespace again after removals
    tag = re.sub(r"\s+", " ", tag).strip()

    return tag


def _extract_hazard_tag(name: str) -> str | None:
    if "<" not in name or ">" not in name:
        return None
    raw = name.split("<", 1)[1].split(">", 1)[0]
    tag = _normalize_hazard_tag(raw)
    return tag or None

def _wrap_label(label: str, width: int) -> str:
    return "\n".join(textwrap.wrap(label, width=width))

# ============================================================
# HTML generation
# ============================================================

_HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Interactive Causal Graph (Cytoscape.js)</title>

  <!-- Cytoscape -->
  <script src="https://unpkg.com/cytoscape/dist/cytoscape.min.js"></script>

  <!-- Dagre (for hierarchical layout) -->
  <script src="https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"></script>
  <script src="https://unpkg.com/cytoscape-dagre/cytoscape-dagre.js"></script>

  <style>
    :root{
      /* Page background */
      --bg: #ffffff;

      /* Panels / cards */
      --panel: #ffffff;

      /* Text colors */
      --text: #111111;
      --muted: #555555;

      /* Borders & dividers */
      --border: #dddddd;

      /* Shadows (lighter than dark theme) */
      --shadow: 0 8px 24px rgba(0,0,0,0.12);

      /* UI shape */
      --radius: 14px;

      /* Fonts */
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
              "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto,
              Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
    }

    html, body { height: 100%; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
    }

    .app{
      display: grid;
      grid-template-columns: 420px 1fr;
      gap: 14px;
      height: 100%;
      padding: 14px;
      box-sizing: border-box;
    }

    .panel{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }

    .panel-header{
      padding: 14px 14px 10px 14px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.04));
    }

    .title{
      font-size: 14px;
      letter-spacing: 0.2px;
      font-weight: 650;
      margin: 0 0 6px 0;
    }
    .subtitle{
      font-size: 12px;
      color: var(--muted);
      margin: 0;
      line-height: 1.35;
    }

    .panel-body{
      padding: 12px 14px;
      display: grid;
      gap: 12px;
      overflow: auto;
      min-height: 0;
    }

    .row{ display: grid; gap: 8px; }
    .row label{ font-size: 12px; color: var(--muted); }

    textarea{
      width: 100%;
      box-sizing: border-box;
      background: #fdfdfd;
      border: 1px solid rgba(17,17,17,0.1);
      border-radius: 10px;
      color: var(--text);
      padding: 10px 10px;
      outline: none;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.35;
      min-height: 210px;
      resize: vertical;
    }
    textarea:focus{
      border-color: rgba(122,162,255,0.5);
      box-shadow: 0 0 0 3px rgba(122,162,255,0.18);
    }

    .toolbar{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .btn{
      cursor: pointer;
      border: 1px solid rgba(17,17,17,0.08);
      background: #f4f6fb;
      color: var(--text);
      padding: 10px 10px;
      border-radius: 12px;
      font-size: 13px;
      font-weight: 620;
      letter-spacing: 0.2px;
      transition: transform .06s ease, background .15s ease, border-color .15s ease;
      user-select: none;
    }
    .btn:hover{ background: #e8eefc; border-color: rgba(17,17,17,0.16); }
    .btn:active{ transform: translateY(1px); }
    .btn.primary{ background: rgba(122,162,255,0.18); border-color: rgba(122,162,255,0.45); }
    .btn.primary:hover{ background: rgba(122,162,255,0.28); border-color: rgba(122,162,255,0.58); }
    .btn.danger{ background: rgba(255,107,107,0.12); border-color: rgba(255,107,107,0.38); }
    .btn.danger:hover{ background: rgba(255,107,107,0.20); border-color: rgba(255,107,107,0.5); }
    .btn.ok{ background: rgba(72,199,142,0.12); border-color: rgba(72,199,142,0.38); }
    .btn.ok:hover{ background: rgba(72,199,142,0.20); border-color: rgba(72,199,142,0.5); }

    .minirow{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: center; }

    .hint{
      font-size: 12px;
      color: var(--muted);
      line-height: 1.4;
    }

    .status{
      font-family: var(--mono);
      font-size: 12px;
      color: var(--text);
      background: #f7f8fb;
      border: 1px solid rgba(17,17,17,0.08);
      border-radius: 12px;
      padding: 10px 10px;
      line-height: 1.35;
      white-space: pre-wrap;
    }

    .right{ position: relative; min-height: 0; }
    #cy{
      width: 100%;
      height: 100%;
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }

    .legend{
      position: absolute;
      right: 16px;
      bottom: 16px;
      width: 280px;
      max-height: 45%;
      overflow: auto;
      background: rgba(255,255,255,0.92);
      border: 1px solid rgba(17,17,17,0.08);
      border-radius: 14px;
      box-shadow: 0 10px 30px rgba(0,0,0,.12);
      padding: 10px 10px;
    }

    .rb-box{
      position: absolute;
      border: 2px dashed rgba(122,162,255,0.9);
      background: rgba(122,162,255,0.12);
      border-radius: 10px;
      pointer-events: none;
      z-index: 9999;
    }

    .legend h3{
      margin: 0 0 8px 0;
      font-size: 12px;
      color: var(--text);
      letter-spacing: .2px;
    }
    .leg-item{
      display:flex;
      align-items:center;
      gap:10px;
      padding: 6px 4px;
      border-radius: 10px;
    }
    .swatch{
      width: 14px;
      height: 14px;
      border-radius: 4px;
      border: 1px solid rgba(17,17,17,0.15);
      flex: 0 0 auto;
    }
    .leg-text{
      font-size: 12px;
      color: var(--text);
    }

    @media (max-width: 1100px){
      .app{
        grid-template-columns: 1fr;
        grid-template-rows: 380px 1fr;
      }
      .legend{ width: 320px; }
    }
    /* ============================================================
      Layout stabilization (fix drifting legend)
      ============================================================ */

    /* Always reserve scrollbar width to avoid layout width jitter */
    html { 
      overflow-y: scroll; 
    }

    /* Prevent internal scrollbars from affecting absolute positioning */
    .right { 
      overflow: hidden; 
    }

    /* Stabilize legend box model and rendering */
    .legend{
      box-sizing: border-box;
      left: auto;
      transform: translateZ(0);   /* promote to its own compositing layer */
      contain: layout paint;      /* isolate layout/paint to avoid reflow coupling */
    }

  </style>
</head>

<body>
  <div class="app">
    <div class="panel">
      <div class="panel-header">
        <p class="title">Interactive causal graph editor</p>
        <p class="subtitle">
          Render from arrow-lines (e.g., <span style="font-family:var(--mono)">A -&gt; B</span>), then interactively add/delete/rename nodes and edges.
          Coloring follows your rules (hazard tags and optional highlight lists).
        </p>
      </div>

      <div class="panel-body">
        <textarea id="txtLines" spellcheck="false" style="display:none;"></textarea>

        <div class="minirow">
          <button class="btn primary" id="btnRender" type="button">Render graph</button>
          <button class="btn" id="btnRelayout" type="button">Re-layout</button>
        </div>

        <div class="toolbar">
          <button class="btn ok" id="btnAddNode" type="button">Add node</button>
          <button class="btn ok" id="btnAddEdgeMode" type="button">Add edge (click 2 nodes)</button>
          <button class="btn" id="btnRename" type="button">Rename selected node</button>
          <button class="btn" id="btnToggleDeleted" type="button">Hide or show deleted</button>
          <button class="btn danger" id="btnDelete" type="button">Delete selected</button>
          <button class="btn" id="btnImportTrack" type="button">Import track (JSON/TXT)</button>
          <button class="btn primary" id="btnSaveBoth" type="button">Save updates (TXT)</button>
        </div>
        <input id="trackFileInput" type="file" accept=".json,.txt,application/json,text/plain" style="display:none" />

        <div class="row">
          <label>Status</label>
          <div id="status" class="status">Ready.</div>
          <div class="hint">
            Tips:
            <br>• Drag nodes to adjust locally. Click empty space to clear selection.
            <br>• “Add edge” mode: click source node then target node.
            <br>• Press Ctrl+Z to undo the last graph edit.
            <br>• Hazard-tag coloring: any node label containing <span style="font-family:var(--mono)">&lt;Pool fire&gt;</span> etc. will auto-color.
            <br>• Drag with left mouse button on empty canvas to box-select.
            <br>• Hold middle mouse button and drag to pan the canvas.
            <br>• Right click on the canvas to create a new node.

          </div>
        </div>
      </div>
    </div>

    <div class="right">
      <div id="cy"></div>

      <div class="legend" id="legendBox">
        <h3>Legend</h3>
        <div class="leg-item"><div class="swatch" style="background:{{NEUTRAL_COLOR}}"></div><div class="leg-text">Event (neutral)</div></div>
        <div class="leg-item"><div class="swatch" style="background:{{CONDITION_COLOR}}"></div><div class="leg-text">Condition (generic)</div></div>
        <div class="leg-item"><div class="swatch" style="background:{{HAZARD_COLOR}}"></div><div class="leg-text">Hazard consequence (generic)</div></div>
        <div class="leg-item">
          <div class="swatch" style="background:transparent;border:2px solid #ff4d4f;border-radius:6px;"></div>
          <div class="leg-text">Added nodes/edges (red solid)</div>
        </div>
        <div class="leg-item">
          <div class="swatch" style="background:transparent;border:2px dashed #2ecc71;border-radius:6px;"></div>
          <div class="leg-text">Delete marks (green dashed)</div>
        </div>
        <div style="height:8px"></div>
        <div id="legendHazards"></div>
      </div>
    </div>
  </div>

  <script id="cySnapshot" type="application/json"></script>
  <script id="initialLinesData" type="application/json">{{INITIAL_TEXT_JSON}}</script>
  <script id="embeddedTrackDiff" type="application/json">{{TRACK_DIFF_JSON}}</script>
  <script>
    /******************************************************************
     * Embedded data from Python
     ******************************************************************/
    function parseJsonFromScript(el){
      if (!el) return null;
      const raw = (el.textContent || "").trim();
      if (!raw) return null;
      try{
        return JSON.parse(raw);
      }catch(err){
        console.warn("Failed to parse embedded JSON", err);
        return null;
      }
    }

    const cySnapshotEl = document.getElementById("cySnapshot");
    const initialLinesEl = document.getElementById("initialLinesData");
    const trackDiffEl = document.getElementById("embeddedTrackDiff");

    const initialTextFromDom = parseJsonFromScript(initialLinesEl);
    let embeddedTrackDiff = parseJsonFromScript(trackDiffEl);

    const INITIAL_TEXT = (typeof initialTextFromDom === "string") ? initialTextFromDom : {{INITIAL_TEXT_JSON}};
    const USER_CONDITIONS = new Set({{CONDITIONS_JSON}});
    const USER_HAZARDS = new Set({{HAZARDS_JSON}});
    const CASE_ID = {{CASE_ID_JSON}};

    /******************************************************************
     * Color table — hazard-specific condition colors
     ******************************************************************/
    const HAZARD_COLORS = {{HAZARD_COLORS_JSON}};

    const COLORS = {
      condition_color: "{{CONDITION_COLOR}}",
      hazard_color: "{{HAZARD_COLOR}}",
      neutral_color: "{{NEUTRAL_COLOR}}",
      border: "#aaaaaa",
      edge: "rgba(85,85,85,0.5)"
    };

    const TRACK_FILE_NAME = `track_${CASE_ID}_final_check_output.txt`;
    const VERIFIED_FILE_NAME = `verified_${CASE_ID}_final_check_output.txt`;
    const HTML_FILE_NAME = `update_${CASE_ID}_causal_graph.html`;

    // Track the baseline text to compare future additions (populated during boot)
    const INITIAL_LINE_SET = new Set();
    const BASELINE_LINE_MAP = new Map();

    function setBaselineFromLines(lines){
      BASELINE_LINE_MAP.clear();
      INITIAL_LINE_SET.clear();
      for (const raw of lines){
        const line = (raw || "").trim();
        if (!line) continue;
        const lower = line.toLowerCase();
        INITIAL_LINE_SET.add(lower);
        if (!BASELINE_LINE_MAP.has(lower)){
          BASELINE_LINE_MAP.set(lower, line);
        }
      }
    }

    function getBaselineLines(){
      return Array.from(BASELINE_LINE_MAP.values());
    }

    /******************************************************************
     * Helpers: sanitize + parse
     ******************************************************************/
    function isDashLike(ch){
      return ["\u2010","\u2011","\u2012","\u2013","\u2014","\u2015","\u2212","\uFE58","\uFE63","\uFF0D"].includes(ch);
    }

    function sanitizeName(name){
      let out = "";
      for (const ch of name){
        if (isDashLike(ch)) out += "_";
        else out += ch;
      }
      return out;
    }

    function normalizeTextBlock(s){
      if (!s) return "";
      s = s.trim();
      if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))){
        s = s.slice(1, -1);
      }
      return s.replaceAll("\\r\\n","\n").replaceAll("\\n","\n").replaceAll("\r\n","\n");
    }

    function toArrowLines(rawText){
      const text = normalizeTextBlock(rawText);
      const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
      const pat = /^(.+?)\s*->\s*(.+)$/;
      const out = [];
      const seen = new Set();
      for (const raw of lines){
        const m = raw.match(pat);
        if (!m) continue;
        const src = m[1].replace(/\s+/g, " ").replace(/\.$/, "").trim();
        const dst = m[2].replace(/\s+/g, " ").replace(/\.$/, "").trim();
        const line = `${src} -> ${dst}`;
        const key = line.toLowerCase();
        if (!seen.has(key)){
          seen.add(key);
          out.push(line);
        }
      }
      return out;
    }

    function normalizeArrowLineInput(raw){
      if (Array.isArray(raw)){
        return toArrowLines(raw.join("\n"));
      }
      if (typeof raw === "string"){
        return toArrowLines(raw);
      }
      return [];
    }

    function normalizeHazardTag(tag){
      tag = (tag || "").trim().toLowerCase();

      // collapse whitespace
      tag = tag.replace(/\s+/g, " ").trim();

      // remove trailing " number" or " number 12"
      tag = tag.replace(/(?:\s+number(?:\s*\d+)?)$/, "");

      // remove trailing digits: " 12" / "-12" / "_12"
      tag = tag.replace(/[\s\-_]*\d+$/, "");

      // collapse again
      tag = tag.replace(/\s+/g, " ").trim();

      return tag;
    }

    function normalizeHazardConsequenceName(s){
      s = (s || "").trim().toLowerCase();
      s = s.replace(/\s+/g, " ").trim();

      // drop trailing "... number" / "... number 12"
      s = s.replace(/(?:\s+number(?:\s*\d+)?)$/, "").trim();

      // drop trailing "(12)"
      s = s.replace(/\s*\(\s*\d+\s*\)\s*$/, "").trim();

      // drop trailing digits: " 12" / "-12" / "_12"
      s = s.replace(/[\s\-_]*\d+$/, "").trim();

      s = s.replace(/\s+/g, " ").trim();
      return s;
    }

function isHazardConsequenceNode(label){
  const norm = normalizeHazardConsequenceName(label);
  return Object.prototype.hasOwnProperty.call(HAZARD_COLORS, norm);
}

    function extractHazardTag(label){
      const lt = label.indexOf("<");
      const gt = label.indexOf(">");
      if (lt !== -1 && gt !== -1 && gt > lt){
        const raw = label.slice(lt + 1, gt);
        const tag = normalizeHazardTag(raw);
        return tag || null;
      }
      return null;
    }

    function wrapLabel(label, width = 28){
      const words = label.split(" ");
      const lines = [];
      let line = "";
      for (const w of words){
        const next = line ? (line + " " + w) : w;
        if (next.length > width){
          if (line) lines.push(line);
          line = w;
        } else {
          line = next;
        }
      }
      if (line) lines.push(line);
      return lines.join("\n");
    }

    function composeLineText(sourceLabel, targetLabel){
      return `${sourceLabel} -> ${targetLabel}`;
    }

    /******************************************************************
     * Build elements from arrow lines
     ******************************************************************/
    function buildElementsFromLines(lines){
      // First, gather all node labels (sanitized) and build auto-tag condition nodes
      const labels = [];
      for (const ln of lines){
        if (!ln.includes("->")) continue;
        const parts = ln.split("->");
        const src = sanitizeName(parts[0].trim());
        const dst = sanitizeName(parts.slice(1).join("->").trim());
        labels.push(src, dst);
      }

      // De-duplicate labels case-insensitively (like Python)
      const uniq = [];
      const seen = new Set();
      for (const l of labels){
        const k = l.toLowerCase();
        if (!seen.has(k)){
          seen.add(k);
          uniq.push(l);
        }
      }

      // auto condition nodes = those containing <...>
      const autoCond = new Set();
      for (const l of uniq){
        if (extractHazardTag(l)) autoCond.add(l.toLowerCase());
      }

      // Effective conditions/hazards sets (match Python logic)
      const conditionSet = new Set([...USER_CONDITIONS, ...autoCond]);
      const hazardSet = new Set([...USER_HAZARDS].filter(x => !autoCond.has(x)));

      // ID map (label lower -> node id)
      const idMap = new Map();
      const labelById = new Map();
      function getId(label){
        const key = label.toLowerCase();
        if (!idMap.has(key)){
          const nid = "n" + idMap.size;
          idMap.set(key, nid);
          labelById.set(nid, label);
        }
        return idMap.get(key);
      }

      // nodes
      const nodes = [];
      for (const l of uniq){
        const label = l;
        const lower = label.toLowerCase();
        const hazardTag = extractHazardTag(label);

        let fill = COLORS.neutral_color;
        if (hazardTag){
          fill = (HAZARD_COLORS[hazardTag] || COLORS.condition_color);
        } else if (isHazardConsequenceNode(label)){
          fill = COLORS.hazard_color;
        } else if (hazardSet.has(lower)){
          fill = COLORS.hazard_color;
        } else if (conditionSet.has(lower)){
          fill = COLORS.condition_color;
        }

        const id = getId(label);
        nodes.push({
          data: {
            id,
            label,
            labelWrapped: wrapLabel(label, 28),
            hazardTag: hazardTag || "",
            fill
          }
        });
      }

      // edges (dedupe)
      const edges = [];
      const eSeen = new Set();
      for (const ln of lines){
        if (!ln.includes("->")) continue;
        const parts = ln.split("->");
        const srcLabel = sanitizeName(parts[0].trim());
        const dstLabel = sanitizeName(parts.slice(1).join("->").trim());
        const sId = getId(srcLabel);
        const tId = getId(dstLabel);
        const ek = (sId + "->" + tId).toLowerCase();
        if (eSeen.has(ek)) continue;
        eSeen.add(ek);
        edges.push({
          data: {
            id: "e" + edges.length,
            source: sId,
            target: tId,
            label: "",
            lineText: composeLineText(srcLabel, dstLabel)
          }
        });
      }

      return { nodes, edges };
    }

    function buildLinesFromTrackDiff(diff){
      if (!diff || typeof diff !== "object"){
        return { finalLines: [], baselineLines: [] };
      }
      const original = normalizeArrowLineInput(diff.original || diff.baseline || []);
      const additions = normalizeArrowLineInput(
        diff.added || diff.addedLines || diff.newLines || []
      );
      const deletions = normalizeArrowLineInput(
        diff.deleted || diff.deletedLines || diff.removed || []
      );
      const deletionKeys = new Set(deletions.map(line => line.toLowerCase()));

      const combined = [];
      const seen = new Set();
      function pushLine(line){
        const key = line.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        combined.push(line);
      }
      original.forEach(pushLine);
      additions.forEach(pushLine);
      const finalLines = combined;
      return { finalLines, baselineLines: original };
    }

    /******************************************************************
     * Cytoscape initialization
     ******************************************************************/
    cytoscape.use(cytoscapeDagre);

    const cy = cytoscape({
      container: document.getElementById("cy"),
      elements: [],
      wheelSensitivity: 3,
      selectionType: "additive",
      boxSelectionEnabled: true,
      userPanningEnabled: false,
      style: [
        {
          selector: "node",
          style: {
            "shape": "round-rectangle",
            "background-color": "data(fill)",
            "border-color": COLORS.border,
            "border-width": 1,
            "label": "data(labelWrapped)",
            "text-wrap": "wrap",
            "text-max-width": 220,
            "text-valign": "center",
            "text-halign": "center",
            "font-size": 11,
            "color": "#111",
            "padding": "10px",
            "width": "label",
            "height": "label",
          }
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 3,
            "border-color": "#7aa2ff",
            "shadow-blur": 12,
            "shadow-color": "rgba(122,162,255,0.55)",
            "shadow-opacity": 0.9,
          }
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "control-point-step-size": 40,
            "line-color": COLORS.edge,
            "target-arrow-shape": "triangle",
            "target-arrow-color": COLORS.edge,
            "arrow-scale": 0.85,
            "width": 2,
            "label": "data(label)",
            "font-size": 10,
            "text-rotation": "autorotate",
            "text-background-color": "rgba(255,255,255,0.65)",
            "text-background-opacity": 1,
            "text-background-padding": 2,
          }
        },
        {
          selector: "edge:selected",
          style: {
            "line-color": "rgba(122,162,255,0.85)",
            "target-arrow-color": "rgba(122,162,255,0.85)",
            "width": 3
          }
        },
        {
          selector: "node.added-highlight",
          style: {
            "border-width": 3,
            "border-color": "#ff4d4f",
            "border-style": "solid"
          }
        },
        {
          selector: "edge.added-highlight",
          style: {
            "line-color": "#ff4d4f",
            "target-arrow-color": "#ff4d4f",
            "line-style": "solid",
            "width": 3
          }
        },
        {
          selector: "node.delete-mark",
          style: {
            "border-width": 3,
            "border-color": "#2ecc71",
            "border-style": "dashed"
          }
        },
        {
          selector: "edge.delete-mark",
          style: {
            "line-color": "#2ecc71",
            "target-arrow-color": "#2ecc71",
            "line-style": "dashed",
            "width": 3
          }
        }
      ],
      layout: { name: "grid" }
    });

    (function enableLeftRubberbandSelect(){
      const container = cy.container();
      const rightPane = document.querySelector(".right");
      if (!container || !rightPane) return;

      let rb = null;
      let dragging = false;
      let start = { x: 0, y: 0 };

      function ptFromEvent(e){
        const rect = container.getBoundingClientRect();
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
      }
      function rectFrom(a, b){
        const x1 = Math.min(a.x, b.x), y1 = Math.min(a.y, b.y);
        const x2 = Math.max(a.x, b.x), y2 = Math.max(a.y, b.y);
        return { x1, y1, x2, y2, w: x2 - x1, h: y2 - y1 };
      }
      function ensureBox(){
        if (rb) return rb;
        rb = document.createElement("div");
        rb.className = "rb-box";
        rightPane.appendChild(rb);
        return rb;
      }
      function removeBox(){
        if (rb && rb.parentNode) rb.parentNode.removeChild(rb);
        rb = null;
      }
      function updateBox(r){
        const box = ensureBox();
        box.style.left = (r.x1 + container.offsetLeft) + "px";
        box.style.top  = (r.y1 + container.offsetTop) + "px";
        box.style.width  = r.w + "px";
        box.style.height = r.h + "px";
      }
      function selectInRect(r){
        if (r.w < 6 && r.h < 6) return;

        cy.$(":selected").unselect(); 

        const selectedNodes = cy.nodes().filter(n => {
          const p = n.renderedPosition();
          return p.x >= r.x1 && p.x <= r.x2 && p.y >= r.y1 && p.y <= r.y2;
        });

        selectedNodes.select();
        selectedNodes.connectedEdges().select(); 
        setStatus(`Box-selected: ${selectedNodes.length} nodes (+ attached edges).`);
      }

      cy.on("mousedown", (evt) => {
        const oe = evt.originalEvent;
        if (!oe) return;
        if (oe.button !== 0) return;    
        if (evt.target !== cy) return;  

        dragging = true;
        start = ptFromEvent(oe);
        updateBox(rectFrom(start, start));
        oe.preventDefault();
      });

      cy.on("mousemove", (evt) => {
        if (!dragging) return;
        const oe = evt.originalEvent;
        if (!oe) return;
        updateBox(rectFrom(start, ptFromEvent(oe)));
        oe.preventDefault();
      });

      cy.on("mouseup", (evt) => {
        if (!dragging) return;
        const oe = evt.originalEvent;
        dragging = false;
        if (!oe){ removeBox(); return; }
        const r = rectFrom(start, ptFromEvent(oe));
        removeBox();
        selectInRect(r);
        oe.preventDefault();
      });

      container.addEventListener("mouseleave", () => {
        if (!dragging) return;
        dragging = false;
        removeBox();
      });
    })();

    /******************************************************************
    * Force wheel zoom on #cy container (robust across browsers)
    ******************************************************************/
    (function enableWheelZoom(){
      const container = cy.container();
      if (!container) return;

      // 确保 Cytoscape 本身不禁用缩放（兜底）
      cy.userZoomingEnabled(true);

      container.addEventListener("wheel", (e) => {
        // 关键：阻止页面滚动，把 wheel 留给图
        e.preventDefault();

        // deltaY > 0 通常是向下滚（缩小），< 0 放大
        const current = cy.zoom();

        // 这个系数手感比较接近常见缩放（可微调 1.001）
        const factor = Math.pow(1.001, -e.deltaY);
        let next = current * factor;

        // 限制缩放范围，避免飞走
        const minZoom = 0.08;
        const maxZoom = 5;
        next = Math.max(minZoom, Math.min(maxZoom, next));

        // 以鼠标所在点为中心缩放
        const rect = container.getBoundingClientRect();
        const rp = { x: e.clientX - rect.left, y: e.clientY - rect.top };

        cy.zoom({ level: next, renderedPosition: rp });
      }, { passive: false });
    })();


    /******************************************************************
    * Middle mouse drag => pan the canvas
    ******************************************************************/
    (function enableMiddleMousePan(){
      const container = cy.container();
      if (!container) return;

      let panning = false;
      let last = { x: 0, y: 0 };

      function onDown(e){

        if (e.button !== 1) return;


        panning = true;
        last = { x: e.clientX, y: e.clientY };

        e.preventDefault();
      }

      function onMove(e){
        if (!panning) return;

        const dx = e.clientX - last.x;
        const dy = e.clientY - last.y;
        last = { x: e.clientX, y: e.clientY };

        cy.panBy({ x: dx, y: dy });

        e.preventDefault();
      }

      function onUp(e){
        if (!panning) return;
        if (e.button !== 1) return;

        panning = false;
        e.preventDefault();
      }

      container.addEventListener("mousedown", onDown, { passive: false });
      window.addEventListener("mousemove", onMove, { passive: false });
      window.addEventListener("mouseup", onUp, { passive: false });

      container.addEventListener("mouseleave", () => { panning = false; });

      container.addEventListener("contextmenu", (e) => e.preventDefault());
    })();


    const BASELINE_NODE_MAP = new Map();

    function setBaselineNodesFromGraph(){
      BASELINE_NODE_MAP.clear();
      cy.nodes().forEach(node => {
        const label = node.data("label");
        if (!label) return;
        const key = label.toLowerCase();
        if (!BASELINE_NODE_MAP.has(key)){
          BASELINE_NODE_MAP.set(key, label);
        }
      });
    }

    const SELECTION_MODES = {
      DEFAULT: "default",
      ADD: "add",
      DELETE: "delete"
    };
    let currentSelectionMode = SELECTION_MODES.DEFAULT;

    function selectionStylesFor(mode){
      switch (mode){
        case SELECTION_MODES.ADD:
          return {
            node: {
              "border-width": 3,
              "border-color": "#ff4d4f",
              "border-style": "solid",
              "shadow-blur": 12,
              "shadow-color": "rgba(255,77,79,0.55)",
              "shadow-opacity": 0.9,
            },
            edge: {
              "line-color": "#ff4d4f",
              "target-arrow-color": "#ff4d4f",
              "line-style": "solid",
              "width": 3
            }
          };
        case SELECTION_MODES.DELETE:
          return {
            node: {
              "border-width": 3,
              "border-color": "#2ecc71",
              "border-style": "dashed",
              "shadow-blur": 12,
              "shadow-color": "rgba(46,204,113,0.55)",
              "shadow-opacity": 0.9,
            },
            edge: {
              "line-color": "#2ecc71",
              "target-arrow-color": "#2ecc71",
              "line-style": "dashed",
              "width": 3
            }
          };
        default:
          return {
            node: {
              "border-width": 3,
              "border-color": "#7aa2ff",
              "border-style": "solid",
              "shadow-blur": 12,
              "shadow-color": "rgba(122,162,255,0.55)",
              "shadow-opacity": 0.9,
            },
            edge: {
              "line-color": "rgba(122,162,255,0.85)",
              "target-arrow-color": "rgba(122,162,255,0.85)",
              "line-style": "solid",
              "width": 3
            }
          };
      }
    }

    function applySelectionModeStyles(){
      const styles = selectionStylesFor(currentSelectionMode);
      cy.style()
        .selector("node:selected").style(styles.node)
        .selector("edge:selected").style(styles.edge)
        .update();
    }

    function setSelectionMode(mode){
      if (currentSelectionMode === mode) return;
      currentSelectionMode = mode;
      applySelectionModeStyles();
    }

    applySelectionModeStyles();

    function runLayout(){
      cy.layout({
        name: "dagre",
        rankDir: "LR",
        nodeSep: 30,
        rankSep: 80,
        edgeSep: 10,
        spacingFactor: 1.05,
        padding: 30
      }).run();
    }

    function renderGraphFromArrowLines(rawInput, options = {}){
      const { updateBaseline = false, baselineLines = null, silent = false, statusMessage = null } = options;
      const lines = normalizeArrowLineInput(rawInput);
      if (!lines.length){
        if (!silent){
          alert("No valid 'A -> B' lines found.");
        }
        return false;
      }
      const { nodes, edges } = buildElementsFromLines(lines);
      if (cy.elements().length){
        pushUndoState();
      }
      cy.elements().remove();
      cy.add(nodes);
      cy.add(edges);
      runLayout();
      setBaselineNodesFromGraph();
      const textarea = document.getElementById("txtLines");
      if (textarea){
        textarea.value = lines.join("\n");
      }
      if (updateBaseline){
        const baseCandidate = baselineLines && baselineLines.length ? normalizeArrowLineInput(baselineLines) : lines;
        setBaselineFromLines(baseCandidate.length ? baseCandidate : lines);
      }
      setStatus(statusMessage || `Rendered: ${nodes.length} nodes, ${edges.length} edges (deduplicated).`);
      return true;
    }

    /******************************************************************
     * UI + interactions: add/delete/rename nodes and add edges
     ******************************************************************/
    const statusEl = document.getElementById("status");
    function setStatus(msg){ statusEl.textContent = msg; }

    const undoStack = [];
    const MAX_UNDO_STATES = 50;
    const HISTORY_DATA_KEY = "__trackHistory";

    function clearHistoryFlag(elements){
      if (!elements || !elements.length) return;
      elements.forEach(ele => ele.removeData(HISTORY_DATA_KEY));
    }

    function tagAsHistory(elements, tag){
      if (!elements || !elements.length) return;
      elements.forEach(ele => ele.data(HISTORY_DATA_KEY, tag));
    }

    function markAsAdded(elements){
      if (!elements || !elements.length) return;
      clearHistoryFlag(elements);
      elements.removeClass("delete-mark");
      elements.addClass("added-highlight");
    }

    function markAsDeleted(elements){
      if (!elements || !elements.length) return;
      clearHistoryFlag(elements);
      elements.removeClass("added-highlight");
      elements.addClass("delete-mark");
    }

    /******************************************************************
    * Deleted (green dashed) visibility + clear marks
    ******************************************************************/
    let deletedVisible = true;

    function setDeletedVisibility(visible){
      deletedVisible = !!visible;

      const nodeDisplay = deletedVisible ? "element" : "none";
      const edgeDisplay = deletedVisible ? "element" : "none";

      cy.style()
        .selector("node.delete-mark").style({ "display": nodeDisplay })
        .selector("edge.delete-mark").style({ "display": edgeDisplay })
        .update();

      const btn = document.getElementById("btnToggleDeleted");
      if (btn){
        btn.textContent = deletedVisible ? "Hide or show deleted" : "Show deleted";
      }

      setStatus(deletedVisible ? "Deleted marks are visible." : "Deleted marks are hidden.");
    }

    const btnToggleDeleted = document.getElementById("btnToggleDeleted");
    if (btnToggleDeleted){
      btnToggleDeleted.addEventListener("click", () => {
        setDeletedVisibility(!deletedVisible); // ✅ toggle
      });
    }

    setDeletedVisibility(true);

    function updateEdgeLineText(edge){
      if (!edge || !edge.isEdge()) return;
      const sourceLabel = edge.source().data("label");
      const targetLabel = edge.target().data("label");
      if (sourceLabel && targetLabel){
        edge.data("lineText", composeLineText(sourceLabel, targetLabel));
      }
    }

    function refreshEdgesForNode(node){
      if (!node || !node.isNode()) return;
      node.connectedEdges().forEach(updateEdgeLineText);
    }

    function cloneElementsSnapshot(){
      const elements = cy.elements().jsons().map(el => JSON.parse(JSON.stringify(el)));
      return {
        elements,
        pan: { ...cy.pan() },
        zoom: cy.zoom()
      };
    }

    function pushUndoState(snapshotOverride = null){
      const snapshot = snapshotOverride || cloneElementsSnapshot();
      undoStack.push(snapshot);
      if (undoStack.length > MAX_UNDO_STATES){
        undoStack.shift();
      }
    }

    function restoreSnapshot(snapshot){
      if (!snapshot) return;
      const currentPan = { ...cy.pan() };
      const currentZoom = cy.zoom();
      cy.$(":selected").unselect();
      cy.elements().remove();
      const elements = snapshot.elements || snapshot;
      if (Array.isArray(elements)){
        cy.add(elements);
      } else if (elements && (elements.nodes || elements.edges)){
        if (elements.nodes) cy.add(elements.nodes);
        if (elements.edges) cy.add(elements.edges);
      }
      if (currentPan) cy.pan(currentPan);
      if (typeof currentZoom === "number") cy.zoom(currentZoom);
      setSelectionMode(SELECTION_MODES.DEFAULT);
      runLayout();
    }

    function undoLastAction(){
      if (!undoStack.length){
        setStatus("Nothing to undo.");
        return;
      }
      const snapshot = undoStack.pop();
      restoreSnapshot(snapshot);
      setStatus("Undo applied.");
    }

    document.addEventListener("keydown", (evt) => {
      if (!evt.key) return;
      if ((evt.ctrlKey || evt.metaKey) && !evt.shiftKey && evt.key.toLowerCase() === "z"){
        const target = evt.target;
        const tag = target && target.tagName ? target.tagName.toUpperCase() : "";
        const isEditable = (target && target.isContentEditable) || tag === "INPUT" || tag === "TEXTAREA";
        if (isEditable) return;
        evt.preventDefault();
        undoLastAction();
      }
    });

    let edgeMode = false;
    let edgeSource = null;
    let addNodeHighlightTimer = null;

    let dragUndoSnapshot = null;
    let dragUndoCommitted = false;

    cy.on("grab", "node", (evt) => {
      const node = evt.target;
      node.scratch("_dragStartPos", { ...node.position() });
      if (!dragUndoSnapshot){
        dragUndoSnapshot = cloneElementsSnapshot();
        dragUndoCommitted = false;
      }
    });

    cy.on("dragfree", "node", (evt) => {
      const node = evt.target;
      const startPos = node.scratch("_dragStartPos");
      if (node.removeScratch){
        node.removeScratch("_dragStartPos");
      } else {
        node.scratch("_dragStartPos", null);
      }
      const pos = node.position();
      const moved = startPos && (startPos.x !== pos.x || startPos.y !== pos.y);
      if (dragUndoSnapshot && !dragUndoCommitted && moved){
        pushUndoState(dragUndoSnapshot);
        dragUndoCommitted = true;
        setStatus("Node position updated (Ctrl+Z to undo).");
      }
      if (!cy.$(":grabbed").length){
        dragUndoSnapshot = null;
        dragUndoCommitted = false;
      }
    });

    document.getElementById("btnAddEdgeMode").addEventListener("click", () => {
      if (edgeSource){
        edgeSource.unselect();
      }
      cy.$(":selected").unselect();
      edgeMode = true;
      edgeSource = null;
      setSelectionMode(SELECTION_MODES.ADD);
      setStatus("Edge mode: click source node, then target node.");
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy){
        if (edgeMode && edgeSource){
          edgeSource.unselect();
          edgeSource = null;
          setStatus("Edge mode: click source node, then target node.");
        } else if (edgeMode){
          edgeMode = false;
          setSelectionMode(SELECTION_MODES.DEFAULT);
          setStatus("Ready.");
        } else {
          setStatus("Ready.");
        }
      }
    });

    cy.on("tap", "node", (evt) => {
      const node = evt.target;
      if (!edgeMode) return;

      if (!edgeSource){
        edgeSource = node;
        node.select();
        setSelectionMode(SELECTION_MODES.ADD);
        setStatus(`Edge mode: source="${node.data("label")}". Now click target node.`);
      } else {
        const target = node;
        if (edgeSource.id() === target.id()){
          setStatus("Edge mode cancelled: cannot connect a node to itself.");
          edgeSource.unselect();
          edgeSource = null;
          edgeMode = false;
          setSelectionMode(SELECTION_MODES.DEFAULT);
          return;
        }

        const exists = cy.edges().some(e => e.source().id() === edgeSource.id() && e.target().id() === target.id());
        let addedEdge = false;
        if (exists){
          setStatus("Edge already exists. Edge mode ended.");
        } else {
          pushUndoState();
          const newEdge = cy.add({
            group: "edges",
            data: {
              id: "e" + Date.now(),
              source: edgeSource.id(),
              target: target.id(),
              label: "",
              lineText: composeLineText(edgeSource.data("label"), target.data("label"))
            }
          });
          markAsAdded(newEdge);
          setStatus(`Added edge: "${edgeSource.data("label")}" -> "${target.data("label")}".`);
          addedEdge = true;
        }

        edgeSource.unselect();
        edgeSource = null;
        edgeMode = false;
        setSelectionMode(SELECTION_MODES.DEFAULT);
        if (addedEdge){
          runLayout();
        }
      }
    });

    document.getElementById("btnAddNode").addEventListener("click", () => {
      if (addNodeHighlightTimer){
        clearTimeout(addNodeHighlightTimer);
        addNodeHighlightTimer = null;
      }
      if (edgeMode){
        if (edgeSource){
          edgeSource.unselect();
        }
        edgeMode = false;
        edgeSource = null;
      }
      setSelectionMode(SELECTION_MODES.ADD);
      const name = prompt("Node name (label):");
      if (!name){
        setSelectionMode(SELECTION_MODES.DEFAULT);
        return;
      }
      const label = sanitizeName(name.trim());
      if (!label){
        setSelectionMode(SELECTION_MODES.DEFAULT);
        return;
      }

      const dup = cy.nodes().some(n => (n.data("label") || "").toLowerCase() === label.toLowerCase());
      if (dup){
        alert("A node with the same label already exists (case-insensitive).");
        setSelectionMode(SELECTION_MODES.DEFAULT);
        return;
      }

      const hazardTag = extractHazardTag(label);
      const lower = label.toLowerCase();
      const autoCond = hazardTag ? true : false;
      const conditionSet = new Set([...USER_CONDITIONS, ...(autoCond ? [lower] : [])]);
      const hazardSet = new Set([...USER_HAZARDS].filter(x => !(autoCond && x === lower)));

      let fill = COLORS.neutral_color;
      if (hazardTag){
        fill = (HAZARD_COLORS[hazardTag] || COLORS.condition_color);
      } else if (hazardSet.has(lower)){
        fill = COLORS.hazard_color;
      } else if (conditionSet.has(lower)){
        fill = COLORS.condition_color;
      }

      pushUndoState();

      const addedNode = cy.add({
        group: "nodes",
        data: {
          id: "n" + Date.now(),
          label,
          labelWrapped: wrapLabel(label, 28),
          hazardTag: hazardTag || "",
          fill
        }
      });

      if (addedNode && addedNode.length){
        cy.$(":selected").unselect();
        addedNode[0].select();
        markAsAdded(addedNode);
      }

      setStatus(`Added node: "${label}"`);
      runLayout();
      addNodeHighlightTimer = setTimeout(() => {
        setSelectionMode(SELECTION_MODES.DEFAULT);
        addNodeHighlightTimer = null;
      }, 800);
    });

    /******************************************************************
    * Right-click two nodes to connect (context edge)
    ******************************************************************/
    let rcEdgeSource = null;

    cy.on("cxttap", "node", (evt) => {
      const node = evt.target;

      // 阻止浏览器右键菜单（保险）
      if (evt.originalEvent && typeof evt.originalEvent.preventDefault === "function"){
        evt.originalEvent.preventDefault();
      }

      // 如果你正在使用左键“Add edge mode”，避免混淆：右键连边先不介入
      if (typeof edgeMode !== "undefined" && edgeMode){
        setStatus("Edge mode is active (left-click). Finish it or click empty space to exit.");
        return;
      }

      // 右键即选中节点（可选：保留已有多选的话就不要 unselect）
      cy.$(":selected").unselect();
      node.select();

      // 第一次右键：记录源节点
      if (!rcEdgeSource){
        rcEdgeSource = node;
        setSelectionMode(SELECTION_MODES.ADD); // 用你已有的红色高亮风格提示“正在连边”
        setStatus(`Right-click connect: source="${node.data("label")}". Now right-click the target node.`);
        return;
      }

      // 第二次右键：目标节点
      const target = node;

      // 同一个节点：取消
      if (rcEdgeSource.id() === target.id()){
        setStatus("Right-click connect cancelled: cannot connect a node to itself.");
        rcEdgeSource = null;
        setSelectionMode(SELECTION_MODES.DEFAULT);
        cy.$(":selected").unselect();
        return;
      }

      // 已存在：提示并结束
      const exists = cy.edges().some(e => e.source().id() === rcEdgeSource.id() && e.target().id() === target.id());
      if (exists){
        setStatus("Edge already exists. Right-click connect ended.");
        rcEdgeSource = null;
        setSelectionMode(SELECTION_MODES.DEFAULT);
        cy.$(":selected").unselect();
        return;
      }

      // add edge
      pushUndoState();
      const newEdge = cy.add({
        group: "edges",
        data: {
          id: "e" + Date.now(),
          source: rcEdgeSource.id(),
          target: target.id(),
          label: "",
          lineText: composeLineText(rcEdgeSource.data("label"), target.data("label"))
        }
      });

      markAsAdded(newEdge);
      setStatus(`Added edge (right-click): "${rcEdgeSource.data("label")}" -> "${target.data("label")}".`);

      rcEdgeSource = null;
      setSelectionMode(SELECTION_MODES.DEFAULT);
      cy.$(":selected").unselect();
    });

    cy.on("cxttap", (evt) => {
      if (evt.target !== cy){
        return;
      }
      if (evt.originalEvent && typeof evt.originalEvent.preventDefault === "function"){
        evt.originalEvent.preventDefault();
      }

      if (edgeSource){
        edgeSource.unselect();
      }
      edgeMode = false;
      edgeSource = null;
      setSelectionMode(SELECTION_MODES.DEFAULT);

      const name = prompt("Node name (label):");
      if (!name) return;

      const label = sanitizeName(name.trim());
      if (!label) return;

      const dup = cy.nodes().some(n => (n.data("label") || "").toLowerCase() === label.toLowerCase());
      if (dup){
        alert("A node with the same label already exists (case-insensitive).");
        return;
      }

      const hazardTag = extractHazardTag(label);
      const lower = label.toLowerCase();
      const autoCond = hazardTag ? true : false;
      const conditionSet = new Set([...USER_CONDITIONS, ...(autoCond ? [lower] : [])]);
      const hazardSet = new Set([...USER_HAZARDS].filter(x => !(autoCond && x === lower)));

      let fill = COLORS.neutral_color;
      if (hazardTag){
        fill = (HAZARD_COLORS[hazardTag] || COLORS.condition_color);
      } else if (hazardSet.has(lower)){
        fill = COLORS.hazard_color;
      } else if (conditionSet.has(lower)){
        fill = COLORS.condition_color;
      }

      pushUndoState();

      const nodeOptions = {
        group: "nodes",
        data: {
          id: "n" + Date.now(),
          label,
          labelWrapped: wrapLabel(label, 28),
          hazardTag: hazardTag || "",
          fill
        }
      };

      if (evt.position && typeof evt.position.x === "number" && typeof evt.position.y === "number"){
        nodeOptions.position = { x: evt.position.x, y: evt.position.y };
      }

      const addedNode = cy.add(nodeOptions);
      if (addedNode && addedNode.length){
        cy.$(":selected").unselect();
        addedNode[0].select();
        markAsAdded(addedNode);
      }

      setStatus(`Added node via right-click: "${label}"`);
    });

    document.getElementById("btnDelete").addEventListener("click", () => {
      const sel = cy.$(":selected");
      if (!sel || sel.length === 0){
        alert("Select a node or edge first.");
        return;
      }
      setSelectionMode(SELECTION_MODES.DELETE);
      pushUndoState();
      const nodes = sel.filter(ele => ele.isNode());
      if (nodes.length){
        markAsDeleted(nodes);
        markAsDeleted(nodes.connectedEdges());
      }
      const edges = sel.filter(ele => ele.isEdge());
      if (edges.length){
        markAsDeleted(edges);
      }
      cy.$(":selected").unselect();
      setSelectionMode(SELECTION_MODES.DEFAULT);
      setStatus("Marked as deleted (green dashed).");
    });

    document.getElementById("btnRename").addEventListener("click", () => {
      const sel = cy.$("node:selected");
      if (!sel || sel.length !== 1){
        alert("Select exactly one node to rename.");
        return;
      }
      const node = sel[0];
      const oldLabel = node.data("label");
      const name = prompt("New node name (label):", oldLabel);
      if (!name) return;

      const label = sanitizeName(name.trim());
      if (!label) return;

      const dup = cy.nodes().some(n => n.id() !== node.id() && (n.data("label") || "").toLowerCase() === label.toLowerCase());
      if (dup){
        alert("Another node already has that label (case-insensitive).");
        return;
      }

      if (label === oldLabel){
        setStatus("Rename cancelled: label unchanged.");
        return;
      }

      const hazardTag = extractHazardTag(label);
      const lower = label.toLowerCase();
      const autoCond = hazardTag ? true : false;
      const conditionSet = new Set([...USER_CONDITIONS, ...(autoCond ? [lower] : [])]);
      const hazardSet = new Set([...USER_HAZARDS].filter(x => !(autoCond && x === lower)));

      let fill = COLORS.neutral_color;
      if (hazardTag){
        fill = (HAZARD_COLORS[hazardTag] || COLORS.condition_color);
      } else if (hazardSet.has(lower)){
        fill = COLORS.hazard_color;
      } else if (conditionSet.has(lower)){
        fill = COLORS.condition_color;
      }

      pushUndoState();

      node.data("label", label);
      node.data("labelWrapped", wrapLabel(label, 28));
      node.data("hazardTag", hazardTag || "");
      node.data("fill", fill);
      refreshEdgesForNode(node);

      setStatus(`Renamed node: "${oldLabel}" -> "${label}"`);
      runLayout();
    });

    document.getElementById("btnRelayout").addEventListener("click", () => {
      runLayout();
      setStatus("Re-layout applied.");
    });

    document.getElementById("btnRender").addEventListener("click", () => {
      const raw = document.getElementById("txtLines").value;
      renderGraphFromArrowLines(raw);
    });
    /******************************************************************
    * Export helpers
    ******************************************************************/
    function collectArrowLinesFromGraph(){
      const lines = [];
      const seen = new Set();

      cy.edges().forEach(e => {
        if (e.hasClass("delete-mark") || e.source().hasClass("delete-mark") || e.target().hasClass("delete-mark")){
          return;
        }
        const s = e.source().data("label");
        const t = e.target().data("label");
        if (!s || !t) return;

        const stored = e.data("lineText");
        const line = stored || composeLineText(s, t);
        const key = line.toLowerCase();
        if (!seen.has(key)){
          seen.add(key);
          lines.push(line);
        }
      });

      // Stable output: alphabetical order (can be replaced by topological order)
      lines.sort((a,b) => a.toLowerCase().localeCompare(b.toLowerCase()));
      return lines;
    }

    function collectAddedArrowLines(lines){
      return lines.filter(line => !INITIAL_LINE_SET.has(line.toLowerCase()));
    }

    function collectNodeLabelsByClass(selector, { skipHistory = true } = {}){
      const seen = new Set();
      const labels = [];
      cy.nodes(selector).forEach(node => {
        if (skipHistory && node.data(HISTORY_DATA_KEY)) return;
        const label = node.data("label");
        if (!label) return;
        const key = label.toLowerCase();
        if (!seen.has(key)){
          seen.add(key);
          labels.push(label);
        }
      });
      labels.sort((a,b) => a.toLowerCase().localeCompare(b.toLowerCase()));
      return labels;
    }

    function collectEdgeLinesByClass(selector, { skipHistory = true } = {}){
      const seen = new Set();
      const lines = [];
      cy.edges(selector).forEach(edge => {
        if (skipHistory && edge.data(HISTORY_DATA_KEY)) return;
        const stored = edge.data("lineText") || composeLineText(edge.source().data("label"), edge.target().data("label"));
        if (!stored) return;
        const key = stored.toLowerCase();
        if (seen.has(key)){
          return;
        }
        seen.add(key);
        lines.push(stored);
      });
      lines.sort((a,b) => a.toLowerCase().localeCompare(b.toLowerCase()));
      return lines;
    }

    function buildTrackPayload(){
      return {
        original: getBaselineLines(),
        added: collectEdgeLinesByClass(".added-highlight"),
        deleted: collectEdgeLinesByClass(".delete-mark"),
        addedNodes: collectNodeLabelsByClass(".added-highlight"),
        deletedNodes: collectNodeLabelsByClass(".delete-mark")
      };
    }

    function downloadText(filename, content){
      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }

    function encodeJsonForScript(value){
      return JSON.stringify(value).replace(/</g, "\\u003c");
    }

    function persistEmbeddedTrackDiff(diff){
      embeddedTrackDiff = diff || null;
      if (trackDiffEl){
        trackDiffEl.textContent = encodeJsonForScript(embeddedTrackDiff || {});
      }
    }

    function downloadHtmlFromCurrentDom(filename, currentText, trackPayload){
      const textarea = document.getElementById("txtLines");
      const previousTextareaValue = textarea ? textarea.value : null;
      if (textarea){
        textarea.value = currentText;
      }

      const cyDiv = document.getElementById("cy");
      let cyDomSnapshot = null;
      if (cyDiv){
        cyDomSnapshot = {
          html: cyDiv.innerHTML,
          className: cyDiv.className,
          styleAttr: cyDiv.getAttribute("style")
        };
        cyDiv.innerHTML = "";
        cyDiv.className = "";
        cyDiv.removeAttribute("style");
      }

      let prevSnapshotText = null;
      if (cySnapshotEl){
        prevSnapshotText = cySnapshotEl.textContent || "";
        try{
          cySnapshotEl.textContent = encodeJsonForScript(cy.json());
        }catch(err){
          console.warn("Failed to serialize Cytoscape snapshot", err);
        }
      }

      let prevInitialLines = null;
      if (initialLinesEl){
        prevInitialLines = initialLinesEl.textContent || "";
        initialLinesEl.textContent = encodeJsonForScript(currentText);
      }

      let prevTrackText = null;
      if (trackDiffEl){
        prevTrackText = trackDiffEl.textContent || "";
        trackDiffEl.textContent = encodeJsonForScript(trackPayload || {});
      }

      const html = "<!doctype html>\n" + document.documentElement.outerHTML;

      if (cySnapshotEl && prevSnapshotText !== null){
        cySnapshotEl.textContent = prevSnapshotText;
      }
      if (initialLinesEl && prevInitialLines !== null){
        initialLinesEl.textContent = prevInitialLines;
      }
      if (trackDiffEl && prevTrackText !== null){
        trackDiffEl.textContent = prevTrackText;
      }
      if (textarea && previousTextareaValue !== null){
        textarea.value = previousTextareaValue;
      }
      if (cyDiv && cyDomSnapshot){
        cyDiv.innerHTML = cyDomSnapshot.html;
        cyDiv.className = cyDomSnapshot.className || "";
        if (cyDomSnapshot.styleAttr !== null){
          cyDiv.setAttribute("style", cyDomSnapshot.styleAttr);
        } else {
          cyDiv.removeAttribute("style");
        }
      }

      downloadText(filename, html);
    }

    function clearChangeMarkers(){
      cy.nodes().forEach(node => {
        node.removeClass("added-highlight delete-mark");
        node.removeData(HISTORY_DATA_KEY);
      });
      cy.edges().forEach(edge => {
        edge.removeClass("added-highlight delete-mark");
        edge.removeData(HISTORY_DATA_KEY);
      });
    }

    function findNodesByLabel(label){
      const lower = (label || "").toLowerCase();
      if (!lower) return cy.collection();
      return cy.nodes().filter(node => (node.data("label") || "").toLowerCase() === lower);
    }

    function findEdgesByLine(line){
      const lower = (line || "").toLowerCase();
      if (!lower) return cy.collection();
      return cy.edges().filter(edge => {
        const stored = edge.data("lineText") || composeLineText(edge.source().data("label"), edge.target().data("label"));
        return stored && stored.toLowerCase() === lower;
      });
    }

    function applyTrackDiffHighlights(diff){
      if (!diff) return false;
      clearChangeMarkers();
      const addedNodes = Array.isArray(diff.addedNodes) ? diff.addedNodes : [];
      const deletedNodes = Array.isArray(diff.deletedNodes) ? diff.deletedNodes : [];
      const addedLines = Array.isArray(diff.addedLines) ? diff.addedLines : (Array.isArray(diff.added) ? diff.added : []);
      const deletedLines = Array.isArray(diff.deletedLines) ? diff.deletedLines : (Array.isArray(diff.deleted) ? diff.deleted : []);

      addedNodes.forEach(label => {
        const nodes = findNodesByLabel(label);
        if (nodes.length){
          markAsAdded(nodes);
          tagAsHistory(nodes, "added");
        }
      });
      deletedNodes.forEach(label => {
        const nodes = findNodesByLabel(label);
        if (nodes.length){
          markAsDeleted(nodes);
          tagAsHistory(nodes, "deleted");
        }
      });
      addedLines.forEach(line => {
        const edges = findEdgesByLine(line);
        if (edges.length){
          markAsAdded(edges);
          tagAsHistory(edges, "added");
        }
      });
      deletedLines.forEach(line => {
        const edges = findEdgesByLine(line);
        if (edges.length){
          markAsDeleted(edges);
          tagAsHistory(edges, "deleted");
        }
      });
      return true;
    }

    async function fetchTrackDiffFromFile(){
      if (location.protocol === "file:") {
        return null;
      }

      if (!TRACK_FILE_NAME) return null;
      try{
        const res = await fetch(`${TRACK_FILE_NAME}?t=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const text = await res.text();
        if (!text.trim()) return null;
        return JSON.parse(text);
      }catch(err){
        console.warn("Track TXT fetch failed", err);
        return null;
      }
    }

    async function loadAndApplyTrackDiff(){
      const diffFromFile = await fetchTrackDiffFromFile();
      const diff = diffFromFile || embeddedTrackDiff || null;
      if (diff){
        const { finalLines, baselineLines } = buildLinesFromTrackDiff(diff);
        if (finalLines.length){
          renderGraphFromArrowLines(finalLines, {
            updateBaseline: true,
            baselineLines: baselineLines.length ? baselineLines : finalLines,
            statusMessage: diffFromFile ? "Rendered graph from fetched track diff." : "Rendered graph from embedded track diff."
          });
        }
        applyTrackDiffHighlights(diff);
      }
    }

    function readSavedSnapshot(){
      return parseJsonFromScript(cySnapshotEl);
    }

    function applySavedSnapshot(){
      const snapshot = readSavedSnapshot();
      if (!snapshot) return false;
      try{
        cy.json(snapshot);
        cy.resize();
        return true;
      }catch(err){
        console.warn("Failed to apply saved snapshot", err);
        return false;
      }
    }

    function hydrateEditorBaseline(){
      const textarea = document.getElementById("txtLines");
      const prefilled = textarea && textarea.value && textarea.value.trim().length > 0;
      const effective = prefilled ? textarea.value : INITIAL_TEXT;
      if (textarea){
        textarea.value = effective;
      }
      const baselineLines = toArrowLines(effective);
      setBaselineFromLines(baselineLines);
      return effective;
    }

    /******************************************************************
    * One-click export: Verified TXT + Track TXT + HTML snapshot
    ******************************************************************/
    document.getElementById("btnSaveBoth").addEventListener("click", () => {
      const arrowLines = collectArrowLinesFromGraph();
      const additionsOnly = collectAddedArrowLines(arrowLines);
      const updatedText = arrowLines.join("\n");
      const trackPayload = buildTrackPayload();

      downloadText(VERIFIED_FILE_NAME, updatedText);
      downloadText(TRACK_FILE_NAME, JSON.stringify(trackPayload, null, 2));

      setTimeout(() => {
        downloadHtmlFromCurrentDom(HTML_FILE_NAME, updatedText, trackPayload);
        setStatus(`Saved: ${VERIFIED_FILE_NAME}, ${TRACK_FILE_NAME}, ${HTML_FILE_NAME} (additions=${additionsOnly.length})`);
      }, 200);
    });


    /******************************************************************
     * Legend rendering
     ******************************************************************/
    function renderLegendHazards(){
      const box = document.getElementById("legendHazards");
      const keys = Object.keys(HAZARD_COLORS);
      keys.sort((a,b) => a.localeCompare(b));
      box.innerHTML = keys.map(k => `
        <div class="leg-item">
          <div class="swatch" style="background:${HAZARD_COLORS[k]}"></div>
          <div class="leg-text">Condition &lt;${k}&gt;</div>
        </div>
      `).join("");
    }
    renderLegendHazards();

    /******************************************************************
     * Boot
     ******************************************************************/
    function boot(){
      hydrateEditorBaseline();
      const loadedSnapshot = applySavedSnapshot();
      const finalizeBoot = () => {
        setBaselineNodesFromGraph();
        loadAndApplyTrackDiff();
      };
      if (!loadedSnapshot){
        document.getElementById("btnRender").click();
        setTimeout(finalizeBoot, 200);
      } else {
        setStatus("Loaded saved graph.");
        finalizeBoot();
      }
    }

    const trackFileInput = document.getElementById("trackFileInput");
    const importTrackBtn = document.getElementById("btnImportTrack");
    if (importTrackBtn){
      importTrackBtn.addEventListener("click", () => {
        if (!trackFileInput){
          alert("Track file input unavailable in this build.");
          return;
        }
        trackFileInput.value = "";
        trackFileInput.click();
      });
    }

    if (trackFileInput){
      trackFileInput.addEventListener("change", () => {
        const file = trackFileInput.files && trackFileInput.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
          try{
            const text = (reader.result || "").toString().trim();
            if (!text){
              alert("Selected file is empty.");
              return;
            }
            let parsed = null;
            try{
              parsed = JSON.parse(text);
            }catch(err){
              parsed = null;
            }

            let handled = false;
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed) &&
                (parsed.original || parsed.added || parsed.addedLines || parsed.deleted || parsed.deletedLines || parsed.addedNodes || parsed.deletedNodes)){
              const { finalLines, baselineLines } = buildLinesFromTrackDiff(parsed);
              if (!finalLines.length){
                alert("Track diff file does not contain any valid arrow lines.");
                handled = true;
              } else {
                const rendered = renderGraphFromArrowLines(finalLines, {
                  updateBaseline: true,
                  baselineLines: baselineLines.length ? baselineLines : finalLines,
                  statusMessage: `Rendered imported track from "${file.name}".`
                });
                if (rendered){
                  const applied = applyTrackDiffHighlights(parsed);
                  if (applied){
                    persistEmbeddedTrackDiff(parsed);
                    setStatus(`Imported track diff from "${file.name}".`);
                  } else {
                    alert("Track diff applied, but no matching nodes/edges were found to highlight.");
                  }
                }
                handled = true;
              }
            } else if (Array.isArray(parsed)){
              const arrLines = normalizeArrowLineInput(parsed);
              if (!arrLines.length){
                alert("JSON array did not contain recognizable 'A -> B' lines.");
              } else {
                renderGraphFromArrowLines(arrLines, {
                  updateBaseline: true,
                  statusMessage: `Rendered imported lines from "${file.name}".`
                });
              }
              handled = true;
            }

            if (!handled){
              const textLines = toArrowLines(text);
              if (!textLines.length){
                alert("File is neither valid JSON diff nor arrow-line text.");
                return;
              }
              renderGraphFromArrowLines(textLines, {
                updateBaseline: true,
                statusMessage: `Rendered imported lines from "${file.name}".`
              });
            }
          } finally {
            trackFileInput.value = "";
          }
        };
        reader.onerror = () => {
          alert("Failed to read selected file.");
          trackFileInput.value = "";
        };
        reader.readAsText(file);
      });
    }

    boot();
  </script>
</body>
</html>
"""

def _render_html(
    *,
    chain_lines: Union[str, Iterable[str]],
    conditions: Union[None, str, Iterable[str]],
    hazards: Union[None, str, Iterable[str]],
    condition_color: str,
    hazard_color: str,
    neutral_color: str,
    html_path: Path,
    case_id: str | None = None
) -> Path:
    
    def _safe_case_id(s: str) -> str:

        s = s.strip()
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
        return s or "case"

    final_case_id = _safe_case_id(case_id or html_path.parent.name)

    lines = _to_arrow_lines(chain_lines)

    nodes = _collect_nodes_from_arrow_lines(lines)
    # Effective highlight sets (same logic as your Python version)
    condition_nodes = _load_highlight_nodes(conditions)
    hazard_nodes = _load_highlight_nodes(hazards)

    auto_condition_nodes = {n.lower() for n in nodes if "<" in n and ">" in n}
    condition_nodes |= auto_condition_nodes
    hazard_nodes -= auto_condition_nodes

    # Embed as JSON for JS
    initial_text = "\n".join(lines)

    html = _HTML_TEMPLATE
    html = html.replace("{{INITIAL_TEXT_JSON}}", json.dumps(initial_text, ensure_ascii=False))
    html = html.replace("{{CONDITIONS_JSON}}", json.dumps(sorted(condition_nodes), ensure_ascii=False))
    html = html.replace("{{HAZARDS_JSON}}", json.dumps(sorted(hazard_nodes), ensure_ascii=False))
    html = html.replace("{{HAZARD_COLORS_JSON}}", json.dumps(HAZARD_COLORS, ensure_ascii=False))
    html = html.replace("{{CONDITION_COLOR}}", condition_color)
    html = html.replace("{{HAZARD_COLOR}}", hazard_color)
    html = html.replace("{{NEUTRAL_COLOR}}", neutral_color)
    html = html.replace("{{CASE_ID_JSON}}", json.dumps(final_case_id, ensure_ascii=False))
    html = html.replace("{{TRACK_DIFF_JSON}}", "null")

    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    return html_path


# ============================================================
# Main function: draw_causal_graph_interactive
# ============================================================

def draw_causal_graph_interactive(
    chain_lines: Union[str, Iterable[str]],
    rankdir: str = "LR",
    width: int = 28,
    conditions: Union[None, str, Iterable[str]] = None,
    hazards: Union[None, str, Iterable[str]] = None,
    condition_color: str = "#cfe8ff",
    hazard_color: str = "#ffcccc",
    neutral_color: str = "#f9f9f9",
    *,
    save_path: Optional[Union[str, os.PathLike]] = None,
    fmt: str = "png",
    dpi: int = 200,
    case_id: str | None = None,
):
    """
    Render a causal graph.

    If save_path ends with .html (or fmt == "html"), generates an interactive HTML
    using Cytoscape.js + Dagre (CDN). Returns the output path.

    Otherwise, renders a static graph with Graphviz (requires 'graphviz' Python package
    and Graphviz installed). Returns the output path, or returns the Digraph object if
    save_path is None.

    Parameters mirror your original function for drop-in use.
    """
    if save_path is None:
        # preserve backward-compatible behavior: return a Digraph for static output
        # for HTML, require save_path because returning HTML string isn't expected
        if fmt.lower() in ("html", "htm"):
            raise ValueError("For interactive HTML output, please provide save_path ending with .html.")
        try:
            from graphviz import Digraph
        except Exception as e:
            raise RuntimeError("graphviz is required for static rendering. Install 'graphviz' Python package.") from e

        # Build static Digraph
        lines = _to_arrow_lines(chain_lines)

        # sanitize nodes in lines
        san_lines = []
        for ln in lines:
            if "->" not in ln:
                continue
            src, dst = ln.split("->", 1)
            src_s = _sanitize_name(src.strip())
            dst_s = _sanitize_name(dst.strip())
            san_lines.append(f"{src_s} -> {dst_s}")
        lines = san_lines
        nodes = [_sanitize_name(n) for n in _collect_nodes_from_arrow_lines(lines)]

        condition_nodes = _load_highlight_nodes(conditions)
        hazard_nodes = _load_highlight_nodes(hazards)
        auto_condition_nodes = {n.lower() for n in nodes if "<" in n and ">" in n}
        condition_nodes |= auto_condition_nodes
        hazard_nodes -= auto_condition_nodes

        dot = Digraph(format=fmt)
        dot.attr(rankdir=rankdir, dpi=str(dpi), bgcolor="white", splines="true",
                 ranksep="1.2", nodesep="0.5", pad="0.3", concentrate="false")
        dot.attr("node", shape="box", style="rounded,filled", color="#aaaaaa",
                 fontname="Helvetica", fontsize="10", penwidth="0.8")
        dot.attr("edge", color="#55555580", penwidth="1", arrowsize="0.7")

        id_map: Dict[str, str] = {}
        for name in nodes:
            key = name.lower()
            if key not in id_map:
                id_map[key] = f"n{len(id_map)}"

        for name in nodes:
            safe_name = _sanitize_name(name)
            label = _wrap_label(safe_name, width=width)
            node_id = id_map[safe_name.lower()]
            lower = safe_name.lower()
            hazard_tag = _extract_hazard_tag(safe_name)

            if hazard_tag:
                fill = HAZARD_COLORS.get(hazard_tag, condition_color)
            elif _is_hazard_consequence_node(safe_name):
                fill = hazard_color
            elif lower in hazard_nodes:
                fill = hazard_color
            elif lower in condition_nodes:
                fill = condition_color
            else:
                fill = neutral_color

            dot.node(node_id, label=label, fillcolor=fill)

        for line in lines:
            if "->" not in line:
                continue
            src, dst = [part.strip() for part in line.split("->", 1)]
            src = _sanitize_name(src)
            dst = _sanitize_name(dst)
            dot.edge(id_map[src.lower()], id_map[dst.lower()])

        return dot

    # save_path provided
    out_path = Path(save_path)
    ext = out_path.suffix.lower()
    if fmt.lower() in ("html", "htm") or ext in (".html", ".htm"):
        return _render_html(
            chain_lines=chain_lines,
            conditions=conditions,
            hazards=hazards,
            condition_color=condition_color,
            hazard_color=hazard_color,
            neutral_color=neutral_color,
            html_path=out_path,
            case_id=case_id,
        )

    # static output via graphviz
    try:
        from graphviz import Digraph
    except Exception as e:
        raise RuntimeError("graphviz is required for static rendering. Install 'graphviz' Python package.") from e

    dot = draw_causal_graph_interactive(
        chain_lines=chain_lines,
        rankdir=rankdir,
        width=width,
        conditions=conditions,
        hazards=hazards,
        condition_color=condition_color,
        hazard_color=hazard_color,
        neutral_color=neutral_color,
        save_path=None,
        fmt=fmt,
        dpi=dpi,
    )
    # dot is Digraph
    base_no_ext = out_path.with_suffix("")  # graphviz adds its own extension
    dot.format = ext.lstrip(".") if ext else fmt
    rendered = dot.render(str(base_no_ext), cleanup=True)

    # normalize double extensions sometimes produced by graphviz wrapper
    if rendered.endswith(f".{dot.format}.{dot.format}"):
        fixed = rendered[: -(len(dot.format) + 1)]
        os.replace(rendered, fixed)
        rendered = fixed
    return Path(rendered)
