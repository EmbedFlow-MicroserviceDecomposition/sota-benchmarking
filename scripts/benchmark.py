# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Central CLI of the benchmark: run every tool x dataset cell, then print result tables.

    uv run scripts/benchmark.py run                      # all six tools x all datasets, the paper run counts
    uv run scripts/benchmark.py run --tools chgnn,fosci --datasets jpetstore,bear-board --profile quick
    uv run scripts/benchmark.py run --dry-run            # show the plan, run nothing
    uv run scripts/benchmark.py report                   # one table per metric (datasets x tools) from what is on disk
    uv run scripts/benchmark.py report --metrics SM,NED --format markdown --coverage

`run` builds a missing dataset.json, then calls scripts/run_sweep.py for every cell that has no metrics_mean.json yet (finished
cells are skipped; --force redoes them). Cells run one after another: CARGO shares one Neo4j and the Docker tools are CPU-bound.
`report` only reads files, so it can be run at any time, including while a `run` is in progress.
"""

import argparse
import csv
import io
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_sweep  # noqa: E402

TOOLS = ["chgnn", "cogcn", "ae-k", "vae-c", "fosci", "cargo"]            # the tools `run` drives
REPORT_TOOLS = TOOLS + ["triplet-guided-chgnn", "magnet", "mono2micro"]   # `report` also reads these when they have outputs
# run counts of the migration sweep (fyp-benchmarking's protocol): unseeded tools are averaged, CARGO runs its own 30-entry grid
RUNS = {"chgnn": 10, "cogcn": 5, "ae-k": 3, "vae-c": 3, "fosci": 5, "cargo": 1}
RUNS_OVERRIDE = {("vae-c", "bear-board"): 5, ("vae-c", "pharmacy"): 5, ("vae-c", "autocare"): 5,   # the thesis averages 5 attempts
                 ("fosci", "apache-roller"): 1}                                                    # ~1-2 h per run
QUICK_ARGS = {"cargo": "--k 7 --seeds 42"}                                # one CARGO grid entry instead of K x seed = 30
METRICS = ["SM", "ICP", "IFN", "NED", "BCP", "CHM", "CHD"]
HIGHER_IS_BETTER = {"SM": True, "ICP": False, "IFN": False, "NED": True, "BCP": False, "CHM": True, "CHD": True,
                    "SM_undirected": True, "IFN_cross_edge": False, "NED_relative": True, "NED_triplebound": False}


@dataclass
class Cell:
    tool: str
    dataset: str
    runs: int
    args: str
    done: bool


# ------------------------------------------------------------------ planning

def runs_for(tool, dataset, profile):
    if profile == "quick":
        return 1
    return RUNS_OVERRIDE.get((tool, dataset), RUNS[tool])


def tool_args(tool, profile):
    return QUICK_ARGS.get(tool, "") if profile == "quick" else ""


def list_datasets(root):
    base = os.path.join(root, "datasets")
    return sorted(d for d in os.listdir(base) if os.path.exists(os.path.join(base, d, "dataset.py")))


def cell_dir(root, tool, dataset):
    return os.path.join(root, "tools", tool, "outputs", dataset)


def make_plan(root, tools, datasets, profile, force):
    for tool in tools:
        if tool not in TOOLS:
            raise ValueError(f"unknown tool '{tool}' (choose from {', '.join(TOOLS)})")
    known = list_datasets(root)
    for ds in datasets:
        if ds not in known:
            raise ValueError(f"unknown dataset '{ds}' (choose from {', '.join(known)})")
    return [Cell(tool, ds, runs_for(tool, ds, profile), tool_args(tool, profile),
                 not force and os.path.exists(os.path.join(cell_dir(root, tool, ds), "metrics_mean.json")))
            for tool in tools for ds in sorted(datasets)]


def build_dataset_json(dataset_dir):
    subprocess.run(["uv", "run", "dataset.py"], cwd=dataset_dir, check=True)


def is_na(summary):
    """Every failure message of a deliberate N/A cell says so ('... cell is N/A'); a real failure does not."""
    failures = summary.get("failures") or []
    return bool(failures) and all("N/A" in f.get("error", "") for f in failures)


def cmd_run(args, root, sweep_fn, build_fn):
    tools = args.tools.split(",") if args.tools else TOOLS
    datasets = args.datasets.split(",") if args.datasets else list_datasets(root)
    try:
        plan = make_plan(root, tools, datasets, args.profile, args.force)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    todo = [c for c in plan if not c.done]
    print(f"{len(plan)} cells: {len(todo)} to run, {len(plan) - len(todo)} already done "
          f"(profile {args.profile}{', --force' if args.force else ''})")
    if args.dry_run:
        for i, c in enumerate(plan, 1):
            print(f"  [{i}/{len(plan)}] {'skip' if c.done else 'run '}  {c.tool} x {c.dataset} ({c.runs} runs"
                  f"{', ' + c.args if c.args else ''})")
        return 0

    ok = na = failed = 0
    for i, c in enumerate(plan, 1):
        label = f"[{i}/{len(plan)}] {c.tool} x {c.dataset}"
        if c.done:
            print(f"{label}: skip (already has results; --force to redo)")
            continue
        ds_dir = os.path.join(root, "datasets", c.dataset)
        if not os.path.exists(os.path.join(ds_dir, "dataset.json")):
            print(f"{label}: building dataset.json for {c.dataset}")
            build_fn(ds_dir)
        print(f"{label}: running {c.runs} run(s) ...", flush=True)
        summary = sweep_fn(os.path.join(root, "tools", c.tool), ds_dir, cell_dir(root, c.tool, c.dataset), c.runs,
                           extra_args=shlex.split(c.args))
        if summary["runs_ok"] == 0 and is_na(summary):
            na += 1
            print(f"    -> N/A: {summary['failures'][0]['error'][:100]}")
        elif summary["runs_ok"] == 0:
            failed += 1
            print(f"    -> FAILED: {(summary['failures'] or [{'error': 'no output'}])[0]['error'][:100]}")
        else:
            ok += 1
            line = ", ".join(f"{k} {v['mean']:.3f}" for k, v in summary["metrics"].items())
            print(f"    -> {summary['runs_ok']}/{summary['runs_requested']} runs ok | {line}")
    print(f"\ndone: {ok} ok, {na} N/A, {failed} failed, {len(plan) - len(todo)} skipped. Run `report` for the tables.")
    return 1 if failed else 0


# ------------------------------------------------------------------ reading

def load_summary(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def legacy_cell(out):
    """A cell written before run_sweep existed: output.json plus plain *_score.json files, one run."""
    metrics, coverage = {}, None
    for name, fields in run_sweep.FIELDS.items():
        path = os.path.join(out, f"{name}_score.json")
        if not os.path.exists(path):
            continue
        data = load_summary(path)
        for field, key in fields.items():
            if field in data:
                metrics[key] = {"mean": data[field], "std": 0.0, "n": 1}
        if data.get("coverage") and coverage is None:
            c = data["coverage"]
            coverage = {"classes": c["classes"], "assigned_mean": c["assigned"]}
    if metrics:
        return {"runs_ok": 1, "runs_requested": 1, "failures": [], "metrics": metrics, "coverage": coverage}
    output = os.path.join(out, "output.json")
    if os.path.exists(output):
        data = load_summary(output)
        if "error" in data:
            return {"runs_ok": 0, "runs_requested": 1, "failures": [{"run": 1, "error": data["error"]}], "metrics": {}}
    return None


def collect(root, tools, datasets):
    cells = {}
    for tool in tools:
        for ds in datasets:
            out = cell_dir(root, tool, ds)
            mean = os.path.join(out, "metrics_mean.json")
            if os.path.exists(mean):
                cell = load_summary(mean)
                cell["metrics"] = {**cell.get("variants", {}), **cell.get("metrics", {})}
            elif os.path.isdir(out):
                cell = legacy_cell(out)
            else:
                cell = None
            if cell is not None:
                cells[(tool, ds)] = cell
    return cells


# ------------------------------------------------------------------ rendering

def status(cell):
    if cell["runs_ok"]:
        return "ok"
    return "N/A" if (is_na(cell) or not cell.get("failures")) else "FAIL"


def cell_text(cell, metric, with_std):
    if cell is None:
        return "-"
    if cell["runs_ok"] == 0:
        return status(cell)
    m = cell["metrics"].get(metric)
    if m is None:
        return "-"
    digits = 2 if metric.startswith("IFN") else 3
    text = f"{m['mean']:.{digits}f}"
    return f"{text}+-{m['std']:.{digits}f}" if with_std and m.get("n", 1) > 1 else text


def coverage_text(cell):
    if cell is None:
        return "-"
    if cell["runs_ok"] == 0:
        return status(cell)
    c = cell.get("coverage")
    return f"{c['assigned_mean']:.0f}/{c['classes']}" if c else "-"


def table(title, header, rows, fmt):
    if fmt == "markdown":
        lines = [f"**{title}**", "", "| " + " | ".join(header) + " |", "| " + " | ".join([":--"] + ["--:"] * (len(header) - 1)) + " |"]
        lines += ["| " + " | ".join(r) + " |" for r in rows]
        return "\n".join(lines)
    widths = [max(len(r[i]) for r in [header] + rows) for i in range(len(header))]
    def fmt_row(r):
        return "  ".join(r[0].ljust(widths[0]) if i == 0 else r[i].rjust(widths[i]) for i in range(len(r)))
    return "\n".join([title, fmt_row(header), "  ".join("-" * w for w in widths)] + [fmt_row(r) for r in rows])


def render(cells, tools, datasets, metrics, fmt, with_std, coverage):
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["tool", "dataset", "metric", "mean", "std", "n", "runs_ok", "status"])
        for tool in tools:
            for ds in datasets:
                cell = cells.get((tool, ds))
                if cell is None:
                    continue
                for metric in metrics:
                    m = cell["metrics"].get(metric) if cell["runs_ok"] else None
                    w.writerow([tool, ds, metric, f"{m['mean']:.4f}" if m else "", f"{m['std']:.4f}" if m else "",
                                m["n"] if m else "", cell["runs_ok"], status(cell)])
        return out.getvalue()

    blocks = []
    for metric in metrics:
        arrow = "higher is better" if HIGHER_IS_BETTER.get(metric, True) else "lower is better"
        rows = [[ds] + [cell_text(cells.get((t, ds)), metric, with_std) for t in tools] for ds in datasets]
        blocks.append(table(f"{metric} ({arrow})", ["dataset"] + list(tools), rows, fmt))
    if coverage:
        rows = [[ds] + [coverage_text(cells.get((t, ds))) for t in tools] for ds in datasets]
        blocks.append(table("classes assigned / classes in dataset.json (mean over runs)", ["dataset"] + list(tools), rows, fmt))
    legend = "-  no result    N/A  not applicable for this tool (error-form output)    FAIL  every run failed"
    if with_std:
        legend += "    a+-b  mean and standard deviation over the runs"
    return "\n\n".join(blocks) + "\n\n" + legend + "\n"


def cmd_report(args, root):
    tools = args.tools.split(",") if args.tools else [t for t in REPORT_TOOLS if os.path.isdir(os.path.join(root, "tools", t, "outputs"))]
    datasets = args.datasets.split(",") if args.datasets else list_datasets(root)
    cells = collect(root, tools, datasets)
    if not cells:
        print(f"no results found for tools {', '.join(tools) or '(none)'} under tools/<tool>/outputs/")
        return 1
    datasets = [d for d in datasets if any((t, d) in cells for t in tools)]
    metrics = args.metrics.split(",") if args.metrics else METRICS
    print(render(cells, tools, datasets, metrics, args.format, not args.no_std, args.coverage), end="")
    return 0


def main(argv=None, root=ROOT, sweep_fn=None, build_fn=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the missing tool x dataset cells")
    run.add_argument("--tools", help=f"comma-separated, default all of: {', '.join(TOOLS)}")
    run.add_argument("--datasets", help="comma-separated, default every dataset directory")
    run.add_argument("--profile", choices=["paper", "quick"], default="paper",
                     help="paper: the migration sweep's run counts; quick: one run per cell (one CARGO grid entry)")
    run.add_argument("--force", action="store_true", help="redo cells that already have results")
    run.add_argument("--dry-run", action="store_true", help="print the plan and exit")

    rep = sub.add_parser("report", help="print result tables from the results on disk")
    rep.add_argument("--tools", help="comma-separated, default every tool that has outputs")
    rep.add_argument("--datasets", help="comma-separated, default every dataset with a result")
    rep.add_argument("--metrics", help=f"comma-separated, default {','.join(METRICS)} (variants such as SM_undirected also work)")
    rep.add_argument("--format", choices=["text", "markdown", "csv"], default="text")
    rep.add_argument("--no-std", action="store_true", help="show means only")
    rep.add_argument("--coverage", action="store_true", help="add a table of assigned classes per cell")

    args = parser.parse_args(argv)
    if args.command == "run":
        return cmd_run(args, root, sweep_fn or run_sweep.sweep, build_fn or build_dataset_json)
    return cmd_report(args, root)


if __name__ == "__main__":
    sys.exit(main())
