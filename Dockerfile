# DeepGIS XR Docker image with YOLOv8 support
# YOLOv8 (Ultralytics) is a pure Python package - no custom CUDA compilation needed
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu20.04

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

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.9 \
    python3.9-dev \
    python3.9-venv \
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
RUN python3.9 -m venv /opt/venv
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

# Install PyTorch with CUDA support from PyTorch index, then the rest of requirements.
# detectron2 was previously installed here as well, but no Python in this codebase
# imports it (the Mask R-CNN rocks model runs as a remote service via
# MASKRCNN_ROCKS_API_URL). Re-add only if a future analyzer needs in-process
# detectron2 — note that it locks the numpy/torch ABI and has long build times.
RUN pip install --no-cache-dir torch torchvision \
        --index-url https://download.pytorch.org/whl/cu121 && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir fiona==$(pip show fiona | grep Version | cut -d' ' -f2) --no-binary fiona || \
    (echo "Failed to install requirements" && exit 1)

# Create models directory for YOLO weights (auto-downloaded on first use)
RUN mkdir -p /app/models

# Verify YOLOv8 installation
RUN python -c "from ultralytics import YOLO; print('✓ YOLOv8 installed successfully')"

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
