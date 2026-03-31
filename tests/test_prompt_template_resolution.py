from pathlib import Path

from utils.prompt_manifest import resolve_template_path


def test_resolve_template_path_accepts_extensionless_txt() -> None:
    resolved = resolve_template_path(Path("prompt"), "causal_edge_linking")
    assert resolved == Path("prompt/causal_edge_linking.txt")


def test_resolve_template_path_keeps_explicit_extension() -> None:
    resolved = resolve_template_path(Path("prompt"), "causal_edge_linking.txt")
    assert resolved == Path("prompt/causal_edge_linking.txt")
