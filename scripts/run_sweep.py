# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Produce one tool x dataset cell: run the tool N times, score every run, write the mean metrics.

    uv run scripts/run_sweep.py --tool chgnn --dataset jpetstore --runs 10

Layout of tools/<tool>/outputs/<dataset>/ afterwards:
    run_<i>/            one tool run (output.json, raw files, *_score.json, metrics_summary.json)
    output.json, *_score.json, metrics_summary.json   copies from the first successful run
    metrics_mean.json   per-metric mean/std/min/max over all scored runs, failures, coverage

A tool that writes a grid of results (CARGO: run_<i>/runs/k*_seed*/output.json) has every grid entry scored as one sample.
A cell where every run fails keeps the error-form output.json and an empty metrics block (an N/A cell).
"""

import argparse
import glob
import json
import os
import shutil
import statistics
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPUTE_ALL = os.path.join(ROOT, "metrics", "compute_all.py")
# score file -> {field in the file: key in metrics_mean.json}
FIELDS = {
    "sm": {"score": "SM", "score_undirected": "SM_undirected"},
    "icp": {"score": "ICP"},
    "ifn": {"score": "IFN", "score_cross_edge": "IFN_cross_edge"},
    "ned": {"score": "NED", "score_relative": "NED_relative", "score_triplebound": "NED_triplebound"},
    "bcp": {"score": "BCP"},
    "chm": {"score": "CHM"},
    "chd": {"score": "CHD"},
}
MAIN = {"SM", "ICP", "IFN", "NED", "BCP", "CHM", "CHD"}


def stats(values):
    return {"mean": statistics.mean(values), "std": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": min(values), "max": max(values), "n": len(values)}


def discover_units(run_dir):
    """Directories to score for one tool run: its runs/* grid entries if it wrote any, else the run directory."""
    grid = sorted(d for d in glob.glob(os.path.join(run_dir, "runs", "*")) if os.path.exists(os.path.join(d, "output.json")))
    return grid or ([run_dir] if os.path.exists(os.path.join(run_dir, "output.json")) else [])


def read_error(unit):
    try:
        with open(os.path.join(unit, "output.json"), encoding="utf-8") as f:
            return json.load(f).get("error")
    except (OSError, ValueError):
        return None


def score_unit(dataset_dir, unit):
    """Run compute_all on one output directory; returns ({metric: value}, coverage) or raises RuntimeError."""
    proc = subprocess.run([sys.executable, COMPUTE_ALL, "--dataset-path", dataset_dir, "--output-path", unit],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"compute_all exit {proc.returncode}")
    values, coverage = {}, None
    for metric, fields in FIELDS.items():
        path = os.path.join(unit, f"{metric}_score.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for field, key in fields.items():
            if field in data:
                values[key] = data[field]
        coverage = coverage or data.get("coverage")
    return values, coverage


def sweep(tool_dir, dataset_dir, out_dir, runs, tool_cmd=None, extra_args=()):
    tool_dir, dataset_dir, out_dir = (os.path.abspath(p) for p in (tool_dir, dataset_dir, out_dir))
    tool_cmd = tool_cmd or ["uv", "run", "tool.py"]
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "run_*")):
        shutil.rmtree(old)

    samples, coverages, failures, ok_runs, first_unit, first_error = [], [], [], 0, None, None
    for i in range(1, runs + 1):
        run_dir = os.path.join(out_dir, f"run_{i}")
        proc = subprocess.run(tool_cmd + ["--dataset-path", dataset_dir, "--output-path", run_dir] + list(extra_args),
                              cwd=tool_dir, capture_output=True, text=True)
        units = discover_units(run_dir)
        error = read_error(run_dir) or (None if units else "no output.json")
        if proc.returncode != 0 or error or not units:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] 
            failures.append({"run": i, "error": error or (tail[0] if tail else f"exit {proc.returncode}")})
            first_error = first_error or (run_dir if os.path.exists(os.path.join(run_dir, "output.json")) else None)
            continue
        run_samples = []
        try:
            for unit in units:
                run_samples.append(score_unit(dataset_dir, unit))
        except RuntimeError as e:
            failures.append({"run": i, "error": str(e)})
            continue
        ok_runs += 1
        for values, coverage in run_samples:
            samples.append(values)
            if coverage:
                coverages.append(coverage)
        first_unit = first_unit or units[0]

    summary = {"tool": os.path.basename(tool_dir), "dataset": os.path.basename(dataset_dir), "runs_requested": runs,
               "runs_ok": ok_runs, "units": len(samples), "failures": failures, "metrics": {}, "variants": {}}
    for key in sorted({k for s in samples for k in s}):
        target = summary["metrics"] if key in MAIN else summary["variants"]
        target[key] = stats([s[key] for s in samples if key in s])
    if coverages:
        summary["coverage"] = {"classes": coverages[0]["classes"],
                               "assigned_mean": statistics.mean(c["assigned"] for c in coverages),
                               "unassigned_mean": statistics.mean(c["unassigned"] for c in coverages),
                               "unmatched_ids_mean": statistics.mean(c["unmatched_ids"] for c in coverages)}

    source = first_unit or first_error
    if source:
        for name in ["output.json", "metrics_summary.json"] + [f"{m}_score.json" for m in FIELDS]:
            if os.path.exists(os.path.join(source, name)):
                shutil.copy(os.path.join(source, name), os.path.join(out_dir, name))
    with open(os.path.join(out_dir, "metrics_mean.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tool", required=True, help="Tool directory name under tools/ (e.g. chgnn)")
    parser.add_argument("--dataset", required=True, help="Dataset directory name under datasets/ (e.g. jpetstore)")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--tool-args", default="", help="Extra arguments passed to tool.py, as one quoted string")
    args = parser.parse_args(argv)

    import shlex

    tool_dir = os.path.join(ROOT, "tools", args.tool)
    dataset_dir = os.path.join(ROOT, "datasets", args.dataset)
    summary = sweep(tool_dir, dataset_dir, os.path.join(tool_dir, "outputs", args.dataset), args.runs,
                    extra_args=shlex.split(args.tool_args))
    line = ", ".join(f"{k} {v['mean']:.4f}" for k, v in summary["metrics"].items()) or "N/A"
    print(f"{args.tool} x {args.dataset}: {summary['runs_ok']}/{args.runs} runs ok ({len(summary['failures'])} failed) | {line}")
    return 0 if summary["runs_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
