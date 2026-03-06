from __future__ import annotations

from typing import Dict, List, Set, Tuple
from collections import defaultdict, Counter, deque
import re

from .edges import Edge
from .taxonomy import is_condition_label, is_hazard_consequence

_TAG_RE = re.compile(r"<([^>]+)>")
_HC_NUM_SUFFIX = re.compile(r"\s+\d+\s*$")


def _hazard_base(s: str) -> str:
    return _HC_NUM_SUFFIX.sub("", s.strip()).strip()


def _hazard_key_from_phrase(phrase: str) -> str:
    bare = phrase.split("<", 1)[0].strip() if "<" in phrase else phrase.strip()
    return _hazard_base(bare)


def _first_angle_tag(phrase: str) -> str | None:
    m = _TAG_RE.search(phrase or "")
    if not m:
        return None
    tag = m.group(1).strip()
    return tag or None


def remove_hazard_upstream_edges(
    edges: List[Edge],
    *,
    hazard_consequence: List[str],
) -> List[Edge]:
    """
    Remove edges that point from a hazard node back to its own upstream ancestor.

    Example:
    - Input edges:
      `A -> Leak`, `Leak -> Explosion`, `Explosion -> A`
    - hazard_consequence contains: `["Explosion"]`
    - `A` is an ancestor of `Explosion`, so `Explosion -> A` is removed.
    """
    hc_set: Set[str] = {_hazard_base(h) for h in hazard_consequence}

    rev_adj: Dict[str, Set[str]] = defaultdict(set)
    for e in edges:
        rev_adj[e.dst].add(e.src)

    key_to_nodes: Dict[str, Set[str]] = defaultdict(set)
    for e in edges:
        for node in (e.src, e.dst):
            if is_hazard_consequence(node, hazard_consequence):
                k = _hazard_key_from_phrase(node)
                if k in hc_set:
                    key_to_nodes[k].add(node)

    if not key_to_nodes:
        return edges

    ancestors_by_key: Dict[str, Set[str]] = {}
    for k, nodes in key_to_nodes.items():
        seen: Set[str] = set()
        q = deque()
        for hnode in nodes:
            q.extend(rev_adj.get(hnode, ()))

        while q:
            u = q.popleft()
            if u in seen:
                continue
            seen.add(u)
            for p in rev_adj.get(u, ()):
                if p not in seen:
                    q.append(p)

        ancestors_by_key[k] = seen

    filtered: List[Edge] = []
    for e in edges:
        if is_hazard_consequence(e.src, hazard_consequence):
            k = _hazard_key_from_phrase(e.src)
            if e.dst in ancestors_by_key.get(k, set()):
                continue
        filtered.append(e)

    return filtered


