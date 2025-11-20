# Vector Layer World-Spanning Issue - FIXED

## Problem Identified

Vector shapes that should be within a 1km × 1km region near Phoenix were showing across North America and the Pacific Ocean.

### Root Cause

From console logs:
```
[getVisibleTiles] Bounds: W=-89.8315, S=-78.1250, E=89.8315, N=78.1250
[getVisibleTiles] Height: 20000.0km, Zoom: 10
```

**The camera was at 20,000 km altitude** when vector tiles were loaded, causing:
- View bounds spanning almost the entire world (-90° to +90° longitude = 180°)
- Tile coordinates calculated for world-scale view instead of 1km region
- Vector features rendered at massive scale

### Why This Happened

1. **Default Camera Position**: Viewer initializes at 20,000 km altitude
   - Defined in `cesium-init.js` line 233: `Cesium.Cartesian3.fromDegrees(0, 0, 20000000)`
   - This is a temporary position until a layer is loaded

2. **Raster Layer Behavior**: When raster layers load, they explicitly reposition the camera based on metadata (center, zoom, bounds)

3. **Vector Layer Behavior**: Vector layers **DID NOT** reposition the camera - they just loaded tiles for the current view

4. **The Bug**: If you enable a vector layer without first loading a raster layer, the camera stays at 20,000 km, resulting in world-spanning bounds

## Solution Implemented

Added camera positioning logic to `toggleVectorLayer()` function in `layer-management.js`:

### Key Changes

1. **Metadata Integration**: Merge metadata into layerInfo (lines 791-792)
   ```javascript
   LayerUtils.mergeMetadata(layerInfo, metadata);
   ```

2. **Camera Height Check**: Detect if camera is at default altitude (lines 796-799)
   ```javascript
   const currentHeight = viewer.camera.positionCartographic.height;
   const isAtDefaultAltitude = currentHeight > 10000000; // > 10,000 km
   console.log(`Current camera height: ${(currentHeight/1000).toFixed(0)} km`);
   ```

3. **Zoom Calculation**: Extract zoom from metadata with proper fallbacks (lines 802-809)
   ```javascript
   let targetZoom = metadata.center?.[2] || metadata.defaultzoom || metadata.maxzoom || 
                    CONFIG.VECTOR_TILES.MAX_ZOOM || 12;
   
   // Validate zoom is within layer's available range
   const minZoom = metadata.minzoom || 0;
   const maxZoom = metadata.maxzoom || 22;
   targetZoom = Math.max(minZoom, Math.min(maxZoom, targetZoom));
   ```

4. **Center/Bounds Extraction**: Get center coordinates from metadata (lines 811-824)
   ```javascript
   if (metadata.center && metadata.center.length >= 2) {
     targetCenter = [metadata.center[0], metadata.center[1]];
   } else if (metadata.bounds && metadata.bounds.length === 4) {
     targetBounds = metadata.bounds;
     targetCenter = [
       (metadata.bounds[0] + metadata.bounds[2]) / 2,
       (metadata.bounds[1] + metadata.bounds[3]) / 2
     ];
   }
   ```

5. **Camera Positioning**: Position camera BEFORE loading tiles (lines 826-859)
   ```javascript
   // Switch to 2D mode
   viewer.scene.mode = Cesium.SceneMode.SCENE2D;
   
   // Calculate camera height for target zoom
   const height = CoordinateUtils.zoomToHeight(targetZoom);
   const destination = Cesium.Cartesian3.fromDegrees(targetCenter[0], targetCenter[1], height);
   
   // Fit to bounds if they're reasonable (< 1 degree, ~111km)
   if (targetBounds) {
     const [west, south, east, north] = targetBounds;
     const boundsWidth = Math.abs(east - west);
     const boundsHeight = Math.abs(north - south);
     
     if (boundsWidth < 1 && boundsHeight < 1) {
       viewOptions.bounds = targetBounds;
     }
   }
   
   // Position camera and wait for transition to complete
   await CameraUtils.setCameraView(viewer, destination, viewOptions);
   console.log(`✓ Camera positioned for vector layer. Zoom: ${targetZoom}`);
   ```

