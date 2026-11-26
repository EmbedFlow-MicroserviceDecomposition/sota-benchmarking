# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "numpy==2.4.4",
#     "scikit-learn==1.9.0",
#     "pandas",
# ]
# ///

import argparse
import functools
import importlib
import json
import os
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hydec_adapter import build_hydec_inputs  # noqa: E402

TOOL = "HyDec"
REPO = os.path.join(HERE, "decomp-hydec")
STOCK_APPROACH = "hierDec"
STOCK_EPSILON = 0.65
STOCK_MIN_SAMPLES = 2
STOCK_STRATEGY = "alternating_epsilon"


class TraceError(Exception):
    pass


def write_error(output_path, message):
    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"error": message, "tool": TOOL}, f, indent=4)
    print(f"Error written to {output_path}/output.json: {message}", file=sys.stderr)
    return 1


def patch_onehotencoder():
    """Map deprecated OneHotEncoder(sparse=...) keyword used by unmodified decomp-hydec to sparse_output."""
    from sklearn.preprocessing import OneHotEncoder

    if getattr(OneHotEncoder.__init__, "_hydec_sparse_patched", False):
        return
    orig_init = OneHotEncoder.__init__

    @functools.wraps(orig_init)
    def patched_init(self, *args, **kwargs):
        if "sparse" in kwargs:
            sparse_val = kwargs.pop("sparse")
            kwargs.setdefault("sparse_output", sparse_val)
        return orig_init(self, *args, **kwargs)

    patched_init._hydec_sparse_patched = True
    OneHotEncoder.__init__ = patched_init


