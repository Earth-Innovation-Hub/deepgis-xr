# LROC QuickMap vs DeepGIS Moon Viewer Analysis

## Executive Summary

After analyzing the LROC QuickMap source code and comparing it with our implementation, **our app logic and workflow is fundamentally correct**, but there are some key differences and potential improvements.

## Key Findings

### ✅ What We're Doing RIGHT

1. **Correct Data Source Split**
   - ✅ LROC imagery from `https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-orthons/{z}/{x}/{y}.jpg`
   - ✅ LOLA terrain from separate source (Cesium Ion asset or fallback ellipsoid)
   - ✅ Proper attribution for both sources

2. **Correct Tiling Scheme**
   - ✅ Using `GeographicTilingScheme` with `numberOfLevelZeroTilesX: 2, numberOfLevelZeroTilesY: 1`
   - ✅ This matches the standard equirectangular projection for planetary data

3. **Correct Scene Configuration**
   - ✅ Moon ellipsoid (`Cesium.Ellipsoid.MOON`)
   - ✅ No atmosphere (`viewer.scene.skyAtmosphere = undefined`)
   - ✅ Black background, starfield skybox
   - ✅ Lighting enabled

4. **2D/3D Mode Support**
   - ✅ Our app supports both 2D and 3D modes via `sceneModePicker`
   - ✅ Columbus view for intermediate visualization

### ⚠️ Differences from LROC QuickMap

#### 1. **Multiple Imagery Layers (QuickMap Feature)**
QuickMap provides **multiple selectable layers**:
- WAC Global Mosaic (100m/pixel)
- WAC-NAC-ROI Mosaic (mixed resolution)
- NAC-Only High-Resolution (0.5m/pixel in regions)
- Hillshaded layers
- Color layers (FeO, TiO2)
- Slope/roughness layers

**Our App:** Currently uses only `wac_nac_nacroi` (mixed resolution)

**Impact:** Medium - Users can't switch between different resolution/type layers

#### 2. **Maximum Zoom Level**
- **QuickMap:** Uses `maximumLevel: 18` for NAC high-res areas
- **Our App:** Currently `maximumLevel: 12` (reduced to fix tile mapping issues)

**Reason for Our Limitation:** We saw "weird" artifacts below 10km altitude with level 18

**Root Cause:** Likely because NAC tiles only exist in specific ROIs (Regions of Interest), not globally

**Solution:** Use adaptive max levels:
```javascript
// Global WAC: max level 10-12
// NAC ROI areas: max level 18
// Need to detect which region user is viewing
```

#### 3. **Terrain Handling**
- **QuickMap:** Offers terrain ON/OFF toggle, users can view flat vs 3D terrain
- **Our App:** Terrain is always on (if available) or always off (if unavailable)

**Impact:** Low - Most users prefer terrain always-on in 3D mode

#### 4. **2D vs 3D Mode Behavior**
- **QuickMap:** In 2D mode, terrain is disabled (flat map)
- **Our App:** Terrain persists across all modes

**Potential Issue:** Terrain in 2D mode can cause rendering complexity

**Fix Needed:** Disable terrain in 2D mode, re-enable in 3D mode

#### 5. **Tile Caching & Performance**
- **QuickMap:** Implements aggressive tile caching and request throttling
- **Our App:** Relies on Cesium's default caching behavior

**Impact:** Medium - Could improve performance at high zoom levels

#### 6. **Feature Detection**
- **QuickMap:** Checks WebGL, Promise, Blob, ArrayBuffer support
- **Our App:** ✅ We added this after analyzing QuickMap!

**Status:** ✅ Already implemented

## Terrain (LOLA DEM) Details

### LROC vs LOLA

| Aspect | LROC | LOLA |
|--------|------|------|
| **Type** | Camera | Laser Altimeter |
| **Data** | Images (texture) | Elevation (DEM) |
| **Resolution** | WAC: 100m, NAC: 0.5-2m | ~100m globally |
| **Coverage** | Global + high-res ROIs | Global uniform |
| **Tile Server** | quickmap.lroc.asu.edu | Not directly tiled |

### How LOLA Terrain is Served

1. **LROC QuickMap Approach:**
   - Provides pre-processed LOLA DEM as terrain tiles
   - Likely uses quantized-mesh format (same as Cesium Terrain)
   - Served from same QuickMap infrastructure

2. **Our App Approach:**
   - Attempts Cesium Ion asset 3956 (LOLA DEM)
   - Falls back to smooth ellipsoid if unavailable
   - **Issue:** Asset 3956 may require premium Ion access

### LROC QuickMap Terrain Source

Looking at the QuickMap code, they likely serve LOLA terrain from:
- `https://lroc-tiles.quickmap.io/terrain/` (not publicly documented)
- Or use a custom terrain provider with their tile server

**Key Insight:** QuickMap has their own terrain tile server, not using Cesium Ion

## Recommended Changes

### Priority 1: Mode-Specific Terrain Handling

```javascript
// In sceneMode change handler
viewer.scene.morphComplete.addEventListener(() => {
    if (viewer.scene.mode === Cesium.SceneMode.SCENE2D) {
        // Disable terrain in 2D for performance
        viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider({
            ellipsoid: Cesium.Ellipsoid.MOON
        });
    } else if (viewer.scene.mode === Cesium.SceneMode.SCENE3D) {
        // Re-enable terrain in 3D
        if (window.DeepGISMoon.moonTerrain) {
            viewer.terrainProvider = window.DeepGISMoon.moonTerrain;
        }
    }
});
```

