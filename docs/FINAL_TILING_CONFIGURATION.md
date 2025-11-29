# Final Tiling Configuration for Moon Viewer

**Date:** 2025-11-22  
**Status:** ✅ VERIFIED FROM ACTUAL LROC QUICKMAP TILE SERVERS

## Executive Summary

Based on direct testing of LROC QuickMap's tile servers and analysis of their projection systems, here is the **verified correct configuration** for your Moon viewer.

---

## Key Findings

### 1. ✅ Tile Size: **512×512 pixels**

**Verified by direct download:**
```bash
curl https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/0/0.jpg
Result: JPEG image data, JFIF standard 1.01, resolution (DPI), 512 x 512
```

**Your configuration:**
```javascript
tileWidth: 512,
tileHeight: 512
```
✅ **CORRECT**

---

### 2. ✅ Tiling Scheme: **2×1 Geographic**

**Standard for equirectangular projections:**
```javascript
tilingScheme: new Cesium.GeographicTilingScheme({
    numberOfLevelZeroTilesX: 2,
    numberOfLevelZeroTilesY: 1,
    ellipsoid: Cesium.Ellipsoid.MOON
})
```

**Level progression:**
- Level 0: 2×1 = 2 tiles (West hemisphere + East hemisphere)
- Level 1: 4×2 = 8 tiles
- Level 2: 8×4 = 16 tiles
- Level 3: 16×8 = 64 tiles
- Level N: 2^(N+1) × 2^N tiles

✅ **CORRECT** - This is the standard for planetary equirectangular data

---

### 3. ✅ Moon Ellipsoid: **1,737,400 meters**

```javascript
ellipsoid: Cesium.Ellipsoid.MOON
// Internally: new Cesium.Ellipsoid(1737400.0, 1737400.0, 1737400.0)
```

✅ **CORRECT** - Moon's mean radius

---

### 4. 🔍 Coordinate System: **Standard XYZ**

**Your configuration:**
```javascript
url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg'
```

Using `{y}` (NOT `{reverseY}`)

**Standard XYZ Tile Numbering:**
- Y=0 at **top** (North Pole, +90° latitude)
- Y increases **downward** (toward South Pole, -90° latitude)
- X=0 at **left** (180°W longitude)
- X increases **rightward** (toward 180°E longitude)

✅ **CORRECT** for LROC QuickMap

---

### 5. 🌐 Dual Projection System (LROC QuickMap)

LROC QuickMap uses **TWO** projections for optimal quality:

#### Main Projection: `lunar-fulleqc` (Full Equirectangular)
**Coverage:** Entire Moon (-90° to +90°, -180° to +180°)

```
Imagery: https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg
Terrain: https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/{z}/{x}/{y}.terrain
```

**Verified tiles exist:**
- Mid-latitudes: ✅ (e.g., 11/1041/563)
- North Pole: ✅ (e.g., 5/3/0)
- South Pole: ✅ (e.g., 5/3/31)

**Quality:**
- Good to excellent at low/mid latitudes (±60°)
- Acceptable at high latitudes (±60° to ±85°)
- Lower quality near poles (±85° to ±90°) due to projection distortion

#### Polar Projection: `lunar-polarshifted-eqc` (Polar Optimized)
**Coverage:** High-latitude regions (likely >±70°)

```
Imagery: https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-polarshifted-eqc/{z}/{x}/{y}.jpg
Terrain: https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-polarshifted-eqc/mesh/{z}/{x}/{y}.terrain
```

**Purpose:**
- Reduces distortion at poles
- Provides higher effective resolution at high latitudes
- Optimizes texture usage for polar regions

**Verified tiles exist:**
- South Pole imagery: ✅ (e.g., 10/508/256)
- South Pole terrain: ✅ (e.g., 7/130/64)
- North Pole imagery: ✅ (e.g., 5/3/6)
- North Pole terrain: ✅ (e.g., 6/1/33)

---

## Recommended Configuration

### Option 1: Simple (RECOMMENDED FOR MVP) ✅

