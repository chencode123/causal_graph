from __future__ import annotations

import unittest

import networkx as nx

from scripts.evaluation_structure_similarity import compute_bipartite_graph_edit_metrics


def make_graph(
    nodes: list[tuple[str, str]],
    edges: list[tuple[str, str, str]],
) -> nx.DiGraph:
    graph = nx.DiGraph()
    for node_id, node_type in nodes:
        graph.add_node(node_id, node_type=node_type, label=node_type)
    for source, target, relation in edges:
        graph.add_edge(source, target, relation=relation, label=relation)
    return graph


class BipartiteGedTests(unittest.TestCase):
    def assert_distance_and_counts(
        self,
        generated: nx.DiGraph,
        reference: nx.DiGraph,
        expected_distance: float,
        **expected_counts: int,
    ) -> None:
        distance, _, _, counts = compute_bipartite_graph_edit_metrics(
            generated,
            reference,
        )
        self.assertEqual(distance, expected_distance)
        for key, expected in expected_counts.items():
            self.assertEqual(counts[key], expected, key)

    def test_identical_graphs_have_similarity_one(self) -> None:
        graph = make_graph(
            [("C1", "Condition"), ("Ev1", "Event"), ("H1", "HazardConsequence")],
            [("C1", "Ev1", "enables"), ("Ev1", "H1", "enables")],
        )
        distance, normalized, similarity, counts = compute_bipartite_graph_edit_metrics(
            graph,
            graph.copy(),
        )
        self.assertEqual(distance, 0.0)
        self.assertEqual(normalized, 0.0)
        self.assertEqual(similarity, 1.0)
        self.assertTrue(all(value == 0 for value in counts.values()))

    def test_node_insertion_uses_unit_cost(self) -> None:
        generated = make_graph([("H1", "HazardConsequence")], [])
        reference = make_graph(
            [("H1", "HazardConsequence"), ("En1", "Entity")],
            [],
        )
        self.assert_distance_and_counts(
            generated,
            reference,
            1.0,
            ged_node_insertion_count=1,
        )

    def test_node_type_difference_is_a_substitution(self) -> None:
        generated = make_graph([("X", "Condition")], [])
        reference = make_graph([("Y", "Event")], [])
        self.assert_distance_and_counts(
            generated,
            reference,
            1.0,
            ged_node_substitution_count=1,
        )

    def test_edge_insertion_uses_unit_cost(self) -> None:
        nodes = [("Ev1", "Event"), ("H1", "HazardConsequence")]
        generated = make_graph(nodes, [])
        reference = make_graph(nodes, [("Ev1", "H1", "enables")])
        self.assert_distance_and_counts(
            generated,
            reference,
            1.0,
            ged_edge_insertion_count=1,
        )

    def test_relation_difference_is_an_edge_substitution(self) -> None:
        nodes = [("En1", "Entity"), ("En2", "Entity")]
        generated = make_graph(nodes, [("En1", "En2", "has")])
        reference = make_graph(nodes, [("En1", "En2", "enables")])
        self.assert_distance_and_counts(
            generated,
            reference,
            1.0,
            ged_edge_substitution_count=1,
        )

    def test_reversed_edge_has_cost_two(self) -> None:
        nodes = [("En1", "Entity"), ("Ev1", "Event")]
        generated = make_graph(nodes, [("En1", "Ev1", "enables")])
        reference = make_graph(nodes, [("Ev1", "En1", "enables")])
        self.assert_distance_and_counts(generated, reference, 2.0)

    def test_symmetric_unit_costs_produce_symmetric_distance(self) -> None:
        left = make_graph(
            [("C1", "Condition"), ("Ev1", "Event"), ("H1", "HazardConsequence")],
            [("C1", "Ev1", "enables"), ("Ev1", "H1", "enables")],
        )
        right = make_graph(
            [("C9", "Condition"), ("Ev9", "Event"), ("H9", "HazardConsequence")],
            [("C9", "Ev9", "has")],
        )
        forward = compute_bipartite_graph_edit_metrics(left, right)[0]
        reverse = compute_bipartite_graph_edit_metrics(right, left)[0]
        self.assertEqual(forward, reverse)

    def test_induced_path_is_not_below_exact_ged_on_small_graph(self) -> None:
        generated = make_graph(
            [("C1", "Condition"), ("Ev1", "Event"), ("H1", "HazardConsequence")],
            [("C1", "Ev1", "enables"), ("Ev1", "H1", "enables")],
        )
        reference = make_graph(
            [("C9", "Condition"), ("Ev9", "Event"), ("H9", "HazardConsequence")],
            [("C9", "Ev9", "enables"), ("C9", "H9", "enables")],
        )
        approximate = compute_bipartite_graph_edit_metrics(generated, reference)[0]
        exact = nx.graph_edit_distance(
            generated,
            reference,
            node_subst_cost=lambda left, right: (
                0.0 if left.get("node_type") == right.get("node_type") else 1.0
            ),
            node_del_cost=lambda _: 1.0,
            node_ins_cost=lambda _: 1.0,
            edge_subst_cost=lambda left, right: (
                0.0 if left.get("relation") == right.get("relation") else 1.0
            ),
            edge_del_cost=lambda _: 1.0,
            edge_ins_cost=lambda _: 1.0,
        )
        self.assertIsNotNone(exact)
        self.assertGreaterEqual(approximate, float(exact))


if __name__ == "__main__":
    unittest.main()
