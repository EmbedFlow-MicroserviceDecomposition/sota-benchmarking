"""Run fosci-wrap's NSGA-II search (unmodified, imported as a module) plus the paper's knee-point selection.

fosci-wrap's own __main__ dumps the whole final Pareto front; Jin et al. TSE 2019 section 2.4.3 picks one solution with a
knee point, which is done here. Writes {cluster_id: [class FQN, ...]} to --out. Run as a subprocess: fosci-wrap keeps its state
in module globals.
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fosci-wrap"))
import main as fosci_main  # noqa: E402
import msconfig  # noqa: E402


def run(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--atoms", required=True)
    p.add_argument("--calldep", required=True)
    p.add_argument("--concerndep", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--k", type=int, required=True, help="target number of service candidates (PARTITION_K)")
    p.add_argument("--seed", type=int, required=True)
    args = p.parse_args(argv)

    random.seed(args.seed)
    msconfig.GLOBAL_VAR_OBJECT.PARTITION_K = args.k
    fosci_main.prepare(args.atoms, args.calldep, args.concerndep)
    best, best_fit = fosci_main.getKneePoint(fosci_main.nsga_process())

    clusters = {}
    for _, candidate_id, classname in fosci_main.getPartionResult(fosci_main.toSet(best)):
        clusters.setdefault(str(candidate_id), []).append(classname)
    with open(args.out, "w") as f:
        json.dump(clusters, f, indent=1)
    print("clusters=%d classes=%d fitness=%s" % (len(clusters), sum(len(v) for v in clusters.values()), best_fit))


if __name__ == "__main__":
    run()
