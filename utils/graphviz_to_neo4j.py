from neo4j import GraphDatabase
import re, json, os, shutil
from collections import OrderedDict
from typing import Iterable, Union, List
from pathlib import Path


def _normalize_text_block(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    return s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")


def _split_into_lines(s: str):
    if "\n" in s:
        return s.splitlines()
    return re.split(r"(?<=[\.!?])\s+", s)


def _to_arrow_lines(data):
    if isinstance(data, str):
        data = _normalize_text_block(data)
        lines = _split_into_lines(data)
    else:
        lines = list(data)
    pat = re.compile(r"(.+?)\s*->\s*(.+)")
    out = []
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
    return list(OrderedDict.fromkeys(out))


def _collect_nodes_from_arrow_lines(lines):
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


def _load_highlight_nodes(source):
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


def upload_causal_graph(
    chain_lines: Union[str, Iterable[str]],
    *,
    uri: str = "bolt://localhost:7687",
    user: str = "neo4j",
    password: str = None,
    conditions: Union[None, str, Iterable[str]] = None,
    hazards: Union[None, str, Iterable[str]] = None,
    export_graphml: Union[str, None] = None,
    export_local: bool = False,
    local_folder: Union[str, Path, None] = None,
):
    """
    Upload causal graph data to Neo4j and optionally export a .graphml file,
    then copy it back to a local folder if export_local=True.

    Args:
        chain_lines: Text or list of 'A -> B' relations
        uri: Neo4j bolt URI
        user: Username
        password: Password
        conditions: Path or list of condition nodes
        hazards: Path or list of hazard nodes
        export_graphml: Filename for exported .graphml (in Neo4j import folder)
        export_local: If True, copy exported file back to local folder
        local_folder: Local folder path to copy file into
    """

    lines = _to_arrow_lines(chain_lines)
    nodes = _collect_nodes_from_arrow_lines(lines)
    condition_nodes = _load_highlight_nodes(conditions)
    hazard_nodes = _load_highlight_nodes(hazards)

    print(f"📊 Parsed {len(nodes)} nodes and {len(lines)} edges")

    driver = GraphDatabase.driver(uri, auth=(user, password))

    def create_graph(tx):
        for n in nodes:
            label_type = "Condition" if n.lower() in condition_nodes else (
                "Hazard" if n.lower() in hazard_nodes else "Event"
            )
            tx.run(f"MERGE (a:{label_type} {{name:$name}})", name=n)
        for line in lines:
            if "->" not in line:
                continue
            src, dst = [s.strip() for s in line.split("->")]
            tx.run("""
                MATCH (a {name:$src}), (b {name:$dst})
                MERGE (a)-[:CAUSES]->(b)
            """, src=src, dst=dst)

    with driver.session() as session:
        session.execute_write(create_graph)

        # === export graph to GraphML ===
        if export_graphml:
            print(f"💾 Exporting graph to '{export_graphml}' ...")
            session.run(f"""
            CALL apoc.export.graphml.all("{export_graphml}", {{useTypes:true}})
            """)
            print("✅ Export complete! File saved in Neo4j import folder.")

            # === copy back to local folder ===
            if export_local and local_folder:
                neo4j_import_path = Path.home() / "Neo4jDesktop" / "relate-data"
                graphml_found = list(neo4j_import_path.glob(f"**/{export_graphml}"))
                if graphml_found:
                    src = graphml_found[0]
                    dst = Path(local_folder) / export_graphml
                    shutil.copy(src, dst)
                    print(f"📂 Copied to local folder: {dst}")
                else:
                    print("⚠️ Could not find exported file in Neo4j import path.")

    driver.close()
    print("✅ Causal graph successfully uploaded to Neo4j.")
    print("   View it at → http://localhost:7474")
    return {"nodes": len(nodes), "edges": len(lines)}
