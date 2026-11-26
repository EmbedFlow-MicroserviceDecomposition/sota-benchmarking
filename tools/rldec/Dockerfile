FROM --platform=linux/amd64 python:3.10-slim

RUN pip install --no-cache-dir \
    "ray[rllib]==2.9.2" \
    "torch>=2.1.0,<2.6" \
    "gymnasium>=0.28.1" \
    "numpy>=1.26.4,<2.0" \
    "pandas<=2.2.0,>=1.5.3" \
    "pyarrow>=14.0.0,<19.0.0" \
    "scikit-learn>=1.2.2,<1.4.0" \
    "scipy>=1.11.4,<1.14.0" \
    "networkx>=2.8.4" \
    "protobuf>=4.25.2,<5.26.0" \
    "grpcio>=1.48.2" \
    "dm-tree>=0.1.8" \
    "lz4>=4.3.2" \
    "tifffile>=2024.1.30" \
    "setuptools<70"

# a repo copy is mounted at /workspace/rldec by tool.py
WORKDIR /workspace/rldec
