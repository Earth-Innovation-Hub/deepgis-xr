# Critical Tile Coordinate System Analysis

## TL;DR - Found Potential Issue! ⚠️

**MBTiles stores tiles in TMS format (Y-axis inverted)**, but **TileServer GL automatically converts to XYZ when serving**. This should work correctly, but we need to verify.

## The Full Picture

### 1. MBTiles Storage Format (in database)
From `convert_rocks_to_mbtiles.py`:

```python
# Convert from XYZ (Google/OSM) to TMS (MBTiles) y-coordinate
# TMS uses inverted Y: y_tms = (2^zoom - 1) - y
y_tms = (1 << zoom) - 1 - y
```

**MBTiles specification uses TMS format:**
- Y-axis: Inverted (increases from bottom to top)
- Y coordinate formula: `y_tms = (2^zoom - 1) - y_xyz`

### 2. TileServer GL Serving Format

**TileServer GL automatically converts TMS → XYZ when serving tiles**

According to TileServer GL documentation and behavior:
- Reads tiles from MBTiles (TMS format)
- Automatically converts Y coordinate when serving
- Serves tiles in XYZ format (Web Mercator standard)

URL format served: `https://mbtiles.deepgis.org/data/{layerId}/{z}/{x}/{y}.png`
- This `{y}` is in **XYZ format** (not TMS)
- TileServer GL does the conversion internally

### 3. Leaflet Expectations

**Leaflet uses XYZ format:**
- Y-axis: Increases from top to bottom (north to south)
- Standard Web Mercator tile scheme
- URL template: `{z}/{x}/{y}.png`

**This matches what TileServer GL serves** ✅

### 4. Cesium Expectations

**Cesium's `WebMercatorTilingScheme` uses XYZ format:**
- Y-axis: Increases from top to bottom (same as Leaflet)
- Standard Web Mercator tile scheme
- Same coordinate system as Leaflet

**This also matches what TileServer GL serves** ✅

## Coordinate Handling in Current Implementation

### Latitude/Longitude → Cartesian Conversion

```javascript
// In coordinates.js
Cesium.Cartesian3.fromDegrees(longitude, latitude, height)
```

**Order:** `(longitude, latitude, height)` = `(X, Y, Z)` ✅ **Correct!**

### Metadata Format (TileJSON from TileServer GL)

```json
{
  "center": [longitude, latitude, zoom],
  "bounds": [west, south, east, north]
}
```

**Both use standard lon/lat order** ✅ **Correct!**

### Usage in Code

```javascript
// In layer-management.js
const [longitude, latitude] = targetCenter;
const destination = Cesium.Cartesian3.fromDegrees(longitude, latitude, height);
```

**Longitude comes first, latitude second** ✅ **Correct!**

```javascript
// In coordinates.js - centerToDestination
const [longitude, latitude, zoom] = center;
return Cesium.Cartesian3.fromDegrees(longitude, latitude, height);
```

**Order is correct** ✅

## Verification Checklist

### ✅ Tile Format Conversion
- MBTiles: TMS format (Y inverted)
- TileServer GL: Converts to XYZ automatically
- Leaflet: Expects XYZ ✅
- Cesium: Expects XYZ ✅

### ✅ Coordinate Order
- Metadata: `[lon, lat, zoom]` ✅
- Cesium API: `fromDegrees(lon, lat, height)` ✅
- Code uses: `(longitude, latitude)` ✅

### ✅ Bounds Format
- Metadata: `[west, south, east, north]` ✅
- Code expects: `[west, south, east, north]` ✅
- Cesium Rectangle: Uses same order ✅

### ✅ Projection
- MBTiles: Web Mercator (EPSG:3857) ✅
- TileServer GL: Web Mercator ✅
- Leaflet: Web Mercator ✅
- Cesium WebMercatorTilingScheme: Web Mercator ✅

## Testing Verification

To confirm tiles are correctly positioned:

### 1. Compare Tile Requests

**Leaflet (browser network tab):**
```
https://mbtiles.deepgis.org/data/layer_id/15/5242/12667.png
                                           z   x    y
```

**Cesium (browser network tab):**
```
https://mbtiles.deepgis.org/data/layer_id/15/5242/12667.png
                                           z   x    y
```

**They should be identical for the same geographic area!**

### 2. Visual Alignment Test

For a known location (e.g., San Francisco: -122.4, 37.8):

**In Leaflet:**
- Load layer at zoom 15
- Center at [-122.4, 37.8]
- Note which tile coordinates cover this area

**In Cesium:**
- Load same layer at level 15
- Center at same coordinates
- Should request same tile coordinates

### 3. Metadata Verification

From `https://mbtiles.deepgis.org/data/bf_aug_2020_raster.json`:

```json
{
  "center": [-122.4, 37.8, 15],
  "bounds": [-122.5, 37.7, -122.3, 37.9]
}
```

**Cesium should:**
- Position camera at lon=-122.4, lat=37.8
- Set zoom level 15
- Fit bounds correctly

## Potential Issues to Watch For

### Issue 1: Tiles Appear Flipped Vertically

**Symptom:** Features appear upside down

**Cause:** Y-axis mismatch (TMS vs XYZ)

**Solution:** TileServer GL should handle this automatically, but if it doesn't:
```javascript
// Add custom Y flip in URL template
const y_flipped = (2 ** zoom) - 1 - y;
```

**Current Status:** Should not be needed - TileServer GL converts automatically

### Issue 2: Tiles in Wrong Location

**Symptom:** Tiles appear but in wrong geographic location

**Possible Causes:**
- Latitude/longitude order swapped
- Bounds format incorrect
- Projection mismatch

**Check:**
```javascript
// Verify order in center
console.log('Center:', metadata.center); // Should be [lon, lat, zoom]

// Verify Cesium usage
console.log('Destination:', Cesium.Cartesian3.fromDegrees(lon, lat, height));
```

### Issue 3: Tiles Don't Appear

**Symptom:** No tiles load or 404 errors

**Possible Causes:**
- Zoom level out of range
- Incorrect tile URL format
- CORS issues

**Check:**
- Browser network tab for 404s
- Verify `minimumLevel` and `maximumLevel` match metadata
- Check tile URL format matches TileServer GL

## Conclusion

**The current implementation appears CORRECT:**

1. ✅ TileServer GL converts TMS → XYZ automatically
2. ✅ Both Leaflet and Cesium expect XYZ format
3. ✅ Coordinate order is correct: (longitude, latitude)
4. ✅ Bounds format is correct: [west, south, east, north]
5. ✅ Projection is correct: Web Mercator (EPSG:3857)

**No transformations should be needed.** Tiles that work in Leaflet should work in Cesium with the current implementation.

## Debugging Steps if Tiles Don't Align

1. **Check tile URLs in browser network tab** (Leaflet vs Cesium)
2. **Compare camera positions** (should be at same lat/long)
3. **Verify zoom levels** (should be same number)
4. **Check metadata format** (should be standard TileJSON)
5. **Test with known location** (e.g., downtown SF, NYC)

## References

- [MBTiles Specification](https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md) - Uses TMS format
- [TileServer GL](https://tileserver.readthedocs.io/) - Converts TMS → XYZ
- [Slippy Map Tilenames](https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames) - XYZ format
- [Cesium WebMercatorTilingScheme](https://cesium.com/learn/cesiumjs/ref-doc/WebMercatorTilingScheme.html) - Uses XYZ

