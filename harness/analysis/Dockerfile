FROM ghcr.io/openhands/agent-server:61470a1-python
USER root
RUN apt-get update && apt-get install -y --no-install-recommends clang libclang-dev python3-clang && rm -rf /var/lib/apt/lists/*
