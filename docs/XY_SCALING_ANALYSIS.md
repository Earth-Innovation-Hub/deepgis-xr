# XY Scaling Issues Analysis

## Overview

Analyzing potential XY scaling issues when displaying TileServer GL tiles (designed for Leaflet) in Cesium.

## 1. Tile Dimensions ✅

### Current Configuration
```javascript
TILE_DIMENSIONS: { width: 256, height: 256 }
```

### Leaflet Default
- **256x256 pixels** per tile (standard)

### Cesium Default
- **256x256 pixels** per tile (standard)

### TileServer GL
- Serves **256x256 pixel tiles** by default for raster

**Status:** ✅ **No scaling issue** - all use same dimensions

---

## 2. Web Mercator Extent

### Web Mercator Bounds
- **Latitude range:** -85.05112878° to +85.05112878° (not ±90°!)
- **Longitude range:** -180° to +180°
- **Projection:** EPSG:3857

### Why -85.05112878°?
Web Mercator projection becomes infinite at the poles. The practical limit is where:
```
arctan(sinh(π)) ≈ 85.05112878°
```

### Current Code Check

```javascript
// In coordinates.js - boundsToDestination
const isWorldBounds = Math.abs(west - (-180)) < 0.01 && 
                     Math.abs(east - 180) < 0.01 &&
                     Math.abs(south - (-85.0511)) < 0.01 &&  // ✅ Correct limit
                     Math.abs(north - 85.0511) < 0.01;       // ✅ Correct limit
```

**Status:** ✅ **Correct** - uses proper Web Mercator limits

---

## 3. Tile Coordinate Calculations

### XYZ Tile Calculation (Standard)

For a given lat/lon and zoom level:

```javascript
// Longitude to tile X
n = 2^zoom
x = floor((lon + 180) / 360 * n)

// Latitude to tile Y (XYZ format)
y = floor((1 - ln(tan(lat_rad) + sec(lat_rad)) / π) / 2 * n)
```

### Web Mercator Projection Formula

```javascript
// Lon/Lat to Web Mercator meters
x_meters = lon * 20037508.34 / 180
y_meters = ln(tan((90 + lat) * π / 360)) / (π / 180) * 20037508.34 / 180
```

### Cesium's Implementation

Cesium uses `WebMercatorTilingScheme` which:
- Uses standard Web Mercator projection
- Divides world into 2^zoom tiles in each direction
- Each tile covers: `(2 * π * Earth_radius) / (256 * 2^zoom)` meters

**Potential Issue:** If Cesium and Leaflet use slightly different projection formulas, tiles could be misaligned.

---

## 4. Rectangle/Bounds Scaling

### Cesium Rectangle

```javascript
Cesium.Rectangle.fromDegrees(west, south, east, north)
```

This converts degrees to radians internally and creates a rectangle in geodetic coordinates.

### Bounds Fitting

```javascript
// In camera.js
viewer.camera.flyTo({
  destination: Cesium.Rectangle.fromDegrees(west, south, east, north),
  // ...
});
```

**Potential Issue:** If bounds are very small (< 0.001 degrees), floating point precision could cause issues.

---

## 5. High DPI / Retina Display

### Leaflet
- Detects device pixel ratio
- Can request higher resolution tiles (512x512 for 2x displays)
- Option: `tileSize: 256, zoomOffset: 0`

### Cesium
- Uses device pixel ratio for rendering
- Tile dimensions stay at 256x256
- Scales internally for high DPI

### Current Configuration
```javascript
tileWidth: 256,   // Physical tile size, not display size
tileHeight: 256,
```

**Potential Issue:** On retina displays, tiles might appear pixelated if Cesium doesn't scale them properly.

**Solution:** Cesium handles this automatically through its rendering pipeline.

---

## 6. Zoom Level to Scale Calculation

### Leaflet Zoom to Scale
```javascript
scale = 256 * 2^zoom pixels per 360 degrees longitude
```

At zoom 0:
- 1 tile (256px) = entire world (360°)
- Scale: 256 pixels / 40,075,017 meters (Earth circumference)

At zoom 15:
- 2^15 = 32,768 tiles across
- Scale: ~1.19 meters per pixel

### Cesium Height to Zoom

```javascript
// In coordinates.js
zoomToHeight: (zoom) => {
  return CONFIG.DEFAULT_ZOOM_HEIGHT_BASE / Math.pow(2, zoom);
}

// DEFAULT_ZOOM_HEIGHT_BASE = 40,000,000 meters
```

At zoom 0:
- Height: 40,000,000 meters (~10x Earth radius)

At zoom 15:
- Height: 40,000,000 / 2^15 = ~1,221 meters

**Potential Issue:** The relationship between Cesium camera height and Leaflet zoom may not be exactly equivalent.

### Verification Needed

For the same geographic area:
- Leaflet at zoom 15 should show same detail as
- Cesium at height ~1,221 meters

**If mismatch:** Tiles at different detail levels would be requested, causing apparent scaling issues.

---

## 7. Coordinate Precision

### JavaScript Number Precision
- 64-bit floating point (double precision)
- ~15-17 significant decimal digits

### At Equator
- 1 degree longitude ≈ 111,320 meters
- JavaScript precision: ~0.00000000000001° ≈ 0.000001 mm

**Status:** ✅ More than sufficient precision for tile coordinates

---

## 8. Tile Boundary Calculations

### Potential Rounding Issues

```javascript
// Tile boundaries must align exactly
// Otherwise, sub-pixel gaps or overlaps occur

// Cesium calculates tile rectangle as:
west = tile_x * tileWidth / 2^zoom * 360° - 180°
east = (tile_x + 1) * tileWidth / 2^zoom * 360° - 180°
```

