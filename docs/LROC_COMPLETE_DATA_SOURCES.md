# LROC QuickMap Complete Data Sources

**Date:** 2025-11-22  
**Status:** ✅ VERIFIED AND IMPLEMENTED

## Overview

LROC QuickMap provides **two types of data** for the Moon:

1. **Imagery Tiles** (2D texture/photos) - What you SEE
2. **Terrain Tiles** (3D elevation/mesh) - What you FEEL (depth/relief)

Both use the same coordinate system and projection structure.

---

## 📸 Imagery Tiles (Surface Photos)

### Purpose
Photographic texture that drapes over the 3D sphere, showing:
- Surface features (craters, maria, highlands)
- Brightness variations
- Geological features
- Landing sites and spacecraft tracks (at high zoom)

### Format
- **File Type:** JPEG images (`.jpg`)
- **Tile Size:** 512×512 pixels
- **Color:** Grayscale (Moon has no color variation)
- **Instruments:** WAC (Wide Angle Camera) + NAC (Narrow Angle Camera)

### Main Projection
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg
```

**Coverage:** Global (-180° to +180° longitude, -90° to +90° latitude)

**Resolution:**
- Zoom 0-8: WAC (100m/pixel)
- Zoom 9-12: WAC + NAC blend (~10m/pixel where available)
- Zoom 13-18: NAC high-res (0.5-2m/pixel in specific ROI areas)

### Polar Projection
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-polarshifted-eqc/{z}/{x}/{y}.jpg
```

**Coverage:** High latitudes (>±70°)  
**Purpose:** Reduced distortion at poles

---

## 🏔️ Terrain Tiles (3D Elevation)

### Purpose
3D mesh data that defines the actual shape of the surface:
- Crater depth
- Mountain height
- Slope angles
- Surface roughness

### Format
- **File Type:** Quantized Mesh (`.terrain`)
- **Tile Structure:** Triangulated 3D mesh
- **Compression:** Binary, highly compressed
- **Instrument:** LOLA (Lunar Orbiter Laser Altimeter)

### Main Projection
```
https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/{z}/{x}/{y}.terrain
```

**Coverage:** Global (-180° to +180°, -90° to +90°)

**Resolution:** ~100 meters per elevation point globally

**Vertical Accuracy:** ~1 meter elevation precision

### Polar Projection
```
https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-polarshifted-eqc/mesh/{z}/{x}/{y}.terrain
```

**Coverage:** High latitudes (>±70°)  
**Purpose:** Better elevation sampling at poles

---

## 🎯 Complete Implementation

### Imagery + Terrain Together

```javascript
// ===== IMAGERY PROVIDER =====
const lrocImagery = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg',
    credit: new Cesium.Credit('NASA/GSFC/ASU - LROC QuickMap', true),
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

viewer.imageryLayers.addImageryProvider(lrocImagery);

// ===== TERRAIN PROVIDER =====
const lrocTerrain = await Cesium.CesiumTerrainProvider.fromUrl(
    'https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh',
    {
        requestVertexNormals: true,  // Smooth lighting on slopes
        requestWaterMask: false,     // Moon has no water
        requestMetadata: true        // Load tile availability info
    }
);

viewer.terrainProvider = lrocTerrain;

// ===== OPTIONAL: TERRAIN EXAGGERATION =====
viewer.scene.globe.terrainExaggeration = 1.5;  // 1.5x vertical scale for visibility
```

---

## 📊 Data Specifications Comparison

| Feature | Imagery | Terrain |
|---------|---------|---------|
| **Purpose** | Surface photos | 3D elevation |
| **Format** | JPEG (512×512) | Quantized Mesh |
| **Instrument** | LROC (WAC/NAC cameras) | LOLA (laser altimeter) |
| **Resolution** | 100m WAC, 0.5-2m NAC | ~100m globally |
| **File Size** | ~50-150 KB per tile | ~20-80 KB per tile |
| **Projection** | Equirectangular | Same as imagery |
| **Tiling Scheme** | 2×1 at level 0 | 2×1 at level 0 |
| **Coverage** | Global + ROI high-res | Global uniform |
| **Update Frequency** | Ongoing (new NAC) | Static (LOLA complete) |

---

## 🎨 Visual Effect Comparison

### Without Terrain (Ellipsoid Only)
```javascript
viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider({
    ellipsoid: Cesium.Ellipsoid.MOON
});
```

