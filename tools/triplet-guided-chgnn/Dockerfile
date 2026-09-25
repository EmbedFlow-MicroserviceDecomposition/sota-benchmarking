FROM python:3.8-slim

WORKDIR /workspace

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    graphviz \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch 1.8.0 CPU build
RUN pip install --no-cache-dir \
    torch==1.8.0+cpu \
    torchvision==0.9.0+cpu \
    -f https://download.pytorch.org/whl/torch_stable.html

# Install PyTorch Geometric and C++ extensions for CPU torch 1.8.0
RUN pip install --no-cache-dir \
    torch-scatter==2.0.8 \
    torch-sparse==0.6.12 \
    torch-cluster==1.5.9 \
    torch-spline-conv==1.2.1 \
    -f https://data.pyg.org/whl/torch-1.8.0+cpu.html

# Install PyG and data science dependencies
RUN pip install --no-cache-dir \
    torch-geometric==2.0.1 \
    scikit-learn==0.24.2 \
    scipy==1.7.1 \
    numpy==1.20.3 \
    pandas==1.3.3 \
    networkx==2.5 \
    python-louvain==0.15 \
    tqdm==4.62.3 \
    pyyaml==5.4.1 \
    yacs==0.1.6 \
    requests==2.25.1

WORKDIR /workspace/tools/triplet-guided-chgnn/triplet-guided-chgnn
CMD ["python3", "examples/train_with_triplets.py", "--help"]