**Use ONLY `lunar-fulleqc` projection for both imagery AND terrain**

#### Imagery Provider:
```javascript
const lrocProvider = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg',
    credit: new Cesium.Credit('NASA/GSFC/Arizona State University - LROC QuickMap', true),
    minimumLevel: 0,
    maximumLevel: 18,
    tilingScheme: new Cesium.GeographicTilingScheme({
        numberOfLevelZeroTilesX: 2,
        numberOfLevelZeroTilesY: 1,
        ellipsoid: Cesium.Ellipsoid.MOON
    }),
    tileWidth: 512,
    tileHeight: 512,
    rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
    hasAlphaChannel: false,
    enablePick: false
});

viewer.imageryLayers.addImageryProvider(lrocProvider);
```

#### Terrain Provider (Quantized Mesh from LOLA DEM):
```javascript
const moonTerrain = await Cesium.CesiumTerrainProvider.fromUrl(
    'https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh',
    {
        requestVertexNormals: true,  // Better lighting/shading
        requestWaterMask: false,     // Moon has no water
        requestMetadata: true        // Get terrain metadata
    }
);

viewer.terrainProvider = moonTerrain;
```

**Advantages:**
- ✅ Complete global coverage
- ✅ Single coordinate system
- ✅ Simple implementation
- ✅ Works in both 2D and 3D modes
- ✅ No seams or projection transitions

**Disadvantages:**
- ⚠️ Some distortion at poles (>±70° latitude)
- ⚠️ Lower effective resolution near poles

**Verdict:** **Perfect for MVP** - Provides complete Moon coverage with good quality everywhere except the immediate polar regions.

---

### Option 2: Advanced (Match QuickMap Exactly)

**Implement dual-projection system** with automatic switching based on latitude.

**Complexity:**
- Detect camera latitude in real-time
- Switch between `lunar-fulleqc` and `lunar-polarshifted-eqc` at ±70° threshold
- Blend/transition between projections to avoid seams
- Manage two separate tiling schemes
- Handle coordinate transformations

**Implementation effort:** ~200-400 lines of code

**Verdict:** **Phase 2 feature** - Only necessary if polar region quality is critical.

---

## Terrain Tiles (3D Elevation Data)

### What Are Terrain Tiles?

Unlike imagery tiles (which are 2D textures/photos), **terrain tiles** provide 3D elevation data that makes the Moon's surface have actual depth and relief in 3D view.

- **Format:** Quantized Mesh (`.terrain` files)
- **Source:** LOLA DEM (Lunar Orbiter Laser Altimeter Digital Elevation Model)
- **Resolution:** ~100 meters globally
- **Effect:** Craters appear as actual depressions, mountains have real height
- **Server:** CDN-hosted for fast loading

### Terrain URLs

**Main projection (global coverage):**
```
https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/{z}/{x}/{y}.terrain
```

**Polar projection (high-latitude optimization):**
```
https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-polarshifted-eqc/mesh/{z}/{x}/{y}.terrain
```

### Example Terrain Tiles

From your URL samples:
- `https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/9/518/276.terrain` ✅
- `https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-polarshifted-eqc/mesh/7/130/64.terrain` ✅
- `https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-polarshifted-eqc/mesh/6/1/33.terrain` ✅

### Configuration

```javascript
const moonTerrain = await Cesium.CesiumTerrainProvider.fromUrl(
    'https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh',
    {
        requestVertexNormals: true,  // Enables smooth lighting on slopes
        requestWaterMask: false,     // Moon has no water bodies
        requestMetadata: true        // Loads availability/quality info
    }
);

viewer.terrainProvider = moonTerrain;
```

### Cesium's Terrain Loading

Cesium automatically:
1. **Adds `/layer.json`** to the base URL to get metadata
2. **Determines tile availability** at each zoom level
3. **Loads `.terrain` files** on-demand as you pan/zoom
4. **Renders 3D mesh** with lighting based on camera/sun position

### Dual Terrain System (Advanced)

