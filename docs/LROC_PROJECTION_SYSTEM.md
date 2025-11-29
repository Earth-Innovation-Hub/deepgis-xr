# LROC QuickMap Projection System Analysis

**Date:** 2025-11-22  
**Status:** ✅ VERIFIED FROM ACTUAL TILE REQUESTS

## Discovery: Dual Projection System

LROC QuickMap uses **TWO projection systems** depending on latitude:

### 1. Main Projection: `lunar-fulleqc` (Full Equirectangular)

**Coverage:** Entire Moon surface (0° to 360° longitude, -90° to +90° latitude)

**URLs:**
- **Imagery:** `https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg`
- **Terrain:** `https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/{z}/{x}/{y}.terrain`

**Example tiles:**
- Region 1 (Mid-latitude): `11/1041/563.jpg` ✅
- North Pole: `5/3/0.jpg` ✅ (200 OK)
- South Pole: `5/3/31.jpg` ✅ (200 OK)

### 2. Polar Projection: `lunar-polarshifted-eqc` (Polar Shifted Equirectangular)

**Coverage:** High-latitude regions (likely >60° or >70° latitude)

**URLs:**
- **Imagery:** `https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-polarshifted-eqc/{z}/{x}/{y}.jpg`
- **Terrain:** `https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-polarshifted-eqc/mesh/{z}/{x}/{y}.terrain`

**Example tiles:**
- South Pole: `10/508/256.jpg` ✅
- South Pole terrain: `7/130/64.terrain` ✅
- North Pole: `5/3/6.jpg` ✅
- North Pole terrain: `6/1/33.terrain` ✅

---

## Why Use Dual Projections?

### Problem with Standard Equirectangular at Poles:
- **Extreme horizontal stretching** near poles
- **Distortion increases** as latitude approaches ±90°
- **Wasted texture space** - pixels cover tiny surface area at poles

### Solution: Polar-Shifted Projection
- **Better resolution** at high latitudes
- **Less distortion** near poles
- **Optimized tile usage** for polar regions

---

## Analysis for Your Implementation

### Finding 1: `lunar-fulleqc` Has Complete Coverage ✅

Tested and confirmed:
```bash
curl https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/5/3/0.jpg   # North Pole → 200 OK
curl https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/5/3/31.jpg  # South Pole → 200 OK
```

**Conclusion:** Using ONLY `lunar-fulleqc` should provide **complete Moon coverage**.

### Finding 2: QuickMap Switches Projections Dynamically

QuickMap's 3D globe likely:
1. Uses `lunar-fulleqc` for latitudes between ~-70° to +70°
2. Switches to `lunar-polarshifted-eqc` for latitudes beyond ±70°
3. Blends between projections at the transition boundary

This is an **optimization for quality**, not a requirement.

---

## Recommendations

### Option 1: Simple Approach (RECOMMENDED for MVP)
**Use ONLY `lunar-fulleqc` projection**

```javascript
const lrocProvider = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg',
    tilingScheme: new Cesium.GeographicTilingScheme({
        numberOfLevelZeroTilesX: 2,
        numberOfLevelZeroTilesY: 1,
        ellipsoid: Cesium.Ellipsoid.MOON
    }),
    tileWidth: 512,
    tileHeight: 512,
    rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90)
});
```

**Pros:**
- ✅ Complete coverage (verified)
- ✅ Simple implementation
- ✅ Single coordinate system
- ✅ Works for both 2D and 3D

**Cons:**
- ⚠️ Lower quality at poles (acceptable for most use cases)
- ⚠️ Some distortion at high latitudes

### Option 2: Advanced Approach (Match QuickMap Exactly)
**Implement dynamic projection switching**

Would require:
1. Detecting camera latitude
2. Switching imagery providers at ~70° threshold
3. Managing two separate tiling schemes
4. Blending at transition zones

**Pros:**
- ✅ Best quality at all latitudes
- ✅ Matches QuickMap exactly

**Cons:**
- ❌ Complex implementation (~200+ lines)
- ❌ Requires projection math
- ❌ Potential seams at transition zones
- ❌ Harder to debug

---

## Current Status of Your Implementation

**Your configuration:**
- Projection: `lunar-fulleqc` ✅
- Tiling scheme: 2×1 ✅
- Tile size: 512×512 ✅
- Coordinate system: `{y}` ✅
- Ellipsoid: `Cesium.Ellipsoid.MOON` ✅

**This should work correctly!**

---

## Troubleshooting "Empty Bottom Hemisphere"

If you're still seeing an empty bottom hemisphere in 2D view, check:

### 1. Camera Rectangle in 2D Mode
```javascript
viewer.camera.setView({
    destination: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90)  // Full Moon
});
```

### 2. Y-Coordinate System
- Standard: `{y}` - Y=0 at North Pole, increases southward
- TMS: `{reverseY}` - Y=0 at South Pole, increases northward

Test both to see which LROC uses (currently you have `{y}`).

### 3. Tile Availability Test
```bash
# Test if southern hemisphere tiles exist
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/5/3/31.jpg  # South Pole
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/5/3/16.jpg  # Equator
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/5/3/0.jpg   # North Pole
```

---

## Next Steps

1. **Test current configuration** with `lunar-fulleqc` only
2. **If poles look poor quality** but functional → acceptable for MVP
3. **If coverage is still incomplete** → investigate Y-coordinate system
4. **If quality at poles is critical** → implement dual-projection system (Phase 2)

---

## Additional Notes

### Terrain Data
LROC also provides terrain/elevation data:
- Same dual-projection system
- `.terrain` format (Cesium Quantized Mesh)
- Could be added for 3D relief visualization

### Tile CDN
- Imagery: `lroc-tiles.quickmap.io` (main server)
- Terrain: `dem-tiles.b-cdn.net` (CDN for performance)

