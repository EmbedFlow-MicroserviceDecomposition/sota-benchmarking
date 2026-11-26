# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Record a dataset's FoSCI execution trace by running its functional test suite under the tracer agent.

    uv run record_trace.py --dataset-path ../../datasets/jpetstore [--package org.mybatis.jpetstore] [--jdk8]

1. `docker compose down -v` then `up -d` the dataset's compose file (fresh database), with JAVA_AGENT pointing the app at
   `tracer-agent/` (mounted at /fosci) and TRACE_DIR at `outputs/<dataset>/trace/` (mounted at /trace).
2. Run every use case of `datasets/<dataset>/exercise_usecases.py`, noting which trace rows each one produced
   (`usecase_spans.json`).
3. Only if every use case passed: gzip the trace to `datasets/<dataset>/fosci_trace.csv.gz` and write
   `fosci_trace_coverage.json` next to it (trace_coverage.py).
"""

import argparse
import gzip
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import trace_coverage  # noqa: E402


def load_suite(dataset_dir):
    path = os.path.join(dataset_dir, "exercise_usecases.py")
    spec = importlib.util.spec_from_file_location("exercise_usecases", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "suite"):
        sys.exit(f"{path} does not define a workload.Suite named `suite`")
    return module.suite


def package_prefix(dataset_dir):
    """Longest common package of dataset.json's classes."""
    classes = json.load(open(os.path.join(dataset_dir, "dataset.json"), encoding="utf-8"))["classes"]
    parts = [c.split(".")[:-1] for c in classes]
    prefix = os.path.commonprefix(parts)
    if not prefix:
        sys.exit("dataset classes share no package; pass --package")
    return ".".join(prefix)


def compose_file(dataset_dir):
    for name in ("docker-compose.yml", "docker-compose.yaml"):
        if os.path.exists(os.path.join(dataset_dir, name)):
            return os.path.join(dataset_dir, name)
    sys.exit(f"no docker-compose.yml in {dataset_dir}")


def count_rows(path):
    if not os.path.exists(path):
        return 0
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def wait_until_up(suite, compose, env, timeout=900):
    """Wait for the app, failing at once (with its log) if a container exits, e.g. a JDK 8 app given the JDK 11 agent."""
    deadline = time.time() + timeout
    while True:
        try:
            suite.wait_ready(timeout=10)
            return
        except TimeoutError:
            pass
        exited = subprocess.run(compose + ["ps", "-a", "--status", "exited", "--format", "{{.Name}}"], env=env,
                                capture_output=True, text=True).stdout.split()
        if exited:
            logs = subprocess.run(compose + ["logs", "--tail", "20"], env=env, capture_output=True, text=True)
            sys.exit(f"container(s) exited before the app came up: {', '.join(exited)}\n{logs.stdout}{logs.stderr}\n"
                     "(UnsupportedClassVersionError means a JDK 8 app: pass --jdk8)")
        if time.time() > deadline:
            sys.exit(f"{suite.name} did not come up within {timeout}s")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--package", help="instrumented package prefix (default: common package of dataset.json)")
    parser.add_argument("--jdk8", action="store_true", help="use tracer-agent-jdk8.jar (apps running on JDK 8)")
    parser.add_argument("--keep-running", action="store_true", help="leave the containers up afterwards")
    args = parser.parse_args()

    dataset_dir = os.path.abspath(args.dataset_path)
    name = os.path.basename(dataset_dir)
    trace_dir = os.path.join(HERE, "outputs", name, "trace")
    raw = os.path.join(trace_dir, "trace.csv")
    os.makedirs(trace_dir, exist_ok=True)
    if os.path.exists(raw):
        os.remove(raw)

    prefix = args.package or package_prefix(dataset_dir)
    jar = "tracer-agent-jdk8.jar" if args.jdk8 else "tracer-agent.jar"
    env = dict(os.environ, JAVA_AGENT=f"-javaagent:/fosci/{jar}={prefix},/trace/trace.csv", TRACE_DIR=trace_dir)
    compose = ["docker", "compose", "-f", compose_file(dataset_dir)]
    suite = load_suite(dataset_dir)

    print(f"Recording {name}: package {prefix}, agent {jar}")
    subprocess.run(compose + ["down", "-v"], env=env, check=True)
    subprocess.run(compose + ["up", "-d"], env=env, check=True)
    try:
        wait_until_up(suite, compose, env)
        spans, start = {}, {}
        results = suite.run_all(on_start=lambda n: start.__setitem__(n, count_rows(raw)),
                                on_end=lambda n: spans.__setitem__(n, [start[n], count_rows(raw)]))
    finally:
        if not args.keep_running:
            subprocess.run(compose + ["down", "-v"], env=env)

    with open(os.path.join(trace_dir, "usecase_spans.json"), "w") as f:
        json.dump({"rows": spans, "results": results}, f, indent=2)
    failed = [n for n, err in results.items() if err]
    if failed:
        sys.exit(f"{len(failed)} use case(s) failed ({', '.join(failed)}); trace kept at {raw}, dataset not updated")
    if count_rows(raw) <= 1:
        sys.exit(f"the tracer wrote no calls to {raw}: check the package prefix {prefix!r} and the agent")

    out = os.path.join(dataset_dir, "fosci_trace.csv.gz")
    with open(raw, "rb") as src, open(out, "wb") as dst, gzip.GzipFile(fileobj=dst, mode="wb", mtime=0,
                                                                         compresslevel=9, filename="") as gz:
        shutil.copyfileobj(src, gz)
    report = trace_coverage.coverage(dataset_dir, out)
    with open(os.path.join(dataset_dir, "fosci_trace_coverage.json"), "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(f"wrote {out}: {report['traces']} traces, class coverage {report['class_coverage']:.0%} "
          f"({report['traceable_class_coverage']:.0%} of non-interfaces), method coverage {report['method_coverage']:.0%}")
    if report["class_coverage"] < trace_coverage.TARGET:
        print(f"BELOW TARGET {trace_coverage.TARGET:.0%}; uncovered: {', '.join(report['uncovered_classes'])}")


if __name__ == "__main__":
    main()
