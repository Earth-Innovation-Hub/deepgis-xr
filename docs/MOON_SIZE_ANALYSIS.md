# Moon Size and Scale Analysis

**Date:** 2025-11-21

## Moon's Actual Dimensions

### Physical Measurements
- **Mean radius:** 1,737.4 km = **1,737,400 meters**
- **Equatorial radius (a):** 1,738.1 km = 1,738,100 meters
- **Polar radius (c):** 1,736.0 km = 1,736,000 meters
- **Ellipticity:** Very small (~0.0012)

The Moon is nearly spherical compared to Earth.

---

## Cesium.Ellipsoid.MOON Definition

Cesium defines the Moon ellipsoid as:

```javascript
Cesium.Ellipsoid.MOON = Object.freeze(
    new Cesium.Ellipsoid(1737400.0, 1737400.0, 1737400.0)
);
```

**Cesium uses a perfect sphere with radius 1,737,400 meters.**

---

## Your Implementation - Status Check

### ✅ Correct Usage
You're consistently using `Cesium.Ellipsoid.MOON`:

1. **Globe ellipsoid** (line 1342):
```javascript
viewer.scene.globe.ellipsoid = Cesium.Ellipsoid.MOON;
```

2. **Tiling scheme** (line 1409):
```javascript
tilingScheme: new Cesium.GeographicTilingScheme({
    numberOfLevelZeroTilesX: 2,
    numberOfLevelZeroTilesY: 1,
    ellipsoid: Cesium.Ellipsoid.MOON  // ✅
}),
```

3. **Terrain provider** (line 1570):
```javascript
viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider({
    ellipsoid: Cesium.Ellipsoid.MOON  // ✅
});
```

4. **Position calculations** (lines 1595, 1692, 1735, 1755, 1780):
```javascript
Cesium.Cartesian3.fromDegrees(lon, lat, height, Cesium.Ellipsoid.MOON)  // ✅
```

---

## Scale Comparison: Moon vs Earth

| Property | Earth | Moon | Ratio |
|----------|-------|------|-------|
| Mean radius | 6,371,000 m | 1,737,400 m | **3.67× larger** |
| Surface area | 510.1 M km² | 37.9 M km² | **13.5× larger** |
| Circumference | 40,075 km | 10,921 km | **3.67× larger** |

---

## Potential Scale Issues

### Issue 1: Camera Distance Scaling

Your camera distances might be set for Earth's scale:

**Current distances:**
```javascript
// Initial view
destination: Cesium.Cartesian3.fromDegrees(lon, lat, 10000, Cesium.Ellipsoid.MOON)
```

**Analysis:**
- 10,000 meters above Moon surface = 10 km
- As % of Moon radius: 10,000 / 1,737,400 = **0.58%**
- Equivalent on Earth: 6,371,000 × 0.0058 = 36,952 m ≈ 37 km

This seems reasonable for a close-up view.

### Issue 2: Zoom Limits

**Current limits** (lines 1376-1377):
```javascript
minimumZoomDistance: 10,
maximumZoomDistance: 30000000,
```

**Analysis:**
- **Minimum:** 10 meters - Very close (fine for detailed inspection)
- **Maximum:** 30,000,000 meters = 30,000 km
  - As % of Moon radius: 30,000,000 / 1,737,400 = **17.3× radius**
  - This is quite far - you can see the entire Moon easily

**For comparison, LROC QuickMap likely uses:**
- Minimum: ~50 meters (based on common practice)
- Maximum: ~10-15× Moon radius for full globe view

---

## The "Factor of 8 or 4" Scale Problem

If everything appears scaled wrong by a factor of 8 or 4, here are the likely causes:

### Hypothesis 1: Tile Size Mismatch
Standard web map tiles are 256×256 pixels, but LROC might use:
- 512×512 pixels (2× larger)
- 1024×1024 pixels (4× larger)

**Your current config:**
```javascript
tileWidth: 256,
tileHeight: 256,
```

