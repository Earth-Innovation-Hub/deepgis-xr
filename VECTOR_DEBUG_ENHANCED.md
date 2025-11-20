# Vector Layer Debug Enhancement

## Issue Observed

From the screenshot, vector layers are loading but **0 tiles** are being calculated:
```
Loading vector layer: BF_08-02-2020.mbtiles (bf_aug_2020)
Loaded 0 vector tiles for layer bf_aug_2020  ← Problem!
```

## Root Cause Hypothesis

The fallback methods aren't being executed or logged, suggesting:
1. `computeViewRectangle()` returns `undefined` (not `null`)
2. Fallback methods fail silently
3. Tile calculation produces empty arrays

## Solution: Enhanced Logging

Added comprehensive diagnostic logging at every step:

### 1. Method Tracking
```javascript
[getVisibleTiles] Starting for layer: BF_08-02-2020.mbtiles
[getVisibleTiles] ✓ Primary method succeeded
// OR
[getVisibleTiles] Primary method failed: ...
[getVisibleTiles] Trying canvas corner fallback...
```

### 2. Bounds Calculation
```javascript
[getVisibleTiles] Method: computeViewRectangle
[getVisibleTiles] Bounds: W=-111.2933, S=33.7020, E=-111.2833, N=33.7120
[getVisibleTiles] Height: 13105.2km, Zoom: 12, Range: 0-22
```

### 3. Tile Generation
```javascript
[getVisibleTiles] Tile range: (1618,3117) to (1621,3120)
[getVisibleTiles] Tile count: 4 x 4 = 16 tiles
[getVisibleTiles] ✓ Generated 16 tiles
```

### 4. Fallback Details
```javascript
[Fallback] Canvas size: 1920x1080
[Fallback] Sampled 5/5 points
[Fallback] Created rectangle from sampled points
```

## Changes Made

### File: `staticfiles/web/js/utils/vector-tiles.js`

**Enhanced Functions:**

1. **`getVisibleTiles()`**
   - Added `[getVisibleTiles]` prefix to all logs
   - Track which method succeeded: `rectMethod` variable
   - Log bounds, zoom, height at each step
   - Log tile coordinate ranges
   - Log final tile count
   - Increased camera position offset from 0.1° to 1.0° (~111km coverage)

2. **`computeViewRectangleFallback()`**
   - Added `[Fallback]` prefix to all logs
   - Log canvas dimensions
   - Try-catch around each canvas point sample
   - Count successful samples (X/5)
   - Log rectangle creation success
   - Wrap entire function in try-catch

## Testing Instructions

### Step 1: Hard Refresh Browser
```bash
Ctrl + Shift + R  (or Cmd + Shift + R on Mac)
```

### Step 2: Open DevTools Console
Enable "Preserve log" to keep messages across page loads

### Step 3: Enable Vector Layer
Check any vector layer in the "Vector Layers" section

### Expected Console Output (Debug Mode)

**Scenario A: Primary Method Works**
```javascript
Loading vector layer: BF_08-02-2020.mbtiles (bf_aug_2020)
Initialized vector layer renderer
[getVisibleTiles] Starting for layer: BF_08-02-2020.mbtiles
[getVisibleTiles] ✓ Primary method succeeded
[getVisibleTiles] Method: computeViewRectangle
[getVisibleTiles] Bounds: W=-111.2933, S=33.7020, E=-111.2833, N=33.7120
[getVisibleTiles] Height: 13105.2km, Zoom: 8, Range: 0-22
[getVisibleTiles] Tile range: (202,389) to (202,389)
[getVisibleTiles] Tile count: 1 x 1 = 1 tiles
[getVisibleTiles] ✓ Generated 1 tiles
Loading 1 visible vector tiles for layer bf_aug_2020
Loaded 1 vector tiles for layer bf_aug_2020
```

**Scenario B: Canvas Fallback**
```javascript
[getVisibleTiles] Starting for layer: BF_08-02-2020.mbtiles
[getVisibleTiles] Primary method failed: Cannot read property 'west' of undefined
[getVisibleTiles] Trying canvas corner fallback...
[Fallback] Canvas size: 1920x1080
[Fallback] Sampled 5/5 points
[Fallback] Created rectangle from sampled points
[getVisibleTiles] ✓ Canvas corner fallback succeeded
[getVisibleTiles] Method: canvasCornerSampling
[getVisibleTiles] Bounds: W=-111.3000, S=33.6900, E=-111.2700, N=33.7200
[getVisibleTiles] Height: 13105.2km, Zoom: 8, Range: 0-22
[getVisibleTiles] Tile range: (202,389) to (202,389)
[getVisibleTiles] Tile count: 1 x 1 = 1 tiles
[getVisibleTiles] ✓ Generated 1 tiles
```

