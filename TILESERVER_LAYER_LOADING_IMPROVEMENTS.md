# TileServer GL Layer Loading Improvements

## Overview

Reimplemented the tileserver layer loading to properly handle TileServer GL format from [mbtiles.deepgis.org](https://mbtiles.deepgis.org/), ensuring metadata is fetched first, map center and zoom are set from metadata before loading tiles, and only necessary tiles for the appropriate zoom level are loaded.

## Key Improvements

### 1. Metadata-First Loading Strategy

**Before**: Metadata was fetched but camera view was set using calculated values that might not match metadata.

**After**: 
- Metadata is fetched **FIRST** and validated before any tile requests
- Camera view is set using **exact values from metadata** (center, zoom, bounds)
- Only after camera is positioned correctly are tiles loaded

**Implementation**:
```javascript
// STEP 1: Fetch metadata FIRST
const metadata = await fetchLayerMetadata(layerId);

// STEP 2: Extract center/zoom from metadata
if (metadata.center && metadata.center.length >= 3) {
  targetZoom = metadata.center[2];  // Use zoom from metadata
  targetCenter = [metadata.center[0], metadata.center[1]];
}

// STEP 3: Set camera view BEFORE loading tiles
CameraUtils.setCameraView(viewer, destination, viewOptions);

// STEP 4: Wait for camera to settle
await new Promise(resolve => setTimeout(resolve, 100));

// STEP 5: Only then create provider and load tiles
const provider = LayerUtils.createImageryProvider(...);
```

### 2. Zoom Level Priority from Metadata

The system now uses a clear priority order for determining zoom level:

1. **`center[2]`** - Zoom level from center array in metadata (if available)
2. **`defaultzoom`** - Default zoom from metadata
3. **`maxzoom`** - Maximum zoom from metadata (capped for memory safety)
4. **`minzoom`** - Minimum zoom from metadata
5. **CONFIG default** - System default zoom level

This ensures the map always uses the zoom level that the layer metadata recommends.

### 3. Proper TileServer GL URL Handling

**Improvements**:
- Better URL normalization for TileServer GL format: `/data/{layerId}/{z}/{x}/{y}.{ext}`
- Validates URLs contain template variables (`{z}`, `{x}`, `{y}`)
- Handles both raster (`.png`) and vector (`.pbf`) formats
- Ensures URLs point to `mbtiles.deepgis.org` domain

**Example URLs handled**:
- `https://mbtiles.deepgis.org/data/bf_aug_2020_raster/{z}/{x}/{y}.png`
- `https://mbtiles.deepgis.org/data/bf_dec_2020_vector/{z}/{x}/{y}.pbf`

### 4. Zoom Range Enforcement

The imagery provider now strictly enforces zoom ranges from metadata:

```javascript
// Use minzoom/maxzoom from metadata
const safeMinZoom = metadata.minzoom || 0;
const safeMaxZoom = LayerUtils.calculateSafeMaxZoom(metadata.maxzoom || 22);

// Provider only loads tiles within this range
const provider = new Cesium.UrlTemplateImageryProvider({
  maximumLevel: safeMaxZoom,  // Only load tiles up to this zoom
  minimumLevel: safeMinZoom,   // Only load tiles from this zoom
  // ...
});
```

This ensures:
- No tiles are requested for zoom levels not available in the layer
- Memory is protected by capping high zoom levels
- Only necessary tiles for the current viewport are loaded

### 5. Center and Bounds Handling

**Center Priority**:
1. Use `center` array from metadata if available (with optional zoom)
2. Calculate center from `bounds` if center not available
3. Fallback to default center (0, 0)

**Bounds Usage**:
- Bounds are used for view fitting if available and reasonably sized
- World bounds are detected and avoided
- Large bounds (>30 degrees) are rejected to prevent memory issues
- Bounds fitting provides smooth transition to layer extent

## Implementation Details

### File Changes

#### `layer-management.js` - `loadBaseRasterLayer()`
- Complete rewrite with step-by-step metadata-first approach
- Added validation for metadata before proceeding
- Improved zoom level determination from metadata
- Better error handling and logging

#### `layers.js` - `getTileUrl()`
- Enhanced URL normalization for TileServer GL format
- Better handling of missing template variables
- Domain normalization to ensure correct server

#### `layers.js` - `createImageryProvider()`
- Accepts `minzoom`/`maxzoom` from options (metadata)
- Enforces zoom range limits strictly
- Better logging of zoom ranges

## Benefits

1. **Faster Initial Load**: Camera is positioned correctly before tiles load, reducing unnecessary tile requests
2. **Correct Zoom Level**: Always uses the zoom level recommended by layer metadata
3. **Memory Efficiency**: Only loads tiles for available zoom levels, preventing 404 errors
4. **Better User Experience**: Map immediately shows the correct area and zoom level
5. **TileServer GL Compatibility**: Properly handles TileServer GL format and URLs

## Testing Recommendations

1. **Test with Different Layers**: Load various layers from [mbtiles.deepgis.org](https://mbtiles.deepgis.org/) and verify:
   - Center and zoom match metadata
   - Only appropriate tiles are loaded
   - No 404 errors for unavailable zoom levels

2. **Test Metadata Priority**: Verify zoom level selection follows priority order:
   - Layers with `center[2]` use that zoom
   - Layers with `defaultzoom` use that
   - Layers with only `maxzoom` use capped maxzoom

3. **Test URL Handling**: Verify TileServer GL URLs are properly formatted:
   - Check browser network tab for correct tile URLs
   - Verify no localhost references
   - Ensure template variables are present

4. **Test Zoom Range**: Verify tiles are only requested within `minzoom`-`maxzoom` range:
   - Try zooming beyond maxzoom (should not request tiles)
   - Try zooming below minzoom (should not request tiles)

## Example Metadata Format

TileServer GL provides metadata in TileJSON format:

```json
{
  "tiles": [
    "https://mbtiles.deepgis.org/data/bf_aug_2020_raster/{z}/{x}/{y}.png"
  ],
  "bounds": [-122.5, 37.7, -122.3, 37.8],
  "center": [-122.4, 37.75, 15],
  "minzoom": 0,
  "maxzoom": 18,
  "name": "BF_08-02-2020_raster"
}
```

The implementation now properly uses all these fields to set up the layer correctly.

## Related Documentation

- [Raster Layer Timeout Analysis](./RASTER_LAYER_TIMEOUT_ANALYSIS.md) - Timeout and retry improvements
- [Raster Layer Workflow Analysis](./RASTER_LAYER_WORKFLOW_ANALYSIS.md) - Original workflow documentation
- [TileServer GL Documentation](https://github.com/maptiler/tileserver-gl) - Official TileServer GL docs

