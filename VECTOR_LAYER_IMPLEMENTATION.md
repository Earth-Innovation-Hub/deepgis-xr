# Vector Layer Implementation for Cesium Viewer

## Overview

This implementation adds support for Mapbox Vector Tiles (MVT/PBF) to the Cesium-based `label_topology` viewer, enabling visualization of vector layers from the TileServer GL instance at https://mbtiles.deepgis.org/.

## What Was Implemented

### 1. **Vector Tile Utilities** (`staticfiles/web/js/utils/vector-tiles.js`)
   - `VectorTileParser`: Fetches and caches vector tiles from the tileserver
   - `VectorLayerRenderer`: Renders vector tiles as Cesium entities
   - Tile management with progressive loading
   - Support for polygons, linestrings, and points
   - Configurable styling per layer

### 2. **Configuration Updates** (`staticfiles/web/js/config.js`)
   - Added `VECTOR_TILES` configuration section
   - Layer-specific color schemes for different vector layers
   - Performance limits (max zoom, tile cache, etc.)

### 3. **Layer Management** (`staticfiles/web/js/core/layer-management.js`)
   - `toggleVectorLayer()`: Load/unload vector layers
   - Auto-population of vector layer UI controls
   - Opacity and visibility controls for vector layers
   - Integration with existing layer management system

### 4. **UI Updates** (`templates/web/label_topology.html`)
   - Added "Vector Layers" section in sidebar
   - Checkboxes for each available vector layer
   - Opacity sliders for vector layers
   - Visual distinction (purple border) for vector layer controls

### 5. **State Management** (`staticfiles/web/js/state.js`)
   - Added `vectors` object to track active vector layers
   - Added `vectorRenderer` instance holder

## Available Vector Layers

From https://mbtiles.deepgis.org/, the following vector layers should be available:

1. **BF_08-02-2020** (`bf_aug_2020`) - Orange colored
2. **BF_10-03-2020** (`bf_oct_2020`) - Green colored
3. **BF_12-20-2020_vector** (`bf_dec_2020_vector`) - Purple colored
4. **BF_2-15-2021_3d** (`bf_feb_2021_3d`) - Yellow colored

## How to Test

### Step 1: Access the Application

Navigate to the label_topology viewer:
```
https://your-domain/label_topology/
```

### Step 2: Locate Vector Layer Controls

In the sidebar, look for the **"Vector Layers"** section (highlighted with purple border).

### Step 3: Enable a Vector Layer

1. Check the checkbox next to a vector layer (e.g., "BF_08-02-2020")
2. The opacity slider will appear
3. Watch the status indicator for loading progress

### Step 4: What to Expect

**Current Implementation (Placeholder Visualization):**
- Vector tiles are fetched from the tileserver
- **Tile bounding boxes** are rendered as colored rectangles
- Each tile shows as a semi-transparent colored rectangle
- Colors are assigned per layer (see configuration)
- Hover over rectangles to see tile coordinates (z/x/y)

**Why Bounding Boxes?**
The current implementation renders tile boundaries as placeholders because:
- Full MVT parsing requires external libraries (`@mapbox/vector-tile`, `pbf`)
- This demonstrates the tile loading system is working
- Shows proper integration with Cesium's entity system
- Validates tile URL construction and fetching

### Step 5: Test Multiple Layers

1. Enable multiple vector layers simultaneously
2. Adjust opacity sliders to see layering effects
3. Different colors should help distinguish layers
4. Zoom in/out to see tile loading at different zoom levels

### Step 6: Verify in Console

Open browser DevTools Console and look for:

```javascript
// Layer initialization
"Loaded 4 vector layers"

// Layer activation
"Loading vector layer: BF_08-02-2020 (bf_aug_2020)"
"Loading 16 visible vector tiles for layer bf_aug_2020"
"Loaded 16 vector tiles for layer bf_aug_2020"

// Tile fetching
"Vector tile received, size: 12345 bytes"
```

### Step 7: Performance Testing

1. Start in 2D mode at high altitude (world view)
2. Enable a vector layer - should see ~4-16 tiles
3. Zoom in progressively
4. Tile count should increase but stay within limits
5. Check `CONFIG.VECTOR_TILES.MAX_TILES_PER_DIMENSION` (4x4 = max 16 tiles)

## Known Limitations

### Current Implementation

1. **Placeholder Visualization**: Renders tile boundaries, not actual features
2. **No Feature Properties**: Cannot display attributes or click for info
3. **Basic Styling**: Uses simple colors, no property-based styling
4. **Limited Geometry**: No multi-polygons or complex geometries yet

### Performance Constraints

1. **Max Zoom**: Limited to zoom level 14 to prevent overload
2. **Tile Limits**: Maximum 16 tiles visible at once (4x4 grid)
3. **No Clustering**: High-density features not optimized
4. **Memory**: Vector entities consume more memory than raster tiles

## Upgrading to Full MVT Support

