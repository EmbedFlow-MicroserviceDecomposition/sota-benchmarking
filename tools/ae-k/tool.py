# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "numpy==2.4.4",
#     "scipy==1.18.0",
#     "scikit-learn==1.9.0",
#     "tensorflow==2.21.0",
# ]
# ///

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_common"))
import vaec_core  # noqa: E402
import vaec_tool  # noqa: E402


def run(adj, entrypoints, seed, max_paths, n_epochs, k, info):
    # AE-K sweeps k itself (SSE elbow); the thesis publishes no fixed-k default for it, so `k` is unused
    return vaec_core.run_ae_k(adj, entrypoints, seed, max_paths=max_paths, n_epochs=n_epochs, info=info)


if __name__ == "__main__":
    sys.exit(vaec_tool.main("AE-K", run, description="Tool: AE-K baseline (autoencoder + KMeans)"))
