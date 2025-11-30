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

# Install PyTorch with CUDA support from PyTorch index, then other requirements
# Note: detectron2 is installed separately after torch because its setup.py imports torch
RUN pip install --no-cache-dir torch torchvision \
        --index-url https://download.pytorch.org/whl/cu121 && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir fiona==$(pip show fiona | grep Version | cut -d' ' -f2) --no-binary fiona && \
    pip install --no-cache-dir --no-build-isolation 'git+https://github.com/facebookresearch/detectron2.git' || \
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

# Run the application
CMD ["python3.9", "manage.py", "runserver", "0.0.0.0:8090"]
