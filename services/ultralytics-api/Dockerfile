# syntax=docker/dockerfile:1.6
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/weights/.ultralytics

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/program

# The CLIP fork is the text encoder SAM 3 and YOLOE use; the PyPI "clip"
# package breaks SAM 3 with "'SimpleTokenizer' object is not callable".
RUN pip install \
      flask==3.0.3 \
      ultralytics==8.4.216 \
      timm==1.0.31 \
      "git+https://github.com/ultralytics/CLIP.git"

COPY app.py .

ENV WEIGHTS_DIR=/weights \
    DEFAULT_MODEL=yolo26x-seg \
    UNLOAD_AFTER_PREDICT=true \
    DEFAULT_IMGSZ=1024 \
    MAX_IMGSZ=1280

EXPOSE 5000

CMD ["python", "app.py"]
