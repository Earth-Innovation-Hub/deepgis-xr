#!/usr/bin/env python3
"""
DeepGIS Topology Server
Research-grade server for streaming large 3D scenes without Cesium Ion dependency.

Features:
- Terrain tile streaming (heightmaps, quantized mesh)
- 3D Tiles format support (B3DM, I3DM, PNTS)
- GLTF/GLB model optimization and streaming
- Level of Detail (LOD) management
- Spatial indexing and culling
"""

import os
import sys
import json
import gzip
import sqlite3
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import rasterio
from rasterio.warp import transform_bounds, reproject
from rasterio.enums import Resampling
import trimesh
import struct
import base64
from scipy.spatial import cKDTree
import math

# Configuration
@dataclass
class ServerConfig:
    """Server configuration settings"""
    host: str = "0.0.0.0"
    port: int = 8092
    data_dir: str = "./data"
    cache_dir: str = "./cache"
    max_tile_size: int = 256
    terrain_format: str = "quantized-mesh"  # or "heightmap"
    compression_level: int = 6
    max_lod_levels: int = 18
    enable_3d_tiles: bool = True
    enable_terrain: bool = True
    enable_models: bool = True

class DeepGISTopologyServer:
    """Main server class for handling 3D topology data streaming"""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.app = Flask(__name__)
        CORS(self.app)
        
        # Create directories
        Path(config.data_dir).mkdir(parents=True, exist_ok=True)
        Path(config.cache_dir).mkdir(parents=True, exist_ok=True)
        
        # Initialize spatial database
        self._init_spatial_db()
        
        # Set up routes
        self._setup_routes()
        
        # Load terrain data
        self.terrain_data = {}
        self.model_cache = {}
        self._load_terrain_datasets()
        
    def _init_spatial_db(self):
        """Initialize spatial database for efficient querying"""
        self.db_path = os.path.join(self.config.cache_dir, "spatial_index.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        
        # Create tables for spatial indexing
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS terrain_tiles (
                id INTEGER PRIMARY KEY,
                z INTEGER,
                x INTEGER,
                y INTEGER,
                dataset_id TEXT,
                bounds_west REAL,
                bounds_south REAL,
                bounds_east REAL,
                bounds_north REAL,
                min_height REAL,
                max_height REAL,
                data_path TEXT,
                file_size INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS model_tiles (
                id INTEGER PRIMARY KEY,
                tileset_id TEXT,
                bounds_west REAL,
                bounds_south REAL,
                bounds_east REAL,
                bounds_north REAL,
                lod_level INTEGER,
                geometric_error REAL,
                content_uri TEXT,
                parent_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_terrain_spatial ON terrain_tiles(z, x, y);
            CREATE INDEX IF NOT EXISTS idx_model_spatial ON model_tiles(bounds_west, bounds_south, bounds_east, bounds_north);
        """)
        self.conn.commit()

    def _setup_routes(self):
        """Set up Flask routes for the server"""
        
        @self.app.route('/')
        def index():
            return jsonify({
                "name": "DeepGIS Topology Server",
                "version": "1.0.0",
                "description": "Research-grade 3D scene streaming server",
                "endpoints": {
                    "terrain": "/terrain/{dataset}/{z}/{x}/{y}.{format}",
                    "models": "/models/{tileset}/tileset.json",
                    "3dtiles": "/3dtiles/{tileset}/{z}/{x}/{y}.{format}",
                    "elevation": "/elevation?lon={lon}&lat={lat}",
                    "datasets": "/datasets",
                    "status": "/status"
                }
            })
        
        @self.app.route('/terrain/<dataset>/<int:z>/<int:x>/<int:y>.<format>')
        def serve_terrain_tile(dataset, z, x, y, format):
            """Serve terrain tiles in various formats"""
            return self._serve_terrain_tile(dataset, z, x, y, format)
        
        @self.app.route('/models/<tileset>/tileset.json')
        def serve_tileset_json(tileset):
            """Serve 3D Tiles tileset.json"""
            return self._serve_tileset_json(tileset)
        
        @self.app.route('/3dtiles/<tileset>/<path:tile_path>')
        def serve_3d_tile(tileset, tile_path):
            """Serve individual 3D tiles"""
            return self._serve_3d_tile(tileset, tile_path)
        
        @self.app.route('/elevation')
        def get_elevation():
            """Get elevation at a specific point"""
            lon = float(request.args.get('lon'))
            lat = float(request.args.get('lat'))
            return self._get_elevation_at_point(lon, lat)
        
        @self.app.route('/datasets')
        def list_datasets():
            """List available datasets"""
            return jsonify(self._list_available_datasets())
        
        @self.app.route('/status')
        def server_status():
            """Server status and statistics"""
            return jsonify(self._get_server_status())

    def _load_terrain_datasets(self):
        """Load terrain datasets from data directory"""
        terrain_dir = os.path.join(self.config.data_dir, "terrain")
        if not os.path.exists(terrain_dir):
            os.makedirs(terrain_dir)
            return
        
        for dataset_file in os.listdir(terrain_dir):
            if dataset_file.endswith(('.tif', '.tiff')):
                dataset_id = dataset_file.split('.')[0]
                dataset_path = os.path.join(terrain_dir, dataset_file)
                self.terrain_data[dataset_id] = self._load_terrain_dataset(dataset_path)

    def _load_terrain_dataset(self, file_path: str) -> Dict[str, Any]:
        """Load a terrain dataset and prepare for tiling"""
        try:
            with rasterio.open(file_path) as dataset:
                return {
                    'path': file_path,
                    'bounds': dataset.bounds,
                    'crs': dataset.crs,
                    'width': dataset.width,
                    'height': dataset.height,
                    'dtype': dataset.dtypes[0],
                    'nodata': dataset.nodata,
                    'transform': dataset.transform
                }
        except Exception as e:
            print(f"Error loading terrain dataset {file_path}: {e}")
            return None

    def _serve_terrain_tile(self, dataset: str, z: int, x: int, y: int, format: str):
        """Generate and serve terrain tiles on demand"""
        if dataset not in self.terrain_data:
            return jsonify({'error': 'Dataset not found'}), 404
        
        # Check cache first
        cache_path = self._get_terrain_cache_path(dataset, z, x, y, format)
        if os.path.exists(cache_path):
            return send_file(cache_path)
        
        # Generate tile
        tile_data = self._generate_terrain_tile(dataset, z, x, y, format)
        if tile_data is None:
            return jsonify({'error': 'Failed to generate tile'}), 500
        
        # Cache the tile
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, 'wb') as f:
            f.write(tile_data)
        
        return Response(tile_data, mimetype=self._get_content_type(format))

    def _generate_terrain_tile(self, dataset: str, z: int, x: int, y: int, format: str) -> Optional[bytes]:
        """Generate a terrain tile for the given coordinates"""
        dataset_info = self.terrain_data[dataset]
        
        # Calculate tile bounds in Web Mercator
        tile_bounds = self._get_tile_bounds(z, x, y)
        
        # Transform bounds to dataset CRS
        src_bounds = transform_bounds(
            'EPSG:3857', dataset_info['crs'], 
            *tile_bounds
        )
        
        try:
            with rasterio.open(dataset_info['path']) as src:
                # Read data for the tile bounds
                window = rasterio.windows.from_bounds(*src_bounds, src.transform)
                data = src.read(1, window=window)
                
                # Resample to tile size
                if data.size > 0:
                    data = self._resample_to_tile_size(data, self.config.max_tile_size)
                else:
                    # Return empty tile
                    data = np.zeros((self.config.max_tile_size, self.config.max_tile_size), dtype=np.float32)
                
                # Convert to requested format
                if format == 'png':
                    return self._heightmap_to_png(data)
                elif format == 'terrain':
                    return self._heightmap_to_quantized_mesh(data, tile_bounds)
                elif format == 'bin':
                    return self._heightmap_to_binary(data)
                else:
                    return None
                    
        except Exception as e:
            print(f"Error generating terrain tile: {e}")
            return None

    def _heightmap_to_quantized_mesh(self, heightmap: np.ndarray, bounds: Tuple[float, float, float, float]) -> bytes:
        """Convert heightmap to Cesium quantized mesh format"""
        height, width = heightmap.shape
        
        # Quantize coordinates and heights
        u_coords = []
        v_coords = []
        height_coords = []
        
        min_height = float(np.min(heightmap))
        max_height = float(np.max(heightmap))
        height_range = max_height - min_height if max_height != min_height else 1.0
        
        # Generate vertices
        for i in range(height):
            for j in range(width):
                u = j / (width - 1) if width > 1 else 0.0
                v = i / (height - 1) if height > 1 else 0.0
                h = (heightmap[i, j] - min_height) / height_range
                
                # Quantize to 16-bit integers
                u_coords.append(int(u * 32767))
                v_coords.append(int(v * 32767))
                height_coords.append(int(h * 32767))
        
        # Generate indices for triangulation
        indices = []
        for i in range(height - 1):
            for j in range(width - 1):
                # Two triangles per quad
                base = i * width + j
                indices.extend([
                    base, base + 1, base + width,
                    base + 1, base + width + 1, base + width
                ])
        
        # Pack binary data
        header = struct.pack('<fff', bounds[0], bounds[1], bounds[2])  # west, south, east
        header += struct.pack('<fff', bounds[3], min_height, max_height)  # north, min_height, max_height
        
        vertex_count = len(u_coords)
        triangle_count = len(indices) // 3
        
        data = struct.pack('<II', vertex_count, triangle_count)
        
        # Pack vertex data
        for i in range(vertex_count):
            data += struct.pack('<HHH', u_coords[i], v_coords[i], height_coords[i])
        
        # Pack indices
        for idx in indices:
            data += struct.pack('<H', idx)
        
        # Compress with gzip
        return gzip.compress(header + data, compresslevel=self.config.compression_level)

    def _heightmap_to_png(self, heightmap: np.ndarray) -> bytes:
        """Convert heightmap to PNG format for visualization"""
        from PIL import Image
        
        # Normalize to 0-255 range
        normalized = ((heightmap - np.min(heightmap)) / 
                     (np.max(heightmap) - np.min(heightmap)) * 255).astype(np.uint8)
        
        # Create PIL image
        image = Image.fromarray(normalized, mode='L')
        
        # Convert to bytes
        import io
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()

    def _heightmap_to_binary(self, heightmap: np.ndarray) -> bytes:
        """Convert heightmap to binary format"""
        return heightmap.astype(np.float32).tobytes()

    def _resample_to_tile_size(self, data: np.ndarray, target_size: int) -> np.ndarray:
        """Resample data to target tile size"""
        from scipy.ndimage import zoom
        
        current_shape = data.shape
        if current_shape[0] == target_size and current_shape[1] == target_size:
            return data
        
        zoom_factors = (target_size / current_shape[0], target_size / current_shape[1])
        return zoom(data, zoom_factors, order=1)  # Bilinear interpolation

    def _get_tile_bounds(self, z: int, x: int, y: int) -> Tuple[float, float, float, float]:
        """Calculate tile bounds in Web Mercator (EPSG:3857)"""
        n = 2.0 ** z
        lon_deg_min = x / n * 360.0 - 180.0
        lon_deg_max = (x + 1) / n * 360.0 - 180.0
        lat_rad_min = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
        lat_rad_max = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        lat_deg_min = math.degrees(lat_rad_min)
        lat_deg_max = math.degrees(lat_rad_max)
        
        # Convert to Web Mercator
        def deg_to_mercator(lon, lat):
            x = lon * 20037508.34 / 180
            y = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180)
            y = y * 20037508.34 / 180
            return x, y
        
        west, south = deg_to_mercator(lon_deg_min, lat_deg_min)
        east, north = deg_to_mercator(lon_deg_max, lat_deg_max)
        
        return west, south, east, north

    def _get_terrain_cache_path(self, dataset: str, z: int, x: int, y: int, format: str) -> str:
        """Get cache file path for terrain tile"""
        return os.path.join(
            self.config.cache_dir, 'terrain', dataset, 
            str(z), str(x), f"{y}.{format}"
        )

    def _get_content_type(self, format: str) -> str:
        """Get MIME type for format"""
        types = {
            'png': 'image/png',
            'terrain': 'application/vnd.quantized-mesh',
            'bin': 'application/octet-stream',
            'json': 'application/json'
        }
        return types.get(format, 'application/octet-stream')

    def _serve_tileset_json(self, tileset: str):
        """Generate and serve 3D Tiles tileset.json"""
        tileset_path = os.path.join(self.config.data_dir, "3dtiles", tileset)
        if not os.path.exists(tileset_path):
            return jsonify({'error': 'Tileset not found'}), 404
        
        # Generate tileset.json dynamically
        tileset_json = self._generate_tileset_json(tileset_path)
        return jsonify(tileset_json)

    def _generate_tileset_json(self, tileset_path: str) -> Dict[str, Any]:
        """Generate 3D Tiles tileset.json structure"""
        # This is a simplified version - in production you'd scan the actual tile structure
        return {
            "asset": {
                "version": "1.0",
                "generator": "DeepGIS Topology Server"
            },
            "geometricError": 240.0,
            "root": {
                "boundingVolume": {
                    "region": [-1.3197004795898053, 0.6988582109, -1.3196595204101946, 0.6989055463, 0, 88]
                },
                "geometricError": 120.0,
                "refine": "REPLACE",
                "content": {
                    "uri": "0/0/0.b3dm"
                },
                "children": []
            }
        }

    def _serve_3d_tile(self, tileset: str, tile_path: str):
        """Serve individual 3D tile files"""
        full_path = os.path.join(self.config.data_dir, "3dtiles", tileset, tile_path)
        if os.path.exists(full_path):
            return send_file(full_path)
        return jsonify({'error': 'Tile not found'}), 404

    def _get_elevation_at_point(self, lon: float, lat: float):
        """Get elevation at a specific longitude/latitude point"""
        elevations = {}
        
        for dataset_id, dataset_info in self.terrain_data.items():
            try:
                with rasterio.open(dataset_info['path']) as src:
                    # Transform coordinates to dataset CRS
                    xs, ys = rasterio.warp.transform('EPSG:4326', src.crs, [lon], [lat])
                    
                    # Sample elevation
                    elevation = next(src.sample([(xs[0], ys[0])]))
                    elevations[dataset_id] = float(elevation[0]) if elevation[0] != src.nodata else None
                    
            except Exception as e:
                print(f"Error sampling elevation from {dataset_id}: {e}")
                elevations[dataset_id] = None
        
        return jsonify({
            'longitude': lon,
            'latitude': lat,
            'elevations': elevations
        })

    def _list_available_datasets(self) -> Dict[str, Any]:
        """List all available datasets"""
        datasets = {
            'terrain': {},
            '3dtiles': [],
            'models': []
        }
        
        # List terrain datasets
        for dataset_id, info in self.terrain_data.items():
            datasets['terrain'][dataset_id] = {
                'bounds': info['bounds'],
                'crs': str(info['crs']),
                'width': info['width'],
                'height': info['height']
            }
        
        # List 3D Tiles
        tiles_dir = os.path.join(self.config.data_dir, "3dtiles")
        if os.path.exists(tiles_dir):
            datasets['3dtiles'] = [d for d in os.listdir(tiles_dir) 
                                 if os.path.isdir(os.path.join(tiles_dir, d))]
        
        return datasets

    def _get_server_status(self) -> Dict[str, Any]:
        """Get server status and statistics"""
        cache_size = sum(
            os.path.getsize(os.path.join(dirpath, filename))
            for dirpath, dirnames, filenames in os.walk(self.config.cache_dir)
            for filename in filenames
        ) / (1024 * 1024)  # MB
        
        return {
            'status': 'running',
            'datasets_loaded': len(self.terrain_data),
            'cache_size_mb': round(cache_size, 2),
            'config': {
                'terrain_format': self.config.terrain_format,
                'max_tile_size': self.config.max_tile_size,
                'max_lod_levels': self.config.max_lod_levels
            }
        }

    def run(self):
        """Start the server"""
        print(f"Starting DeepGIS Topology Server on {self.config.host}:{self.config.port}")
        print(f"Data directory: {self.config.data_dir}")
        print(f"Cache directory: {self.config.cache_dir}")
        
        self.app.run(
            host=self.config.host,
            port=self.config.port,
            debug=False,
            threaded=True
        )

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='DeepGIS Topology Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8092, help='Port to bind to')
    parser.add_argument('--data-dir', default='./data', help='Data directory')
    parser.add_argument('--cache-dir', default='./cache', help='Cache directory')
    parser.add_argument('--terrain-format', default='quantized-mesh', 
                       choices=['quantized-mesh', 'heightmap'], help='Terrain format')
    
    args = parser.parse_args()
    
    config = ServerConfig(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir,
        cache_dir=args.cache_dir,
        terrain_format=args.terrain_format
    )
    
    server = DeepGISTopologyServer(config)
    server.run()

if __name__ == '__main__':
    main() 