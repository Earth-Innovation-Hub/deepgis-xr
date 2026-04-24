# syntax=docker/dockerfile:1.6
# maskrcnn-rocks-api — REST service that serves our rock Mask R-CNN checkpoints
# (bishop_jezero_field, gobabeb_namib, tornado/eureka, hypolith, c3 ablations...)
#
# Mirrors the container pattern of the grounding-dino-api container that already
# runs on tesseract (jdas@192.168.0.232) at port 5000, so that deepgis-xr can
# route to it with a single new env var (MASKRCNN_ROCKS_API_URL).

FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TORCH_HOME=/opt/torch \
    MPLBACKEND=Agg

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1-mesa-glx \
        libglib2.0-0 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/program

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py model.py inference.py registry.py ./
COPY templates/ ./templates/

# Default model id served out of /opt/program/weights (bind-mounted to
# /mnt/22tb-hdd/maskrcnn on the host; read-only).
ENV DEFAULT_MODEL_ID=bishop_hero_e0004 \
    WEIGHTS_ROOT=/opt/program/weights \
    UPLOAD_FOLDER=/tmp/uploads \
    RESULTS_FOLDER=/tmp/results \
    MAX_CONTENT_LENGTH=33554432

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:5000/health || exit 1

CMD ["python", "app.py"]
