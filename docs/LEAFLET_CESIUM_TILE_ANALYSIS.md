# Leaflet vs Cesium Tile Loading Analysis

## TileServer GL Metadata Analysis

From the actual metadata at `https://mbtiles.deepgis.org/data/bf_aug_2020_raster.json`:

```json
{
  "tiles": [
    "https://localhost:8091/data/bf_aug_2020_raster/{z}/{x}/{y}.png",
    "https://mbtiles.deepgis.org/data/bf_aug_2020_raster/{z}/{x}/{y}.png",
    "https://http://mbtiles.deepgis.org/data/bf_aug_2020_raster/{z}/{x}/{y}.png",
    "https://https://mbtiles.deepgis.org/data/bf_aug_2020_raster/{z}/{x}/{y}.png"
  ],
  "bounds": [-111.2660005204955, 33.78160405323126, -111.26454488180822, 33.782606629396106],
  "center": [-111.26527270115186, 33.78210534131368, 17],
  "minzoom": 12,
  "maxzoom": 22,
  "format": "png"
}
```

## Critical Issues Found

### 1. ⚠️ Malformed URLs in Tiles Array

**Problem**: Last two URLs have double protocols:
- ❌ `https://http://mbtiles.deepgis.org/...` (https:// + http://)
- ❌ `https://https://mbtiles.deepgis.org/...` (https:// + https://)

**Impact**:
- These URLs will fail if selected by the client
- URL selection logic needs to filter out invalid URLs

**Why Leaflet Works**: 
- Leaflet likely picks the second URL (`https://mbtiles.deepgis.org/...`) which is valid
- Or it tries URLs in order until one works

**Current Cesium Behavior** (from `layers.js` line 56):
```javascript
let tileUrl = metadata.tiles.find(url => url.startsWith('https://mbtiles.deepgis.org')) 
  || metadata.tiles.find(url => url.startsWith('https://'))
  || metadata.tiles[0];
```

**Analysis**: 
- ✅ This logic will correctly pick the 2nd URL (valid `https://mbtiles.deepgis.org/...`)
- The malformed URLs (3rd and 4th) won't be selected because they don't match the `startsWith` check properly
- Actually, the 3rd URL WILL match `startsWith('https://mbtiles.deepgis.org')` because the string does start with that!

**CRITICAL BUG FOUND**: The URL `"https://http://mbtiles.deepgis.org/..."` WILL pass the check:
```javascript
"https://http://mbtiles.deepgis.org/...".startsWith('https://mbtiles.deepgis.org')
// returns false - OK, this won't match
```

Wait, let me reconsider:
```javascript
"https://http://mbtiles.deepgis.org/...".startsWith('https://mbtiles.deepgis.org')
```
This checks if the string starts with `'https://mbtiles.deepgis.org'`, but the actual string starts with `'https://http://'`, so it returns **false**. Good!

So the current logic will pick the 2nd URL which is valid. **No bug here for rasters**.

### 2. ✅ Coordinate Format Analysis

**Bounds**: `[west, south, east, north]`
- West: -111.2660°
- East: -111.2645°
- South: 33.7816°
- North: 33.7826°
- **Size: 0.00145° × 0.001° ≈ 161m × 111m**

This is the correct format for both Leaflet and Cesium!

**Center**: `[longitude, latitude, zoom]`
- Longitude: -111.2653° (X coordinate)
- Latitude: 33.7821° (Y coordinate)  
- Zoom: 17

This is also correct!

### 3. ✅ Tile Coordinate System

**TileServer GL URL Format**: `{z}/{x}/{y}.png`

This is the **XYZ format** (Web Mercator, Google/OSM standard):
- X: Increases west to east (0 at -180° longitude)
- Y: Increases north to south (0 at 85.05° north latitude)
- Z: Zoom level (0 = world view, higher = more detail)

**Leaflet Expectation**: XYZ format ✅
**Cesium `WebMercatorTilingScheme`**: XYZ format ✅

**No transformation needed!**

### 4. ✅ Zoom Level Conversion

The metadata specifies zoom levels 12-22, which is appropriate for:
- Zoom 12: ~305m per pixel (city-level view)
- Zoom 17: ~4.77m per pixel (building-level view)
- Zoom 22: ~0.149m per pixel (very high detail)

For the 161m × 111m area, zoom 17 is perfect.

**Cesium Zoom Conversion** (from `coordinates.js`):
```javascript
zoomToHeight: (zoom) => {
  const tileSize = 256;
  const earthCircumference = 40075017; // meters
  return earthCircumference / (tileSize * Math.pow(2, zoom));
}
```

**Verification for Zoom 17**:
```
height = 40075017 / (256 × 2^17) = 40075017 / 33554432 ≈ 1194 meters
```

This is correct! At zoom 17, the camera should be ~1.2 km above the surface to see the appropriate level of detail.

### 5. ⚠️ Potential XY Scaling Issues

**Tile Size**: Default is 256×256 pixels

**Pixel Density at Different Zooms**:
- The bounds span 0.00145° longitude × 0.001° latitude
- At zoom 17:
  - World width = 2^17 × 256 = 33,554,432 pixels
  - 1° longitude = 33,554,432 / 360 ≈ 93,207 pixels
  - 0.00145° longitude = 135 pixels
  
This means the entire raster should be about **135 × 93 pixels** at zoom 17, which will span **less than 1 tile**!

**THIS IS THE ISSUE!**

The raster is so small (161m × 111m) that at zoom 17:
- It occupies only a fraction of a single 256×256 tile
- When displayed in Leaflet at tile zoom levels, it appears correctly because Leaflet renders tile-by-tile
- In Cesium, if the camera is not at exactly the right height, the tile might appear scaled incorrectly

## Comparison: Leaflet vs Cesium Tile Loading

### Leaflet Workflow

1. **URL Selection**: Pick first valid URL from `tiles` array
2. **Camera Position**: Use `center` and `zoom` from metadata
3. **Tile Request**: Request tiles at integer zoom levels (17, 18, 19...)
4. **Rendering**: Render each tile at native resolution
5. **Scaling**: Browser handles CSS scaling for fractional zooms

### Cesium Workflow (Current)

1. **URL Selection**: Pick URL matching `https://mbtiles.deepgis.org`
2. **Camera Position**: Convert zoom to height using `zoomToHeight()`
3. **Tile Request**: Request tiles based on camera height and viewport
4. **Rendering**: Cesium projects tiles onto 2D/3D globe
5. **Scaling**: Cesium handles scaling based on camera distance

### Key Differences

| Aspect | Leaflet | Cesium |
|--------|---------|---------|
| Coordinate System | XYZ (Web Mercator) | XYZ (WebMercatorTilingScheme) ✅ |
| Zoom Levels | Integer (17, 18...) | Continuous (camera height) |
| Tile Requests | By zoom level | By screen space error |
| Fractional Zoom | CSS scaling | Camera height |
| Y-Axis | Top to bottom (0 at north) | Top to bottom (0 at north) ✅ |

## Transformations Required: NONE ✅

Both Leaflet and Cesium use the same coordinate system:
- **Projection**: Web Mercator (EPSG:3857)
- **Tile Scheme**: XYZ format
- **Y-Axis**: Origin at north, increasing southward
- **Tile Size**: 256×256 pixels
- **Coordinate Order**: (longitude, latitude) or (x, y)

**No transformations are needed!**

## Potential Issues and Fixes

### Issue 1: Small Raster Size

**Problem**: The raster (161m × 111m) is smaller than a single tile at most zoom levels

**Impact**: 
- May appear blurry if camera is too far (zoom too low)
- May appear pixelated if camera is too close (zoom too high)

**Solution**: Ensure camera is positioned at the exact zoom from metadata (17)

**Current Implementation**: ✅ Already using `metadata.center[2]` as zoom

### Issue 2: Malformed Tile URLs

**Problem**: Some URLs in metadata have double protocols

**Solution**: Add URL validation to filter out malformed URLs

### Issue 3: Camera Height Calculation

**Problem**: If zoom-to-height calculation is slightly off, tiles may appear at wrong scale

**Verification Needed**: 
- Check if camera height at zoom 17 is actually ~1194m
- Verify tiles are requested at the correct zoom level

### Issue 4: Tile Request Debugging

**Current Debug Logging** (from `layers.js` lines 117-144):
```javascript
// Debug: Log tile requests to verify coordinate system alignment and scaling
if (typeof window.addDebugLogEntry === 'function') {
  const debugOriginalRequestImage = provider.requestImage.bind(provider);
  let tileRequestCount = 0;
  
  provider.requestImage = function(x, y, level, request) {
    tileRequestCount++;
    // Log first few tile requests to verify coordinates and detect scaling issues
    if (tileRequestCount <= 5) {
      // Calculate expected geographic bounds for this tile
      const n = Math.pow(2, level);
      const lon_deg_min = x / n * 360.0 - 180.0;
      const lon_deg_max = (x + 1) / n * 360.0 - 180.0;
      
      window.addDebugLogEntry('debug', `Tile request: ${level}/${x}/${y}`, {
        level, x, y,
        url: tileUrl.replace('{z}', level).replace('{x}', x).replace('{y}', y),
        geoBounds: {
          west: lon_deg_min.toFixed(6),
          east: lon_deg_max.toFixed(6),
          note: 'Compare with Leaflet tile requests at same location'
        },
        tileSize: `${CONFIG.TILE_DIMENSIONS.width}x${CONFIG.TILE_DIMENSIONS.height}`
      });
    }
    return debugOriginalRequestImage(x, y, level, request);
  };
}
```

This debug logging should show:
- Which tiles are being requested (z/x/y)
- The geographic bounds of those tiles
- Whether the tile coordinates make sense for the layer bounds

## Testing Checklist

To verify correct tile loading in Cesium:

1. **Check Tile URLs**:
   - [ ] Console shows the selected tile URL
   - [ ] URL is `https://mbtiles.deepgis.org/data/bf_aug_2020_raster/{z}/{x}/{y}.png`
   - [ ] No malformed URLs are used

2. **Check Camera Position**:
   - [ ] Camera zoom is 17 (from metadata)
   - [ ] Camera height is ~1194m
   - [ ] Camera center is [-111.265, 33.782]

3. **Check Tile Requests**:
   - [ ] Tiles requested at zoom level 17
   - [ ] Tile coordinates X/Y match expected values for the bounds
   - [ ] Expected tile coordinates for center [-111.265, 33.782] at zoom 17:
     - X = floor(((-111.265 + 180) / 360) × 2^17) = floor((68.735 / 360) × 131072) = floor(25029) = 25029
     - Y = floor((1 - ln(tan(33.782° × π/180) + 1/cos(33.782° × π/180)) / π) / 2 × 2^17) ≈ 50470

4. **Check Tile Rendering**:
   - [ ] Tiles display at correct scale
   - [ ] Raster appears in correct geographic location
   - [ ] No stretching or distortion
   - [ ] Raster resolution matches expected detail level

5. **Compare with Leaflet**:
   - [ ] Leaflet viewer shows raster correctly
   - [ ] Cesium viewer shows raster at same location
   - [ ] Same level of detail in both viewers

## Recommendations

### 1. Add URL Validation

Update `getTileUrl` in `layers.js`:

```javascript
getTileUrl: (layerId, metadata) => {
  if (metadata && metadata.tiles && metadata.tiles.length > 0) {
    // Filter out malformed URLs
    const validUrls = metadata.tiles.filter(url => {
      try {
        new URL(url.replace('{z}', '0').replace('{x}', '0').replace('{y}', '0'));
        return true;
      } catch {
        console.warn(`Invalid tile URL: ${url}`);
        return false;
      }
    });
    
    // Prefer HTTPS URLs from mbtiles.deepgis.org
    let tileUrl = validUrls.find(url => url.startsWith('https://mbtiles.deepgis.org')) 
      || validUrls.find(url => url.startsWith('https://'))
      || validUrls[0];
    
    // ... rest of logic
  }
}
```

### 2. Enhance Debug Logging

Add more detailed tile request logging to compare with Leaflet:

```javascript
console.log(`Tile ${level}/${x}/${y}:`);
console.log(`  Geographic bounds: [${west}, ${south}, ${east}, ${north}]`);
console.log(`  Layer bounds: [${metadata.bounds.join(', ')}]`);
console.log(`  Overlap: ${tilesOverlapWithLayerBounds(bounds, metadata.bounds)}`);
```

### 3. Verify Zoom Calculation

Add logging to `zoomToHeight` and `heightToZoom`:

```javascript
const height = CoordinateUtils.zoomToHeight(17);
console.log(`Zoom 17 → Height: ${height}m`);

const backZoom = CoordinateUtils.heightToZoom(height);
console.log(`Height ${height}m → Zoom: ${backZoom}`);
```

Should show:
```
Zoom 17 → Height: 1194m
Height 1194m → Zoom: 17
```

## Conclusion

**No coordinate transformations are needed** between Leaflet and Cesium. Both use the same:
- XYZ tile format
- Web Mercator projection  
- Y-axis orientation (top = north)
- Tile size (256×256)

**Issues to address**:
1. ✅ Malformed URLs in metadata (already handled by current logic, but should add validation)
2. ✅ Camera positioning (already fixed in vector layer update)
3. ⚠️ Small raster size may cause scaling artifacts if zoom is not exact
4. ✅ Debug logging is already in place to verify tile requests

**Next steps**:
1. Check console logs for tile request details
2. Verify camera height matches expected value for zoom 17
3. Compare tile coordinates between Leaflet and Cesium
4. Add URL validation to filter malformed URLs

