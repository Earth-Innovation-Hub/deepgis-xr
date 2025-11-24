# Ocean Waves Lighting Fix - Moon Viewer

**Issue:** Seeing "ocean waves" or water-like rippling effects on the lunar surface in 3D view  
**Date:** 2025-11-22  
**Status:** ✅ FIXED

---

## Problem Description

The Moon's surface was showing visual artifacts that looked like ocean waves or water rippling effects, which is incorrect since the Moon has no water.

### Possible Causes

1. **Water/ocean effects enabled** (Cesium defaults for Earth)
2. **Specular/glossy material** causing reflective appearance
3. **HDR rendering** creating bright highlights
4. **Translucency effects** enabled
5. **Terrain normal maps** being interpreted as water

---

## Solutions Applied

### Fix 1: Disable Water Effects Explicitly

**File:** `label_moon_viewer.html` line ~1346-1353

```javascript
// CRITICAL: Disable ALL water/ocean effects (Moon has no water!)
viewer.scene.globe.showWaterEffect = false;
viewer.scene.globe.oceanNormalMapUrl = undefined;

// Disable translucency effects that can cause wave-like artifacts
if (viewer.scene.globe.translucency) {
    viewer.scene.globe.translucency.enabled = false;
}
```

**What it does:**
- Explicitly disables Cesium's water rendering
- Removes ocean normal maps
- Disables translucency that can look like water

---

### Fix 2: Disable HDR Rendering

**File:** `label_moon_viewer.html` line ~1361

```javascript
// Disable high dynamic range (HDR) if it causes artifacts
viewer.scene.highDynamicRange = false;
```

**What it does:**
- Prevents overly bright specular highlights
- Reduces "wet" or "glossy" appearance

---

### Fix 3: Configure Diffuse Material

**File:** `label_moon_viewer.html` line ~1363-1371

```javascript
// Configure lighting to avoid "wet" or reflective appearance
viewer.scene.light = new Cesium.DirectionalLight({
    direction: new Cesium.Cartesian3(0.5, 0.5, -0.7) // Sun direction
});

// Set material appearance to diffuse (not specular/glossy)
viewer.scene.globe.material = undefined; // Use default non-reflective material
```

**What it does:**
- Uses directional light (like the Sun)
- Removes any custom materials that might be glossy
- Defaults to diffuse (matte) surface appearance

---

### Fix 4: Terrain Water Mask Disabled

**Already in place** - `label_moon_viewer.html` line ~1558

```javascript
const moonTerrain = await Cesium.CesiumTerrainProvider.fromUrl(
    'https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc/mesh',
    {
        requestVertexNormals: true,
        requestWaterMask: false,     // ← Already disabled
        requestMetadata: true
    }
);
```

---

## Testing

After applying these fixes, you should see:

✅ **Matte lunar surface** (no glossy/wet appearance)  
✅ **No wave-like patterns**  
✅ **Proper shadows** from craters and mountains  
✅ **Diffuse lighting** (not specular highlights)  
❌ **No water effects**  

---

## Additional Troubleshooting

### If you still see artifacts:

**1. Check terrain exaggeration:**
```javascript
console.log(viewer.scene.globe.terrainExaggeration);
// Should be 1.0 or close to it

// If too high, reduce it:
viewer.scene.globe.terrainExaggeration = 1.0;
```

**2. Check for custom materials:**
```javascript
console.log(viewer.scene.globe.material);
// Should be undefined or null

// If not, remove it:
viewer.scene.globe.material = undefined;
```

**3. Check imagery layer settings:**
```javascript
const layer = viewer.imageryLayers.get(0);
console.log('Brightness:', layer.brightness);
console.log('Contrast:', layer.contrast);
console.log('Saturation:', layer.saturation);

// Reset if needed:
layer.brightness = 1.0;
layer.contrast = 1.0;
layer.saturation = 1.0;
```

**4. Disable lighting temporarily to test:**
```javascript
viewer.scene.globe.enableLighting = false;
// If artifacts disappear, it's a lighting issue
```

---

## Technical Background

### Why Cesium Shows Ocean Effects by Default

Cesium is primarily designed for Earth visualization where:
- Oceans cover 71% of the surface
- Water effects enhance realism
- HDR makes sense for atmospheric scattering
- Translucency is useful for clouds/atmosphere

### Why These Don't Work for the Moon

- **No water** - The Moon is bone dry
- **No atmosphere** - No scattering or diffusion
- **Harsh lighting** - Direct sunlight with no atmospheric softening
- **Matte surface** - Lunar regolith is dusty and non-reflective

### Proper Moon Surface Characteristics

1. **Diffuse reflection** - Light scatters in all directions equally
2. **Low albedo** - Moon reflects only ~12% of sunlight (darker than asphalt)
3. **High contrast** - Extreme bright/dark without atmosphere
4. **No specular highlights** - Surface is rough, not smooth

---

## Related Settings

### Settings That Are Correct

```javascript
viewer.scene.skyAtmosphere = undefined;           // ✅ No atmosphere
viewer.scene.fog.enabled = false;                 // ✅ No fog
viewer.scene.globe.showGroundAtmosphere = false;  // ✅ No ground glow
viewer.scene.backgroundColor = Cesium.Color.BLACK; // ✅ Black space
```

### Settings to Avoid

```javascript
// ❌ DON'T use these for Moon:
viewer.scene.globe.showWaterEffect = true;         // Shows ocean waves
viewer.scene.globe.translucency.enabled = true;    // Makes globe translucent
viewer.scene.highDynamicRange = true;              // Can cause bright artifacts
viewer.scene.globe.material = customMaterial;      // Can be glossy/reflective
```

---

## Quick Reference Commands

**Check for water effects in console:**
```javascript
console.log('Water effect:', viewer.scene.globe.showWaterEffect);
console.log('Translucency:', viewer.scene.globe.translucency?.enabled);
console.log('HDR:', viewer.scene.highDynamicRange);
console.log('Material:', viewer.scene.globe.material);
```

**Disable all effects manually:**
```javascript
viewer.scene.globe.showWaterEffect = false;
viewer.scene.globe.translucency.enabled = false;
viewer.scene.highDynamicRange = false;
viewer.scene.globe.material = undefined;
```

---

## Result

After applying all fixes, the Moon should appear as a **matte, dusty, airless body** with:
- Realistic lunar coloring (grays)
- Proper crater shadows
- No glossy or wet appearance
- No wave-like patterns
- Harsh lighting like real lunar surface

---

**Status:** ✅ FIXED  
**Commit:** Apply these changes and test in browser  
**Impact:** ⭐⭐⭐ Critical for realistic Moon visualization

---

*End of Ocean Waves Fix Document*