class _StubParsingClient:
    """Stand-in when grpcio/protobuf are not installed; local matrix paths never invoke RPC calls."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        raise RuntimeError(f"ParsingClient.{name} requires grpcio/decparsing, which is not available in local mode")


def _clear_hydec_modules():
    for mod in [k for k in sys.modules if k == "hydec" or k.startswith("hydec.")]:
        sys.modules.pop(mod, None)


def _loaded_from_repo(repo_dir):
    mod = sys.modules.get("hydec")
    if mod is None:
        return False
    expected = os.path.abspath(os.path.join(repo_dir, "hydec"))
    paths = list(getattr(mod, "__path__", []) or [])
    if not paths and getattr(mod, "__file__", None):
        paths = [os.path.dirname(mod.__file__)]
    return any(os.path.abspath(p) == expected for p in paths)


def _install_grpc_stubs(repo_dir):
    for pkg in ("hydec", "hydec.clients", "hydec.models", "hydec.utils"):
        mod = types.ModuleType(pkg)
        mod.__path__ = [os.path.join(repo_dir, *pkg.split("."))]
        mod.__package__ = pkg
        sys.modules[pkg] = mod
    for mod_name in ("hydec.clients.parsingClient", "hydec.clients.decParsingClient"):
        mod = types.ModuleType(mod_name)
        mod.ParsingClient = _StubParsingClient
        mod.DecParsingClient = _StubParsingClient
        sys.modules[mod_name] = mod


def load_hydec(repo_dir=None):
    """Apply runtime compatibility shims and import hydec.hydec.generate_decomposition from `repo_dir`."""
    repo_dir = os.path.abspath(repo_dir or REPO)
    patch_onehotencoder()
    if not _loaded_from_repo(repo_dir):
        _clear_hydec_modules()
    if repo_dir not in sys.path:
        sys.path.insert(0, repo_dir)

    prev_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        try:
            mod = importlib.import_module("hydec.hydec")
        except (ModuleNotFoundError, ImportError, TypeError) as exc:
            # Unmodified decomp-hydec imports grpc + protoc-3 generated stubs in dataHandler even when given local matrices.
            missing = getattr(exc, "name", "") or ""
            if isinstance(exc, ModuleNotFoundError) and missing not in ("grpc", "google", "google.protobuf"):
                raise
            _clear_hydec_modules()
            _install_grpc_stubs(repo_dir)
            mod = importlib.import_module("hydec.hydec")
        return mod.generate_decomposition
    finally:
        sys.dont_write_bytecode = prev_dont_write


def find_trace(name, dataset_path):
    """Locate datasets/<name>/fosci_trace.csv.gz for dynamic HyDec mode."""
    trace = os.path.join(dataset_path, "fosci_trace.csv.gz")
    if os.path.exists(trace):
        return trace
    # Retriable input error (no "N/A"): benchmark.py retries cells missing optional dynamic traces.
    raise TraceError(
        f"no execution trace for dataset '{name}': --approach hyDec requires datasets/{name}/fosci_trace.csv.gz"
    )


def select_layer(layers):
    """Pick layers[-1], or fall back to the last earlier layer with >= 2 clusters if layers[-1] collapsed to 1."""
    if not layers:
        return [], 0, False
    last_idx = len(layers) - 1
    last = [int(x) for x in layers[last_idx]]
    if len(set(last)) >= 2:
        return last, last_idx, False
    for idx in range(len(layers) - 2, -1, -1):
        cand = [int(x) for x in layers[idx]]
        if len(set(cand)) >= 2:
            return cand, idx, True
    return last, last_idx, False


def clusters_to_microservices(atoms, labels):
    """Convert cluster labels to {"microservice_N": sorted classes}; any -1 outliers become singletons."""
    groups = {}
    outliers = []
    for cls, raw_label in zip(atoms, labels):
        cid = int(raw_label)
        if cid < 0:
            outliers.append(cls)
        else:
            groups.setdefault(cid, []).append(cls)
    microservices = {
        f"microservice_{i}": sorted(groups[cid])
        for i, cid in enumerate(sorted(groups), 1)
    }
    for cls in sorted(outliers):
        microservices[f"microservice_{len(microservices) + 1}"] = [cls]
    return microservices, len(outliers)


def _forward_uv(args):
    cmd = [
        "uv", "run", "--script", os.path.abspath(__file__),
        "--dataset-path", args.dataset_path,
        "--output-path", args.output_path,
        "--approach", args.approach,
        "--epsilon", str(args.epsilon),
        "--min-samples", str(args.min_samples),
        "--strategy", args.strategy,
        "--runner", "local",
    ]
    return subprocess.run(cmd).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tool: HierDec / HyDec (Sellami et al., SANER/ICSOC 2022)")
    parser.add_argument("--dataset-path", required=True, help="Dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", required=True, help="Directory for output.json and raw files")
    parser.add_argument("--approach", choices=["hierDec", "hyDec"], default=STOCK_APPROACH,
                        help=f"Decomposition approach (default: {STOCK_APPROACH})")
    parser.add_argument("--epsilon", type=float, default=STOCK_EPSILON,
                        help=f"DBSCAN epsilon / max epsilon (default: {STOCK_EPSILON})")
    parser.add_argument("--min-samples", type=int, default=STOCK_MIN_SAMPLES,
                        help=f"DBSCAN min_samples (default: {STOCK_MIN_SAMPLES})")
    parser.add_argument("--strategy", choices=["alternating", "alternating_epsilon", "sequential"],
                        default=STOCK_STRATEGY, help=f"Clustering combination strategy (default: {STOCK_STRATEGY})")
    parser.add_argument("--runner", choices=["local", "uv"], default="local",
                        help="Execution mode: local (default, in-process) or uv (re-exec via uv run --script)")
    args = parser.parse_args(argv)

    if args.runner == "uv":
        return _forward_uv(args)

    ds_path = os.path.abspath(args.dataset_path)
    out_path = os.path.abspath(args.output_path)
    name = os.path.basename(ds_path.rstrip("/")) or "app"

    dataset_json = os.path.join(ds_path, "dataset.json")
    if not os.path.exists(dataset_json):
        return write_error(out_path, f"dataset.json not found in {ds_path}")
    with open(dataset_json, encoding="utf-8") as f:
        dataset = json.load(f)
    if not dataset.get("classes") and not dataset.get("methods"):
        return write_error(out_path, f"dataset '{name}' has no Java classes in dataset.json: cell is N/A")
    if not os.path.isfile(os.path.join(REPO, "hydec", "hydec.py")):
        return write_error(out_path, "HyDec submodule is empty: run `git submodule update --init`")
    if args.epsilon <= 0 or args.epsilon > 1.0:
        return write_error(out_path, f"--epsilon must be in (0, 1.0], got {args.epsilon}")
    if args.min_samples < 1:
        return write_error(out_path, f"--min-samples must be >= 1, got {args.min_samples}")

    trace_path = None
    if args.approach == "hyDec":
        try:
            trace_path = find_trace(name, ds_path)
        except TraceError as exc:
            return write_error(out_path, str(exc))

    os.makedirs(out_path, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out_path, prefix="work-") as work:
        try:
            adapter_info = build_hydec_inputs(
                dataset, ds_path, work, approach=args.approach, trace_path=trace_path
            )
        except (ValueError, FileNotFoundError) as exc:
            return write_error(out_path, str(exc))

        hyperparams = {
            "clustering": {
                "strategy": args.strategy,
                "min_samples": args.min_samples,
            },
            "structural": {"epsilon": args.epsilon},
            "semantic": {"epsilon": args.epsilon},
            "dynamic": {"epsilon": args.epsilon},
            "sum": {"epsilon": args.epsilon},
        }

        try:
            generate_decomposition = load_hydec(REPO)
            _, layers, atoms, metadata = generate_decomposition(
                app=name,
                decomp_approach=args.approach,
                hyperparams_path=hyperparams,
                structural_path=os.path.join(work, "structural"),
                semantic_path=os.path.join(work, "semantic"),
                dynamic_path=os.path.join(work, "dynamic") if args.approach == "hyDec" else None,
                include_metadata=True,
                save_output=False,
                granularity="class",
                use_parsing_module=False,
                data_path=work,
            )
        except Exception as exc:
            return write_error(out_path, f"HyDec run failed: {exc}")

    selected_labels, selected_idx, collapsed_fallback = select_layer(layers)
    microservices, outlier_count = clusters_to_microservices(atoms, selected_labels)
    if not microservices:
        return write_error(out_path, "HyDec produced no clusters with classes")

    with open(os.path.join(out_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": TOOL, "microservices": microservices}, f, indent=4)

    raw_layers = {
        "atoms": list(atoms),
        "layers": [[int(x) for x in layer] for layer in layers],
        "selected_layer": selected_idx,
    }
    with open(os.path.join(out_path, "layers.json"), "w", encoding="utf-8") as f:
        json.dump(raw_layers, f, indent=4)

    run_info = {
        **adapter_info,
        "approach": args.approach,
        "epsilon": args.epsilon,
        "min_samples": args.min_samples,
        "strategy": args.strategy,
        "selected_layer": selected_idx,
        "total_layers": len(layers),
        "collapsed_fallback": collapsed_fallback,
        "outliers": outlier_count,
        "outlier_policy": "singleton",
        "n_microservices": len(microservices),
        "exec_time": (metadata or {}).get("exec_time", {}),
    }
    with open(os.path.join(out_path, "run_info.json"), "w", encoding="utf-8") as f:
        json.dump(run_info, f, indent=4)

    print(
        f"HyDec ({args.approach}): {len(microservices)} microservices "
        f"(layer {selected_idx + 1}/{len(layers)}) -> {out_path}/output.json"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
