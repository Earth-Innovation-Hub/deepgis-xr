# Moon Viewer Complete Implementation Guide

**Project:** DeepGIS-XR Moon Viewer  
**Date:** 2025-11-22  
**Status:** ✅ PRODUCTION READY  
**Version:** 1.0

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Quick Start Configuration](#quick-start-configuration)
3. [Complete Data Sources](#complete-data-sources)
4. [Technical Specifications](#technical-specifications)
5. [Issues Found & Fixed](#issues-found--fixed)
6. [Implementation Details](#implementation-details)
7. [Debugging Guide](#debugging-guide)
8. [Advanced Features](#advanced-features)
9. [References](#references)

---

## Executive Summary

### What This Document Covers

Complete implementation guide for a Moon viewer application using LROC QuickMap data sources with Cesium.js. This document consolidates all findings, configurations, and solutions discovered during development.

### Final Configuration Status ✅

| Component | Status | Source |
|-----------|--------|--------|
| **Imagery Tiles** | ✅ Working | LROC QuickMap (WAC/NAC) |
| **Terrain Tiles** | ✅ Working | LOLA DEM (Quantized Mesh) |
| **Tiling Scheme** | ✅ Verified | 2×1 Geographic |
| **Tile Size** | ✅ Verified | 512×512 pixels |
| **Coordinate System** | ✅ Verified | Standard XYZ |
| **Moon Ellipsoid** | ✅ Correct | 1,737,400 m radius |
| **Projection** | ✅ Complete | lunar-fulleqc (global) |

### Key Achievements

- ✅ **Free, production-ready data sources** (no API keys required)
- ✅ **Complete global coverage** (imagery + terrain)
- ✅ **High-resolution support** (up to 0.5m/pixel in NAC regions)
- ✅ **3D terrain relief** (LOLA elevation data)
- ✅ **Optimized performance** (CDN-hosted, efficient streaming)
- ✅ **Standards-compliant** (follows Cesium and OGC conventions)

---

## Quick Start Configuration

### Complete Working Setup

```javascript
// ============================================================
// CESIUM VIEWER INITIALIZATION
// ============================================================
const viewer = new Cesium.Viewer('cesiumContainer', {
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    selectionIndicator: false,
    infoBox: false,
    fullscreenButton: false,
    scene3DOnly: false,
    imageryProvider: false,  // We'll add it manually
    terrainProvider: undefined
});

// Set Moon as the central body
viewer.scene.globe.ellipsoid = Cesium.Ellipsoid.MOON;

// ============================================================
// IMAGERY PROVIDER - LROC QuickMap (WAC/NAC)
// ============================================================
const lrocImagery = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg',
    credit: new Cesium.Credit('NASA/GSFC/Arizona State University - LROC QuickMap', true),
    minimumLevel: 0,
    maximumLevel: 18,
    
    // CRITICAL: Geographic tiling scheme with 2×1 at level 0
    tilingScheme: new Cesium.GeographicTilingScheme({
        numberOfLevelZeroTilesX: 2,  // 2 tiles horizontally (West + East hemisphere)
        numberOfLevelZeroTilesY: 1,  // 1 tile vertically (full latitude range)
        ellipsoid: Cesium.Ellipsoid.MOON
    }),
    
    // CRITICAL: LROC uses 512×512 tiles, not standard 256×256
    tileWidth: 512,
    tileHeight: 512,
    
    rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
    hasAlphaChannel: false,
    enablePick: false
});

viewer.imageryLayers.addImageryProvider(lrocImagery);

// ============================================================
// TERRAIN PROVIDER - LOLA DEM (Quantized Mesh)
// ============================================================
const lrocTerrain = await Cesium.CesiumTerrainProvider.fromUrl(
    'https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh',
    {
        requestVertexNormals: true,  // Enable smooth lighting on slopes
        requestWaterMask: false,     // Moon has no water bodies
        requestMetadata: true        // Load tile availability metadata
    }
);

viewer.terrainProvider = lrocTerrain;

// ============================================================
// CAMERA SETTINGS
// ============================================================
viewer.scene.screenSpaceCameraController.minimumZoomDistance = 10;        // 10m minimum
viewer.scene.screenSpaceCameraController.maximumZoomDistance = 30000000;  // 30,000 km maximum

// Initial view - Show full Moon
viewer.camera.setView({
    destination: Cesium.Cartesian3.fromDegrees(0, 0, 5000000, Cesium.Ellipsoid.MOON)
});

// ============================================================
// OPTIONAL: TERRAIN EXAGGERATION
// ============================================================
viewer.scene.globe.terrainExaggeration = 1.0;  // 1.0 = realistic, 2.0 = 2x height

// ============================================================
// OPTIONAL: DISABLE TERRAIN IN 2D MODE
// ============================================================
viewer.scene.morphComplete.addEventListener(() => {
    if (viewer.scene.mode === Cesium.SceneMode.SCENE2D) {
        // Disable terrain in 2D for performance
        viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider({
            ellipsoid: Cesium.Ellipsoid.MOON
        });
    } else {
        // Re-enable terrain in 3D
        viewer.terrainProvider = lrocTerrain;
    }
});
```

---

## Complete Data Sources

### 🖼️ Imagery Tiles (Surface Photography)

#### What It Provides
- Surface photographs showing craters, maria, highlands, and features
- Grayscale imagery (Moon has minimal color variation)
- Multiple resolution levels from global to site-specific

#### Data Source: LROC (Lunar Reconnaissance Orbiter Camera)

**Instruments:**
- **WAC** (Wide Angle Camera) - 100m/pixel global coverage
- **NAC** (Narrow Angle Camera) - 0.5-2m/pixel targeted high-resolution

**URL Pattern:**
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg
```

**Specifications:**
- **Format:** JPEG (compressed)
- **Tile Size:** 512×512 pixels
- **Levels:** 0-18 (zoom levels)
- **Coverage:** Global (-180° to +180°, -90° to +90°)
- **Updates:** Ongoing (new NAC images continuously added)

**Resolution by Zoom Level:**
| Zoom | Resolution | Coverage |
|------|------------|----------|
| 0-8 | 100 m/px | WAC global |
| 9-12 | ~10 m/px | WAC + NAC blend |
| 13-18 | 0.5-2 m/px | NAC ROI only |

### 🏔️ Terrain Tiles (3D Elevation Data)

#### What It Provides
- 3D mesh data defining surface elevation
- Crater depth, mountain height, slope information
- Enables realistic lighting and shadows

#### Data Source: LOLA (Lunar Orbiter Laser Altimeter)

**Instrument:**
- Laser altimeter measuring surface elevation
- Part of LRO spacecraft (same as LROC)

**URL Pattern:**
```
https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/{z}/{x}/{y}.terrain
```

**Specifications:**
- **Format:** Quantized Mesh (binary)
- **Resolution:** ~100 meters per elevation point
- **Vertical Accuracy:** ~1 meter
- **Levels:** 0-14 (terrain zoom levels)
- **Coverage:** Global uniform
- **Updates:** Static (LOLA mission complete)

### Data Comparison

| Feature | Imagery | Terrain |
|---------|---------|---------|
| **Purpose** | What you SEE | What you FEEL |
| **Format** | JPEG 512×512 | Quantized Mesh |
| **Instrument** | LROC WAC/NAC | LOLA Altimeter |
| **Resolution** | 100m to 0.5m | ~100m globally |
| **File Size** | 50-150 KB/tile | 20-80 KB/tile |
| **Effect** | Surface texture | 3D depth/relief |
| **Cost** | Free | Free |

---

## Technical Specifications

### Tiling Scheme: Geographic 2×1

LROC QuickMap uses the **standard geographic tiling scheme** for equirectangular projections.

#### Level 0 Structure
```
[West Hemisphere]  [East Hemisphere]
     (0,0)              (1,0)
  -180° to 0°        0° to 180°
  -90° to +90°      -90° to +90°
```

#### Tile Progression
| Level | Tiles X | Tiles Y | Total | Degrees/Tile |
|-------|---------|---------|-------|--------------|
| 0 | 2 | 1 | 2 | 180° × 180° |
| 1 | 4 | 2 | 8 | 90° × 90° |
| 2 | 8 | 4 | 16 | 45° × 45° |
| 3 | 16 | 8 | 64 | 22.5° × 22.5° |
| N | 2^(N+1) | 2^N | 2^(N+1) × 2^N | 180/2^N degrees |

#### Why Not 8×8 or 8×4?

Early analysis suggested 8×8 or 8×4, but testing revealed:
- ❌ 8×8 doesn't exist in standard tiling
- ❌ 8×4 is Level 2 of a 2×1 scheme
- ✅ 2×1 is the **standard** for equirectangular data

### Coordinate System: Standard XYZ

LROC uses **standard XYZ** tile numbering (NOT TMS):

```
Y=0 ← North Pole (+90° latitude)
 ↓
 ↓  (tiles numbered downward)
 ↓
Y=max ← South Pole (-90° latitude)

X=0 ← 180°W          X=max ← 180°E
  →  (tiles numbered rightward)  →
```

**Cesium URL Template:**
```javascript
url: 'https://lroc-tiles.quickmap.io/.../lunar-fulleqc/{z}/{x}/{y}.jpg'
// Use {y}, NOT {reverseY}
```

### Moon Ellipsoid Specifications

```javascript
Cesium.Ellipsoid.MOON = new Cesium.Ellipsoid(
    1737400.0,  // x-axis radius (meters)
    1737400.0,  // y-axis radius (meters)
    1737400.0   // z-axis radius (meters)
);
```

**Physical Specifications:**
- **Mean Radius:** 1,737.4 km = 1,737,400 meters
- **Equatorial Radius:** 1,738.1 km
- **Polar Radius:** 1,736.0 km
- **Ellipticity:** ~0.0012 (nearly spherical)

Moon is treated as a **perfect sphere** in Cesium (good approximation).

### Projection System: Equirectangular

#### Main Projection: `lunar-fulleqc`

**Full Name:** Lunar Full Equirectangular  
**Coverage:** Complete global coverage  
**Quality:** Excellent at equator, good at mid-latitudes, acceptable at poles

**Formula:**
```
x = (longitude + 180) / 360
y = (90 - latitude) / 180
```

**Characteristics:**
- ✅ Simple, fast rendering
- ✅ Complete coverage
- ✅ Works in 2D and 3D
- ⚠️ Distortion increases toward poles

#### Polar Projection: `lunar-polarshifted-eqc`

**Full Name:** Lunar Polar-Shifted Equirectangular  
**Coverage:** High latitudes (>±70°)  
**Quality:** Optimized for polar regions

**URLs:**
```
Imagery: lroc-tiles.quickmap.io/.../lunar-polarshifted-eqc/{z}/{x}/{y}.jpg
Terrain: dem-tiles.b-cdn.net/.../lunar-polarshifted-eqc/mesh/{z}/{x}/{y}.terrain
```

**Purpose:**
- Reduces horizontal stretching at poles
- Provides better effective resolution
- Optimizes texture usage

**Implementation:** Optional for MVP (Phase 2 feature)

---

## Issues Found & Fixed

### Issue 1: Wrong Tile Size ✅ FIXED

**Symptom:** Scale off by factor of 2-4  
**Root Cause:** Default tile size is 256×256, but LROC uses 512×512

**Before:**
```javascript
// Default: tileWidth and tileHeight not specified
// Cesium assumes 256×256
```

**After:**
```javascript
tileWidth: 512,
tileHeight: 512
```

**Impact:** ⭐⭐⭐ Critical - Wrong tile size caused major scale issues

### Issue 2: Wrong Tiling Scheme ✅ FIXED

**Symptom:** Missing tiles, incorrect coverage  
**Root Cause:** Used 8×4 or 8×8 instead of standard 2×1

**Before:**
```javascript
numberOfLevelZeroTilesX: 8,  // Wrong!
numberOfLevelZeroTilesY: 4,  // Wrong!
```

**After:**
```javascript
numberOfLevelZeroTilesX: 2,  // Correct: 2 hemispheres
numberOfLevelZeroTilesY: 1,  // Correct: full latitude
```

**Impact:** ⭐⭐⭐ Critical - Caused tile coordinate mismatch

### Issue 3: Wrong Coordinate System ✅ FIXED

**Symptom:** Empty bottom hemisphere in some views  
**Root Cause:** Used {reverseY} when {y} was correct

**Before:**
```javascript
url: 'https://lroc-tiles.quickmap.io/.../lunar-fulleqc/{z}/{x}/{reverseY}.jpg'
```

**After:**
```javascript
url: 'https://lroc-tiles.quickmap.io/.../lunar-fulleqc/{z}/{x}/{y}.jpg'
```

**Impact:** ⭐⭐ High - Caused missing tiles in southern hemisphere

### Issue 4: Missing Terrain Provider ✅ FIXED

**Symptom:** Flat Moon surface, no 3D relief  
**Root Cause:** Tried to use Cesium Ion (requires paid subscription), fell back to ellipsoid

**Before:**
```javascript
// Attempted: Cesium Ion Asset 3956 (paid)
const moonTerrain = await Cesium.CesiumTerrainProvider.fromIonAssetId(3956);
// Failed, fell back to smooth ellipsoid
```

**After:**
```javascript
// Use LROC QuickMap's free terrain tiles
const moonTerrain = await Cesium.CesiumTerrainProvider.fromUrl(
    'https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh'
);
```

**Impact:** ⭐⭐⭐ Critical - Enables 3D terrain relief

### Issue 5: Duplicate CSS Classes ✅ FIXED

**Symptom:** Code bloat, maintenance issues  
**Root Cause:** Three identical CSS classes for form controls

**Before (39 lines):**
```css
.form-control-base { /* 9 lines */ }
.form-select { /* 9 lines */ }
.form-control { /* 9 lines */ }
```

**After (12 lines):**
```css
.form-control,
.form-select,
.form-control-base {
    /* Shared styles - 9 lines */
}
```

**Impact:** ⭐ Low - Code quality improvement, 27 lines saved

### Issue 6: 2D View Not Showing Full Moon ✅ FIXED

**Symptom:** Only part of Moon visible in 2D mode  
**Root Cause:** Camera not set to full extent

**Before:**
```javascript
// Kept current camera position when switching to 2D
viewer.scene.morphTo2D(1.0);
```

**After:**
```javascript
viewer.camera.setView({
    destination: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90)
});
```

**Impact:** ⭐⭐ Medium - Better UX in 2D mode

---

## Implementation Details

### Imagery Loading Process

```javascript
// 1. Create imagery provider
const lrocImagery = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg',
    tilingScheme: new Cesium.GeographicTilingScheme({
        numberOfLevelZeroTilesX: 2,
        numberOfLevelZeroTilesY: 1,
        ellipsoid: Cesium.Ellipsoid.MOON
    }),
    tileWidth: 512,
    tileHeight: 512
});

// 2. Add to viewer
viewer.imageryLayers.addImageryProvider(lrocImagery);

// 3. Cesium automatically:
//    - Calculates visible tiles based on camera position
//    - Requests tiles from server
//    - Loads and caches tiles
//    - Renders tiles on globe
```

### Terrain Loading Process

```javascript
// 1. Create terrain provider (async)
const lrocTerrain = await Cesium.CesiumTerrainProvider.fromUrl(
    'https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh',
    { requestVertexNormals: true }
);

// 2. Set as viewer terrain
viewer.terrainProvider = lrocTerrain;

// 3. Cesium automatically:
//    - Requests layer.json (metadata)
//    - Determines tile availability
//    - Loads .terrain files on-demand
//    - Builds 3D mesh
//    - Applies lighting based on sun position
```

### Camera Distance Calculations

```javascript
// Calculate appropriate zoom distance for feature
function calculateZoomDistance(featureSizeMeters) {
    const fov = viewer.camera.frustum.fov;  // Field of view in radians
    const distance = featureSizeMeters / (2 * Math.tan(fov / 2));
    return distance * 2;  // Add margin
}

// Example: Apollo 11 landing site (100m feature)
const distance = calculateZoomDistance(100);  // ~500-1000m altitude
```

### Tile URL Construction

Given: Zoom=5, X=12, Y=8

```javascript
// Cesium replaces placeholders:
const template = 'https://lroc-tiles.quickmap.io/.../lunar-fulleqc/{z}/{x}/{y}.jpg';
const url = template
    .replace('{z}', '5')
    .replace('{x}', '12')
    .replace('{y}', '8');

// Result:
// https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/5/12/8.jpg
```

### Apollo Landing Sites Configuration

```javascript
const apolloSites = [
    { name: 'Apollo 11', lat: 0.6745, lon: 23.4730, mission: 'First Moon landing', year: 1969 },
    { name: 'Apollo 12', lat: -3.0119, lon: -23.4219, mission: 'Surveyor 3 visit', year: 1969 },
    { name: 'Apollo 14', lat: -3.6454, lon: -17.4714, mission: 'Fra Mauro highlands', year: 1971 },
    { name: 'Apollo 15', lat: 26.1322, lon: 3.6285, mission: 'Hadley Rille', year: 1971 },
    { name: 'Apollo 16', lat: -8.9730, lon: 15.5011, mission: 'Descartes Highlands', year: 1972 },
    { name: 'Apollo 17', lat: 20.1908, lon: 30.7717, mission: 'Last Moon landing', year: 1972 }
];

apolloSites.forEach(site => {
    viewer.entities.add({
        name: site.name,
        position: Cesium.Cartesian3.fromDegrees(
            site.lon, 
            site.lat, 
            0, 
            Cesium.Ellipsoid.MOON
        ),
        point: {
            pixelSize: 10,
            color: Cesium.Color.YELLOW,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2
        },
        label: {
            text: site.name,
            font: '14px sans-serif',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -12)
        }
    });
});
```

---

## Debugging Guide

### 1. Check Tile Loading

**Open Browser DevTools → Network Tab**

**Filter imagery tiles:**
```
lunar-fulleqc
```

**Look for:**
- ✅ Status: 200 OK (tiles loading successfully)
- ❌ Status: 404 (wrong coordinates or URL)
- ❌ Status: 403/CORS (server access issue)

**Expected pattern:**
```
lunar-fulleqc/0/0/0.jpg → 200 OK
lunar-fulleqc/0/1/0.jpg → 200 OK
lunar-fulleqc/1/0/0.jpg → 200 OK
lunar-fulleqc/1/0/1.jpg → 200 OK
...
```

### 2. Check Terrain Loading

**Filter terrain tiles:**
```
.terrain
```

**Look for:**
```
mesh/layer.json → 200 OK (metadata)
mesh/0/0/0.terrain → 200 OK
mesh/1/0/0.terrain → 200 OK
...
```

### 3. Verify Configuration in Console

```javascript
// Check viewer state
console.log('Viewer:', viewer);
console.log('Scene mode:', viewer.scene.mode);
console.log('Globe ellipsoid:', viewer.scene.globe.ellipsoid);

// Check imagery
const layer = viewer.imageryLayers.get(0);
console.log('Imagery provider:', layer.imageryProvider);
console.log('Tile width:', layer.imageryProvider.tileWidth);
console.log('Tile height:', layer.imageryProvider.tileHeight);

// Check terrain
console.log('Terrain provider:', viewer.terrainProvider);
console.log('Terrain ready:', viewer.terrainProvider.ready);

// Check camera
const position = viewer.camera.positionCartographic;
console.log('Camera lon:', Cesium.Math.toDegrees(position.longitude));
console.log('Camera lat:', Cesium.Math.toDegrees(position.latitude));
console.log('Camera height:', position.height);
```

### 4. Test Specific Tiles

```bash
# Test tile availability manually
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/0/0.jpg
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/1/0.jpg
curl -I https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/layer.json
curl -I https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/0/0/0.terrain

# All should return: HTTP/1.1 200 OK
```

### 5. Common Issues & Solutions

#### Issue: No tiles loading

**Check:**
```javascript
// Is imagery provider added?
console.log(viewer.imageryLayers.length);  // Should be > 0

// Is base layer picker disabled?
// Make sure: baseLayerPicker: false in viewer options
```

#### Issue: Tiles loading but black/empty

**Check:**
```javascript
// Correct ellipsoid set?
console.log(viewer.scene.globe.ellipsoid === Cesium.Ellipsoid.MOON);  // Should be true

// Check for alpha channel issues
// hasAlphaChannel: false in imagery provider
```

#### Issue: Terrain not showing

**Check:**
```javascript
// Is terrain provider set?
console.log(viewer.terrainProvider);

// Is terrain exaggeration visible?
viewer.scene.globe.terrainExaggeration = 2.0;  // Try 2x for testing

// Are you in 2D mode? (terrain disabled in 2D)
console.log(viewer.scene.mode === Cesium.SceneMode.SCENE2D);
```

#### Issue: Scale seems wrong

**Check:**
```javascript
// Correct tile size?
const provider = viewer.imageryLayers.get(0).imageryProvider;
console.log('Tile width:', provider.tileWidth);   // Should be 512
console.log('Tile height:', provider.tileHeight); // Should be 512

// Correct tiling scheme?
const scheme = provider.tilingScheme;
console.log('Level 0 X:', scheme.getNumberOfXTilesAtLevel(0));  // Should be 2
console.log('Level 0 Y:', scheme.getNumberOfYTilesAtLevel(0));  // Should be 1
```

### 6. Sample Elevation at Location

```javascript
async function getElevation(longitude, latitude) {
    const position = Cesium.Cartographic.fromDegrees(longitude, latitude);
    const results = await Cesium.sampleTerrainMostDetailed(
        viewer.terrainProvider,
        [position]
    );
    console.log(`Elevation at (${longitude}, ${latitude}):`, results[0].height, 'meters');
    return results[0].height;
}

// Example: Check Tycho crater depth
getElevation(-11.36, -43.31);  // Should show negative elevation
```

---

## Advanced Features

### Dual Projection System (Phase 2)

For optimal quality at poles, implement automatic projection switching:

```javascript
class DualProjectionManager {
    constructor(viewer) {
        this.viewer = viewer;
        this.mainImagery = null;   // lunar-fulleqc
        this.polarImagery = null;  // lunar-polarshifted-eqc
        this.currentProjection = 'main';
        this.latitudeThreshold = 70;  // Switch at ±70°
    }
    
    async init() {
        // Main projection (global)
        this.mainImagery = new Cesium.UrlTemplateImageryProvider({
            url: 'https://lroc-tiles.quickmap.io/.../lunar-fulleqc/{z}/{x}/{y}.jpg',
            // ... configuration
        });
        
        // Polar projection (high latitudes)
        this.polarImagery = new Cesium.UrlTemplateImageryProvider({
            url: 'https://lroc-tiles.quickmap.io/.../lunar-polarshifted-eqc/{z}/{x}/{y}.jpg',
            // ... configuration
        });
        
        // Start with main
        this.viewer.imageryLayers.addImageryProvider(this.mainImagery);
        
        // Monitor camera position
        this.viewer.camera.moveEnd.addEventListener(() => {
            this.checkProjectionSwitch();
        });
    }
    
    checkProjectionSwitch() {
        const position = this.viewer.camera.positionCartographic;
        const latDegrees = Math.abs(Cesium.Math.toDegrees(position.latitude));
        
        if (latDegrees > this.latitudeThreshold && this.currentProjection === 'main') {
            this.switchToPolar();
        } else if (latDegrees <= this.latitudeThreshold && this.currentProjection === 'polar') {
            this.switchToMain();
        }
    }
    
    switchToPolar() {
        this.viewer.imageryLayers.removeAll();
        this.viewer.imageryLayers.addImageryProvider(this.polarImagery);
        this.currentProjection = 'polar';
        console.log('Switched to polar projection');
    }
    
    switchToMain() {
        this.viewer.imageryLayers.removeAll();
        this.viewer.imageryLayers.addImageryProvider(this.mainImagery);
        this.currentProjection = 'main';
        console.log('Switched to main projection');
    }
}

// Usage
const projectionManager = new DualProjectionManager(viewer);
await projectionManager.init();
```

### Sun Position & Lighting

```javascript
// Calculate sun position on Moon
async function getSunPosition(date) {
    // Using LROC's satview service
    const url = `https://satview.actgate.com/fcgi-bin/fprovweb.exe?_xtype=text/plain&dsource=satview&target=MOON&time=${date.toISOString()}&cmd_script=satview_get_subsolar_records.msh`;
    
    const response = await fetch(url);
    const text = await response.text();
    
    // Parse response for subsolar point
    // Returns [longitude, latitude]
}

// Set lighting based on sun position
function updateSunLighting(sunLon, sunLat) {
    const sunPosition = Cesium.Cartesian3.fromDegrees(
        sunLon,
        sunLat,
        1000000,  // 1000 km above surface
        Cesium.Ellipsoid.MOON
    );
    
    viewer.scene.light = new Cesium.DirectionalLight({
        direction: Cesium.Cartesian3.negate(
            Cesium.Cartesian3.normalize(sunPosition, new Cesium.Cartesian3()),
            new Cesium.Cartesian3()
        )
    });
}
```

### Performance Optimization

```javascript
// Optimize for mobile devices
function optimizeForDevice() {
    const isMobile = /Android|iPhone|iPad/i.test(navigator.userAgent);
    
    if (isMobile) {
        // Reduce tile cache size
        viewer.scene.globe.tileCacheSize = 100;  // Default is 300
        
        // Lower maximum screen space error (fewer tiles)
        viewer.scene.globe.maximumScreenSpaceError = 4;  // Default is 2
        
        // Disable fog for better performance
        viewer.scene.fog.enabled = false;
        
        // Simplify lighting
        viewer.scene.globe.enableLighting = false;
    }
}

// Implement tile loading strategy
function setupTileLoading() {
    // Prioritize tiles near camera
    viewer.scene.globe.preloadAncestors = true;
    viewer.scene.globe.preloadSiblings = true;
    
    // Limit concurrent requests
    Cesium.RequestScheduler.maximumRequestsPerServer = 6;
}
```

### Measurement Tools

```javascript
// Distance measurement between two points
function measureDistance(point1, point2) {
    const ellipsoid = Cesium.Ellipsoid.MOON;
    const surface = Cesium.EllipsoidGeodesic.fromCartesian(point1, point2, ellipsoid);
    return surface.surfaceDistance;  // meters
}

// Elevation profile along path
async function getElevationProfile(coordinates) {
    const positions = coordinates.map(coord => 
        Cesium.Cartographic.fromDegrees(coord[0], coord[1])
    );
    
    const samples = await Cesium.sampleTerrainMostDetailed(
        viewer.terrainProvider,
        positions
    );
    
    return samples.map((sample, i) => ({
        lon: coordinates[i][0],
        lat: coordinates[i][1],
        elevation: sample.height
    }));
}
```

---

## References

### Official Documentation

- **Cesium.js:** https://cesium.com/docs/
- **CesiumJS API:** https://cesium.com/learn/cesiumjs/ref-doc/
- **LROC Website:** https://www.lroc.asu.edu/
- **LROC QuickMap:** https://quickmap.lroc.asu.edu/
- **LOLA Mission:** https://lunar.gsfc.nasa.gov/lola/

### Data Sources

- **Imagery Server:** https://lroc-tiles.quickmap.io/
- **Terrain Server:** https://dem-tiles.b-cdn.net/
- **LROC Data:** https://wms.lroc.asu.edu/
- **PDS Geosciences Node:** https://pds-geosciences.wustl.edu/

### Tile Server Endpoints

**Imagery - Main Projection:**
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg
```

**Imagery - Polar Projection:**
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-polarshifted-eqc/{z}/{x}/{y}.jpg
```

**Terrain - Main Projection:**
```
https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/{z}/{x}/{y}.terrain
https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh/layer.json (metadata)
```

**Terrain - Polar Projection:**
```
https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-polarshifted-eqc/mesh/{z}/{x}/{y}.terrain
```

### Technical Standards

- **OGC WMTS:** Web Map Tile Service standard
- **TMS:** Tile Map Service specification
- **Quantized Mesh:** Cesium terrain format
- **Equirectangular:** Simple cylindrical map projection

### Community Resources

- **Cesium Community:** https://community.cesium.com/
- **Cesium GitHub:** https://github.com/CesiumGS/cesium
- **LROC Twitter:** @LROC_ASU
- **NASA LRO:** https://lunar.gsfc.nasa.gov/

---

## Appendix: Complete File Structure

```
deepgis-xr/
├── deepgis_xr/
│   └── apps/
│       └── web/
│           └── templates/
│               └── web/
│                   └── label_moon_viewer.html  ← Main implementation
├── MOON_VIEWER_COMPLETE_GUIDE.md  ← This document
└── static/
    └── (CSS, JavaScript, assets)
```

---

## Appendix: Change Log

### 2025-11-22 - Initial Complete Implementation

**Changes:**
1. ✅ Fixed tile size (256 → 512)
2. ✅ Fixed tiling scheme (8×4 → 2×1)
3. ✅ Fixed coordinate system ({reverseY} → {y})
4. ✅ Added terrain provider (LOLA DEM)
5. ✅ Cleaned up duplicate CSS (39 lines → 12 lines)
6. ✅ Fixed 2D view camera positioning
7. ✅ Verified all configurations against actual tile servers
8. ✅ Created comprehensive documentation

**Status:** Production ready ✅

---

## Quick Reference Card

### Essential URLs
```
Imagery: https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg
Terrain: https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh
```

### Essential Configuration
```javascript
// Tiling
numberOfLevelZeroTilesX: 2
numberOfLevelZeroTilesY: 1

// Tiles
tileWidth: 512
tileHeight: 512

// Ellipsoid
Cesium.Ellipsoid.MOON  // 1,737,400 m radius

// Coordinate System
{y}  // NOT {reverseY}
```

### Essential Commands
```javascript
// Check tiles loading
viewer.imageryLayers.get(0).imageryProvider

// Check terrain
viewer.terrainProvider.ready

// Camera position
viewer.camera.positionCartographic

// Zoom to location
viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(lon, lat, height, Cesium.Ellipsoid.MOON)
})
```

---

**Document Version:** 1.0  
**Last Updated:** 2025-11-22  
**Status:** ✅ Complete and Production Ready  
**Contact:** NASA/GSFC/Arizona State University - LROC Team

---

*End of Complete Implementation Guide*