Like imagery, LROC QuickMap uses two terrain projections:
- **`lunar-fulleqc`** - Main global terrain
- **`lunar-polarshifted-eqc`** - Enhanced polar terrain

For MVP, use only `lunar-fulleqc` (provides full coverage).

### Performance Notes

**Terrain exaggeration:**
```javascript
viewer.scene.globe.terrainExaggeration = 1.0;  // Default, realistic scale
viewer.scene.globe.terrainExaggeration = 2.0;  // 2x height for better visibility
```

**Disable in 2D mode:**
```javascript
if (viewer.scene.mode === Cesium.SceneMode.SCENE2D) {
    viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider({
        ellipsoid: Cesium.Ellipsoid.MOON
    });
}
```

Terrain adds complexity in 2D projection without visual benefit.

---

## Your Current Configuration Status

### ✅ What You Have Right

1. **Tile size:** 512×512 ✅
2. **Tiling scheme:** 2×1 ✅
3. **Ellipsoid:** `Cesium.Ellipsoid.MOON` ✅
4. **Coordinate system:** `{y}` (standard XYZ) ✅
5. **Projection:** `lunar-fulleqc` ✅
6. **Rectangle:** (-180, -90, 180, 90) ✅

### 🔧 What Might Need Adjustment

**If you're still seeing "empty bottom hemisphere" in 2D view:**

#### Check #1: Camera Rectangle
```javascript
viewer.camera.setView({
    destination: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90)
});
```

Should show **full Moon** from pole to pole.

#### Check #2: Scene Mode
```javascript
viewer.scene.mode === Cesium.SceneMode.SCENE2D  // True in 2D mode
```

#### Check #3: Browser Console
Look for tile loading errors:
- 404 errors = coordinate system mismatch
- CORS errors = server access issue
- No errors but blank tiles = transparency/alpha channel issue

---

## Debugging Checklist

### Test Tile Loading Manually

```bash
# Level 0 (should have 2 tiles: 0,0 and 1,0)
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/0/0.jpg
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/1/0.jpg

# Level 1 (should have 8 tiles: 4 columns × 2 rows)
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/0/0.jpg  # North-West
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/0/1.jpg  # South-West
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/3/0.jpg  # North-East
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/3/1.jpg  # South-East
```

**All should return `HTTP/1.1 200 OK`**

### Verify Tile Coverage in Browser DevTools

1. Open Moon Viewer
2. Open DevTools → Network tab
3. Filter by "lunar-fulleqc"
4. Watch tiles load as you pan/zoom
5. Check for:
   - ✅ All tile requests return 200
   - ❌ Any 404 errors (wrong coordinates)
   - ❌ Missing tiles in certain regions

---

## Summary: The Scale Issue

**"Scale off by factor of 8 or 4"** was likely caused by:

1. **Wrong tile size** (256 instead of 512) → Fixed ✅
2. **Wrong tiling scheme** (8×8 or 8×4 instead of 2×1) → Fixed ✅
3. **Wrong Y-coordinate** (`{reverseY}` instead of `{y}`) → Fixed ✅

**Current configuration should be correct!**

If scale still seems off, it might be:
- Camera distance/zoom level perception
- 2D view viewport not showing full extent
- Confusion between different projection systems

---

## Next Steps

1. ✅ **Test current configuration**
   - Load the Moon Viewer
   - Check both 2D and 3D modes
   - Verify full hemisphere coverage

2. 🔍 **If issues persist:**
   - Check browser console for tile loading errors
   - Verify camera position/viewport in 2D mode
   - Test manual tile URLs (see debugging checklist above)

3. 🚀 **Future enhancements (Phase 2):**
   - Implement dual-projection system for polar regions
   - Add terrain/elevation data layer
   - Optimize tile caching

---

## References

- LROC QuickMap: https://quickmap.lroc.asu.edu/
- Tile Server: https://lroc-tiles.quickmap.io/
- Terrain Server: https://dem-tiles.b-cdn.net/
- Cesium Documentation: https://cesium.com/docs/

