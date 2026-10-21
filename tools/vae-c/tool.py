# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "numpy==2.4.4",
#     "scipy==1.18.0",
#     "scikit-learn==1.9.0",
#     "scikit-fuzzy==0.5.0",
#     "tensorflow==2.21.0",
# ]
# ///

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_common"))
import vaec_core  # noqa: E402
import vaec_tool  # noqa: E402

# the thesis (Table 2.1) fixes k=5 on its own three apps; everywhere else k comes from the SSE elbow
PAPER_K = {"bear-board": 5, "pharmacy": 5, "autocare": 5}


def run(adj, entrypoints, seed, max_paths, n_epochs, k, info):
    return vaec_core.run_vae_c(adj, entrypoints, seed, k=k, max_paths=max_paths, n_epochs=n_epochs, info=info)


if __name__ == "__main__":
    sys.exit(vaec_tool.main("VAE-C", run, paper_k=PAPER_K,
                            description="Tool: VAE-C (variational autoencoder + fuzzy c-means)"))
