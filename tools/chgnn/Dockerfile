# CHGNN (Mathai et al., IJCAI 2022): CPU torch 1.8 + PyG 2.0.1. torch_scatter/sparse/cluster have no arm64 CPU wheels,
# so the image is amd64 (emulated on Apple silicon).
FROM --platform=linux/amd64 python:3.8-slim

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir torch==1.8.0+cpu -f https://download.pytorch.org/whl/torch_stable.html

RUN pip install --no-cache-dir \
    torch-scatter==2.0.8 torch-sparse==0.6.12 torch-cluster==1.5.9 torch-spline-conv==1.2.1 \
    -f https://data.pyg.org/whl/torch-1.8.0+cpu.html

RUN pip install --no-cache-dir \
    torch-geometric==2.0.1 scikit-learn==0.24.2 scipy==1.7.1 numpy==1.20.3 pandas==1.3.3 \
    networkx==2.5 tensorboard==2.5.0 protobuf==3.20.3 tqdm==4.62.3 pyyaml==5.4.1 requests==2.25.1

# the repo copy is mounted at /workspace/chgnn by tool.py
WORKDIR /workspace/chgnn
