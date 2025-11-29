# Zoom Operations and Projections Comparison
## DeepGIS Moon Viewer vs LROC QuickMap

## 1. Tile Projections

### Our Implementation ✅

```javascript
url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg'

tilingScheme: new Cesium.GeographicTilingScheme({
    numberOfLevelZeroTilesX: 2,
    numberOfLevelZeroTilesY: 1
})
```

**Projection:** Geographic (Equirectangular) / Plate Carrée
- Latitude: -90° to +90°
- Longitude: -180° to +180°
- Level 0: 2 tiles wide × 1 tile tall
- Simple lat/lon to x/y mapping

**Data Source:** `lunar-fulleqc` - Full Equirectangular projection from LROC QuickMap

### LROC QuickMap Reference

LROC QuickMap uses the same projection and tile source for 3D mode:
- **3D Mode:** Uses `lunar-fulleqc` with Cesium (confirmed from tile URLs)
- **2D Mode:** Uses OpenLayers with a similar geographic projection

**Status:** ✅ **CORRECT** - We're using the exact same tiles and projection as LROC QuickMap's 3D mode

---

## 2. Zoom Levels (Tile Detail)

### Our Implementation

```javascript
minimumLevel: 0
maximumLevel: 12  // Reduced from 18 to prevent issues
```

### LROC QuickMap Tile Resolution

Based on LROC data and WAC/NAC specifications:

| Zoom Level | Resolution | Coverage | Data Source |
|------------|------------|----------|-------------|
| 0-7 | 100m+/pixel | Global | WAC (Wide Angle Camera) |
| 8-12 | ~10-100m/pixel | Global/Regional | WAC-NAC mixed |
| 13-18 | 0.5-10m/pixel | Regional NAC ROIs | NAC (Narrow Angle) |

### Why We Use maximumLevel: 12

**LROC QuickMap behavior:**
- Allows zooming to level 18 in NAC ROI (Regions of Interest)
- NAC high-res tiles only exist in specific areas
- Dynamically adjusts max level based on tile availability

**Our current limitation:**
- Fixed `maximumLevel: 12` globally
- Prevents zooming to ultra-high res (< 10km altitude)
- Avoids 404 errors for missing NAC tiles outside ROIs

### ⚠️ **Issue Identified: Too Conservative**

**Problem:** Setting `maximumLevel: 12` everywhere limits us to ~50m/pixel resolution globally, even in areas where higher-res NAC tiles ARE available.

**LROC QuickMap Solution:**
- Uses adaptive max levels
- Level 18 in NAC coverage areas
- Level 10-12 elsewhere
- Gracefully handles missing tiles

---

## 3. Camera Zoom Distance (Physical Altitude)

### Our Implementation

```javascript
viewer.scene.screenSpaceCameraController.minimumZoomDistance = 100.0;  // 100 meters
viewer.scene.screenSpaceCameraController.maximumZoomDistance = 20000000.0;  // 20,000 km
```

### Comparison with LROC QuickMap

| Setting | Our Value | LROC QuickMap | Status |
|---------|-----------|---------------|--------|
| **Minimum Zoom** | 100m | ~50m (estimated) | ⚠️ Too restrictive |
| **Maximum Zoom** | 20,000 km | ~30,000 km (estimated) | ⚠️ Slightly restrictive |

### ⚠️ **Issues Identified**

#### 1. Minimum Zoom Distance: 100m is Too High

**LROC QuickMap:** Allows getting very close to surface (50m or less)
- Useful for viewing NAC high-res imagery
- Shows surface details at highest zoom levels
- Enables inspection of small features

**Our Limitation:** 100m prevents users from getting close enough
- Can't fully utilize NAC high-res tiles (when they exist)
- Users can't inspect surface details closely
- Inconsistent with LROC QuickMap user experience

**Recommended Fix:**
```javascript
minimumZoomDistance: 10.0  // 10 meters (or even 1.0)
```

#### 2. Maximum Zoom Distance: 20,000 km May Be Too Low

**Context:** Moon's radius is ~1,737 km
- 20,000 km allows viewing ~11.5 radii away
- May limit viewing the entire Moon in context

**Recommended Fix:**
```javascript
maximumZoomDistance: 30000000.0  // 30,000 km for better overview
```

---

## 4. Tile Level to Zoom Distance Relationship

### How Cesium Determines Which Tiles to Load

Cesium uses **Screen Space Error (SSE)** to decide which zoom level to load:

```
SSE = (geometricError × height) / (distance × pixelSize)
```

