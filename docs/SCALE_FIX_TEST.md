# Scale Fix Test - Moon Viewer

**Date:** 2025-11-21  
**Issue:** Scale appears off by factor of 8 or 4

## Changes Made

### Test 1: Tile Size Increased to 512×512

**File:** `label_moon_viewer.html` line ~1411-1412

```javascript
tileWidth: 512,    // TEST: Try 512 instead of default 256 (factor of 2)
tileHeight: 512,   // TEST: Try 512 instead of default 256 (factor of 2)
```

**Rationale:**
- LROC tiles might be 512×512 pixels instead of standard 256×256
- This is a factor of 2 in each dimension (4× total area)
- Would explain why things appear 2× too small or large

---

## Test Results Expected

### If 512×512 is CORRECT:
✅ **Moon should appear at proper scale**
✅ **Imagery should align with globe**
✅ **No stretching or distortion**

### If 512×512 makes it WORSE:
❌ **Revert to 256×256 (or try not specifying at all)**

---

## Alternative Tests if 512×512 Doesn't Work

### Test 2: Try Zoom Level Offset

If scale is still wrong, LROC might use a different base zoom level:

```javascript
minimumLevel: 2,   // Start at level 2 instead of 0
maximumLevel: 20,  // Adjust max accordingly
```

**This would fix:** Scale off by factor of 4 (if LROC's level 0 = standard level 2)

### Test 3: Try Y Instead of reverseY

```javascript
url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg',
```

**This would fix:** Tiles appearing upside down or misaligned

### Test 4: Try Different Tile Format

LROC might serve tiles in PNG format with better quality:

```javascript
url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{reverseY}.png',
```

---

## How to Test

1. **Load the application** in browser
2. **Check browser DevTools → Network tab**
3. **Look for tile requests** like:
   ```
   https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/0/0/0.jpg
   ```
4. **Download a tile** and check its actual size:
   ```bash
   curl https://lroc-tiles.quickmap.io/tiles/.../0/0/0.jpg -o test_tile.jpg
   file test_tile.jpg  # Should show: "JPEG image data, 512 x 512" or similar
   ```

---

## Debugging Checklist

- [ ] Check actual tile pixel dimensions (256×256 or 512×512?)
- [ ] Verify tile URL format in network requests
- [ ] Check if tiles are loading (200 status) or failing (404 status)
- [ ] Test at different zoom levels
- [ ] Compare with LROC QuickMap official site behavior
- [ ] Check console for Cesium errors/warnings

---

## Moon Ellipsoid Status: ✅ CORRECT

Your implementation correctly uses:
- `Cesium.Ellipsoid.MOON` (radius: 1,737,400 meters)
- Applied consistently across:
  - Globe rendering
  - Tiling scheme
  - Terrain provider
  - Position calculations
  - Camera movements

**No changes needed to ellipsoid configuration!**

---

## Quick Revert if Needed

If 512×512 makes things worse, revert by:

1. **Remove the tileWidth/tileHeight lines** (lines 1411-1412)
2. **Or change back to 256:**
   ```javascript
   tileWidth: 256,
   tileHeight: 256,
   ```

---

## Expected Outcome

With correct tile size, you should see:
1. **Proper scale** - Moon looks correctly sized
2. **Sharp imagery** - No blurry or pixelated areas
3. **Aligned features** - Craters and landmarks in correct positions
4. **Smooth zoom** - No sudden jumps or scale changes

Report back with what you observe!

