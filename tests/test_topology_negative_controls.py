from __future__ import annotations

import random

import networkx as nx

from scripts.evaluate_topology_negative_controls import (
    combined_perturbation,
    delete_edges,
    delete_nodes,
    reverse_edge_directions,
    rewire_edge_endpoints,
)


def make_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    for node, node_type in (
        ("En1", "Entity"),
        ("En2", "Entity"),
        ("C1", "Condition"),
        ("C2", "Condition"),
        ("Ev1", "Event"),
        ("Ev2", "Event"),
        ("H1", "HazardConsequence"),
    ):
        graph.add_node(node, label=node_type, node_type=node_type)
    for source, target in (
        ("En1", "C1"),
        ("En2", "C2"),
        ("C1", "Ev1"),
        ("C2", "Ev2"),
        ("Ev1", "H1"),
        ("Ev2", "H1"),
    ):
        graph.add_edge(source, target, relation="enables", label="enables")
    return graph


def test_node_deletion_preserves_hazard_node_and_attributes() -> None:
    graph = make_graph()
    perturbed, changes = delete_nodes(graph, 0.5, random.Random(7))
    assert "H1" in perturbed
    assert changes["nodes_deleted"] == 3
    assert perturbed.nodes["H1"] == graph.nodes["H1"]


def test_edge_deletion_changes_only_edge_membership() -> None:
    graph = make_graph()
    perturbed, changes = delete_edges(graph, 0.5, random.Random(7))
    assert set(perturbed.nodes()) == set(graph.nodes())
    assert all(perturbed.nodes[node] == graph.nodes[node] for node in graph.nodes())
    assert changes["edges_deleted"] == 3
    assert perturbed.number_of_edges() == graph.number_of_edges() - 3


def test_direction_reversal_preserves_counts_and_attributes() -> None:
    graph = make_graph()
    perturbed, changes = reverse_edge_directions(graph, 0.5, random.Random(7))
    assert perturbed.number_of_nodes() == graph.number_of_nodes()
    assert perturbed.number_of_edges() == graph.number_of_edges()
    assert changes["edges_reversed"] == 3
    assert sorted(data["relation"] for _, _, data in perturbed.edges(data=True)) == [
        "enables"
    ] * graph.number_of_edges()


def test_endpoint_rewiring_preserves_directed_degree_sequence() -> None:
    graph = make_graph()
    before = {node: (graph.in_degree(node), graph.out_degree(node)) for node in graph}
    perturbed, changes = rewire_edge_endpoints(graph, 0.5, random.Random(11))
    after = {node: (perturbed.in_degree(node), perturbed.out_degree(node)) for node in perturbed}
    assert after == before
    assert perturbed.number_of_edges() == graph.number_of_edges()
    assert changes["edges_rewired"] > 0
    assert len(set(graph.edges()) - set(perturbed.edges())) == changes["edges_rewired"]
    assert not any(source == target for source, target in perturbed.edges())


def test_combined_control_preserves_h1_and_does_not_mutate_source() -> None:
    graph = make_graph()
    original_nodes = set(graph.nodes())
    original_edges = set(graph.edges())
    perturbed, changes = combined_perturbation(graph, 0.25, random.Random(23))
    assert "H1" in perturbed
    assert changes["nodes_deleted"] > 0
    assert set(graph.nodes()) == original_nodes
    assert set(graph.edges()) == original_edges
