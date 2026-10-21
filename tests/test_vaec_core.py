import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("sklearn")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "_common"))
import vaec_core  # noqa: E402

CLASSES = [f"p.C{i}" for i in range(7)]
DATASET = {
    "classes": CLASSES + ["p.Lonely"],
    "methods": {},
    "edges": [
        {"src": "p.C0", "dst": "p.C1", "type": "CALL", "weight": 3.0},
        {"src": "p.C0", "dst": "p.C1", "type": "FIELD", "weight": 1.0},   # duplicate pair, other type
        {"src": "p.C1", "dst": "p.C2", "type": "CALL", "weight": 1.0},
        {"src": "p.C2", "dst": "p.C2", "type": "CALL", "weight": 1.0},    # self edge
        {"src": "p.C2", "dst": "p.C3", "type": "EXTENDS", "weight": 1.0},
        {"src": "p.C4", "dst": "p.C5", "type": "CALL", "weight": 1.0},
        {"src": "p.C5", "dst": "p.C6", "type": "CALL", "weight": 1.0},
        {"src": "p.C6", "dst": "p.C4", "type": "CALL", "weight": 1.0},    # cycle
    ],
}
ENTRYPOINTS = ["p.C0", "p.C4"]


def test_adjacency_has_every_class_deduplicated_without_self_edges():
    adj = vaec_core.build_adjacency(DATASET)
    assert set(adj) == set(CLASSES) | {"p.Lonely"}
    assert adj["p.C0"] == ["p.C1"]
    assert adj["p.C2"] == ["p.C3"]
    assert adj["p.Lonely"] == []


def test_elbow_is_the_point_farthest_from_the_first_last_chord():
    assert vaec_core.elbow_k([100, 40, 20, 18, 17], [2, 3, 4, 5, 6]) == 3


def test_feature_matrix_shape_and_path_cap_warning(capsys):
    A, _, class_to_node = vaec_core.build_graph(vaec_core.build_adjacency(DATASET))
    eps = [class_to_node[e] for e in ENTRYPOINTS]
    X = vaec_core.build_features(A.copy(), eps, max_paths=1)
    assert X.shape == (A.shape[0], len(eps) + A.shape[0])
    assert "WARNING" in capsys.readouterr().err


def test_unresolvable_entrypoints_raise():
    with pytest.raises(ValueError, match="entrypoints"):
        vaec_core.run_ae_k(vaec_core.build_adjacency(DATASET), ["org.Ghost"], seed=0, n_epochs=2)


tf = pytest.importorskip("tensorflow")


def test_ae_k_assigns_every_class_and_reports_k():
    info = {}
    labels = vaec_core.run_ae_k(vaec_core.build_adjacency(DATASET), ENTRYPOINTS, seed=0, n_epochs=40, info=info)
    assert set(labels) == set(CLASSES) | {"p.Lonely"}
    assert info["k"] >= 2 and info["capped"] is False


def test_ae_k_is_deterministic_for_a_seed():
    adj = vaec_core.build_adjacency(DATASET)
    first = vaec_core.run_ae_k(adj, ENTRYPOINTS, seed=7, n_epochs=40)
    second = vaec_core.run_ae_k(adj, ENTRYPOINTS, seed=7, n_epochs=40)
    assert first == second


def test_vae_c_with_a_fixed_k_returns_at_most_k_clusters():
    pytest.importorskip("skfuzzy")
    labels = vaec_core.run_vae_c(vaec_core.build_adjacency(DATASET), ENTRYPOINTS, seed=0, k=3, n_epochs=40)
    assert set(labels) == set(CLASSES) | {"p.Lonely"}
    assert len(set(labels.values())) <= 3