**Potential Issue:** If tileWidth doesn't match actual tile size, scaling problems occur.

**Current:** `tileWidth: 256` matches actual tile size ✅

---

## 9. Testing for Scaling Issues

### Visual Tests

1. **Grid Alignment Test**
   - Load a layer with grid lines (lat/lon graticule)
   - Check if grid lines align with expected coordinates
   - Look for drift or distortion

2. **Known Feature Test**
   - Load layer with known landmarks (e.g., building)
   - Verify feature appears at correct coordinates
   - Check if feature is distorted or stretched

3. **Multi-Zoom Test**
   - View same area at multiple zoom levels
   - Verify tiles align consistently
   - Look for "tile creep" (shifting at different zooms)

### Measurement Tests

```javascript
// Log tile requests and compare
console.log('Camera position:', {
  lon: Cesium.Math.toDegrees(viewer.camera.positionCartographic.longitude),
  lat: Cesium.Math.toDegrees(viewer.camera.positionCartographic.latitude),
  height: viewer.camera.positionCartographic.height
});

// Calculate expected zoom from height
const zoom = Math.log2(CONFIG.DEFAULT_ZOOM_HEIGHT_BASE / height);
console.log('Equivalent zoom:', zoom);

// Compare tile URLs between Leaflet and Cesium
```

---

## 10. Known Scaling Issues to Watch For

### Issue 1: Zoom/Height Mismatch

**Symptom:** Tiles appear at wrong resolution (too zoomed in/out)

**Cause:** `zoomToHeight` formula doesn't match Cesium's internal zoom calculation

**Check:**
```javascript
// At a specific location, compare:
// - Leaflet zoom level
// - Cesium camera height
// - Tiles requested by each
```

**Fix:** Adjust `DEFAULT_ZOOM_HEIGHT_BASE` to match Cesium's actual zoom behavior

### Issue 2: Tile Boundary Misalignment

**Symptom:** Gaps between tiles, or tile overlaps

**Cause:** Incorrect tile boundary calculations

**Check:** Verify `tileWidth` and `tileHeight` match actual tile size

**Current:** 256x256 ✅

### Issue 3: Projection Differences

**Symptom:** Features slightly offset from correct position

**Cause:** Subtle differences in Web Mercator implementation

**Check:** Compare coordinates of known feature in Leaflet vs Cesium

**Fix:** Ensure both use same projection (EPSG:3857)

### Issue 4: Rectangle Scaling

**Symptom:** Bounds fitting doesn't cover correct area

**Cause:** Incorrect conversion between degrees and Cesium's rectangle

**Check:**
```javascript
const [west, south, east, north] = bounds;
const rect = Cesium.Rectangle.fromDegrees(west, south, east, north);
console.log('Rectangle:', {
  west: Cesium.Math.toDegrees(rect.west),
  south: Cesium.Math.toDegrees(rect.south),
  east: Cesium.Math.toDegrees(rect.east),
  north: Cesium.Math.toDegrees(rect.north)
});
```

---

## 11. Current Implementation Review

### Tile Size ✅
```javascript
tileWidth: CONFIG.TILE_DIMENSIONS.width,   // 256
tileHeight: CONFIG.TILE_DIMENSIONS.height, // 256
```
**Status:** Correct - matches standard

### Tiling Scheme ✅
```javascript
tilingScheme: new Cesium.WebMercatorTilingScheme()
```
**Status:** Correct - uses Web Mercator

### Zoom Calculation ⚠️
```javascript
zoomToHeight: (zoom) => {
  return CONFIG.DEFAULT_ZOOM_HEIGHT_BASE / Math.pow(2, zoom);
}
```
**Status:** May need verification - ensure this matches Cesium's actual zoom behavior

---

## 12. Recommendations

### Immediate Actions

1. **Test at Known Location**
   - Load layer at specific coordinates (e.g., San Francisco: -122.4, 37.8)
   - Compare tile requests between Leaflet (zoom 15) and Cesium (height ~1221m)
   - Verify same tiles are requested

2. **Add Zoom/Height Logging**
   ```javascript
   console.log('Zoom to Height conversion:', {
     zoom: targetZoom,
     calculatedHeight: CoordinateUtils.zoomToHeight(targetZoom),
     actualHeight: viewer.camera.positionCartographic.height,
     difference: Math.abs(CoordinateUtils.zoomToHeight(targetZoom) - 
                         viewer.camera.positionCartographic.height)
   });
   ```

3. **Verify Tile Dimensions Match**
   - Check actual tile file dimensions (should be 256x256)
   - Verify TileServer GL serves 256x256 tiles

### Potential Adjustments

If scaling issues are found:

1. **Adjust DEFAULT_ZOOM_HEIGHT_BASE**
   ```javascript
   // Current: 40,000,000
   // May need: Different value based on testing
   ```

2. **Add Tile Size Override**
   ```javascript
   // If TileServer GL serves different size tiles
   tileWidth: 512,  // For high-res tiles
   tileHeight: 512,
   ```

3. **Use Custom Tiling Scheme**
   ```javascript
   // If standard WebMercatorTilingScheme doesn't work
   // Create custom scheme with adjusted parameters
   ```

---

## Summary

**Likely Status:** ✅ **No scaling issues expected**

- Tile dimensions: 256x256 (standard) ✅
- Projection: Web Mercator EPSG:3857 ✅
- Coordinate precision: Sufficient ✅
- Bounds handling: Correct ✅

**Main Uncertainty:** Zoom-to-height conversion

The `DEFAULT_ZOOM_HEIGHT_BASE` of 40,000,000 meters needs verification that it produces the correct tile requests at each zoom level.

**Testing Required:** Load a layer and compare tile URLs between Leaflet and Cesium at the same location.

