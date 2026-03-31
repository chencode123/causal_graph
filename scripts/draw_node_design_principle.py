from __future__ import annotations

from pathlib import Path

from graphviz import Digraph


OUTPUT_BASENAME = Path("runs/node_design_principle")


def build_diagram() -> Digraph:
    """Build a Graphviz diagram that explains the node design principles."""
    dot = Digraph("node_design_principle", format="png")
    dot.attr(rankdir="LR", splines="polyline", nodesep="0.35", ranksep="0.65", pad="0.2", dpi="300")
    dot.attr(
        "node",
        shape="box",
        style="rounded,filled",
        fontname="Helvetica",
        fontsize="15",
        margin="0.12,0.08",
        color="#999999",
    )
    dot.attr("edge", fontname="Helvetica", fontsize="13", color="#666666")

    dot.node(
        "Entity",
        "\n".join(
            [
                "Entity",
                "",
                "Role:",
                "What exists in the process",
                "",
                "Labels:",
                "- Material",
                "- Location",
            ]
        ),
        fillcolor="#ddf5df",
    )

    dot.node(
        "Condition",
        "\n".join(
            [
                "Condition",
                "",
                "Role:",
                "State or property shaping accident evolution",
                "",
                "Labels:",
                "- Phase",
                "- Pressure",
                "- Temperature",
                "- Volatility",
                "- Combustibility",
                "- ToxicSubstance",
                "- Asphyxiant",
                "- Conductivity",
                "- ReleaseType",
                "- Confinement",
                "- Dispersion",
            ]
        ),
        fillcolor="#d8ebff",
    )

    dot.node(
        "Event",
        "\n".join(
            [
                "Event",
                "",
                "Role:",
                "What happens in the accident sequence",
                "",
                "Labels:",
                "- InitiatingEvent",
                "- MechanicalFailure",
                "- IgnitionSource",
            ]
        ),
        fillcolor="#f3e7ff",
    )

    dot.node(
        "HazardConsequence",
        "\n".join(
            [
                "HazardConsequence",
                "",
                "Role:",
                "Realized accident outcome",
                "",
                "Labels:",
                "- VCE",
                "- BLEVE",
                "- Dust explosion",
                "- Confined explosion",
                "- Pool fire",
                "- Jet fire",
                "- Fire ball",
                "- Flash fire",
                "- Toxicity dispersion",
                "- Asphyxiation",
            ]
        ),
        fillcolor="#ffd6d6",
    )

    dot.edge("Entity", "Condition", label="has")
    dot.edge("Condition", "Event", label="enables")
    dot.edge("Event", "HazardConsequence", label="enables")

    return dot


def main() -> None:
    OUTPUT_BASENAME.parent.mkdir(parents=True, exist_ok=True)
    dot = build_diagram()
    output_path = dot.render(str(OUTPUT_BASENAME), cleanup=True)
    print(output_path)


if __name__ == "__main__":
    main()
