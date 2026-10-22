import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "cogcn"))
from cogcn_adapter import build_cogcn_inputs  # noqa: E402


def method(cls, name, params=(), ret="void"):
    pkg, _, simple = cls.rpartition(".")
    return {"id": f"{cls}.{name}", "class": simple, "package": pkg, "method_name": name,
            "return_type": ret, "parameters": list(params), "calls": []}


DATASET = {
    "classes": ["p.OrderService", "p.OrderRepo", "p.Account", "p.Lonely"],
    "methods": {m["id"]: m for m in (
        method("p.OrderService", "placeOrder", ["Order"], "String"),
        method("p.OrderRepo", "saveOrder", ["Order"]),
        method("p.Account", "getBalance", [], "int"),
    )},
    "edges": [
        {"src": "p.OrderService", "dst": "p.OrderRepo", "type": "CALL", "weight": 3.0},
        {"src": "p.OrderRepo", "dst": "p.OrderService", "type": "FIELD", "weight": 1.0},
        {"src": "p.Account", "dst": "p.Account", "type": "CALL", "weight": 1.0},
        {"src": "p.OrderService", "dst": "p.Account", "type": "EXTENDS", "weight": 1.0},
    ],
}


def read(path):
    with open(path, newline="") as f:
        return [list(map(float, row)) for row in csv.reader(f)]


@pytest.fixture()
def built(tmp_path):
    info = build_cogcn_inputs(DATASET, str(tmp_path))
    return tmp_path, info


def test_classes_file_fixes_the_row_order(built):
    out, info = built
    classes = (out / "classes.txt").read_text().split()
    assert classes == sorted(DATASET["classes"])
    assert info["classes"] == 4


def test_struct_is_a_symmetric_binary_matrix_without_self_loops(built):
    out, _ = built
    classes = (out / "classes.txt").read_text().split()
    a = read(out / "struct.csv")
    assert len(a) == 4 and all(len(r) == 4 for r in a)
    idx = {c: i for i, c in enumerate(classes)}
    assert a[idx["p.OrderService"]][idx["p.OrderRepo"]] == 1 == a[idx["p.OrderRepo"]][idx["p.OrderService"]]
    assert a[idx["p.Account"]][idx["p.OrderService"]] == 1  # EXTENDS counts as structure
    assert all(a[i][i] == 0 for i in range(4))
    assert all(sum(r) == 0 for r in [a[idx["p.Lonely"]]])
    assert all(v in (0.0, 1.0) for r in a for v in r)


def test_content_rows_are_term_frequencies_over_class_method_and_type_names(built):
    out, info = built
    c = read(out / "content.csv")
    classes = (out / "classes.txt").read_text().split()
    vocab = (out / "vocabulary.txt").read_text().split()
    assert len(c) == 4 and all(len(r) == len(vocab) == info["terms"] for r in c)
    row = dict(zip(vocab, c[classes.index("p.OrderService")]))
    # terms of OrderService: class name -> order, service; method placeOrder -> place, order; parameter type Order -> order;
    # the return type String is a JDK noise word and dropped
    assert {k: v for k, v in row.items() if v} == {"order": pytest.approx(3 / 5), "service": pytest.approx(1 / 5),
                                                  "place": pytest.approx(1 / 5)}
    assert "void" not in vocab and "string" not in vocab and "int" not in vocab


def test_each_class_contributes_its_own_name_terms(built):
    out, _ = built
    classes = (out / "classes.txt").read_text().split()
    vocab = (out / "vocabulary.txt").read_text().split()
    row = dict(zip(vocab, read(out / "content.csv")[classes.index("p.Lonely")]))
    assert {k: v for k, v in row.items() if v} == {"lonely": 1.0}


def test_a_class_whose_terms_are_all_noise_gets_a_zero_row_and_the_matrix_keeps_one_column(tmp_path):
    info = build_cogcn_inputs({"classes": ["p.List"], "methods": {}, "edges": []}, str(tmp_path))
    assert read(tmp_path / "content.csv") == [[0.0]]
    assert info["terms"] == 0
