# CRITICAL Coordinate System Correction

**Date:** November 22, 2025  
**Issue:** Incorrect tile coordinate system (TMS vs XYZ)

---

## Problem

Our implementation was using `{reverseY}` in the tile URL, assuming LROC used TMS (Tile Map Service) coordinate system where Y=0 is at the South Pole.

**Wrong URL:**
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{reverseY}.jpg
```

## Investigation

By inspecting the actual LROC QuickMap website's network requests when in 3D "Lunar Globe" mode, we discovered they use **standard XYZ coordinates**:

**Actual LROC URLs:**
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/0/0.jpg
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/1/0.jpg
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/3/3/1.jpg
```

They use `{z}/{x}/{y}` format, NOT `{z}/{x}/{reverseY}`.

## Coordinate System Clarification

### XYZ (Standard) - What LROC Actually Uses
- **Y=0 at North Pole** (top of the map)
- **Y increases southward** (towards South Pole)
- **Origin:** Top-left corner (Northwest)
- **Standard for most web mapping tiles**

### TMS (Tile Map Service) - What We Incorrectly Assumed
- **Y=0 at South Pole** (bottom of the map)
- **Y increases northward** (towards North Pole)
- **Origin:** Bottom-left corner (Southwest)
- **Used by some tile servers, but NOT LROC**

## Solution

Changed the URL template from `{reverseY}` to `{y}`:

**Corrected URL:**
```
https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg
```

## Impact

This change affects:
- ✅ Tile loading orientation in both 2D and 3D modes
- ✅ North/South hemisphere display
- ✅ Polar region rendering
- ✅ All zoom levels

## Verification Method

1. Opened LROC QuickMap at https://quickmap.lroc.im-ldi.com/
2. Switched to "Lunar Globe (3D)" projection
3. Opened browser Developer Tools → Network tab
4. Observed actual tile requests:
   ```
   https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{z}/{x}/{y}.jpg
   ```
5. Confirmed they use `{y}` not `{reverseY}`

## Previous Misunderstanding

We had previously tested tile existence using curl and observed:
- Tile at `1/0/0` (71KB) - Larger file, more detail
- Tile at `1/0/3` (4.7KB) - Smaller file, mostly black space

We incorrectly interpreted this as TMS because Y=3 appeared to be at the pole. However, we didn't consider that in a 2×2 tiling scheme at level 0, level 1 has 4×4 tiles, so Y=3 is indeed at the top (near North Pole) in standard XYZ!

## Lesson Learned

**Always verify by observing the actual tile server's behavior**, not just by theoretical analysis or file size comparisons. The definitive proof is in the network requests from the official application.

---

## Status

**FIXED** - Changed `{reverseY}` to `{y}` in line 1410 of `label_moon_viewer.html`

**File:** `/home/jdas/dreams-lab-website-server/deepgis-xr/deepgis_xr/apps/web/templates/web/label_moon_viewer.html`