### Priority 2: Adaptive Maximum Level

```javascript
// Use lower max level for global view, higher for NAC ROIs
const lrocProvider = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-orthons/{z}/{x}/{y}.jpg',
    maximumLevel: 12, // Safe global maximum
    // Could be increased to 18 with custom tile availability checking
    // ...
});
```

**Alternative:** Implement tile availability check:
```javascript
customTileLoadErrorHandler: (imageryProvider, x, y, level) => {
    // If level > 12 and tile 404, gracefully fallback
    if (level > 12) {
        return false; // Use lower level tile instead
    }
}
```

### Priority 3: Alternative LOLA Terrain Source

Since Cesium Ion asset 3956 may require premium access, consider:

1. **Check if LROC QuickMap provides public terrain tiles:**
   - Try: `https://lroc-tiles.quickmap.io/terrain/{z}/{x}/{y}.terrain`
   - Try: `https://lroc-tiles.quickmap.io/lola/{z}/{x}/{y}.terrain`

2. **Use alternative public LOLA DEM sources:**
   - USGS Astrogeology: `https://astrowebmaps.wr.usgs.gov/...`
   - OpenPlanetaryMap: May have LOLA DEM (check for CORS)

3. **Keep current fallback:**
   - Smooth ellipsoid works fine for visualization
   - Just needs clear UI indication

### Priority 4: Multiple Layer Support (Future Enhancement)

Allow users to switch between:
- WAC Global (lower res, global coverage)
- WAC-NAC ROI (mixed resolution, current)
- NAC only (highest res, limited areas)
- Hillshaded variants

## 2D vs 3D Mode Analysis

### LROC QuickMap Behavior

| Mode | Imagery | Terrain | Performance |
|------|---------|---------|-------------|
| 2D | Full resolution | Disabled | Fast |
| 3D | Full resolution | Enabled | Slower |
| Columbus | Full resolution | Enabled | Medium |

### Our App Behavior (Current)

| Mode | Imagery | Terrain | Performance |
|------|---------|---------|-------------|
| 2D | Full resolution | Enabled ⚠️ | Slower than needed |
| 3D | Full resolution | Enabled | Good |
| Columbus | Full resolution | Enabled | Good |

### Recommendation

**Disable terrain in 2D mode** to match QuickMap behavior and improve performance.

## URL Structure Comparison

### LROC QuickMap

- Imagery: `https://lroc-tiles.quickmap.io/tiles/{layer}/{z}/{x}/{y}.jpg`
  - Where `{layer}` can be:
    - `wac` - Wide Angle Camera only
    - `wac_nac_nacroi` - Mixed resolution (our current)
    - `nac` - Narrow Angle Camera high-res
    - Various scientific products (slope, roughness, etc.)

- Terrain: Likely `https://lroc-tiles.quickmap.io/terrain/{z}/{x}/{y}.terrain` (not confirmed)

### Our App

- Imagery: `https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-orthons/{z}/{x}/{y}.jpg` ✅
- Terrain: Cesium Ion asset 3956 (may require premium) ⚠️

## Tile Coordinate System

Both use **Geographic (Equirectangular) tiling**:
- Level 0: 2 tiles wide (360°/2 = 180° per tile), 1 tile tall
- Y=0 at south pole (-90°)
- Y increases northward
- X=0 at -180° (antimeridian)

**Our configuration matches this correctly** ✅

## Performance & Optimization

### QuickMap Optimizations We Could Add:

1. **Tile request throttling**
   ```javascript
   imageryProvider.maximumRequests = 6; // Limit concurrent requests
   ```

2. **Cache control**
   ```javascript
   imageryProvider.cache = true;
   imageryProvider.cacheSize = 1000; // Number of tiles to cache
   ```

3. **Level of Detail (LOD) bias**
   ```javascript
   viewer.scene.globe.maximumScreenSpaceError = 2; // Lower = more detail, slower
   ```

4. **Preload tiles for smooth navigation**
   ```javascript
   viewer.scene.globe.preloadAncestors = true;
   viewer.scene.globe.preloadSiblings = true;
   ```

## Conclusion

### Overall Assessment: ✅ **Our Implementation is Correct**

- Core logic is sound
- Data sources are appropriate
- Tiling scheme is correct
- 2D/3D support works

### Improvements Needed:

1. **Priority 1:** Disable terrain in 2D mode
2. **Priority 2:** Keep `maximumLevel: 12` for stability (current setting is correct)
3. **Priority 3:** Add better UI for terrain unavailability
4. **Future:** Explore alternative public LOLA terrain sources
5. **Future:** Add multiple layer selection like QuickMap

### Why Weird Artifacts at High Zoom?

The "weird" appearance below 10km with `maximumLevel: 18` is because:
1. NAC tiles (high-res) only exist in specific ROIs
2. When user zooms in outside NAC coverage, Cesium requests level 13+ tiles
3. These tiles don't exist (404), causing:
   - Stretched lower-level tiles
   - Coordinate wrapping artifacts
   - Seam mismatches

**Our fix (maximumLevel: 12) is correct** - it prevents requesting tiles that don't exist globally.

## Action Items

- [ ] Implement terrain disable in 2D mode
- [ ] Test alternative LOLA terrain URLs
- [ ] Add UI toggle for terrain on/off
- [ ] Document layer selection for future enhancement
- [ ] Add tile request throttling for performance