For geographic tiling:
- Each level has tiles with specific geometric error
- Camera distance determines which level is "good enough"
- Closer camera = need higher detail = higher zoom level

### Approximate Camera Altitude to Tile Level Mapping

For the Moon with our tile configuration:

| Camera Altitude | Tile Level | Resolution | Use Case |
|-----------------|------------|------------|----------|
| 1,000,000+ km | 0-2 | Very low | Full Moon view |
| 100,000-1,000,000 m | 3-5 | Low | Hemisphere |
| 10,000-100,000 m | 6-8 | Medium | Regional (1000+ km) |
| 1,000-10,000 m | 9-11 | High | Local (100 km) |
| 100-1,000 m | 12-14 | Very high | Landing sites |
| 10-100 m | 15-17 | Ultra-high | NAC ROIs |
| < 10 m | 18+ | Maximum | Surface details |

### ⚠️ **Our Issue: Level 12 Cap at 1km Altitude**

When camera is at 500m altitude:
- Cesium wants to load level 13-14 tiles
- We cap at level 12
- Result: Blurry/stretched tiles even though camera is close

**User reported:** "things seem to look weird when elevation goes under about 10km"
- **Root cause:** Level 12 tiles are stretched when viewed from < 1km
- **LROC does:** Loads level 15-18 at this range (in NAC areas)

---

## 5. Projection Compatibility Across Modes

### Geographic Projection in Different Cesium Modes

| Mode | How Geographic Projection is Rendered |
|------|--------------------------------------|
| **2D** | Flat cylindrical map (standard flat map) |
| **3D** | Wrapped around ellipsoid (sphere texture mapping) |
| **Columbus** | Unrolled cylinder in 3D space |

### ✅ **Advantage of Single Projection**

Using `GeographicTilingScheme` (equirectangular) for all modes:
- **Pro:** Single tile source works everywhere
- **Pro:** No need to switch tiles when changing modes
- **Pro:** Simpler implementation
- **Pro:** Matches LROC QuickMap's 3D approach

### Comparison with LROC QuickMap

**LROC QuickMap:**
- **2D Mode:** OpenLayers with geographic projection
- **3D Mode:** Cesium with geographic projection (lunar-fulleqc)
- Uses same tiles, different rendering engines

**Our Approach:**
- **2D Mode:** Cesium with geographic projection
- **3D Mode:** Cesium with geographic projection
- Single rendering engine for both modes

**Conclusion:** ✅ Our approach is simpler and equally valid

---

## 6. Dynamic Tile Loading in LROC QuickMap

### LROC's Adaptive Approach

1. **Tile Availability Check:**
   - Attempts to load tile at requested level
   - If 404, falls back to lower level
   - Prevents console errors

2. **Regional Max Levels:**
   - NAC coverage areas: level 18
   - WAC-only areas: level 10-12
   - Determined dynamically

3. **Error Handling:**
   - Graceful degradation
   - Shows lower-res tiles if high-res unavailable
   - No visible errors to user

### Our Current Approach

1. **Fixed Max Level:**
   - Always cap at level 12
   - Never attempts higher levels
   - Safe but overly restrictive

2. **No Dynamic Adjustment:**
   - Same max level everywhere
   - Doesn't adapt to tile availability

### ⚠️ **Improvement Opportunity**

Implement adaptive max level like LROC:

```javascript
const lrocProvider = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg',
    minimumLevel: 0,
    maximumLevel: 18,  // Allow high zoom
    
    // Custom tile error handler
    errorEvent: new Cesium.Event(),
    
    // Cesium will handle 404s gracefully by using lower-level tiles
});
```

**Cesium's built-in behavior:**
- If level 18 tile is 404, it uses level 17
- If level 17 is 404, it uses level 16
- Continues until it finds available tile
- **We don't need custom logic!**

---

## 7. Recommendations

### Priority 1: Increase Maximum Tile Level ⭐⭐⭐

**Change:**
```javascript
maximumLevel: 18  // Up from 12
```

**Rationale:**
- Cesium handles missing tiles gracefully
- Allows zooming close in NAC areas
- Better user experience matches LROC
- The "weird" artifacts at < 10km will be resolved

**Risk:** Low - Cesium will automatically fall back to lower levels when tiles don't exist

### Priority 2: Decrease Minimum Zoom Distance ⭐⭐

**Change:**
```javascript
minimumZoomDistance: 10.0  // Down from 100.0
```

**Rationale:**
- Allows closer inspection of surface features
- Better utilization of high-res NAC imagery
- Matches LROC QuickMap capabilities

