# Builder stage
FROM python:3-slim AS builder
WORKDIR /build
# build-essential: fallback compiler for any dependency that ships no
# prebuilt wheel for the target platform (relevant for arm64)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3-slim
# libmagic1: shared library required at runtime by python-magic
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/*
WORKDIR /thephish
COPY --from=builder /root/.local /root/.local
COPY . .
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
# Mount your configuration into the container, e.g.:
#   docker run -v ./config:/thephish/config:ro ghcr.io/dead-plant/thephish-ng:1
# run.py resolves --config-dir to ./config next to itself by default.
EXPOSE 8080
ENTRYPOINT ["python", "run.py"]
