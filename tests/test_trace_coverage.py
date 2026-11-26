import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "fosci"))
import trace_coverage as tc  # noqa: E402
import record_trace  # noqa: E402

HEADER = "traceID,order,structtype,method1,method2,m1_para,m2_para,class1,class2,m1_return,m2_return"


def make_dataset(tmp_path):
    src = tmp_path / "src" / "p"
    src.mkdir(parents=True)
    (src / "A.java").write_text("class A { void run() {} static class In { void go() {} } }")
    (src / "B.java").write_text("class B { void b() {} }")
    (src / "C.java").write_text("class C { void c() {} }")
    (src / "Repo.java").write_text("public interface Repo { void find(); }")
    methods = {}
    for cls, meth in [("A", "run"), ("A.In", "go"), ("B", "b"), ("C", "c"), ("Repo", "find")]:
        top = cls.split(".")[0]
        methods[f"p.{cls}.{meth}"] = {"id": f"p.{cls}.{meth}", "class": cls, "package": "p", "method_name": meth,
                                      "file_path": f"p/{top}.java"}
    (tmp_path / "dataset.json").write_text(json.dumps({
        "source_path": "src", "classes": ["p.A", "p.A.In", "p.B", "p.C", "p.Repo"], "methods": methods}))
    rows = ["0,0,null,p.A.run,p.B.b,,,p.A,p.B,,",
            "0,1,null,p.A.run,p.A$In.go,,,p.A,p.A$In,,",
            "1,0,null,p.A$1.call,p.B.b,,,p.A$1,p.B,,",
            "1,1,null,p.B.b,q.Other.x,,,p.B,q.Other,,"]
    with gzip.open(tmp_path / "fosci_trace.csv.gz", "wt") as f:
        f.write(HEADER + "\n" + "\n".join(rows) + "\n")
    return tmp_path


def test_coverage_counts_inner_classes_and_separates_interfaces(tmp_path):
    report = tc.coverage(str(make_dataset(tmp_path)), str(tmp_path / "fosci_trace.csv.gz"))
    assert report["traces"] == 2
    assert (report["classes_covered"], report["classes"]) == (3, 5)  # A (incl. A$1), A.In, B
    assert report["class_coverage"] == 0.6
    assert report["traceable_classes"] == 4 and report["traceable_class_coverage"] == 0.75
    assert report["uncovered_classes"] == ["p.C"]
    assert report["uncovered_interfaces"] == ["p.Repo"]
    assert report["unmatched_trace_classes"] == ["q.Other"]
    assert (report["methods_covered"], report["method_coverage"]) == (3, 0.6)  # A.run, A.In.go, B.b


def test_package_prefix_is_the_common_package(tmp_path):
    (tmp_path / "dataset.json").write_text(json.dumps({"classes": ["org.x.web.A", "org.x.svc.B", "org.x.C"]}))
    assert record_trace.package_prefix(str(tmp_path)) == "org.x"
