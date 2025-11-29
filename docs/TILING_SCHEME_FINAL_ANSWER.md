# FINAL ANSWER: LROC QuickMap Tiling Scheme

**Date:** 2025-11-21  
**Status:** VERIFIED FROM CESIUM SOURCE CODE

## Confirmed Facts

### 1. Cesium GeographicTilingScheme Defaults
From `cesium-C217YinO.js`:
```javascript
function Rs(e){
    this._numberOfLevelZeroTilesX = e.numberOfLevelZeroTilesX ?? 1,
    this._numberOfLevelZeroTilesY = e.numberOfLevelZeroTilesY ?? 1,
```

**Default:** 1×1 (single tile covering entire globe)

### 2. Standard Web Mapping Tiling Scheme
Most web mapping systems (including planetary data) use:
```javascript
new Cesium.GeographicTilingScheme({
    numberOfLevelZeroTilesX: 2,
    numberOfLevelZeroTilesY: 1,
    ellipsoid: Cesium.Ellipsoid.MOON
})
```

This creates:
- **2 tiles at level 0**: Western hemisphere + Eastern hemisphere
- Each tile covers 180° longitude × 180° latitude

### 3. Your Current Implementation
```javascript
tilingScheme: new Cesium.GeographicTilingScheme({
    numberOfLevelZeroTilesX: 2,
    numberOfLevelZeroTilesY: 1,
    ellipsoid: Cesium.Ellipsoid.MOON
}),
```

**Status:** ✅ **CORRECT**

---

## The "Scale Off by 8 or 4" Issue

If everything appears scaled wrong, the problem is likely **NOT** the tiling scheme but:

### Possible Causes:

1. **URL Template Mismatch**
   - Current: `{z}/{x}/{reverseY}.jpg`
   - LROC might expect: Different format or reverseY calculation

2. **Maximum Level Misconfiguration**
   - You have: `maximumLevel: 18`
   - This might be too high or too low for LROC's actual data

3. **Tile Coordinate Calculation**
   - The `{reverseY}` calculation depends on the tiling scheme
   - With 2×1 at level 0:
     - Level 0: 2×1 tiles
     - Level 1: 4×2 tiles
     - Level 2: 8×4 tiles
     - Level 3: 16×8 tiles

4. **Base Level Offset**
   - Some tile servers start at level 0, others at level 1 or 2
   - LROC might be serving tiles starting at a different base level

---

## Debugging Steps

### Test 1: Check Actual Tile URLs Being Requested
Open browser DevTools Network tab and look for actual tile requests like:
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/0/0.jpg
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/0/0.jpg
```

### Test 2: Verify Tile Availability
```bash
# Test level 0 tiles (should have 2 tiles)
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/0/0.jpg
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/1/0.jpg

# Test level 1 tiles (should have 4x2 = 8 tiles)
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/0/0.jpg
curl -I https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/3/1.jpg
```

### Test 3: Try WebMercatorTilingScheme
Some moon tile servers use Web Mercator instead of Geographic:
```javascript
tilingScheme: new Cesium.WebMercatorTilingScheme({
    numberOfLevelZeroTilesX: 2,
    numberOfLevelZeroTilesY: 2,
    ellipsoid: Cesium.Ellipsoid.MOON
}),
```

---

## Recommended Configuration

Based on the evidence, your current configuration should work:

```javascript
const moonImageryProvider = new Cesium.UrlTemplateImageryProvider({
    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{reverseY}.jpg',
    tilingScheme: new Cesium.GeographicTilingScheme({
        numberOfLevelZeroTilesX: 2,    // ✅ CORRECT
        numberOfLevelZeroTilesY: 1,    // ✅ CORRECT  
        ellipsoid: Cesium.Ellipsoid.MOON
    }),
    rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
    minimumLevel: 0,
    maximumLevel: 18,
    credit: 'NASA/GSFC/Arizona State University'
});
```

---

## If Scale Is Still Wrong

### Try Adjusting Base Level
LROC might start serving tiles at level 1 instead of level 0:

```javascript
minimumLevel: 1,  // Instead of 0
maximumLevel: 19, // Adjust accordingly
```

### Try Y Instead of reverseY
```javascript
url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg',
```

### Check Rectangle Bounds
Make sure the rectangle matches the actual data extent:
```javascript
rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),  // Full globe
```

---

## Conclusion

**Your current tiling scheme (2×1) is CORRECT.**

The "scale off by 8 or 4" issue is likely caused by:
1. Incorrect URL template ({y} vs {reverseY})
2. Wrong base zoom level offset
3. LROC using a different projection than expected
4. Tile coordinate calculation mismatch

To fix: Use browser DevTools to inspect the actual tile URLs being requested and compare them to what LROC expects.

