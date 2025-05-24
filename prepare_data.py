#!/usr/bin/env python3
"""
Data Preparation Script for DeepGIS Topology Server

This script helps prepare your research data for streaming:
- Convert DEMs to tiled terrain format
- Process 3D models into 3D Tiles
- Optimize textures and compression
- Generate spatial indices
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
import trimesh
import numpy as np
from typing import List, Dict, Tuple

class DataPreparer:
    """Main class for preparing research data for streaming"""
    
    def __init__(self, data_dir: str, output_dir: str):
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        
        # Create output directories
        self.terrain_dir = self.output_dir / "terrain"
        self.models_dir = self.output_dir / "3dtiles"
        self.cache_dir = self.output_dir / "cache"
        
        for dir in [self.terrain_dir, self.models_dir, self.cache_dir]:
            dir.mkdir(parents=True, exist_ok=True)

    def prepare_terrain_data(self, input_files: List[str]):
        """Prepare terrain/DEM data for streaming"""
        print("Preparing terrain data...")
        
        for input_file in input_files:
            input_path = Path(input_file)
            if not input_path.exists():
                print(f"Warning: {input_file} not found, skipping")
                continue
                
            print(f"Processing {input_path.name}...")
            
            # Convert to Web Mercator if needed
            output_path = self.terrain_dir / f"{input_path.stem}_webmercator.tif"
            self._reproject_to_web_mercator(input_path, output_path)
            
            # Generate overviews for efficient tiling
            self._generate_overviews(output_path)
            
            print(f"  → {output_path}")

    def _reproject_to_web_mercator(self, input_path: Path, output_path: Path):
        """Reproject raster to Web Mercator (EPSG:3857)"""
        with rasterio.open(input_path) as src:
            # Check if already in Web Mercator
            if src.crs.to_epsg() == 3857:
                print(f"  {input_path.name} already in Web Mercator, copying...")
                import shutil
                shutil.copy2(input_path, output_path)
                return
            
            # Calculate transform and dimensions for Web Mercator
            transform, width, height = calculate_default_transform(
                src.crs, 'EPSG:3857', src.width, src.height, *src.bounds
            )
            
            # Create output dataset
            kwargs = src.meta.copy()
            kwargs.update({
                'crs': 'EPSG:3857',
                'transform': transform,
                'width': width,
                'height': height
            })
            
            with rasterio.open(output_path, 'w', **kwargs) as dst:
                for i in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, i),
                        destination=rasterio.band(dst, i),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs='EPSG:3857',
                        resampling=Resampling.bilinear
                    )

    def _generate_overviews(self, raster_path: Path):
        """Generate overview pyramids for efficient rendering"""
        with rasterio.open(raster_path, 'r+') as src:
            # Calculate overview levels (powers of 2)
            overview_levels = []
            level = 2
            while level < min(src.width, src.height):
                overview_levels.append(level)
                level *= 2
            
            if overview_levels:
                src.build_overviews(overview_levels, Resampling.average)
                src.update_tags(ns='rio_overview', resampling='average')
                print(f"  Generated {len(overview_levels)} overview levels")

    def prepare_3d_models(self, input_files: List[str]):
        """Prepare 3D models for streaming"""
        print("Preparing 3D models...")
        
        for input_file in input_files:
            input_path = Path(input_file)
            if not input_path.exists():
                print(f"Warning: {input_file} not found, skipping")
                continue
                
            print(f"Processing {input_path.name}...")
            
            try:
                # Load mesh
                mesh = trimesh.load(input_path)
                
                if isinstance(mesh, trimesh.Scene):
                    # Handle scenes with multiple meshes
                    self._process_scene(mesh, input_path)
                else:
                    # Single mesh
                    self._process_single_mesh(mesh, input_path)
                    
            except Exception as e:
                print(f"  Error processing {input_path.name}: {e}")

    def _process_single_mesh(self, mesh: trimesh.Trimesh, input_path: Path):
        """Process a single mesh into 3D Tiles format"""
        output_dir = self.models_dir / input_path.stem
        output_dir.mkdir(exist_ok=True)
        
        # Optimize mesh
        mesh = self._optimize_mesh(mesh)
        
        # Export as GLB (binary GLTF)
        glb_path = output_dir / "model.glb"
        mesh.export(glb_path)
        
        # Create simple tileset.json
        tileset = self._create_simple_tileset(mesh, "model.glb")
        tileset_path = output_dir / "tileset.json"
        
        with open(tileset_path, 'w') as f:
            json.dump(tileset, f, indent=2)
        
        print(f"  → {output_dir}")

    def _process_scene(self, scene: trimesh.Scene, input_path: Path):
        """Process a scene with multiple meshes"""
        output_dir = self.models_dir / input_path.stem
        output_dir.mkdir(exist_ok=True)
        
        # Export scene as GLB
        glb_path = output_dir / "scene.glb"
        scene.export(glb_path)
        
        # Create tileset for scene
        bounds = scene.bounds
        tileset = {
            "asset": {"version": "1.0", "generator": "DeepGIS Data Preparer"},
            "geometricError": self._calculate_geometric_error(bounds),
            "root": {
                "boundingVolume": {"box": self._bounds_to_box(bounds)},
                "geometricError": self._calculate_geometric_error(bounds) / 2,
                "content": {"uri": "scene.glb"},
                "refine": "REPLACE"
            }
        }
        
        tileset_path = output_dir / "tileset.json"
        with open(tileset_path, 'w') as f:
            json.dump(tileset, f, indent=2)
        
        print(f"  → {output_dir}")

    def _optimize_mesh(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """Optimize mesh for streaming"""
        # Remove duplicate vertices
        mesh.remove_duplicate_faces()
        mesh.remove_unreferenced_vertices()
        
        # Simplify if too many faces
        if len(mesh.faces) > 50000:
            print(f"  Simplifying mesh: {len(mesh.faces)} → ", end="")
            mesh = mesh.simplify_quadric_decimation(50000)
            print(f"{len(mesh.faces)} faces")
        
        # Ensure mesh is manifold
        if not mesh.is_watertight:
            mesh.fill_holes()
        
        return mesh

    def _create_simple_tileset(self, mesh: trimesh.Trimesh, content_uri: str) -> Dict:
        """Create a simple tileset.json for a single mesh"""
        bounds = mesh.bounds
        center = mesh.centroid
        
        return {
            "asset": {
                "version": "1.0",
                "generator": "DeepGIS Data Preparer"
            },
            "geometricError": self._calculate_geometric_error(bounds),
            "root": {
                "boundingVolume": {
                    "box": self._bounds_to_box(bounds)
                },
                "geometricError": self._calculate_geometric_error(bounds) / 2,
                "content": {
                    "uri": content_uri
                },
                "refine": "REPLACE"
            }
        }

    def _bounds_to_box(self, bounds: np.ndarray) -> List[float]:
        """Convert mesh bounds to 3D Tiles box format"""
        min_pt, max_pt = bounds
        center = (min_pt + max_pt) / 2
        extents = (max_pt - min_pt) / 2
        
        # Box format: [centerX, centerY, centerZ, halfX, 0, 0, 0, halfY, 0, 0, 0, halfZ]
        return [
            float(center[0]), float(center[1]), float(center[2]),
            float(extents[0]), 0.0, 0.0,
            0.0, float(extents[1]), 0.0,
            0.0, 0.0, float(extents[2])
        ]

    def _calculate_geometric_error(self, bounds: np.ndarray) -> float:
        """Calculate geometric error for LOD"""
        diagonal = np.linalg.norm(bounds[1] - bounds[0])
        return float(diagonal / 50)  # Heuristic

    def create_sample_data(self):
        """Create sample terrain and model data for testing"""
        print("Creating sample data...")
        
        # Create sample DEM
        self._create_sample_dem()
        
        # Create sample 3D model
        self._create_sample_model()

    def _create_sample_dem(self):
        """Create a sample DEM for testing"""
        # Generate synthetic terrain
        width, height = 1024, 1024
        x = np.linspace(-111.5, -111.0, width)
        y = np.linspace(33.5, 34.0, height)
        X, Y = np.meshgrid(x, y)
        
        # Create realistic elevation data
        Z = (1000 + 
             500 * np.sin(X * 10) * np.cos(Y * 10) +
             200 * np.sin(X * 20) * np.cos(Y * 20) +
             100 * np.random.random((height, width)))
        
        # Save as GeoTIFF
        from rasterio.transform import from_bounds
        
        transform = from_bounds(-111.5, 33.5, -111.0, 34.0, width, height)
        
        sample_dem_path = self.data_dir / "sample_terrain.tif"
        with rasterio.open(
            sample_dem_path, 'w',
            driver='GTiff',
            height=height, width=width,
            count=1, dtype=Z.dtype,
            crs='EPSG:4326',
            transform=transform
        ) as dst:
            dst.write(Z, 1)
        
        print(f"Created sample DEM: {sample_dem_path}")
        return str(sample_dem_path)

    def _create_sample_model(self):
        """Create a sample 3D model for testing"""
        # Create a simple building-like structure
        # Base
        base = trimesh.creation.box([20, 20, 5])
        base.apply_translation([0, 0, 2.5])
        
        # Tower
        tower = trimesh.creation.box([8, 8, 30])
        tower.apply_translation([0, 0, 20])
        
        # Combine
        building = base + tower
        
        # Add some color
        building.visual.face_colors = [100, 100, 200, 255]
        
        sample_model_path = self.data_dir / "sample_building.ply"
        building.export(sample_model_path)
        
        print(f"Created sample model: {sample_model_path}")
        return str(sample_model_path)

    def generate_config(self):
        """Generate configuration file for the server"""
        config = {
            "server": {
                "host": "0.0.0.0",
                "port": 8092
            },
            "data": {
                "terrain_dir": str(self.terrain_dir),
                "models_dir": str(self.models_dir),
                "cache_dir": str(self.cache_dir)
            },
            "optimization": {
                "max_tile_size": 256,
                "compression_level": 6,
                "enable_caching": True
            }
        }
        
        config_path = self.output_dir / "server_config.json"
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"Generated config: {config_path}")

def main():
    parser = argparse.ArgumentParser(description='Prepare data for DeepGIS Topology Server')
    parser.add_argument('--data-dir', default='./input_data', help='Input data directory')
    parser.add_argument('--output-dir', default='./data', help='Output data directory')
    parser.add_argument('--terrain', nargs='*', help='Terrain/DEM files to process')
    parser.add_argument('--models', nargs='*', help='3D model files to process')
    parser.add_argument('--create-samples', action='store_true', help='Create sample data')
    parser.add_argument('--config-only', action='store_true', help='Only generate config file')
    
    args = parser.parse_args()
    
    preparer = DataPreparer(args.data_dir, args.output_dir)
    
    if args.config_only:
        preparer.generate_config()
        return
    
    if args.create_samples:
        preparer.create_sample_data()
        # Process the created samples
        sample_terrain = preparer._create_sample_dem()
        sample_model = preparer._create_sample_model()
        preparer.prepare_terrain_data([sample_terrain])
        preparer.prepare_3d_models([sample_model])
    else:
        if args.terrain:
            preparer.prepare_terrain_data(args.terrain)
        
        if args.models:
            preparer.prepare_3d_models(args.models)
    
    preparer.generate_config()
    
    print("\nData preparation complete!")
    print("To start the server:")
    print(f"  cd {args.output_dir}")
    print("  python ../deepgis_topology_server.py")

if __name__ == '__main__':
    main() 