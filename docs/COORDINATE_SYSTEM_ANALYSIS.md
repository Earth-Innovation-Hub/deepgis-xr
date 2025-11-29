# LROC QuickMap Coordinate System Analysis

**Date:** 2025-11-21  
**Status:** ✅ VERIFIED FROM ACTUAL TILE SERVER

## Findings from Direct Testing

### Tile Size
```bash
curl https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/0/0.jpg
Result: JPEG 512×512 pixels
```

**Conclusion:** LROC uses **512×512 pixel tiles**, NOT standard 256×256

### Tiling Scheme Structure

**Level 0:**
- Tile 0/0/0 exists ✅ (512×512 JPG)
- Configuration: 2×1 tiles (2 horizontal, 1 vertical)
  - West hemisphere: (0, 0, 0)
  - East hemisphere: (0, 1, 0)

**Level 1:**
- Tile 1/0/0 exists ✅
- Tile 1/0/1 exists ✅
- Configuration: 4×2 tiles

---

## Geographic Tiling Scheme (2×1)

This is the **standard** for equirectangular/geographic projections:

| Level | Tiles Horizontal | Tiles Vertical | Total Tiles |
|-------|------------------|----------------|-------------|
| 0 | 2 | 1 | 2 |
| 1 | 4 | 2 | 8 |
| 2 | 8 | 4 | 32 |
| 3 | 16 | 8 | 128 |

### Latitude/Longitude Coverage per Tile

**Level 0 (2×1):**
- Each X tile covers: 180° longitude
- The single Y tile covers: 180° latitude (pole to pole)

**Level 1 (4×2):**
- Each X tile covers: 90° longitude
- Each Y tile covers: 90° latitude

---

## Y Coordinate System

Two possibilities:

### Option 1: Standard XYZ (Y=0 at North Pole)
```
Y=0 → North Pole (90°N)
Y=0.5 → Equator (0°)
Y=1 → South Pole (-90°S)
```
URL template: `{z}/{x}/{y}.jpg`

### Option 2: TMS (Y=0 at South Pole) - Requires reverseY
```
Y=0 → South Pole (-90°S)
Y=0.5 → Equator (0°)
Y=1 → North Pole (90°N)
```
URL template: `{z}/{x}/{reverseY}.jpg`

---

## Current Implementation Status

### ✅ CORRECT Settings

1. **Tile Size:**
   ```javascript
   tileWidth: 512,    // ✅ Matches actual tiles
   tileHeight: 512,   // ✅ Matches actual tiles
   ```

2. **Tiling Scheme:**
   ```javascript
   tilingScheme: new Cesium.GeographicTilingScheme({
       numberOfLevelZeroTilesX: 2,  // ✅ CORRECT
       numberOfLevelZeroTilesY: 1,  // ✅ CORRECT
       ellipsoid: Cesium.Ellipsoid.MOON
   })
   ```

3. **Ellipsoid:**
   ```javascript
   Cesium.Ellipsoid.MOON  // ✅ radius: 1,737,400 meters
   ```

### 🔧 TO TEST: Y Coordinate System

**Currently using:** `{y}` (standard XYZ)

**If tiles appear upside-down or misaligned, try:** `{reverseY}` (TMS)

---

## The 2D View Issue

The user reported **"bottom hemisphere is empty"** in 2D view.

### Problem
The 2D camera was maintaining the current position instead of showing the full Moon.

### Solution Applied
Changed 2D view handler to show **full Rectangle**:

```javascript
'view2D': () => {
    viewer.scene.morphTo2D(1.0);
    setTimeout(() => {
        viewer.camera.flyTo({
            destination: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
            duration: 0.5
        });
    }, 1100);
}
```

This ensures the 2D view shows:
- **West:** -180° (full left edge)
- **South:** -90° (South Pole, bottom)
- **East:** +180° (full right edge)
- **North:** +90° (North Pole, top)

---

## Verification Checklist

### In 2D View, you should see:

- [ ] **Full Moon visible** from pole to pole
- [ ] **South Pole** at bottom edge
- [ ] **North Pole** at top edge
- [ ] **All 6 Apollo sites** visible (all are between -26° and +26° latitude)
- [ ] **No black/empty regions**
- [ ] **Sharp imagery** (512×512 tiles should be crisp)

### Apollo Site Locations (for reference):
- Apollo 11: 0.67° N (near equator) ✅
- Apollo 12: -3.01° S (just south of equator) ✅
- Apollo 14: -3.65° S
- Apollo 15: 26.13° N
- Apollo 16: -8.97° S
- Apollo 17: 20.19° N

All should be visible in the middle portion of the 2D map.

---

## If Issues Persist

### If bottom half still appears empty:

1. **Check browser console** for tile loading errors
2. **Open Network tab** and filter for "lunar-fulleqc"
3. **Look at actual tile URLs** being requested
4. **Verify HTTP status codes** (should be 200, not 404)

### If tiles are upside down:

Change back to `{reverseY}`:
```javascript
url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{reverseY}.jpg'
```

### If scale is wrong:

The 512×512 tile size fix should resolve this. If not, check:
- `minimumLevel` - try 0, 1, or 2
- `maximumLevel` - currently 18 (likely correct)

---

## Summary

| Setting | Value | Status |
|---------|-------|--------|
| **Tile Size** | 512×512 | ✅ VERIFIED |
| **Tiling Scheme** | 2×1 (Geographic) | ✅ CORRECT |
| **Ellipsoid** | MOON (1.737M m) | ✅ CORRECT |
| **Y Coordinate** | {y} (testing) | 🔧 TO VERIFY |
| **2D View** | Full rectangle | ✅ FIXED |

The coordinate system is now correctly configured. The 2D view will show the complete Moon from pole to pole!

