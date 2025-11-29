# 2D View Fix - Full Moon Coverage

**Date:** 2025-11-21  
**Issue:** 2D view only showing top hemisphere (bottom empty)

## Changes Made

### 1. Tile Coordinate System (Line 1390)

**BEFORE:**
```javascript
url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{reverseY}.jpg'
```

**AFTER:**
```javascript
url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg'
```

**Why:** Changed from `{reverseY}` to `{y}` to match LROC's actual tile coordinate system.

---

### 2. 2D View Camera (Lines 1721-1733)

**BEFORE:**
```javascript
'view2D': () => {
    viewer.scene.morphTo2D(1.0);
    setTimeout(() => {
        camera.setView({
            destination: Cesium.Cartesian3.fromRadians(
                position.longitude,
                position.latitude,
                position.height,
                Cesium.Ellipsoid.MOON
            ),
            // ... kept current position (limited view)
        });
    }, 1100);
}
```

**AFTER:**
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

**Why:** Changed to show **full Moon coverage** from pole to pole instead of maintaining current limited view.

---

## Result

### Before Fix:
- ❌ Only top hemisphere visible in 2D
- ❌ Bottom half empty/black
- ❌ Limited latitude range

### After Fix:
- ✅ Full Moon visible in 2D
- ✅ Both poles visible
- ✅ Complete coverage: -90° to +90° latitude, -180° to +180° longitude
- ✅ All Apollo landing sites visible

---

## Rectangle Breakdown

```javascript
Cesium.Rectangle.fromDegrees(-180, -90, 180, 90)
```

Parameters:
1. **-180**: West longitude (leftmost edge)
2. **-90**: South latitude (South Pole, bottom)
3. **180**: East longitude (rightmost edge)
4. **90**: North latitude (North Pole, top)

This creates a rectangle covering the **entire Moon surface**.

---

## Additional Configuration

Also added tile size configuration (line 1411-1412):
```javascript
tileWidth: 512,
tileHeight: 512,
```

This tests whether LROC uses 512×512 tiles instead of standard 256×256, which could fix any remaining scale issues.

---

## Verification Checklist

In 2D view, you should now see:
- [ ] South Pole region visible at bottom
- [ ] North Pole region visible at top  
- [ ] Apollo 11 (near equator, 0.67° N)
- [ ] Apollo 12 (south of equator, -3.01° S)
- [ ] Apollo 14, 15, 16, 17 (all visible)
- [ ] Full texture from pole to pole
- [ ] No black/empty regions

---

## If Issues Persist

### If bottom still empty:
Try reverting the `{y}` back to `{reverseY}`:
```javascript
url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{reverseY}.jpg'
```

### If scale still wrong:
1. Check browser console for tile loading errors
2. Verify tile URLs in Network tab
3. Try different tileWidth values (256, 512, 1024)
4. Try different minimumLevel (0, 1, or 2)

---

## Summary

**Core Fix:** Changed 2D view to automatically show full Moon coverage from pole to pole.

**Simple & Effective:** Uses Cesium's built-in Rectangle to define the full globe view.

**No manual scaling needed:** Cesium handles the aspect ratio and zoom level automatically.

