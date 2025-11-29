# Cesium vs Leaflet Tile Compatibility

## Overview

Since tiles work correctly in Leaflet, we need to ensure they display correctly in Cesium. Both use Web Mercator (EPSG:3857) projection, but there are some differences to consider.

## Tile Coordinate Systems

### Leaflet
- **Format**: XYZ (standard Web Mercator)
- **Y-axis**: Increases from top to bottom (north to south)
- **Zoom levels**: 0-22+ (standard numbering)
- **URL format**: `{z}/{x}/{y}.png`

### Cesium
- **Format**: XYZ (Web Mercator) - same as Leaflet
- **Y-axis**: Increases from top to bottom (same as Leaflet)
- **Zoom levels**: 0-22+ (same numbering as Leaflet)
- **TilingScheme**: `WebMercatorTilingScheme()` - uses XYZ format

### TMS (Tile Map Service)
- **Format**: TMS (alternative format)
- **Y-axis**: **INVERTED** - increases from bottom to top
- **Conversion**: `y_tms = (2^zoom - 1) - y_xyz`

## Key Finding: No Transformation Needed! ✅

**TileServer GL serves tiles in XYZ format** (same as Leaflet), and Cesium's `WebMercatorTilingScheme()` also uses XYZ format. Therefore:

1. ✅ **Zoom levels**: No transformation needed - both use same numbering (0-22+)
2. ✅ **Y-axis**: No flip needed - both use same orientation (top-to-bottom)
3. ✅ **X-axis**: No transformation needed
4. ✅ **Projection**: Both use Web Mercator (EPSG:3857)

## Current Implementation

The current code correctly uses:

```javascript
const provider = new Cesium.UrlTemplateImageryProvider({
  url: tileUrl,  // Format: https://mbtiles.deepgis.org/data/{layerId}/{z}/{x}/{y}.png
  maximumLevel: finalMaxZoom,
  minimumLevel: finalMinZoom,
  tilingScheme: new Cesium.WebMercatorTilingScheme(),  // ✅ Correct - uses XYZ format
  // ...
});
```

**This is correct!** `WebMercatorTilingScheme()` uses XYZ format, which matches:
- Leaflet's tile format
- TileServer GL's tile format
- Standard Web Mercator tile conventions

## Verification

To verify tiles are displaying correctly:

1. **Check tile URLs in browser network tab**:
   - Should see requests like: `https://mbtiles.deepgis.org/data/bf_aug_2020_raster/15/5242/12667.png`
   - Format: `{z}/{x}/{y}.png` (XYZ format)

2. **Compare with Leaflet**:
   - Same tile URL should work in both Leaflet and Cesium
   - Same zoom level should show same geographic area
   - Tiles should align correctly

3. **Check for flipped/misaligned tiles**:
   - If tiles appear flipped vertically → might need Y-axis flip
   - If tiles appear in wrong location → might need coordinate transformation
   - If tiles don't appear → check zoom level limits

## If Tiles Appear Flipped (Edge Case)

If tiles appear flipped vertically in Cesium (unlikely with TileServer GL), you would need to:

```javascript
// Option 1: Use custom tiling scheme with flipped Y
const tilingScheme = new Cesium.WebMercatorTilingScheme();
// Override tileXYToRectangle to flip Y if needed

// Option 2: Transform Y coordinate in URL
// Modify tileUrl to flip Y: y_flipped = (2^z - 1) - y
```

**However, this should NOT be necessary** because:
- TileServer GL serves XYZ format (not TMS)
- Cesium's WebMercatorTilingScheme uses XYZ format
- Both match Leaflet's format

## Zoom Level Handling

### Leaflet Zoom → Cesium Level
- **No transformation needed** - they use the same numbering
- Leaflet zoom 15 = Cesium level 15
- Both represent the same geographic scale

### Setting Zoom Limits
```javascript
// From metadata (TileServer GL TileJSON)
minimumLevel: metadata.minzoom || 0,  // e.g., 0
maximumLevel: metadata.maxzoom || 22,  // e.g., 18

// Cesium will only request tiles within this range
// This prevents 404 errors for unavailable zoom levels
```

## Summary

✅ **No transformations needed** for tiles that work in Leaflet:
- Zoom levels: Same numbering (0-22+)
- Y-axis: Same orientation (top-to-bottom)
- X-axis: Same orientation (left-to-right)
- Projection: Both use Web Mercator (EPSG:3857)
- Format: Both use XYZ tile format

The current implementation is correct and should display tiles properly in Cesium, matching how they appear in Leaflet.

## Troubleshooting

If tiles don't display correctly:

1. **Check tile URL format**:
   - Should be: `{z}/{x}/{y}.png` (XYZ format)
   - Not: `{z}/{x}/{y_tms}.png` (TMS format)

2. **Check zoom level limits**:
   - Verify `minimumLevel` and `maximumLevel` match metadata
   - Check browser console for 404 errors

3. **Check tile server response**:
   - Verify tileserver returns tiles for requested zoom levels
   - Check CORS headers if tiles don't load

4. **Check coordinate alignment**:
   - Compare tile coordinates between Leaflet and Cesium
   - Should request same `{z}/{x}/{y}` for same geographic area

