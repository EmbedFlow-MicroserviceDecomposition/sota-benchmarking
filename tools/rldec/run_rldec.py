# /// script
# requires-python = ">=3.10,<3.11"
# dependencies = [
#     "ray[rllib]==2.9.2",
#     "torch>=2.1.0,<2.6",
#     "gymnasium>=0.28.1",
#     "numpy>=1.26.4,<2.0",
#     "pandas<=2.2.0,>=1.5.3",
#     "pyarrow>=14.0.0,<19.0.0",
#     "scikit-learn>=1.2.2,<1.4.0",
#     "scipy>=1.11.4,<1.14.0",
#     "networkx>=2.8.4",
#     "protobuf>=4.25.2,<5.26.0",
#     "grpcio>=1.48.2",
#     "dm-tree>=0.1.8",
#     "lz4>=4.3.2",
#     "tifffile>=2024.1.30",
#     "setuptools<70",
# ]
# ///
"""Run unmodified upstream RLDec (train_model + generate_decomposition) inside a repo copy.

Usage (cwd = a copy of tools/rldec/decomp-rldec):
    python run_rldec.py --app <name> --data-dir data --models-dir trained_models --out-dir out
"""

import argparse
import inspect
import json
import logging
import os
import re
import sys
import time

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)


def _ensure_writable_home():
    home = os.path.expanduser("~")
    if not os.path.isdir(home) or not os.access(home, os.W_OK):
        fallback = os.path.join(REPO_DIR, ".home")
        os.makedirs(fallback, exist_ok=True)
        os.environ["HOME"] = fallback


def _apply_compat_shims():
    import numpy as np
    from sklearn.preprocessing import OneHotEncoder

    for attr, replacement in (("int", int), ("float", float), ("bool", bool), ("object", object)):
        if attr not in np.__dict__:
            setattr(np, attr, replacement)

    if "sparse" not in inspect.signature(OneHotEncoder.__init__).parameters:
        orig_init = OneHotEncoder.__init__

        def compat_init(self, *args, sparse=None, **kwargs):
            if sparse is not None and "sparse_output" not in kwargs:
                kwargs["sparse_output"] = sparse
            return orig_init(self, *args, **kwargs)

        OneHotEncoder.__init__ = compat_init


def partitions_to_microservices(raw):
    """Convert RLDec's {'partition_<id>': [classes]} into {'microservice_N': sorted classes}."""
    clusters = raw.get("microservices", raw) if isinstance(raw, dict) else {}
    entries = []
    outliers = 0
    for key, members in clusters.items():
        if not members:
            continue
        match = re.fullmatch(r"partition_(-?\d+(?:\.\d+)?)", str(key))
        if match:
            num = float(match.group(1))
            if int(num) == -1:
                outliers += len(members)
                continue
            sort_key = (0, num, str(key))
        else:
            sort_key = (1, 0.0, str(key))
        entries.append((sort_key, sorted(str(m) for m in members)))
    entries.sort(key=lambda item: item[0])
    microservices = {f"microservice_{i}": members for i, (_, members) in enumerate(entries, 1)}
    return microservices, outliers


def _infer_n_classes(data_dir, app):
    import pandas as pd

    names_path = os.path.join(data_dir, app, "class_names.json")
    if os.path.isfile(names_path):
        with open(names_path, encoding="utf-8") as f:
            return len(json.load(f))
    inter_path = os.path.join(data_dir, app, "class_interactions.parquet")
    return len(pd.read_parquet(inter_path).index)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Execute unmodified RLDec training and decomposition")
    parser.add_argument("--app", required=True)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--models-dir", default="trained_models")
    parser.add_argument("--out-dir", default="out")
    parser.add_argument("--approach", default="combsequential", choices=["combsequential", "sequential", "flattened"])
    parser.add_argument("--feature", default="structural", choices=["structural", "semantic"])
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--strategy", default="last", choices=["last", "best"])
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--n-classes", type=int, default=None)
    args = parser.parse_args(argv)

    _ensure_writable_home()
    _apply_compat_shims()

    import ray
    import torch

    from rldec.decompose import generate_decomposition
    from rldec.train_model import train_model

    n_classes = args.n_classes if args.n_classes is not None else _infer_n_classes(args.data_dir, args.app)
    gpu_available = bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    num_gpus = 1 if gpu_available else 0

    custom_config = {"num_gpus": num_gpus}
    if args.approach in ("combsequential", "sequential"):
        custom_config["env_config"] = {"max_microservices": min(20, max(2, n_classes))}
    if args.seed is not None:
        custom_config["seed"] = args.seed

    os.makedirs(args.out_dir, exist_ok=True)
    config_path = os.path.join(args.out_dir, "rldec_run_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(custom_config, f, indent=2)

    model_name = f"rldec_{args.approach}"
    ray.init(
        ignore_reinit_error=True,
        include_dashboard=False,
        num_gpus=num_gpus,
        logging_level=logging.WARNING,
    )
    try:
        t0 = time.monotonic()
        train_model(
            app_name=args.app,
            rldec_approach=args.approach,
            features_name=args.feature,
            n_iterations=args.iterations,
            config_path=config_path,
            data_path=args.data_dir,
            output_path=args.models_dir,
            model_name=model_name,
            eval_model=False,
            data_format="parquet",
        )
        train_seconds = round(time.monotonic() - t0, 3)

        t1 = time.monotonic()
        orig_cwd = os.getcwd()
        try:
            raw_decomp = generate_decomposition(
                app_name=args.app,
                models_path=args.models_dir,
                model_name=model_name,
                verbose=False,
                output_path=args.out_dir,
                num_episodes=args.episodes,
                select_strategy=args.strategy,
            )
        finally:
            os.chdir(orig_cwd)
        decompose_seconds = round(time.monotonic() - t1, 3)
    finally:
        ray.shutdown()

    microservices, outliers_dropped = partitions_to_microservices(raw_decomp)
    if not microservices:
        raise RuntimeError("RLDec produced no non-outlier microservice partitions")

    with open(os.path.join(args.out_dir, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": "RLDec", "microservices": microservices}, f, indent=4)

    meta = {
        "gpu_available": gpu_available,
        "gpu_name": torch.cuda.get_device_name(0) if gpu_available else None,
        "num_gpus": num_gpus,
        "max_microservices": custom_config.get("env_config", {}).get("max_microservices"),
        "train_seconds": train_seconds,
        "decompose_seconds": decompose_seconds,
        "raw_partitions": len(raw_decomp),
        "outliers_dropped": outliers_dropped,
    }
    with open(os.path.join(args.out_dir, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4)


if __name__ == "__main__":
    main()
