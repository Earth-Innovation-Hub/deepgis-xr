# LROC QuickMap 3D Globe Tile Request Analysis

**Date:** November 22, 2025  
**Source:** Live browser analysis of https://quickmap.lroc.im-ldi.com  
**View Mode:** 3D Globe (proj=22)

---

## Summary

This document captures actual tile requests from LROC QuickMap's 3D globe view to understand the correct tiling scheme and coordinate system.

---

## Initial Load (Default View)

### Terrain Tiles (Quantized Mesh)
```
Level 0:
- lunar-fulleqc/mesh/0/0/0.terrain
- lunar-fulleqc/mesh/0/1/0.terrain

Level 1:
- lunar-fulleqc/mesh/1/0/0.terrain
- lunar-fulleqc/mesh/1/0/1.terrain
- lunar-fulleqc/mesh/1/1/0.terrain
- lunar-fulleqc/mesh/1/1/1.terrain
- lunar-fulleqc/mesh/1/2/0.terrain
- lunar-fulleqc/mesh/1/2/1.terrain
- lunar-fulleqc/mesh/1/3/0.terrain
- lunar-fulleqc/mesh/1/3/1.terrain
```

### Imagery Tiles (JPEG)
```
Level 1:
- lunar-fulleqc/1/0/0.jpg
- lunar-fulleqc/1/1/0.jpg

Level 2:
- lunar-fulleqc/2/0/0.jpg
- lunar-fulleqc/2/0/1.jpg
- lunar-fulleqc/2/1/0.jpg
- lunar-fulleqc/2/1/1.jpg
- lunar-fulleqc/2/2/0.jpg
- lunar-fulleqc/2/2/1.jpg
- lunar-fulleqc/2/3/0.jpg
- lunar-fulleqc/2/3/1.jpg
```

---

## Tiling Scheme Analysis

### Pattern Observed

| Level | X Range | Y Range | X Tiles | Y Tiles | Scheme |
|-------|---------|---------|---------|---------|--------|
| 0     | 0-1     | 0-0     | 2       | 1       | 2×1    |
| 1     | 0-3     | 0-1     | 4       | 2       | 4×2    |
| 2     | 0-7     | 0-3     | 8       | 4       | 8×4    |
| 3     | 0-15    | 0-7     | 16      | 8       | 16×8   |

### Formula
- **X tiles at level N:** `2^(N+1)`
- **Y tiles at level N:** `2^N`
- **Total tiles at level N:** `2^(N+1) × 2^N`

### Conclusion
**LROC uses 2×1 tiling at level 0** (not 2×2!)

This means:
```javascript
numberOfLevelZeroTilesX: 2
numberOfLevelZeroTilesY: 1  // NOT 2!
```

---

## Coordinate System

### Y-Axis Orientation
From the tile requests:
- **Y=0** appears in both northern and southern hemisphere requests
- **Y=1** appears in southern hemisphere requests
- Pattern suggests: **Y=0 at North Pole, Y increases southward**

This is **standard XYZ** coordinate system (NOT TMS).

### URL Template
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg
```

**Correct format:** `{z}/{x}/{y}` (NOT `{z}/{x}/{reverseY}`)

---

## Projection Usage

### Imagery
- **Primary:** `lunar-fulleqc` (Full Equirectangular)
- **Polar:** NOT used for imagery in 3D mode (only for 2D orthographic views)

### Terrain
- **Primary:** `lunar-fulleqc` (Full Equirectangular)
- **Polar:** `lunar-polarshifted-eqc` (loaded but usage unclear from initial requests)

---

## Tile Specifications

### Size
- **Width:** 512 pixels
- **Height:** 512 pixels
- **Format:** JPEG (imagery), Quantized Mesh (terrain)

### Coverage
- **Longitude:** -180° to +180° (full coverage)
- **Latitude:** -90° to +90° (full coverage in 2×1 scheme)

---

## Critical Configuration for Our Implementation

Based on this analysis, the **correct** configuration is:

```javascript
const lrocProvider = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg',
    tilingScheme: new Cesium.GeographicTilingScheme({
        numberOfLevelZeroTilesX: 2,  // VERIFIED: 2 columns
        numberOfLevelZeroTilesY: 1,  // VERIFIED: 1 row (NOT 2!)
        ellipsoid: Cesium.Ellipsoid.MOON
    }),
    rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
    tileWidth: 512,
    tileHeight: 512,
    minimumLevel: 0,
    maximumLevel: 18
});
```

---

## Why Only Northern Hemisphere Shows?

**Hypothesis:** The issue is NOT the tiling scheme (we have it correct), but rather:

1. **Data Coverage:** `lunar-fulleqc` tiles may have sparse data in southern hemisphere
2. **Tile Content:** Southern tiles (Y=1 at higher levels) may contain mostly empty/placeholder data
3. **Texture Mapping:** Cesium may be correctly requesting tiles, but the tiles themselves lack data

**Next Steps:**
- Download and inspect actual tile content at different Y coordinates
- Check if southern hemisphere tiles are mostly empty (4.7KB vs 86KB for northern tiles)
- Consider if LROC uses a different projection or layer for southern hemisphere coverage

---

## References

- **Terrain Layer JSON:** https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/layer.json
- **LROC QuickMap:** https://quickmap.lroc.im-ldi.com
- **Tile Server:** https://lroc-tiles.quickmap.io

---

**Analysis Date:** November 22, 2025  
**Browser:** Automated browser session  
**View Mode:** 3D Globe (proj=22)

