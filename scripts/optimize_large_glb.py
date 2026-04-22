#!/usr/bin/env python3
"""
Optimize large GLB models for web delivery
Specifically designed for the 140MB Navagunjara model
"""

import os
import sys
import subprocess
import json
import shutil
from pathlib import Path

def check_dependencies():
    """Check if required tools are installed"""
    required_tools = {
        'gltf-pipeline': 'npm install -g gltf-pipeline',
        'meshoptimizer': 'Download from https://github.com/zeux/meshoptimizer',
        'draco_encoder': 'Download from https://github.com/google/draco'
    }
    
    missing = []
    for tool, install_cmd in required_tools.items():
        if shutil.which(tool) is None:
            missing.append(f"{tool}: {install_cmd}")
    
    if missing:
        print("Missing required tools:")
        for tool in missing:
            print(f"  - {tool}")
        return False
    return True

def optimize_glb_model(input_path, output_dir):
    """
    Optimize a large GLB model for web delivery
    
    Args:
        input_path: Path to the original GLB file
        output_dir: Directory to save optimized versions
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    base_name = input_path.stem
    
    print(f"Optimizing {input_path.name} ({input_path.stat().st_size / 1024 / 1024:.1f} MB)")
    
    # 1. Create Draco compressed version
    draco_output = output_dir / f"{base_name}_draco.glb"
    print("Creating Draco compressed version...")
    
    try:
        subprocess.run([
            'gltf-pipeline',
            '-i', str(input_path),
            '-o', str(draco_output),
            '--draco.compressionLevel', '10',
            '--draco.quantizePositionBits', '14',
            '--draco.quantizeNormalBits', '10',
            '--draco.quantizeTexcoordBits', '12',
            '--draco.quantizeColorBits', '8',
            '--draco.quantizeGenericBits', '12'
        ], check=True)
        
        draco_size = draco_output.stat().st_size / 1024 / 1024
        original_size = input_path.stat().st_size / 1024 / 1024
        compression_ratio = (1 - draco_size / original_size) * 100
        
        print(f"✓ Draco compressed: {draco_size:.1f} MB ({compression_ratio:.1f}% reduction)")
        
    except subprocess.CalledProcessError as e:
        print(f"✗ Draco compression failed: {e}")
        draco_output = None
    
    # 2. Create LOD versions
    lod_levels = [
        {'name': 'LOD0', 'simplify': 1.0, 'description': 'Full quality'},
        {'name': 'LOD1', 'simplify': 0.7, 'description': 'High quality'},
        {'name': 'LOD2', 'simplify': 0.4, 'description': 'Medium quality'},
        {'name': 'LOD3', 'simplify': 0.2, 'description': 'Low quality'},
        {'name': 'LOD4', 'simplify': 0.1, 'description': 'Very low quality'}
    ]
    
    lod_files = {}
    
    for lod in lod_levels:
        lod_output = output_dir / f"{base_name}_{lod['name']}.glb"
        print(f"Creating {lod['name']} ({lod['description']})...")
        
        try:
            # Use meshoptimizer for LOD generation
            subprocess.run([
                'gltf-pipeline',
                '-i', str(draco_output if draco_output else input_path),
                '-o', str(lod_output),
                '--meshopt.simplify', str(lod['simplify']),
                '--meshopt.compressTextures'
            ], check=True)
            
            lod_size = lod_output.stat().st_size / 1024 / 1024
            print(f"✓ {lod['name']}: {lod_size:.1f} MB")
            
            lod_files[lod['name']] = {
                'file': lod_output.name,
                'size_mb': lod_size,
                'simplify_ratio': lod['simplify'],
                'description': lod['description']
            }
            
        except subprocess.CalledProcessError as e:
            print(f"✗ {lod['name']} generation failed: {e}")
    
    # 3. Create manifest file
    manifest = {
        'original': {
            'file': input_path.name,
            'size_mb': input_path.stat().st_size / 1024 / 1024
        },
        'optimized': {
            'draco': {
                'file': draco_output.name if draco_output else None,
                'size_mb': draco_output.stat().st_size / 1024 / 1024 if draco_output else None
            },
            'lod_levels': lod_files
        },
        'usage_recommendations': {
            'mobile': 'LOD3 or LOD4',
            'desktop': 'LOD1 or LOD2',
            'high_end': 'LOD0 or Draco',
            'vr': 'LOD2 or LOD3'
        }
    }
    
    manifest_file = output_dir / f"{base_name}_manifest.json"
    with open(manifest_file, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"✓ Manifest created: {manifest_file}")
    
    # 4. Create usage instructions
    instructions = f"""
# Usage Instructions for {base_name}

## File Sizes:
- Original: {manifest['original']['size_mb']:.1f} MB
- Draco compressed: {manifest['optimized']['draco']['size_mb']:.1f} MB
- LOD levels: {len(lod_files)} variants

## Recommended Usage:

### In your HTML template:
```html
<!-- Preload the appropriate model -->
<link rel="preload" href="/static/deepgis/models/gltf/{base_name}_LOD2.glb" as="fetch" crossorigin>

<!-- For mobile devices -->
<script>
const isMobile = /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
const modelPath = isMobile ? 
    '/static/deepgis/models/gltf/{base_name}_LOD3.glb' :
    '/static/deepgis/models/gltf/{base_name}_LOD1.glb';
</script>
```

### In your Cesium code:
```javascript
// Progressive loading with fallback
async function loadNavagujaraModel() {{
    const models = [
        '/static/deepgis/models/gltf/{base_name}_draco.glb',
        '/static/deepgis/models/gltf/{base_name}_LOD1.glb',
        '/static/deepgis/models/gltf/{base_name}_LOD2.glb',
        '/static/deepgis/models/gltf/{base_name}_LOD3.glb'
    ];
    
    for (const modelUrl of models) {{
        try {{
            const tileset = await Cesium.Cesium3DTileset.fromUrl(modelUrl);
            return tileset;
        }} catch (error) {{
            console.warn(`Failed to load ${{modelUrl}}, trying next...`);
        }}
    }}
    throw new Error('All model variants failed to load');
}}
```

## File Locations:
Place optimized files in: `deepgis-xr/deepgis_xr/static/deepgis/models/gltf/`
"""
    
    instructions_file = output_dir / f"{base_name}_usage.md"
    with open(instructions_file, 'w') as f:
        f.write(instructions)
    
    print(f"✓ Usage instructions: {instructions_file}")
    print("\nOptimization complete!")
    
    return manifest

def main():
    if len(sys.argv) != 3:
        print("Usage: python optimize_large_glb.py <input_glb> <output_directory>")
        print("Example: python optimize_large_glb.py navagunjara-v4.glb ./optimized/")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_dir = sys.argv[2]
    
    if not os.path.exists(input_file):
        print(f"Error: Input file {input_file} not found")
        sys.exit(1)
    
    if not check_dependencies():
        print("\nInstall missing dependencies and try again.")
        sys.exit(1)
    
    try:
        manifest = optimize_glb_model(input_file, output_dir)
        print(f"\nOptimization summary:")
        print(f"Original size: {manifest['original']['size_mb']:.1f} MB")
        if manifest['optimized']['draco']['size_mb']:
            print(f"Draco compressed: {manifest['optimized']['draco']['size_mb']:.1f} MB")
        print(f"LOD variants: {len(manifest['optimized']['lod_levels'])}")
        
    except Exception as e:
        print(f"Error during optimization: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 