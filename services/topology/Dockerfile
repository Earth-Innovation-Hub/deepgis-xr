# =============================================================================
# DeepGIS Topology Server — Flask service
# -----------------------------------------------------------------------------
# Separate image from the main Django app. No CUDA, no SAM, no Ultralytics —
# just GDAL / rasterio / trimesh for tile streaming.
# =============================================================================
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps for GDAL / rasterio / trimesh
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgdal-dev \
        gdal-bin \
        libspatialindex-dev \
        libproj-dev \
        libgeos-dev \
        libsqlite3-mod-spatialite \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install GDAL matching the system version first (py-gdal is pinned in
# requirements.txt but must match the system libgdal-dev version).
RUN export GDAL_VERSION=$(gdal-config --version) && \
    pip install "GDAL==${GDAL_VERSION}"

# Service-specific Python deps.
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy service code
COPY . /app/

EXPOSE 8092

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8092"]
