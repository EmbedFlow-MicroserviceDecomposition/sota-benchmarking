import json

import pytest

from partition import PartitionError, load_partition


def _method(cls_fqn, name):
    pkg, _, simple = cls_fqn.rpartition(".")
    return {"id": f"{cls_fqn}.{name}", "class": simple, "package": pkg, "method_name": name,
            "return_type": "void", "parameters": [], "calls": []}


def make_dataset():
    ids = [("p.A", "m1"), ("p.A", "m2"), ("p.A", "m3"), ("p.B", "n1"), ("p.C", "x"),
           ("p.Outer.Inner", "z"), ("q.Dup", "d"), ("r.Dup", "d")]
    methods = {f"{c}.{m}": _method(c, m) for c, m in ids}
    return {"methods": methods, "edges": [{"src": "p.A", "dst": "p.B", "type": "CALL", "weight": 1.0}]}


def load(tmp_path, microservices, dataset=None):
    (tmp_path / "output.json").write_text(json.dumps({"tool": "T", "microservices": microservices}))
    return load_partition(str(tmp_path), dataset or make_dataset())


def test_method_level_output_rolls_up_to_classes_by_majority(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A.m1", "p.A.m2", "p.B.n1"], "ms2": ["p.A.m3", "p.C.x"]})
    assert p.granularity == "method"
    assert p.by_class == {"p.A": "ms1", "p.B": "ms1", "p.C": "ms2"}
    assert p.conflicts == {"p.A": ["ms1", "ms2"]}


def test_class_level_output_explodes_to_every_method_of_the_class(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A"], "ms2": ["p.B", "p.C"]})
    assert p.granularity == "class"
    assert p.by_method["p.A.m1"] == p.by_method["p.A.m2"] == p.by_method["p.A.m3"] == "ms1"
    assert p.by_method["p.B.n1"] == "ms2"
    assert "p.Outer.Inner.z" not in p.by_method


def test_majority_tie_goes_to_the_smallest_cluster_id_in_either_order(tmp_path):
    first = load(tmp_path, {"ms2": ["p.A.m1"], "ms1": ["p.A.m2"]})
    second = load(tmp_path, {"ms1": ["p.A.m2"], "ms2": ["p.A.m1"]})
    assert first.by_class == second.by_class == {"p.A": "ms1"}


def test_class_listed_in_two_microservices_is_recorded_as_a_conflict(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A"], "ms2": ["p.A", "p.B"]})
    assert p.by_class["p.A"] == "ms1"
    assert p.conflicts["p.A"] == ["ms1", "ms2"]


def test_mixed_granularity_is_reported(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A.m1", "p.B"]})
    assert p.granularity == "mixed"
    assert p.by_class == {"p.A": "ms1", "p.B": "ms1"}


def test_unknown_ids_are_counted_not_fuzzy_matched(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A", "org.ghost.Ghost", "Dup"]})
    assert p.by_class == {"p.A": "ms1"}
    assert sorted(p.unmatched) == ["Dup", "org.ghost.Ghost"]  # Dup is ambiguous (q.Dup, r.Dup)


def test_unique_simple_name_matches_its_class(tmp_path):
    p = load(tmp_path, {"ms1": ["B"]})
    assert p.by_class == {"p.B": "ms1"}


def test_unassigned_classes_cover_the_rest_of_the_dataset(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A"]})
    assert p.unassigned_classes == {"p.B", "p.C", "p.Outer.Inner", "q.Dup", "r.Dup"}
    assert p.coverage() == {"classes": 6, "assigned": 1, "unassigned": 5,
                            "unmatched_ids": 0, "conflicts": 0}


def test_nested_class_methods_resolve_to_the_nested_class(tmp_path):
    p = load(tmp_path, {"ms1": ["p.Outer.Inner.z"]})
    assert p.by_class == {"p.Outer.Inner": "ms1"}


def test_single_cluster_output_loads(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A", "p.B", "p.C"]})
    assert set(p.clusters) == {"ms1"}
    assert p.clusters["ms1"] == {"p.A", "p.B", "p.C"}


def test_microservice_without_matched_classes_is_not_a_cluster(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A"], "ms2": [], "ms3": ["org.ghost.Ghost"]})
    assert p.clusters == {"ms1": {"p.A"}}


def test_legacy_suffix_is_stripped_and_resource_nodes_skipped(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A [annot]", "db-res", "p.B"]})
    assert p.by_class == {"p.A": "ms1", "p.B": "ms1"}
    assert p.unmatched == []


def test_get_cluster_accepts_method_ids_and_class_fqns(tmp_path):
    p = load(tmp_path, {"ms1": ["p.A.m1", "p.A.m2", "p.A.m3"]})
    assert p.get_cluster("p.A") == "ms1"
    assert p.get_cluster("p.A.m2") == "ms1"
    assert p.get_cluster("java.util.List") is None
    assert p.get_cluster("") is None


def test_error_output_is_never_scored(tmp_path):
    (tmp_path / "output.json").write_text(json.dumps({"error": "boom", "tool": "T"}))
    with pytest.raises(PartitionError, match="boom"):
        load_partition(str(tmp_path), make_dataset())
