# causal-graph-interactive

Generate causal graphs from `A -> B` arrow-line chains:

- Static images via Graphviz (PNG/SVG/PDF)
- Interactive HTML via Cytoscape.js + Dagre (CDN)

## Install (editable)
```bash
pip install -e .
```

## Usage

### Static PNG
```python
from causal_graph_interactive import draw_causal_graph
out = draw_causal_graph(chain_lines=text, save_path="causal_graph.png")
```

### Interactive HTML
```python
from causal_graph_interactive import draw_causal_graph
out = draw_causal_graph(chain_lines=text, conditions="conditions.json", hazards="hazards.json",
                        save_path="causal_graph.html")
```

Open the generated HTML file in a browser.
