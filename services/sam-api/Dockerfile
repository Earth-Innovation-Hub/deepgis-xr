# syntax=docker/dockerfile:1.6
FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        libgl1-mesa-glx \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/program

RUN pip install \
      flask==3.0.0 \
      flask-cors==4.0.0 \
      opencv-python-headless==4.8.1.78 \
      Pillow==10.1.0 \
      git+https://github.com/facebookresearch/segment-anything.git@dca509fe793f601edb92606367a655c15ac00fdf

COPY app.py .

ENV UPLOAD_FOLDER=/tmp/uploads \
    RESULTS_FOLDER=/tmp/results \
    SAM_CHECKPOINT_DIR=/opt/program/checkpoints \
    DEFAULT_MODEL_TYPE=vit_b \
    MAX_CONTENT_LENGTH=33554432 \
    SAM_EAGER_WARMUP=false \
    SAM_UNLOAD_AFTER_PREDICT=true \
    SAM_EMPTY_CACHE_AFTER_PREDICT=true

RUN mkdir -p /tmp/uploads /tmp/results /opt/program/checkpoints

EXPOSE 5000

CMD ["python", "app.py"]