**Scenario C: Layer Bounds Fallback**
```javascript
[getVisibleTiles] Starting for layer: BF_08-02-2020.mbtiles
[getVisibleTiles] Primary method failed: ...
[getVisibleTiles] Trying canvas corner fallback...
[Fallback] Canvas size: 1920x1080
[Fallback] Sampled 0/5 points
[Fallback] No valid canvas positions found
[getVisibleTiles] Canvas corner fallback failed
[getVisibleTiles] Trying layer bounds fallback...
[getVisibleTiles] ✓ Layer bounds fallback: [-111.266, 33.769, -111.244, 33.791]
[getVisibleTiles] Method: layerBounds
[getVisibleTiles] Bounds: W=-111.2660, S=33.7690, E=-111.2440, N=33.7910
[getVisibleTiles] Height: 13105.2km, Zoom: 8, Range: 0-22
[getVisibleTiles] Tile range: (202,389) to (202,390)
[getVisibleTiles] Tile count: 1 x 2 = 2 tiles
[getVisibleTiles] ✓ Generated 2 tiles
```

**Scenario D: Camera Position Fallback**
```javascript
[getVisibleTiles] Starting for layer: BF_08-02-2020.mbtiles
[getVisibleTiles] Primary method failed: ...
[getVisibleTiles] Trying canvas corner fallback...
[Fallback] No valid canvas positions found
[getVisibleTiles] Canvas corner fallback failed
[getVisibleTiles] Trying camera position fallback...
[getVisibleTiles] ✓ Camera position fallback: [-111.2831, 33.7802]
[getVisibleTiles] Method: cameraPosition
[getVisibleTiles] Bounds: W=-112.2831, S=32.7802, E=-110.2831, N=34.7802
[getVisibleTiles] Height: 13105.2km, Zoom: 8, Range: 0-22
[getVisibleTiles] Tile range: (199,386) to (205,392)
[getVisibleTiles] Tile count: 4 x 4 = 16 tiles  ← Now generates tiles!
[getVisibleTiles] ✓ Generated 16 tiles
```

## What to Look For

### ✅ Good Signs:
- `[getVisibleTiles] ✓ Generated X tiles` where X > 0
- One of the fallback methods succeeds
- Tile range shows valid coordinates
- Colored rectangles appear on map

### ❌ Problem Indicators:
- `[getVisibleTiles] ✗ All fallback methods failed`
- `[getVisibleTiles] ✓ Generated 0 tiles`
- `[Fallback] Sampled 0/5 points`
- Tile count calculation shows 0 x 0 = 0

### 🔍 Key Metrics to Report:
1. **Which method succeeded?** (computeViewRectangle, canvasCornerSampling, layerBounds, cameraPosition)
2. **Zoom level**: Should be between layer's minzoom and maxzoom
3. **Camera height**: Very high altitude may cause issues
4. **Tile range**: Should produce at least 1 tile
5. **Bounds**: Should be reasonable geographic coordinates

## Debugging Commands

Run these in browser console to diagnose:

```javascript
// Check if viewer is ready
console.log('Viewer:', viewer);
console.log('Scene mode:', viewer.scene.mode);

// Manually test rectangle calculation
try {
  const rect = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid);
  console.log('Manual rectangle test:', rect);
} catch (e) {
  console.error('Manual rectangle test failed:', e);
}

// Test fallback method
if (AppState.vectorRenderer) {
  const fallback = AppState.vectorRenderer.computeViewRectangleFallback();
  console.log('Manual fallback test:', fallback);
}

// Check camera position
const camPos = viewer.camera.positionCartographic;
console.log('Camera position:', {
  lon: Cesium.Math.toDegrees(camPos.longitude),
  lat: Cesium.Math.toDegrees(camPos.latitude),
  height: camPos.height
});

// Force tile reload with logging
if (AppState.vectorRenderer) {
  console.log('=== FORCING TILE UPDATE ===');
  AppState.vectorRenderer.updateVisibleTiles();
}
```

## Next Steps After Testing

### If Logs Show 0 Tiles:
1. Check zoom level - might be outside layer's zoom range
2. Check camera height - might be too high (>20M km)
3. Check tile coordinate calculation - might have math error

### If Logs Show Tiles But Nothing Renders:
1. Check tile URL construction
2. Check tileserver accessibility
3. Check Cesium entity creation
4. Check layer visibility/opacity

### If All Methods Fail:
1. Scene might not be initialized
2. Camera might be in invalid state
3. Globe might not be visible

## Summary

The enhanced logging will reveal:
- ✅ **What method is used** to calculate tiles
- ✅ **Exact bounds and zoom** being computed
- ✅ **How many tiles are generated** and why
- ✅ **Which fallback works** in different scenarios

This diagnostic output will pinpoint the exact failure point in the tile calculation pipeline!

## Expected Result

After hard refresh, you should see **detailed logging** showing:
1. Which calculation method succeeded
2. Exact tile coordinates being generated
3. Non-zero tile count (1-16 tiles depending on zoom)
4. Colored rectangles appearing on the map

**If you still see 0 tiles**, the logs will show exactly which step is failing and why! 🔍

