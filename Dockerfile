# DeepGIS XR web image — Django + DRF + GIS stack with PyTorch/CUDA reserved
# for the in-process Mask R-CNN training endpoint (apps/ml/services/trainer.py)
# that runs in the celery_worker GPU job. ML model packages (ultralytics,
# segment-anything, etc.) and their weight files (*.pt / *.pth) are
# intentionally excluded — every served model (YOLOv8, SAM, Grounding-DINO,
# Grounded-SAM, all Mask R-CNN families) runs as a remote service on
# 192.168.0.232 and is reached via HTTP. See SAM_API_URL / GROUNDING_DINO_API_URL
# / MASKRCNN_*_API_URL in docker-compose.yml and the .dockerignore at the
# repo root.
#
# Base image upgraded from ubuntu20.04 to ubuntu22.04 (April 2026): focal LTS
# has standard support ending May 2025 and the focal deadsnakes PPA stopped
# serving a usable Packages index for python3.11. Ubuntu 22.04 (jammy) ships
# python3.10 natively — Django 5.2 officially supports 3.10–3.13 and all of
# our heavy GIS + ML wheels (PyTorch 2.5.1+cu121, fiona 1.9, rasterio 1.3,
# numpy 1.26, pandas 2.2) have cp310 wheels — so no PPA is required.
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Set CUDA environment variables
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Add UbuntuGIS PPA for latest GDAL
RUN apt-get update && apt-get install -y software-properties-common
RUN add-apt-repository ppa:ubuntugis/ppa

# Install system dependencies. python3.10 ships natively with Ubuntu 22.04
# and is supported by Django 5.2 LTS (>=3.10) plus the entire heavy GIS +
# ML stack used here.
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3.10-venv \
    python3-pip \
    build-essential \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    python3-gdal \
    git \
    libspatialindex-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    libgeos-dev \
    libgeos++-dev \
    libffi-dev \
    libsqlite3-mod-spatialite \
    # OpenCV dependencies
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    libgtk2.0-dev \
    pkg-config \
    # Font for visualization
    fonts-dejavu-core \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Get GDAL version and set environment variables
RUN export GDAL_VERSION=$(gdal-config --version) && \
    export CPLUS_INCLUDE_PATH=/usr/include/gdal && \
    export C_INCLUDE_PATH=/usr/include/gdal && \
    export GDAL_LIBRARY_PATH=$(gdal-config --prefix)/lib/libgdal.so && \
    echo "GDAL_VERSION=${GDAL_VERSION}" >> /etc/environment && \
    echo "CPLUS_INCLUDE_PATH=${CPLUS_INCLUDE_PATH}" >> /etc/environment && \
    echo "C_INCLUDE_PATH=${C_INCLUDE_PATH}" >> /etc/environment && \
    echo "GDAL_LIBRARY_PATH=${GDAL_LIBRARY_PATH}" >> /etc/environment

# Create virtual environment
RUN python3.10 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install wheel
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# Install GDAL with system version first
RUN export GDAL_VERSION=$(gdal-config --version) && \
    pip install --no-cache-dir GDAL==${GDAL_VERSION}

# Set work directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install PyTorch with CUDA support from PyTorch index, then the rest of
# requirements. Versions are pinned (2.5.1+cu121 / 0.20.1+cu121) to keep the
# numpy/torch ABI stable across rebuilds — leaving them unpinned silently
# shifts to whatever `latest` is on the cu121 index.  detectron2 was previously
# installed here too, but nothing imports it (Mask R-CNN rocks runs remotely
# via MASKRCNN_ROCKS_API_URL). Re-add only if a future analyzer needs
# in-process detectron2 — note that it locks the numpy/torch ABI and has long
# build times.
#
# YOLO (ultralytics) and SAM (segment-anything) are intentionally NOT installed
# here — those models run as remote services on 192.168.0.232 (see SAM_API_URL,
# the YOLOv8 dispatch path, and the per-family MASKRCNN_*_API_URL env vars in
# docker-compose.yml). Keeping the model packages out of the image saves
# ~1.5 GB of wheels and weight downloads on every build.
RUN pip install --no-cache-dir \
        torch==2.5.1+cu121 \
        torchvision==0.20.1+cu121 \
        --index-url https://download.pytorch.org/whl/cu121 && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir fiona==$(pip show fiona | grep Version | cut -d' ' -f2) --no-binary fiona || \
    (echo "Failed to install requirements" && exit 1)

# Copy project
COPY . .

# Make manage.py executable
RUN chmod +x manage.py

# Expose port
EXPOSE 8090

# Run the application via gunicorn (production WSGI server).
#
# Worker count is intentionally low because the analyze-viewport pipeline can
# burn 90+ s on a single request when the remote AI host is warm-loading a
# checkpoint; thread count carries the read-light Django/HTTP work in
# parallel, and --timeout 600 absorbs slow remote inference without
# triggering the worker timeout (the default 30 s would kill in-flight
# AI requests). When the optional `manage.py runserver` workflow is needed
# for local debugging, the docker-compose `command:` override for the web
# service is the right place to flip back to runserver — do not edit this
# CMD.
CMD ["sh", "-c", "exec gunicorn deepgis_xr.wsgi:application \
    --bind 0.0.0.0:8090 \
    --workers ${GUNICORN_WORKERS:-2} \
    --threads ${GUNICORN_THREADS:-4} \
    --timeout ${GUNICORN_TIMEOUT:-600} \
    --access-logfile - \
    --error-logfile -"]
