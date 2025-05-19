#!/usr/bin/env python3
"""
GLTF Model Optimizer for DeepGIS-XR

This script optimizes GLTF models by:
1. Converting GLTF to GLB binary format
2. Applying Draco compression to mesh geometry
3. Optimizing textures for web delivery
4. Generating multiple LOD (Level of Detail) variants

Requirements:
- gltfpack (https://github.com/zeux/meshoptimizer)
- draco-encoder (https://github.com/google/draco)
- Python Pillow (for texture optimization)

Usage:
python optimize_gltf.py input.gltf [--output output.glb] [--quality 10] [--compress]
"""

import os
import sys
import argparse
import subprocess
import json
import shutil
from pathlib import Path
from PIL import Image
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('gltf-optimizer')

class GLTFOptimizer:
    """Optimize GLTF files for web deployment"""
    
    def __init__(self):
        self.check_dependencies()
    
    def check_dependencies(self):
        """Check if required tools are installed"""
        try:
            # Check gltfpack
            subprocess.run(['gltfpack', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logger.info("✓ gltfpack found")
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.error("✗ gltfpack not found. Please install from https://github.com/zeux/meshoptimizer")
            sys.exit(1)
        
        try:
            # Check draco_encoder
            subprocess.run(['draco_encoder', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logger.info("✓ draco_encoder found")
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.warning("⚠ draco_encoder not found. Draco compression will be disabled.")
    
    def optimize_textures(self, input_dir, output_dir):
        """Optimize textures in the input directory"""
        logger.info(f"Optimizing textures in {input_dir}")
        os.makedirs(output_dir, exist_ok=True)
        
        # Process all image files
        texture_count = 0
        for file in Path(input_dir).glob("**/*"):
            if file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                try:
                    output_file = Path(output_dir) / file.name
                    # If output format is the same, optimize in place
                    if file.suffix.lower() == '.webp':
                        img = Image.open(file)
                        img.save(output_file, 'WEBP', quality=85, method=6)
                    # Otherwise convert to WebP
                    else:
                        img = Image.open(file)
                        output_file = output_file.with_suffix('.webp')
                        img.save(output_file, 'WEBP', quality=85, method=6)
                    
                    texture_count += 1
                    logger.info(f"Optimized: {file.name} → {output_file.name}")
                except Exception as e:
                    logger.error(f"Error processing texture {file}: {e}")
        
        return texture_count
    
    def convert_to_glb(self, input_file, output_file, compress=True, texture_quality=10):
        """Convert GLTF to compressed GLB using gltfpack"""
        logger.info(f"Converting {input_file} to optimized GLB")
        
        cmd = ['gltfpack', 
               '-i', input_file, 
               '-o', output_file, 
               '-tc']  # Texture compression
        
        if compress:
            cmd.append('-c')  # Mesh compression
        
        if texture_quality:
            cmd.extend(['-tq', str(texture_quality)])  # Texture quality (1-100)
        
        try:
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if process.returncode == 0:
                logger.info(f"Successfully converted to GLB: {output_file}")
                logger.info(f"Command output: {process.stdout}")
                
                # Get file sizes for comparison
                original_size = os.path.getsize(input_file)
                compressed_size = os.path.getsize(output_file)
                reduction = 100 - (compressed_size / original_size * 100)
                
                logger.info(f"Original size: {original_size/1024:.2f} KB")
                logger.info(f"Compressed size: {compressed_size/1024:.2f} KB")
                logger.info(f"Size reduction: {reduction:.2f}%")
                
                return True
            else:
                logger.error(f"Error converting GLTF to GLB: {process.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error during conversion: {e}")
            return False
    
    def create_lod_variants(self, input_file, output_dir, levels=3):
        """Create multiple LOD variants of the model"""
        logger.info(f"Creating {levels} LOD variants for {input_file}")
        os.makedirs(output_dir, exist_ok=True)
        
        # Base filename without extension
        base_name = Path(input_file).stem
        
        # Define simplification ratios for different LOD levels (higher = more decimation)
        simplify_ratios = [0, 0.5, 0.75, 0.9][:levels]
        
        variants = []
        for level, ratio in enumerate(simplify_ratios):
            lod_file = f"{output_dir}/{base_name}_LOD{level}.glb"
            
            cmd = ['gltfpack',
                   '-i', input_file,
                   '-o', lod_file,
                   '-tc']  # Texture compression
            
            # Apply simplification for all levels except level 0 (full quality)
            if level > 0:
                cmd.extend(['-si', str(ratio)])
            
            try:
                logger.info(f"Creating LOD{level} with simplification ratio {ratio}")
                process = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                if process.returncode == 0:
                    variants.append({
                        'level': level,
                        'file': lod_file,
                        'simplification': ratio,
                        'size': os.path.getsize(lod_file)
                    })
                    logger.info(f"Created LOD{level}: {lod_file} ({os.path.getsize(lod_file)/1024:.2f} KB)")
                else:
                    logger.error(f"Error creating LOD{level}: {process.stderr}")
            
            except Exception as e:
                logger.error(f"Error creating LOD variant: {e}")
        
        # Generate manifest file
        manifest = {
            'original': input_file,
            'variants': variants
        }
        
        with open(f"{output_dir}/{base_name}_manifest.json", 'w') as f:
            json.dump(manifest, f, indent=2)
        
        return variants

def main():
    parser = argparse.ArgumentParser(description='Optimize GLTF models for web deployment')
    parser.add_argument('input_file', help='Input GLTF file')
    parser.add_argument('--output', '-o', help='Output GLB file')
    parser.add_argument('--compress', '-c', action='store_true', help='Apply Draco compression')
    parser.add_argument('--quality', '-q', type=int, default=10, help='Texture quality (1-100)')
    parser.add_argument('--lod', '-l', action='store_true', help='Generate LOD variants')
    parser.add_argument('--optimize-textures', '-t', action='store_true', help='Optimize textures')
    
    args = parser.parse_args()
    
    optimizer = GLTFOptimizer()
    
    input_path = Path(args.input_file)
    if not input_path.exists():
        logger.error(f"Input file not found: {args.input_file}")
        sys.exit(1)
    
    # Determine output file if not specified
    output_file = args.output or str(input_path.with_suffix('.glb'))
    
    # Convert to optimized GLB
    if not optimizer.convert_to_glb(args.input_file, output_file, args.compress, args.quality):
        logger.error("Optimization failed")
        sys.exit(1)
    
    # Generate LOD variants if requested
    if args.lod:
        output_dir = Path(output_file).parent / 'lod'
        optimizer.create_lod_variants(args.input_file, output_dir)
    
    # Optimize textures if requested
    if args.optimize_textures:
        input_dir = input_path.parent
        output_dir = Path(output_file).parent / 'textures_optimized'
        optimizer.optimize_textures(input_dir, output_dir)
    
    logger.info(f"Optimization complete: {output_file}")

if __name__ == "__main__":
    main() 