**Result:**
- ✅ Imagery looks correct
- ❌ Surface is perfectly spherical
- ❌ Craters appear flat (only texture)
- ❌ No shadows from terrain relief
- ❌ No depth perception

**Good for:** 2D maps, low-power devices, quick overviews

### With Terrain (LOLA DEM)
```javascript
viewer.terrainProvider = lrocTerrain;
```

**Result:**
- ✅ Imagery looks correct
- ✅ Craters have actual depth
- ✅ Mountains rise from surface
- ✅ Shadows cast by terrain relief
- ✅ Realistic 3D perception

**Good for:** Scientific visualization, 3D exploration, site planning

---

## 🚀 Performance Optimization

### Terrain Loading Strategy

```javascript
// Enable terrain based on scene mode
viewer.scene.morphComplete.addEventListener(() => {
    const mode = viewer.scene.mode;
    
    if (mode === Cesium.SceneMode.SCENE2D) {
        // Disable terrain in 2D (no visual benefit, adds complexity)
        viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider({
            ellipsoid: Cesium.Ellipsoid.MOON
        });
    } else {
        // Enable terrain in 3D and Columbus view
        viewer.terrainProvider = lrocTerrain;
    }
});
```

### User Toggle

```javascript
// Let users toggle terrain on/off
document.getElementById('terrainToggle').addEventListener('change', (e) => {
    if (e.target.checked) {
        viewer.terrainProvider = lrocTerrain;
    } else {
        viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider({
            ellipsoid: Cesium.Ellipsoid.MOON
        });
    }
});
```

---

## 🔍 Debugging Terrain

### Check if terrain is loaded:

```javascript
console.log('Terrain provider:', viewer.terrainProvider);
console.log('Terrain ready:', viewer.terrainProvider.ready);
```

### Check terrain availability at location:

```javascript
const position = Cesium.Cartographic.fromDegrees(lon, lat);
const terrainAvailable = await Cesium.sampleTerrainMostDetailed(
    viewer.terrainProvider,
    [position]
);
console.log('Elevation at position:', terrainAvailable[0].height, 'meters');
```

### Monitor terrain tile requests:

Open DevTools → Network tab → Filter by `.terrain`

**Look for:**
- ✅ Files loading successfully (200 OK)
- ✅ `layer.json` loaded (terrain metadata)
- ❌ 404 errors (wrong URL or coordinate system)
- ❌ CORS errors (server access issue)

---

## 📦 Complete Data Package

### What You Get From LROC QuickMap

**Imagery:**
- Global WAC coverage at 100m/pixel
- NAC high-resolution patches at 0.5-2m/pixel
- ~18 zoom levels
- Regular updates as new NAC images acquired

**Terrain:**
- Global LOLA DEM at 100m/pixel
- Consistent elevation data
- ~14 zoom levels
- Static dataset (LOLA mission complete)

**Both:**
- Free, no API key required
- CDN-hosted for speed
- Same coordinate system
- Compatible tiling schemes

---

## 🎯 Your Implementation Status

### ✅ What You Now Have

1. **Imagery Provider** ✅
   - Correct URL: `lunar-fulleqc`
   - Correct tiling: 2×1 scheme
   - Correct tile size: 512×512
   - Correct coordinate system: standard XYZ

2. **Terrain Provider** ✅ (NEWLY ADDED)
   - Correct URL: `dem-tiles.b-cdn.net`
   - Correct format: Quantized Mesh
   - Correct projection: `lunar-fulleqc`
   - Vertex normals enabled for lighting

3. **Configuration** ✅
   - Ellipsoid: `Cesium.Ellipsoid.MOON`
   - Rectangle: (-180, -90, 180, 90)
   - Both aligned to same coordinate system

### 🎉 Result

You now have **complete LROC QuickMap data integration:**
- ✅ Surface imagery (what you see)
- ✅ 3D terrain (what you feel)
- ✅ Global coverage
- ✅ Free, no API keys
- ✅ Production-ready

---

## 📚 References

- **LROC Website:** https://www.lroc.asu.edu/
- **QuickMap:** https://quickmap.lroc.asu.edu/
- **Imagery Server:** https://lroc-tiles.quickmap.io/
- **Terrain Server:** https://dem-tiles.b-cdn.net/
- **Cesium Terrain Guide:** https://cesium.com/learn/cesiumjs/ref-doc/CesiumTerrainProvider.html
- **LOLA Mission:** https://lunar.gsfc.nasa.gov/lola/

