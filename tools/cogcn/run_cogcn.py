"""Run upstream train.py unchanged, then dump the k-means membership it pickles as JSON (the host has no numpy).

Usage (cwd = a copy of the cogcn/ package dir): python run_cogcn.py --dataset-str <dir> --k <k> [train.py options]
"""
import json
import os
import pickle
import runpy
import sys

args = sys.argv[1:]
dataset = args[args.index("--dataset-str") + 1]
sys.argv = ["train.py"] + args
runpy.run_path("train.py", run_name="__main__")
with open(os.path.join(dataset, "embeddings_membership.pkl"), "rb") as f:
    membership = pickle.load(f)
with open(os.path.join(dataset, "membership.json"), "w") as f:
    json.dump([int(x) for x in membership], f)
