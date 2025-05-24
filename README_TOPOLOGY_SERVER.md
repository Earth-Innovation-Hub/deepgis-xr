# DeepGIS Topology Server Setup

## Overview

The DeepGIS Topology Server is a research-grade solution for streaming large 3D scenes without requiring Cesium Ion. It provides:

- **Terrain Streaming**: Convert DEMs to tiled terrain (quantized mesh format)
- **3D Tiles Support**: Stream large 3D models efficiently
- **Level of Detail (LOD)**: Automatic optimization for performance
- **Custom Formats**: Support for research data formats
- **No Vendor Lock-in**: Complete control over your data

## Quick Start

### 1. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements-topology.txt

# Install system dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install gdal-bin libgdal-dev python3-gdal

# For macOS (using Homebrew)
brew install gdal
```

### 2. Create Sample Data (for testing)

```bash
# Create sample terrain and 3D models
python prepare_data.py --create-samples --output-dir ./data

# This creates:
# - ./data/terrain/sample_terrain_webmercator.tif
# - ./data/3dtiles/sample_building/
```

### 3. Start the Server

```bash
# Start with default settings
python deepgis_topology_server.py

# Or with custom configuration
python deepgis_topology_server.py --data-dir ./data --port 8092
```

### 4. Update Cesium Configuration

The server automatically integrates with your Cesium viewer. The topology server will be detected at `http://localhost:8092`.

## Preparing Your Research Data

### Terrain Data (DEMs)

```bash
# Process your DEM files
python prepare_data.py \
  --terrain your_dem1.tif your_dem2.tif \
  --output-dir ./data

# Supported formats: GeoTIFF, NetCDF, HDF5, ENVI
```

**Data Requirements:**
- Any coordinate system (automatically reprojected to Web Mercator)
- Elevation in meters
- Recommended resolution: 1-30 meters per pixel
- Large files are automatically tiled

### 3D Models

```bash
# Process 3D models
python prepare_data.py \
  --models building.obj city_model.ply scan.stl \
  --output-dir ./data

# Supported formats: OBJ, PLY, STL, DAE, GLTF, FBX
```

**Optimization Features:**
- Automatic mesh simplification for large models
- Conversion to efficient GLB format
- Generation of 3D Tiles hierarchy
- LOD creation for performance

## Advanced Configuration

### Server Configuration

Create `server_config.json`:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8092,
    "workers": 4
  },
  "data": {
    "terrain_dir": "./data/terrain",
    "models_dir": "./data/3dtiles",
    "cache_dir": "./cache"
  },
  "optimization": {
    "max_tile_size": 256,
    "compression_level": 6,
    "terrain_format": "quantized-mesh",
    "enable_caching": true,
    "cache_ttl": 3600
  },
  "security": {
    "cors_origins": ["http://localhost:8000"],
    "api_rate_limit": 1000
  }
}
```

### Production Deployment

#### Using Docker

```dockerfile
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gdal-bin libgdal-dev python3-gdal \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY . /app
WORKDIR /app

# Install Python dependencies
RUN pip install -r requirements-topology.txt

# Expose port
EXPOSE 8092

# Start server
CMD ["python", "deepgis_topology_server.py", "--host", "0.0.0.0"]
```

#### Using Nginx Reverse Proxy

```nginx
# /etc/nginx/sites-available/deepgis-topology
server {
    listen 80;
    server_name topology.yourdomain.com;
    
    location / {
        proxy_pass http://localhost:8092;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # Enable CORS
        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS";
        add_header Access-Control-Allow-Headers "Content-Type, Authorization";
    }
    
    # Cache terrain tiles
    location ~* \.(terrain|png|bin)$ {
        proxy_pass http://localhost:8092;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
```

## API Endpoints

### Terrain

```
GET /terrain/{dataset}/{z}/{x}/{y}.terrain  # Quantized mesh
GET /terrain/{dataset}/{z}/{x}/{y}.png      # Heightmap PNG
GET /terrain/{dataset}/{z}/{x}/{y}.bin      # Raw binary
```

### 3D Models

```
GET /models/{tileset}/tileset.json          # 3D Tiles metadata
GET /3dtiles/{tileset}/{path}               # Individual tiles
```

### Utilities

```
GET /elevation?lon={lon}&lat={lat}          # Point elevation
GET /datasets                               # Available datasets
GET /status                                 # Server status
```

## Performance Optimization

### Memory Usage

```python
# Configure memory limits in server
import resource

# Limit memory to 4GB
resource.setrlimit(resource.RLIMIT_AS, (4*1024*1024*1024, -1))
```

### Caching Strategy

```python
# Redis caching for high-traffic scenarios
import redis

cache = redis.Redis(host='localhost', port=6379, db=0)

# Cache terrain tiles for 1 hour
cache.setex(f"terrain:{dataset}:{z}:{x}:{y}", 3600, tile_data)
```

### Multi-processing

```bash
# Run multiple server instances
python deepgis_topology_server.py --port 8092 &
python deepgis_topology_server.py --port 8093 &
python deepgis_topology_server.py --port 8094 &

# Use load balancer (nginx, HAProxy)
```

## Integrating with Research Workflows

### Scientific Data Formats

```python
# Custom data loader for NetCDF/HDF5
def load_scientific_data(file_path):
    import xarray as xr
    
    # Load NetCDF climate data
    ds = xr.open_dataset(file_path)
    elevation = ds['elevation'].values
    
    # Convert to GeoTIFF for processing
    return elevation, ds.rio.transform()
```

### Real-time Data Streaming

```python
# WebSocket support for real-time updates
from flask_socketio import SocketIO

socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on('update_terrain')
def handle_terrain_update(data):
    # Process real-time terrain updates
    update_terrain_cache(data)
    emit('terrain_updated', {'status': 'success'})
```

### Custom Coordinate Systems

```python
# Support for custom projections
from pyproj import Transformer

def reproject_custom_crs(src_crs, dst_crs, x, y):
    transformer = Transformer.from_crs(src_crs, dst_crs)
    return transformer.transform(x, y)
```

## Troubleshooting

### Common Issues

1. **GDAL Import Error**
   ```bash
   # Fix GDAL path issues
   export GDAL_DATA=/usr/share/gdal
   export PROJ_LIB=/usr/share/proj
   ```

2. **Memory Issues with Large DEMs**
   ```python
   # Process in chunks
   def process_large_dem(file_path, chunk_size=1024):
       with rasterio.open(file_path) as src:
           for window in src.block_windows():
               data = src.read(window=window)
               # Process chunk
   ```

3. **Performance Issues**
   ```bash
   # Monitor performance
   python -m memory_profiler deepgis_topology_server.py
   
   # Profile specific functions
   python -m cProfile -o profile.prof deepgis_topology_server.py
   ```

### Debug Mode

```bash
# Run with debug logging
python deepgis_topology_server.py --debug --log-level DEBUG
```

## Research Applications

### Use Cases

- **Archaeological Site Reconstruction**: Stream large photogrammetry models
- **Geological Surveys**: Visualize DEM data with multiple temporal layers
- **Climate Research**: Display time-series elevation changes
- **Urban Planning**: Stream city models with LOD optimization
- **Environmental Monitoring**: Real-time terrain change detection

### Citation

If you use this in your research, please cite:

```
DeepGIS Topology Server (2024)
Research-grade 3D scene streaming for geospatial applications
https://github.com/your-repo/deepgis-topology-server
```

## Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature-name`
3. Add tests for new functionality
4. Submit pull request with detailed description

## License

This project is released under the MIT License for research use.

## Support

- **Documentation**: See `docs/` directory
- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions
- **Email**: support@deepgis.org 