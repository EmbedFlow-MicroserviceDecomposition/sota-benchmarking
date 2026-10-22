# CoGCN (Desai et al., AAAI 2021) was written for torch 1.5 / networkx 2.4 (nx.from_numpy_matrix); torch 1.8 CPU with
# networkx 2.5 runs it unchanged. amd64 because the CPU wheels pinned here have no arm64 builds (emulated on Apple silicon).
FROM --platform=linux/amd64 python:3.8-slim

RUN pip install --no-cache-dir torch==1.8.0+cpu -f https://download.pytorch.org/whl/torch_stable.html

RUN pip install --no-cache-dir numpy==1.20.3 scipy==1.7.1 scikit-learn==0.24.2 pandas==1.3.3 \
    networkx==2.5 matplotlib==3.3.4 pillow==9.5.0

# a repo copy is mounted at /workspace/cogcn by tool.py
WORKDIR /workspace/cogcn