def connect_tagged_conditions_to_hazards(
    edges: List[Edge],
    *,
    hazard_consequence: List[str],
) -> List[Edge]:
    """
    Treat any node containing `<...>` as a condition node.

    The tag content corresponds to a hazard consequence. For each tagged-condition
    group (same tag target):
    - If there are condition nodes with no downstream nodes, connect all of them to
      the corresponding hazard consequence.
    - Otherwise, connect only the most downstream condition node (prefer the one
      that does not point to another tagged condition in the same group).
    """
    if not edges:
        return edges

    hc_set: Set[str] = {_hazard_base(h) for h in hazard_consequence}
    edge_set: Set[Edge] = set(edges)

    outgoing: Dict[str, Set[str]] = defaultdict(set)
    all_nodes: Set[str] = set()
    for e in edges:
        outgoing[e.src].add(e.dst)
        all_nodes.add(e.src)
        all_nodes.add(e.dst)

    hazard_nodes_by_key: Dict[str, Set[str]] = defaultdict(set)
    for n in all_nodes:
        if is_hazard_consequence(n, hazard_consequence):
            hazard_nodes_by_key[_hazard_key_from_phrase(n)].add(n)

    tagged_groups: Dict[str, Set[str]] = defaultdict(set)
    for n in all_nodes:
        tag = _first_angle_tag(n)
        if not tag:
            continue
        key = _hazard_base(tag)
        if key not in hc_set:
            continue
        tagged_groups[tag].add(n)

    if not tagged_groups:
        return edges

    def resolve_hazard_node(tag: str) -> str:
        key = _hazard_base(tag)
        candidates = hazard_nodes_by_key.get(key, set())
        if tag in candidates:
            return tag
        # If the exact tagged hazard node does not exist, create it implicitly by
        # connecting to the tag text itself (the edge introduces the node).
        return tag

    def pick_most_downstream(nodes: Set[str]) -> str:
        node_list = sorted(nodes)
        nodes_set = set(nodes)

        # Prefer a node that is not upstream of another tagged condition in same group.
        no_group_child = [
            n for n in node_list if not (outgoing.get(n, set()) & nodes_set)
        ]
        if no_group_child:
            # Among ties, prefer fewer outgoing edges (more terminal-like).
            no_group_child.sort(key=lambda n: (len(outgoing.get(n, set())), n))
            return no_group_child[0]

        # Fall back to shortest distance to any sink in the graph.
        sink_nodes = {x for x in all_nodes if not outgoing.get(x)}

        def dist_to_sink(start: str) -> Tuple[int, str]:
            if start in sink_nodes:
                return (0, start)

            q = deque([(start, 0)])
            seen = {start}
            best = None
            while q:
                cur, d = q.popleft()
                for nxt in sorted(outgoing.get(cur, ())):
                    if nxt in seen:
                        continue
                    nd = d + 1
                    if nxt in sink_nodes:
                        best = (nd, start)
                        q.clear()
                        break
                    seen.add(nxt)
                    q.append((nxt, nd))
            return best if best is not None else (10**9, start)

        ranked = sorted((dist_to_sink(n) for n in node_list))
        return ranked[0][1]

    to_add: List[Edge] = []

    for tag, cond_nodes in tagged_groups.items():
        hazard_node = resolve_hazard_node(tag)
        if not hazard_node:
            continue

        terminal_conditions = [
            n for n in sorted(cond_nodes) if not outgoing.get(n)
        ]

        if terminal_conditions:
            src_nodes = terminal_conditions
        else:
            src_nodes = [pick_most_downstream(cond_nodes)]

        for src in src_nodes:
            if src == hazard_node:
                continue
            new_edge = Edge(src, hazard_node)
            if new_edge in edge_set:
                continue
            to_add.append(new_edge)
            edge_set.add(new_edge)

    if not to_add:
        return edges
    return edges + to_add


# def remove_condition_short_circuits(
#     edges: List[Edge],
#     *,
#     conditions: Dict[str, List[str]],
#     hazard_consequence: List[str],
# ) -> List[Edge]:
#     """
#     Remove direct condition->condition edges when an intermediate non-condition
#     node already forms a 2-hop path between them.

#     Example:
#     - Input edges:
#       `High pressure -> Valve failed`,
#       `Valve failed -> EO release`,
#       `High pressure -> EO release`
#     - If `High pressure` and `EO release` are condition labels,
#       and `Valve failed` is neither condition nor hazard,
#       then `High pressure -> EO release` is removed as a short-circuit.
#     """
#     outgoing = defaultdict(set)
#     incoming = defaultdict(set)
#     edge_set = set(edges)

#     for e in edges:
#         outgoing[e.src].add(e.dst)
#         incoming[e.dst].add(e.src)

#     to_remove: Set[Edge] = set()

#     for mid in list(outgoing.keys()):
#         if is_condition_label(mid, conditions):
#             continue
#         if is_hazard_consequence(mid, hazard_consequence):
#             continue

#         ups = incoming.get(mid, set())
#         dns = outgoing.get(mid, set())
#         if not ups or not dns:
#             continue

#         for u in ups:
#             if not is_condition_label(u, conditions):
#                 continue
#             for d in dns:
#                 if not is_condition_label(d, conditions):
#                     continue
#                 direct = Edge(u, d)
#                 if direct in edge_set:
#                     to_remove.add(direct)

