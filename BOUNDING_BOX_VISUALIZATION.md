# Bounding Box Visualization Mode

## Overview

Replaced complex tile loading with simple bounding box visualization to verify coordinate system, camera positioning, and bounds interpretation are working correctly before dealing with tile rendering complexity.

## What Was Changed

### Raster Layers (`loadBaseRasterLayer`)

**Before**: Loaded actual raster tiles through `UrlTemplateImageryProvider`

**After**: Draws bounding box rectangle with:
- **Cyan semi-transparent fill** (alpha 0.3)
- **Cyan outline** (width 3)
- **Red center point marker** with layer name label
- **Info panel** showing bounds, size, zoom info when clicked

### Vector Layers (`toggleVectorLayer`)

**Before**: Loaded vector tile features through `VectorLayerRenderer`

**After**: Draws bounding box rectangle with:
- **Lime/Green semi-transparent fill** (alpha 0.3)
- **Lime outline** (width 3)
- **Yellow center point marker** with layer name label
- **Info panel** showing bounds, size, zoom info when clicked

## What Still Works

✅ **Metadata fetching** - Layer metadata still loaded from TileServer GL  
✅ **Camera positioning** - Camera still positions based on layer center/bounds  
✅ **Coordinate calculations** - All zoom/height/bounds calculations still execute  
✅ **URL validation** - Malformed URLs still filtered out  
✅ **Error handling** - All error handling and logging preserved  
✅ **Layer management** - Add/remove layers, toggle on/off  

## What Was Removed

❌ **Tile requests** - No HTTP requests for actual tile images  
❌ **ImageryProvider** - No Cesium imagery layers created  
❌ **Tile rendering** - No actual raster/vector data displayed  
❌ **Memory management** - Chunked loading, tile caching removed  
❌ **Tile error handling** - No tile-specific error tracking  

## Benefits

### 1. Immediate Verification

You can now instantly see:
- **Bounds location**: Is the box in the right place?
- **Bounds size**: Is the box the right size?
- **Camera position**: Does the camera fly to the correct location?
- **Coordinate system**: Are coordinates interpreted correctly (no flipping/inversion)?

### 2. Performance

- No network requests for tiles
- No tile rendering overhead
- Instant layer loading
- Can enable multiple layers simultaneously

### 3. Debugging

Clear visual feedback about:
- Layer geographic extent
- Whether bounds from metadata are correct
- If coordinate transformations are working
- Camera positioning accuracy

## How to Use

1. **Load a raster layer**: Check "BF_08-02-2020_raster"
   - Should see **cyan box** at location
   - Camera should fly to center
   - Box should be ~161m × 111m near Phoenix

2. **Load a vector layer**: Check "BF_08-02-2020.mbtiles"
   - Should see **lime/green box** at same location
   - Camera should position to layer bounds
   - Box should overlap with raster box

3. **Click on box**: Info panel shows:
   - Exact bounds coordinates
   - Box size in km/m
   - Center coordinates
   - Zoom range from metadata

4. **Verify alignment**:
   - Do raster and vector boxes overlap correctly?
   - Are they both in Phoenix area (~33.78°N, -111.26°W)?
   - Are box sizes reasonable (< 1 km)?

## Expected Results

### Raster Layer (BF_08-02-2020_raster)

```
Camera positioned at:
- Center: [-111.26527, 33.78210]
- Zoom: 17
- Height: ~1,194m

Bounding box:
- West: -111.266001°
- South: 33.781604°
- East: -111.264545°
- North: 33.782607°
- Size: 0.161 km × 0.111 km (161m × 111m)
```

### Vector Layer (BF_08-02-2020.mbtiles)

```
Camera positioned at:
- Same center and zoom as raster

Bounding box:
- Should overlap/match raster box
- Same size: ~161m × 111m
- Same location: Phoenix area
```

## Console Output

You should see logs like:

```javascript
// Raster layer
Fetching metadata for layer: bf_aug_2020_raster
✓ Metadata loaded and validated
Using layer center from metadata: [-111.265, 33.782]
Positioning camera to center [-111.265, 33.782] at zoom 17...
✓ Camera positioned for vector layer. Zoom: 17, Height: 1194 m
Drawing bounding box: W=-111.266, S=33.782, E=-111.265, N=33.783
Bounds size: 0.001456° × 0.001002° (0.16 km × 0.11 km)
✓ Bounding box created for BF_08-02-2020_raster

// Vector layer
Current camera height: 1194 km
Using layer center from metadata: [-111.265, 33.782]
Positioning camera to center [-111.265, 33.782] at zoom 17...
✓ Camera positioned for vector layer. Zoom: 17, Height: 1194 m
Drawing vector bounding box: W=-111.266, S=33.782, E=-111.265, N=33.783
Bounds size: 0.001456° × 0.001002° (161.90 m × 111.48 m)
✓ Vector bounding box created for BF_08-02-2020.mbtiles
```

## Troubleshooting

### Box is in wrong location
- Check bounds in metadata
- Verify coordinate order (west, south, east, north)
- Check if coordinates need transformation

### Box is wrong size
- Check if degrees are being interpreted correctly
- Verify bounds calculation (east - west, north - south)
- Check projection (should be WGS84 degrees)

### Box is flipped/inverted
- Check Y-axis orientation
- Verify north > south
- Check if TMS vs XYZ coordinate system

### Camera doesn't position correctly
- Check zoom-to-height calculation
- Verify center coordinates from metadata
- Check if camera await is working

### Box doesn't appear
- Check console for errors
- Verify data source was added
- Check entity creation logs
- Verify bounds are valid numbers

## Next Steps

Once bounding boxes display correctly:

1. ✅ Coordinates are correct
2. ✅ Camera positioning works
3. ✅ Bounds are interpreted correctly
4. ✅ No coordinate system issues

Then you can:
- Re-enable actual tile loading
- Debug tile requests knowing coordinates are correct
- Add proper tile rendering
- Implement proper vector tile parsing

## Reverting to Tile Loading

To restore tile loading, revert the changes to:
- `layer-management.js` (lines 548-630 for raster, lines 862-948 for vector)
- Replace bounding box code with original imagery provider / vector renderer code

Or keep both modes and add a config flag:
```javascript
if (CONFIG.DEBUG.BOUNDING_BOX_MODE) {
  // Draw bounding box
} else {
  // Load tiles
}
```

## Color Scheme

- **Cyan (Raster)**: `Cesium.Color.CYAN` - RGB(0, 255, 255)
  - Fill: Alpha 0.3 (semi-transparent)
  - Outline: Alpha 1.0 (solid)
  - Center: Red point

- **Lime/Green (Vector)**: `Cesium.Color.LIME` - RGB(0, 255, 0)
  - Fill: Alpha 0.3 (semi-transparent)
  - Outline: Alpha 1.0 (solid)
  - Center: Yellow point

This color scheme makes it easy to distinguish between raster and vector layers when both are loaded simultaneously.

## Files Modified

- `deepgis-xr/staticfiles/web/js/core/layer-management.js`
  - `loadBaseRasterLayer()` - Lines 548-630
  - `toggleVectorLayer()` - Lines 862-948
  - Layer removal logic updated

