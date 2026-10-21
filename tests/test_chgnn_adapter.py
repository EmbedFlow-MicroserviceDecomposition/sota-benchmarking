"""Tests for the CHGNN adapter using the same tiny 5-class graph as the
metrics tests: A,B,C call/extend each other; E is a web entrypoint.

Graph (src, dst, type, weight):
    A -> B  CALL 2      B -> C CALL 1      C -> D CALL 1
    D -> E  CALL 1      E -> B CALL 2
    B -> A  EXTENDS 1   C -> I IMPLEMENTS 1 (I not a node -> ignored)
    A -> C  FIELD 1
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "chgnn"))

from chgnn_adapter import (
    build_callgraph_dot,
    build_chgnn_inputs,
    build_db_json,
    build_icu,
    load_graph,
    build_service_json,
    reachable,
)

NODES = ["A", "B", "C", "D", "E"]
EDGES = [
    ("A", "B", "CALL", 2),
    ("B", "C", "CALL", 1),
    ("C", "D", "CALL", 1),
    ("D", "E", "CALL", 1),
    ("E", "B", "CALL", 2),
    ("B", "A", "EXTENDS", 1),
    ("A", "C", "FIELD", 1),
]


class TestICU:
    def test_used_counts_aggregate_call_and_field(self):
        icu = build_icu(NODES, EDGES)
        assert icu["A"]["usedClassesToCount"] == {"B": 2, "C": 1}
        assert icu["B"]["usedByClassesToCount"] == {"A": 2, "E": 2}

    def test_inheritance_also_counts_as_usage(self):
        # CHGNN's own acme data lists every EXTENDS/IMPLEMENTS target in the
        # usage counts too (verified 10/10); pure-inheritance parents with a
        # zero usage row make the GCN produce NaNs (zero struct degree).
        icu = build_icu(NODES, EDGES)
        assert icu["B"]["usedClassesToCount"] == {"C": 1, "A": 1}
        assert icu["A"]["usedByClassesToCount"] == {"B": 1}

    def test_superclass_and_interfaces(self):
        icu = build_icu(NODES, EDGES)
        assert icu["B"]["superClass"] == "A"
        assert icu["A"]["superClass"] == "java.lang.Object"
        assert icu["A"]["implementedInterfaces"] == []

    def test_every_node_present_even_if_isolated(self):
        icu = build_icu(NODES + ["Z"], EDGES)
        assert icu["Z"]["usedClassesToCount"] == {}


class TestCallgraph:
    def test_reachable_follows_call_and_field_edges(self):
        # FIELD edges are DI wiring (Spring injects, then dispatches) so they
        # carry reachability; EXTENDS does not (B->A must not be followed).
        assert reachable(EDGES, "D") == {"D", "E", "B", "C"}
        # from A: A->B CALL, A->C FIELD, then C->D->E
        assert reachable(EDGES, "A") == {"A", "B", "C", "D", "E"}
        # a pure FIELD link carries reachability on its own
        assert reachable([("X", "Y", "FIELD", 1)], "X") == {"X", "Y"}
        # EXTENDS alone does not
        assert reachable([("X", "Y", "EXTENDS", 1)], "X") == {"X"}

    def test_dot_annotates_reachable_call_edges_per_entrypoint(self):
        dot = build_callgraph_dot(NODES, EDGES, ["E"])
        ep = "{type: web, method: GET, uri: [/E], entry: E, entrydisplayname: E.call}"  # single-segment FQN
        assert f'"E.call" -> "[{ep}] E.call"' in dot
        assert f'"[{ep}] B.call" -> "[{ep}] C.call"' in dot
        # A is not reachable from E: its edges must not carry E's annotation
        assert f'"[{ep}] A.call"' not in dot

    def test_dot_includes_field_edges_as_links(self):
        # A -> C is FIELD: within A's reachable set it must appear as a link
        dot = build_callgraph_dot(NODES, EDGES, ["A"])
        ep = "{type: web, method: GET, uri: [/A], entry: A, entrydisplayname: A.call}"
        assert f'"[{ep}] A.call" -> "[{ep}] C.call"' in dot

    def test_service_json_matches_dot_annotation(self):
        service = build_service_json(["E"])
        assert service == [{
            "service_entry_name":
                "{type: web, method: GET, uri: [/E], entry: E, entrydisplayname: E.call}",
            "class_method_name": ["E.call"],
        }]


class TestDbJson:
    def test_expands_crud_letters(self):
        db = build_db_json({"B": {"account": "RU"}})
        assert {"service_name": "B.call", "db_name": "account", "crud": "R"} in db
        assert {"service_name": "B.call", "db_name": "account", "crud": "U"} in db
        assert len(db) == 2


class TestEntrypointUniqueness:
    def test_same_simple_name_entrypoints_get_distinct_annotations(self):
        # two controllers named PostController in different packages must not
        # merge into one entrypoint (this truncated CHGNN's EP feature width)
        service = build_service_json(["admin.PostController", "web.PostController"])
        names = {s["service_entry_name"] for s in service}
        assert len(names) == 2


DATASET = {
    "methods": {f"{c}.call": {"id": f"{c}.call", "class": c, "package": "", "method_name": "call",
                              "return_type": "void", "parameters": [], "calls": []} for c in NODES},
    "edges": [{"src": s, "dst": d, "type": t, "weight": float(w)} for s, d, t, w in EDGES],
}


class TestLoadGraph:
    def test_isolated_classes_listed_in_classes_are_nodes(self):
        nodes, _ = load_graph({**DATASET, "classes": NODES + ["Lonely"]})
        assert "Lonely" in nodes

    def test_nodes_are_dataset_classes_and_weights_are_ints(self):
        nodes, edges = load_graph(DATASET)
        assert nodes == sorted(NODES)
        assert ("A", "B", "CALL", 2) in edges
        assert all(isinstance(e[3], int) for e in edges)


def write_config(tmp_path, entrypoints=("E",), dbmap=None, seeds=("account-res, A, B", "C, D, E"), ignore=None):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "entrypoints.txt").write_text("\n".join(entrypoints) + "\n")
    (cfg / "dbmap.json").write_text(json.dumps(dbmap if dbmap is not None else {"B": {"account": "RU"}}))
    (cfg / "seeds.txt").write_text("\n".join(seeds) + "\n")
    if ignore is not None:
        (cfg / "ignore_classes.txt").write_text(ignore)
    return cfg


class TestBuildInputs:
    def test_writes_every_chgnn_input_file_and_the_config(self, tmp_path):
        out = tmp_path / "out"
        build_chgnn_inputs(DATASET, str(write_config(tmp_path, ignore="D\n")), str(out))
        for rel in ("temp/inter_class_usage.json", "temp/callgraph.dot", "temp/service.json", "temp/db.json",
                    "custom/seeds.txt", "custom/ignore_classes.txt", "custom/gcnconfig_with_edge_loss.json"):
            assert (out / rel).exists(), rel
        assert (out / "custom/ignore_classes.txt").read_text() == "D\n"
        config = json.loads((out / "custom/gcnconfig_with_edge_loss.json").read_text())
        assert config["num_clusters"] == 2
        assert config["node_dimension"] == 2 * (5 + 1) + 1  # 5 classes, 1 table, 1 entrypoint
        assert config["code"] == "_with_edge_loss"

    def test_a_config_class_missing_from_the_dataset_fails_loudly(self, tmp_path):
        cfg = write_config(tmp_path, entrypoints=("E", "org.Ghost"))
        with pytest.raises(ValueError, match="org.Ghost"):
            build_chgnn_inputs(DATASET, str(cfg), str(tmp_path / "out"))

    def test_seed_classes_missing_from_the_dataset_fail_loudly(self, tmp_path):
        cfg = write_config(tmp_path, seeds=("res, A, Nope", "C, D, E"))
        with pytest.raises(ValueError, match="Nope"):
            build_chgnn_inputs(DATASET, str(cfg), str(tmp_path / "out"))


class TestIgnoreList:
    def test_ignore_entries_absent_from_the_dataset_are_dropped(self, tmp_path):
        out = tmp_path / "out"
        build_chgnn_inputs(DATASET, str(write_config(tmp_path, ignore="D\norg.gone.Class\n")), str(out))
        assert (out / "custom/ignore_classes.txt").read_text() == "D\n"

    def test_isolated_classes_are_excluded_automatically(self, tmp_path):
        # a class with no edges has a zero usage row and NaNs CHGNN's GCN
        dataset = {**DATASET, "classes": NODES + ["Lonely"]}
        out = tmp_path / "out"
        build_chgnn_inputs(dataset, str(write_config(tmp_path)), str(out))
        assert (out / "custom/ignore_classes.txt").read_text() == "Lonely\n"

    def test_isolated_classes_named_in_the_config_are_kept(self, tmp_path):
        dataset = {**DATASET, "classes": NODES + ["Lonely"]}
        cfg = write_config(tmp_path, seeds=("account-res, A, Lonely", "C, D, E"))
        out = tmp_path / "out"
        build_chgnn_inputs(dataset, str(cfg), str(out))
        assert (out / "custom/ignore_classes.txt").read_text() == ""
