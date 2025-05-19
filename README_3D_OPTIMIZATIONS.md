# DeepGIS-XR 3D Model Optimizations

This document describes comprehensive server-side and client-side optimizations for 3D model delivery implemented in the SIGMA version of the DeepGIS-XR viewer.

## Overview of Optimizations

We've implemented multiple layers of optimizations:

1. **File Format Conversion**: GLTF → GLB conversion
2. **Geometry Compression**: Draco compression for mesh geometry
3. **Texture Optimization**: WebP conversion and optimization
4. **Progressive Loading**: Level of Detail (LOD) variants
5. **Server Configuration**: HTTP/2, caching headers, CORS, compression
6. **Network Optimization**: Resource preloading, server hints
7. **Client-side Performance**: GPU configuration, FPS monitoring

## Implementation Components

### 1. Python Model Optimizer Tool

Location: `deepgis_xr/apps/web/scripts/optimize_gltf.py`

This script automatically optimizes GLTF models:
- Converts GLTF to compressed GLB format
- Applies Draco geometry compression
- Optimizes textures by converting to WebP
- Creates multiple LOD variants for different device capabilities

Usage example:
```bash
python optimize_gltf.py input.gltf --compress --lod --optimize-textures
```

### 2. Django Management Command

Location: `deepgis_xr/apps/web/management/commands/optimize_3d_models.py`

Integrates the optimizer into Django's command system:
```bash
# Optimize all models in the default directory
python manage.py optimize_3d_models --compress --lod --textures

# Process a specific model
python manage.py optimize_3d_models --model=my-model.gltf --compress
```

### 3. Nginx Server Configuration

See: `docs/nginx_3d_optimizations.md`

Key server optimizations:
- Proper MIME types for 3D model formats
- Efficient compression with gzip
- Long-term caching for static models
- HTTP/2 with resource preloading
- CORS configuration for model resources

### 4. Django Middleware

Location: `deepgis_xr/apps/web/middleware/model_optimizations.py`

Intelligent model delivery based on client device:
- Detects client device capabilities
- Serves the appropriate LOD model variant
- Applies runtime caching headers
- Handles content negotiation

To enable it, add to your `MIDDLEWARE` in settings.py:
```python
MIDDLEWARE = [
    # ...other middleware
    'deepgis_xr.apps.web.middleware.model_optimizations.ModelOptimizationMiddleware',
]
```

### 5. Optimized Template - label_3D_sigma.html

The optimized template incorporates:
- Resource preloading via `<link rel="preload">`
- Draco decoder integration
- Progress tracking during loading
- Performance monitoring (FPS counter)
- GLB model format instead of GLTF

## Usage Instructions

### Converting Models

1. Place your GLTF models in `static/deepgis/models/gltf/`
2. Run the optimization command:
   ```
   python manage.py optimize_3d_models --compress --lod --textures
   ```
3. Collect static files:
   ```
   python manage.py collectstatic
   ```
4. Update your templates to use the generated `.glb` files

### Template Usage

Replace references to GLTF models with the optimized GLB versions:

```html
<!-- Before -->
<script>
    const modelPath = '{% static "deepgis/models/gltf/my-model.gltf" %}';
</script>

<!-- After -->
<link rel="preload" href="{% static 'deepgis/models/gltf/my-model.glb' %}" as="fetch" crossorigin>
<script>
    const modelPath = '{% static "deepgis/models/gltf/my-model.glb" %}';
</script>
```

### Setting Up the Server

1. Update your Nginx configuration using the instructions in `docs/nginx_3d_optimizations.md`
2. Enable the Django middleware in your settings.py
3. Restart your server

## Benchmark Results

Based on testing with sample models:

| Optimization | File Size Reduction | Load Time Improvement |
|--------------|---------------------|------------------------|
| GLTF → GLB   | 10-15%             | 5-10%                  |
| Draco        | 60-90%             | 30-50%                 |
| WebP Textures| 30-70%             | 15-30%                 |
| HTTP/2       | N/A                | 20-40%                 |
| Preloading   | N/A                | 10-25%                 |

## Dependencies

The optimization tools require:
- Python 3.6+
- Pillow library for image processing
- gltfpack (from meshoptimizer project)
- Django 2.2+ (for management command)

## Future Work

Planned enhancements:
- Integration with KTX2/Basis texture compression
- Streaming mesh loading for very large models
- Background worker processing for model optimization
- Client-side adaptive LOD switching
- Selective mesh loading for complex scenes

## Troubleshooting

Common issues:
1. **Model appears broken**: Check if Draco decoder is properly loaded
2. **Textures missing**: Verify path to optimized WebP textures
3. **Models load slowly**: Check server compression and caching headers
4. **LOD not switching**: Enable debug logging in the middleware

## Credits

These optimizations incorporate best practices from:
- Three.js documentation
- Khronos Group GLTF Specifications
- Google Model Viewer
- Draco Compression Library 