#     if not to_remove:
#         return edges

#     return [e for e in edges if e not in to_remove]

def remove_short_circuit_edges_any_length(
    edges: List[Edge],
) -> List[Edge]:
    """
    Short-circuit definition (your definition):
    Remove direct edge (u -> d) if there exists an alternative path from u to d
    of length >= 2 that does NOT rely on this direct edge.

    Implementation:
    For each direct edge (u -> d), run a BFS from u while skipping this edge.
    If d is still reachable, then (u -> d) is a short-circuit and will be removed.
    """
    adj = defaultdict(set)
    edge_set: Set[Edge] = set(edges)

    for e in edges:
        adj[e.src].add(e.dst)

    to_remove: Set[Edge] = set()

    for e in edges:
        u, d = e.src, e.dst

        # BFS from u, but skip the tested direct edge u->d
        q = deque([u])
        seen = {u}
        found = False

        while q and not found:
            x = q.popleft()
            for y in adj.get(x, ()):
                # skip ONLY the direct edge under test
                if x == u and y == d:
                    continue
                if y in seen:
                    continue
                if y == d:
                    found = True
                    break
                seen.add(y)
                q.append(y)

        if found:
            to_remove.add(Edge(u, d))

    if not to_remove:
        return edges
    return [ed for ed in edges if ed not in to_remove]

def normalize_hazard_numbering(
    edges: List[Edge],
    *,
    hazard_consequence: List[str],
) -> List[Edge]:
    """
    Normalize hazard labels by removing trailing numbers when the same hazard
    base appears only once in all edges.

    Example:
    - Input edge: `EO release 1 -> Toxicity dispersion 1`
    - hazard_consequence contains: `["EO release", "Toxicity dispersion"]`
    - If each base hazard appears once, output becomes:
      `EO release -> Toxicity dispersion`
    """
    hc_set: Set[str] = {_hazard_base(h) for h in hazard_consequence}
    base_counts = Counter()

    def scan_phrase(p: str) -> None:
        m = _TAG_RE.search(p)
        if m:
            base = _hazard_base(m.group(1).strip())
            if base in hc_set:
                base_counts[base] += 1

        bare = p.split("<", 1)[0].strip()
        bare_base = _hazard_base(bare)
        if bare_base in hc_set:
            base_counts[bare_base] += 1

    for e in edges:
        scan_phrase(e.src)
        scan_phrase(e.dst)

    def normalize_phrase(p: str) -> str:
        def repl_tag(m: re.Match) -> str:
            tag = m.group(1).strip()
            base = _hazard_base(tag)
            if base in hc_set and base_counts[base] == 1:
                return f"<{base}>"
            return f"<{tag}>"

        p2 = re.sub(r"<([^>]+)>", repl_tag, p)

        bare = p2.split("<", 1)[0].strip()
        bare_base = _hazard_base(bare)
        if bare_base in hc_set and base_counts[bare_base] == 1:
            if "<" in p2 and ">" in p2:
                return f"{bare_base} " + p2[p2.find("<"):]
            return bare_base

        return p2

    return [Edge(normalize_phrase(e.src), normalize_phrase(e.dst)) for e in edges]


def remove_tagged_reverse_edges(edges: List[Edge]) -> List[Edge]:
    """
    If an edge points to a tagged node `<...>`, remove the exact reverse edge.

    Example:
    - Input edges:
      `A -> B <EO release>`,
      `B <EO release> -> A`
    - Output keeps only:
      `A -> B <EO release>`
    """
    edge_set: Set[Edge] = set(edges)
    to_remove: Set[Edge] = set()

    for e in edges:
        if "<" in e.dst and ">" in e.dst:
            reverse = Edge(e.dst, e.src)
            if reverse in edge_set:
                to_remove.add(reverse)

    if not to_remove:
        return edges

    return [e for e in edges if e not in to_remove]