To render actual vector features (not just boundaries), add these dependencies:

### Option 1: Using External Libraries

```bash
npm install @mapbox/vector-tile pbf
```

Then update `vector-tiles.js`:

```javascript
import VectorTile from '@mapbox/vector-tile';
import Pbf from 'pbf';

async parseVectorTile(arrayBuffer) {
  const pbf = new Pbf(arrayBuffer);
  const tile = new VectorTile(pbf);
  
  const features = [];
  Object.keys(tile.layers).forEach(layerName => {
    const layer = tile.layers[layerName];
    for (let i = 0; i < layer.length; i++) {
      const feature = layer.feature(i);
      features.push({
        geometry: feature.loadGeometry(),
        properties: feature.properties,
        type: feature.type
      });
    }
  });
  
  return { features, layers: tile.layers, parsed: true };
}
```

### Option 2: Server-Side Conversion

Convert vector tiles to GeoJSON on the server and serve as simplified features:

```python
# In Django view
import mapbox_vector_tile

def get_vector_tile_geojson(request, layer_id, z, x, y):
    # Fetch tile from tileserver
    tile_data = fetch_tile(layer_id, z, x, y)
    
    # Decode MVT to GeoJSON
    features = mapbox_vector_tile.decode(tile_data)
    
    # Simplify and return
    return JsonResponse({
        'type': 'FeatureCollection',
        'features': features
    })
```

## Troubleshooting

### Vector Layers Not Appearing

1. **Check tileserver access**: 
   ```bash
   curl https://mbtiles.deepgis.org/data.json
   ```

2. **Verify layer format**:
   - Vector layers must have `format: "pbf"`
   - Check console for "Loaded X vector layers"

3. **CORS issues**:
   - Ensure tileserver allows cross-origin requests
   - Check browser console for CORS errors

### Tiles Not Loading

1. **Zoom level**: Vector tiles may not be available at all zoom levels
2. **Bounds**: Layer may have specific geographic bounds
3. **Check tile URLs**: Console logs should show constructed URLs
4. **Network tab**: Verify tile requests return 200 status

### Performance Issues

1. **Reduce max zoom**: Edit `CONFIG.VECTOR_TILES.MAX_ZOOM` (default: 14)
2. **Limit tile dimensions**: Edit `MAX_TILES_PER_DIMENSION` (default: 4)
3. **Clear cache**: `AppState.vectorRenderer.parser.clearCache()`
4. **Disable other layers**: Too many active layers can cause slowdown

## Integration with Existing Code

The vector layer system integrates cleanly with existing features:

- ✅ Works alongside raster layers
- ✅ Compatible with 2D/3D/Columbus views
- ✅ Uses existing status indicators and logging
- ✅ Respects memory management settings
- ✅ Lazy-loaded on first use (no startup overhead)

## API Reference

### VectorLayerRenderer

```javascript
const renderer = new VectorLayerRenderer(viewer);

// Load a vector layer
await renderer.loadVectorLayer(layerId, layerInfo);

// Remove a vector layer
await renderer.removeVectorLayer(layerId);

// Control visibility
renderer.setLayerVisibility(layerId, true/false);

// Control opacity
renderer.setLayerOpacity(layerId, 0.0-1.0);

// Cleanup
renderer.cleanup();
```

### Configuration

```javascript
CONFIG.VECTOR_TILES = {
  ENABLED: true,
  MAX_ZOOM: 14,
  MAX_CACHED_TILES: 100,
  MAX_TILES_PER_DIMENSION: 4,
  DEFAULT_STYLE: { /* colors, opacity, etc */ },
  FEATURE_STYLES: {
    'layer_id': { /* layer-specific styling */ }
  }
};
```

## Success Criteria

✅ Vector layers appear in sidebar
✅ Clicking checkbox loads vector layer
✅ Tile boundaries render as colored rectangles
✅ Multiple layers can be active simultaneously
✅ Opacity controls work
✅ Console shows tile loading messages
✅ No JavaScript errors
✅ Performance remains acceptable (< 30ms frame time)

## Next Steps

1. ✅ **Basic Infrastructure**: Tile loading, UI, configuration
2. 🚧 **Full MVT Parsing**: Add @mapbox/vector-tile library
3. ⏳ **Feature Rendering**: Convert geometries to Cesium entities
4. ⏳ **Interaction**: Click handlers, property display
5. ⏳ **Advanced Styling**: Property-based colors, sizes
6. ⏳ **Clustering**: Optimize high-density features
7. ⏳ **3D Extrusion**: Height-based feature extrusion

## Summary

The vector layer implementation provides a **working foundation** for MVT support in Cesium. While it currently renders tile boundaries as placeholders, the architecture is in place for full feature rendering once MVT parsing is added. The system demonstrates successful integration with the tileserver, proper tile coordinate calculation, and seamless integration with the existing application architecture.

For production use with actual vector features, add the MVT parsing libraries as described in the "Upgrading to Full MVT Support" section.