**Try:**
```javascript
tileWidth: 512,
tileHeight: 512,
```

### Hypothesis 2: Degree-to-Pixel Ratio Wrong

The relationship between degrees and pixels depends on the tile size and zoom level:

**At zoom level Z:**
- Number of tiles horizontally: `2^(Z+1)` (for 2×1 at level 0)
- Degrees per tile: `360 / 2^(Z+1)`
- Pixels per degree: `(2^(Z+1) × tileWidth) / 360`

**At zoom level 0:**
- 2 tiles horizontally
- 180° per tile
- With 256px tiles: 2.84 pixels/degree
- With 512px tiles: 5.68 pixels/degree

If LROC is using 512px tiles but you're treating them as 256px, everything would appear **2× too small** (or **0.5× the expected size**).

### Hypothesis 3: Zoom Level Offset

LROC might define zoom levels differently:
- **Standard:** Level 0 = 2×1 tiles
- **LROC might:** Start at level 1 or 2

If LROC's level 0 is actually standard level 2:
- Standard level 2: 8×4 tiles (factor of 4 more tiles!)
- You're requesting level 0 tiles but getting level 2 tiles
- Result: Everything appears **4× too small**

---

## Debugging Steps

### 1. Check Actual Tile Sizes
```bash
# Download a tile and check its dimensions
curl https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/0/0.jpg -o tile.jpg
file tile.jpg  # Should show dimensions
```

### 2. Verify Tile Coverage
Check what geographic area a single tile covers:
- If one tile covers the entire moon: Wrong tiling scheme
- If one tile covers half the moon horizontally: Correct (2×1 scheme)
- If one tile covers 1/8 of moon: You're at zoom level 2, not 0

### 3. Test Different Tile Sizes

**Try 512×512:**
```javascript
tileWidth: 512,
tileHeight: 512,
```

**Try different base zoom level:**
```javascript
minimumLevel: 2,  // Start at level 2 instead of 0
```

---

## Recommended Configuration

```javascript
const moonImageryProvider = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{reverseY}.jpg',
    tilingScheme: new Cesium.GeographicTilingScheme({
        numberOfLevelZeroTilesX: 2,
        numberOfLevelZeroTilesY: 1,
        ellipsoid: Cesium.Ellipsoid.MOON  // ✅ CORRECT
    }),
    rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
    minimumLevel: 0,   // Try 2 if tiles seem wrong
    maximumLevel: 18,
    tileWidth: 256,    // Try 512 if scale is off
    tileHeight: 256,   // Try 512 if scale is off
    hasAlphaChannel: false,
    credit: 'NASA/GSFC/Arizona State University'
});

// Camera setup for Moon-appropriate distances
viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(
        23.47297,  // Apollo 11 longitude
        0.67408,   // Apollo 11 latitude
        5000,      // 5km altitude - good for site overview
        Cesium.Ellipsoid.MOON
    ),
    duration: 2
});
```

---

## Moon-Specific Camera Distances

Good camera distances for Moon exploration:

| View Type | Distance | Purpose |
|-----------|----------|---------|
| **Close-up** | 10-100 m | Individual rocks, equipment |
| **Landing site** | 500-2,000 m | Overview of landing area |
| **Regional** | 5,000-50,000 m | Geological features |
| **Hemisphere** | 500,000-1,000,000 m | Large-scale features |
| **Full globe** | 5,000,000-10,000,000 m | Entire Moon visible |

Your current distances (10m - 30,000,000m) are appropriate!

---

## Conclusion

**Your ellipsoid configuration is CORRECT.** ✅

The scale issue is likely:
1. **Tile size mismatch** - Try 512×512 instead of 256×256
2. **Zoom level offset** - LROC might start at level 2, not 0
3. **URL template issue** - Check actual tile URLs in browser DevTools

Next step: Inspect the network requests to see what tiles are actually being requested and their sizes.