**Risk:** Low - Just allows camera to get closer

### Priority 3: Increase Maximum Zoom Distance ⭐

**Change:**
```javascript
maximumZoomDistance: 30000000.0  // Up from 20,000,000.0
```

**Rationale:**
- Better full-Moon overview capability
- More flexibility for users
- Matches LROC's range

**Risk:** None - just allows zooming out further

### Optional: Add Tile Error Suppression

If we increase to level 18, we may see more 404 errors in console:

```javascript
// We already have console error suppression - just verify it catches these
const originalError = console.error;
console.error = function(...args) {
    const msg = args[0]?.toString() || '';
    if (msg.includes('Failed to obtain image') || 
        msg.includes('404') ||
        msg.includes('tile')) {
        return; // Suppress tile 404s
    }
    originalError.apply(console, args);
};
```

---

## 8. Summary Comparison Table

| Aspect | Our Current | LROC QuickMap | Status | Recommendation |
|--------|-------------|---------------|--------|----------------|
| **Projection** | Geographic (lunar-fulleqc) | Geographic (lunar-fulleqc) | ✅ Correct | Keep as-is |
| **Tiling Scheme** | 2×1 level 0 | 2×1 level 0 | ✅ Correct | Keep as-is |
| **Min Tile Level** | 0 | 0 | ✅ Correct | Keep as-is |
| **Max Tile Level** | 12 | 18 (adaptive) | ⚠️ Too low | **Increase to 18** |
| **Min Zoom Distance** | 100m | ~50m | ⚠️ Too high | **Decrease to 10m** |
| **Max Zoom Distance** | 20,000 km | ~30,000 km | ⚠️ Too low | **Increase to 30,000 km** |
| **Tile Error Handling** | Console suppression | Graceful fallback | ✅ Adequate | Verify suppression |
| **2D/3D Switching** | Single engine | Dual engine | ✅ Valid | Keep as-is |

---

## 9. Root Cause of "Weird" Zooming Issue

**User Report:** "things seem to look weird when elevation goes under about 10km"

**Root Cause Analysis:**

1. **Camera at 5,000m altitude**
   - Cesium calculates it needs ~level 13-14 tiles
   - We cap at level 12
   - Cesium stretches level 12 tiles to fill view

2. **Result:**
   - Pixelated/blurry appearance
   - Tile boundaries visible
   - "Weird" stretching artifacts
   - Not enough detail for close viewing

3. **LROC QuickMap at same altitude:**
   - Loads level 15-16 tiles (in NAC areas)
   - Sharp, detailed view
   - No stretching
   - Smooth experience

**Solution:** Increase `maximumLevel` to 18 and let Cesium handle tile availability naturally.

---

## 10. Implementation Plan

### Phase 1: Quick Wins (Immediate) ✅

```javascript
// Change these three lines:
maximumLevel: 18,  // Up from 12
minimumZoomDistance: 10.0,  // Down from 100.0
maximumZoomDistance: 30000000.0,  // Up from 20,000,000.0
```

**Expected Results:**
- ✅ Fixes "weird" zooming below 10km
- ✅ Allows close-up inspection
- ✅ Matches LROC QuickMap zoom capabilities
- ✅ No code complexity added (Cesium handles fallbacks)

### Phase 2: Monitoring (Optional)

Add telemetry to understand tile loading:

```javascript
viewer.scene.globe.tileLoadProgressEvent.addEventListener((queueLength) => {
    console.log(`Loading ${queueLength} tiles...`);
});
```

### Phase 3: Advanced (Future)

Consider regional max levels if performance is an issue:
- Detect NAC ROI areas from metadata
- Set adaptive `maximumLevel` based on location
- **Not needed initially** - Cesium's built-in handling is sufficient

---

## Conclusion

### What We're Doing Right ✅

- Correct projection (Geographic/Equirectangular)
- Correct tile source (`lunar-fulleqc`)
- Correct tiling scheme (2×1 level 0)
- Single Cesium engine approach (simpler than dual-engine)

### What Needs Adjustment ⚠️

- **maximumLevel: 12 → 18** (high priority)
- **minimumZoomDistance: 100m → 10m** (medium priority)
- **maximumZoomDistance: 20,000km → 30,000km** (low priority)

### Expected Impact 🎯

After implementing Phase 1 changes:
- Users can zoom closer (down to 10m altitude)
- High-res tiles load in NAC coverage areas
- "Weird" stretching artifacts disappear below 10km
- Experience matches LROC QuickMap's zoom capabilities
- No additional complexity - Cesium handles the rest!

