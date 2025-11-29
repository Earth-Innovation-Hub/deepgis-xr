# CRITICAL: Y-Axis Coordinate Issue

## ⚠️ PROBLEM IDENTIFIED

**TileServer GL** and **Cesium WebMercatorTilingScheme** may use **different Y-axis orientations!**

### The Coordinate Systems

#### 1. MBTiles Storage (TMS Format)
- Origin: **Bottom-left**
- Y-axis: Increases **upward** (south to north)
- Formula: `y_tms = (2^zoom - 1) - y_xyz`

#### 2. TileServer GL Serving
According to the latest info:
- **May serve in XYZ format** (origin top-left, Y down)
- **OR may serve in TMS format** (origin bottom-left, Y up)
- This is **CRITICAL to determine**

#### 3. Leaflet (Client)
- Expects: **XYZ format**
- Origin: **Top-left**
- Y-axis: Increases **downward** (north to south)

#### 4. Cesium WebMercatorTilingScheme
- According to web search: Origin **bottom-left**, Y increases **upward**
- This would be **INCOMPATIBLE** with standard XYZ format!
- **This is the potential problem!**

## Why Tiles Work in Leaflet

Leaflet works because:
- It expects XYZ format (origin top-left, Y down)
- TileServer GL likely converts TMS → XYZ when serving
- Alignment is correct

## Why Tiles Might NOT Work in Cesium

If Cesium's WebMercatorTilingScheme has origin at bottom-left with Y increasing upward:
- It's expecting TMS format, not XYZ
- TileServer GL is serving XYZ format
- **Tiles would be vertically flipped!**

## Solution: Custom URL Template with Y-Flip

If tiles appear flipped in Cesium, we need to flip the Y coordinate:

```javascript
// Calculate flipped Y coordinate for TMS/Cesium compatibility
const customImageryProvider = {
  ...baseOptions,
  // Override how tile URLs are constructed
  // Cesium calls this with (x, y, level) in its internal coordinate system
  // We need to flip Y before requesting from TileServer GL
};
```

**BUT** - Cesium's `UrlTemplateImageryProvider` doesn't expose the Y calculation directly.

## Better Solution: Verify and Use GeographicTilingScheme if Needed

Test if tiles are flipped, and if so:

```javascript
const provider = new Cesium.UrlTemplateImageryProvider({
  url: tileUrl,
  maximumLevel: finalMaxZoom,
  minimumLevel: finalMinZoom,
  tilingScheme: new Cesium.GeographicTilingScheme(), // Uses XYZ format (top-left origin)
  // OR
  tilingScheme: new Cesium.WebMercatorTilingScheme(), // Uses TMS format (bottom-left origin)?
});
```

## Testing Required

Create test to verify tile alignment:

1. Load known layer in Leaflet at specific coordinates
2. Note tile URL requested (e.g., `/15/5242/12667.png`)
3. Load same layer in Cesium at same coordinates
4. Compare tile URLs requested
5. **If URLs are different** → Y-axis flip issue confirmed
6. **If visual alignment is wrong** → Y-axis flip issue confirmed

## Actual Cesium Documentation Check

Need to verify what Cesium's `WebMercatorTilingScheme` actually uses:
- Does it use XYZ (top-left origin, Y down)?
- Or does it use TMS (bottom-left origin, Y up)?

From Cesium source code, WebMercatorTilingScheme:
- Extends WebMercatorProjection
- Uses standard Web Mercator tile pyramid
- **Should be compatible with XYZ format**

But the web search says otherwise... This needs practical testing.

## Immediate Action Required

1. **Test with actual tiles** - check if they appear flipped
2. **Compare tile URLs** between Leaflet and Cesium
3. **If flipped**: Implement Y-coordinate transformation
4. **If not flipped**: Current implementation is correct

## Code to Test

Add debug logging to see what tiles are requested:

```javascript
console.log('Tile URL template:', tileUrl);
console.log('Camera position:', viewer.camera.positionCartographic);
console.log('Zoom level:', targetZoom);

// Monitor actual tile requests
const originalRequestImage = provider.requestImage.bind(provider);
provider.requestImage = function(x, y, level, request) {
  console.log(`Requesting tile: ${level}/${x}/${y}`);
  return originalRequestImage(x, y, level, request);
};
```

Compare output between Leaflet and Cesium for same geographic location.