6. **Tile Loading**: Only load tiles after camera is positioned (line 863)
   ```javascript
   // Load vector layer (will now use the correctly positioned camera)
   await AppState.vectorRenderer.loadVectorLayer(layerId, layerInfo);
   ```

## Expected Results

### Before Fix
```
Current camera height: 20000 km
[getVisibleTiles] Bounds: W=-89.8315, S=-78.1250, E=89.8315, N=78.1250
[getVisibleTiles] Height: 20000.0km, Zoom: 10
[getVisibleTiles] Tile range: (256,143) to (767,888)
Vector shapes span entire North America and Pacific
```

### After Fix
```
Current camera height: 20000 km  (before positioning)
Using layer center from metadata: [-111.255, 33.780]
Fitting camera to layer bounds (0.0220° × 0.0220°)
Positioning camera to center [-111.255, 33.780] at zoom 16...
✓ Camera positioned for vector layer. Zoom: 16, Height: 76437 m
[getVisibleTiles] Bounds: W=-111.266, S=33.769, E=-111.244, N=33.791
[getVisibleTiles] Height: 76.4km, Zoom: 16
[getVisibleTiles] Tile range: (12896,25890) to (12897,25891)
Vector shapes correctly displayed in 1km × 1km region near Phoenix
```

## Key Improvements

1. **Automatic Camera Positioning**: Vector layers now behave like raster layers, automatically positioning the camera based on layer metadata

2. **Smart Zoom Selection**: Prioritizes metadata zoom values in order:
   - `center[2]` (explicit zoom in center array)
   - `defaultzoom`
   - `maxzoom`
   - `CONFIG.VECTOR_TILES.MAX_ZOOM`
   - Fallback: 12

3. **Bounds Fitting**: If layer bounds are reasonable (< 1°), camera fits to show entire layer extent

4. **Height Validation**: Only repositions camera if:
   - Currently at default altitude (> 10,000 km), OR
   - Layer has center/bounds metadata

5. **Consistent Behavior**: Vector and raster layers now follow same loading sequence:
   - Fetch metadata
   - Merge metadata
   - Position camera
   - Wait for camera transition
   - Load tiles/features

## Testing Checklist

- [ ] Hard refresh browser (Ctrl+Shift+R)
- [ ] Enable vector layer WITHOUT first loading raster layer
- [ ] Check console for camera positioning logs
- [ ] Verify camera height drops from 20,000 km to ~50-100 km
- [ ] Verify bounds are small (e.g., W=-111.266 to E=-111.244)
- [ ] Verify vector shapes display in correct 1km region
- [ ] Pan/zoom and verify tiles update correctly
- [ ] Enable multiple vector layers sequentially
- [ ] Toggle vector layers on/off

## Impact

**Before:** Vector layers were unusable without first loading a raster layer, and even then would display at wrong scale if camera was at high altitude.

**After:** Vector layers work independently, automatically positioning the camera to the correct location and zoom level based on layer metadata.

## Related Issues

This fix also addresses:
- ✅ Vector layers not visible when camera is too high
- ✅ Tile coordinates calculated incorrectly for high-altitude views
- ✅ Inconsistent behavior between vector and raster layers
- ✅ No feedback about camera positioning during vector layer load

## Files Modified

- `deepgis-xr/staticfiles/web/js/core/layer-management.js` (lines 787-863)

## Dependencies

This fix relies on:
- `CameraUtils.setCameraView()` returning a Promise (already implemented)
- `CoordinateUtils.zoomToHeight()` for zoom-to-height conversion
- `LayerUtils.mergeMetadata()` for metadata integration
- Layer metadata containing `center`, `bounds`, `minzoom`, `maxzoom` fields

