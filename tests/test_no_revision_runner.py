from __future__ import annotations

from no_revision_runner import audit_graph, build_candidate_graph


def _candidate_nodes() -> dict:
    return {
        "hazard_consequence_node": {
            "label": "HazardConsequence",
            "name": "Fire",
            "node_id": "H1",
            "node_type": "HazardConsequence",
        },
        "candidate_entity_nodes": [
            {"label": "Material", "name": "Fuel", "node_id": "En1", "node_type": "Entity"}
        ],
        "candidate_condition_nodes": [
            {
                "label": "Combustibility",
                "name": "Combustible",
                "node_id": "C1",
                "node_type": "Condition",
            }
        ],
        "candidate_event_nodes": [
            {"label": "IgnitionSource", "name": "Spark", "node_id": "Ev1", "node_type": "Event"}
        ],
    }


def test_candidate_groups_and_edges_are_assembled_without_filtering() -> None:
    edge_output = {
        "candidate_edges": [
            {"source": "En1", "target": "C1", "relation": "has"},
            {"source": "C1", "target": "Ev1", "relation": "enables"},
            {"source": "Ev1", "target": "H1", "relation": "enables"},
        ]
    }
    graph = build_candidate_graph(_candidate_nodes(), edge_output)

    assert [node["node_id"] for node in graph["hazard_consequence_node"]] == ["H1"]
    assert [node["node_id"] for node in graph["entity_nodes"]] == ["En1"]
    assert graph["edges"] == edge_output["candidate_edges"]
    assert audit_graph(graph)["valid"] is True


def test_unknown_edge_endpoint_is_reported_not_silently_removed() -> None:
    graph = build_candidate_graph(
        _candidate_nodes(),
        {"candidate_edges": [{"source": "Ev999", "target": "H1", "relation": "enables"}]},
    )
    audit = audit_graph(graph)

    assert graph["edges"][0]["source"] == "Ev999"
    assert audit["valid"] is False
    assert any("unknown edge endpoint" in message for message in audit["errors"])


def test_directed_cycle_is_measured_and_retained() -> None:
    nodes = _candidate_nodes()
    nodes["candidate_event_nodes"].append(
        {"label": "IntermediateEvent", "name": "Feedback", "node_id": "Ev2", "node_type": "Event"}
    )
    graph = build_candidate_graph(
        nodes,
        {
            "candidate_edges": [
                {"source": "En1", "target": "C1", "relation": "has"},
                {"source": "C1", "target": "Ev1", "relation": "enables"},
                {"source": "Ev1", "target": "Ev2", "relation": "enables"},
                {"source": "Ev2", "target": "Ev1", "relation": "enables"},
                {"source": "Ev2", "target": "H1", "relation": "enables"},
            ]
        },
    )
    audit = audit_graph(graph)

    assert audit["valid"] is True
    assert audit["has_directed_cycle"] is True
    assert len(graph["edges"]) == 5
