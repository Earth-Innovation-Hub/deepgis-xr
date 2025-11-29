# Testing Guide: Vector Layer Support for Cesium Viewer

## Summary of Changes

### ✅ Implemented Features

1. **Vector Layer Support**
   - Full infrastructure for loading Mapbox Vector Tiles (MVT/PBF)
   - Integration with TileServer GL at https://mbtiles.deepgis.org/
   - Cesium entity-based rendering system
   - Configurable styling per layer

2. **User Interface**
   - "Vector Layers" section in sidebar (purple-bordered)
   - Checkboxes for each available vector layer
   - Opacity sliders for fine-grained control
   - "Base Raster Layer" dropdown (updated)
   - "Raster Overlays" section with checkboxes

3. **No Auto-Load Behavior**
   - **Page loads with NO layers active**
   - User must manually select layers
   - Cleaner initial state
   - Better performance on initial load

### 🔧 Modified Files

1. `/staticfiles/web/js/utils/vector-tiles.js` - NEW
2. `/staticfiles/web/js/config.js` - Updated
3. `/staticfiles/web/js/core/layer-management.js` - Updated
4. `/staticfiles/web/js/state.js` - Updated
5. `/templates/web/label_topology.html` - Updated

## How to Test

### Prerequisites

1. Access to the application: `https://your-domain/label_topology/`
2. Browser with DevTools (Chrome/Firefox recommended)
3. TileServer GL running at https://mbtiles.deepgis.org/

### Test 1: Initial Page Load

**Expected Behavior:**
- ✅ Page loads successfully
- ✅ No layers are loaded/visible
- ✅ Cesium globe is visible with default terrain
- ✅ Status indicator shows: "Ready - X layers available"
- ✅ Layer dropdowns and checkboxes are populated but unchecked

**Steps:**
1. Navigate to label_topology page
2. Wait for page to fully load
3. Observe Cesium viewer (should show plain globe)
4. Check sidebar - all controls should be present but inactive

### Test 2: Load Raster Layer

**Expected Behavior:**
- ✅ Layer appears on map in 2D mode
- ✅ Camera zooms to layer bounds/center
- ✅ Status indicator updates
- ✅ Tiles load progressively

**Steps:**
1. Open the "Base Raster Layer" dropdown
2. Select any raster layer (e.g., "BF_10-03-2020_raster")
3. Wait for loading (watch status indicator)
4. Verify layer appears
5. Check console for loading messages

**Console Output:**
```
Loading BF_10-03-2020_raster...
Switched to 2D mode for raster layer
Using tile URL: https://mbtiles.deepgis.org/data/...
Loaded: BF_10-03-2020_raster (2D mode, zoom: 18)
```

### Test 3: Load Vector Layer

**Expected Behavior:**
- ✅ Colored rectangles appear (tile boundaries)
- ✅ Each tile is semi-transparent with layer-specific color
- ✅ Status indicator shows "Loaded vector layer: ..."
- ✅ Opacity slider appears when checked

**Steps:**
1. Scroll to "Vector Layers" section (purple border)
2. Check the box next to "BF_08-02-2020" (or any vector layer)
3. Wait for loading
4. Observe colored rectangles appearing on map
5. Hover over rectangles to see tile info
6. Adjust opacity slider

**Console Output:**
```
Loading vector layer: BF_08-02-2020 (bf_aug_2020)
Initialized vector layer renderer
Loading 16 visible vector tiles for layer bf_aug_2020
Vector tile received, size: 12345 bytes
Loaded 16 vector tiles for layer bf_aug_2020
```

### Test 4: Multiple Vector Layers

**Expected Behavior:**
- ✅ Multiple layers stack properly
- ✅ Different colors for different layers
- ✅ Independent opacity controls
- ✅ Performance remains acceptable

**Steps:**
1. Enable first vector layer (e.g., "BF_08-02-2020" - Orange)
2. Enable second vector layer (e.g., "BF_10-03-2020" - Green)
3. Enable third vector layer (e.g., "BF_12-20-2020_vector" - Purple)
4. Adjust opacity sliders for each
5. Verify colors match configuration

**Color Mapping:**
- bf_aug_2020: Orange
- bf_oct_2020: Green
- bf_dec_2020_vector: Purple
- bf_feb_2021_3d: Yellow

### Test 5: Vector + Raster Combination

**Expected Behavior:**
- ✅ Raster layer shows underneath
- ✅ Vector rectangles overlay on top
- ✅ Both layers visible simultaneously
- ✅ Independent opacity controls work

**Steps:**
1. Select a raster base layer first
2. Enable one or more vector layers
3. Adjust raster layer opacity (if using overlay)
4. Adjust vector layer opacity
5. Verify layering is correct

### Test 6: Layer Removal

**Expected Behavior:**
- ✅ Vector layer disappears when unchecked
- ✅ Opacity slider hides
- ✅ Status indicator updates
- ✅ No console errors

**Steps:**
1. Enable a vector layer
2. Uncheck the box
3. Verify layer is removed
4. Check console for cleanup messages

**Console Output:**
```
Removed vector layer: BF_08-02-2020
```

### Test 7: View Mode Switching

**Expected Behavior:**
- ✅ Vector layers persist across view modes
- ✅ Rectangles adjust to new perspective
- ✅ Performance remains good

**Steps:**
1. Load vector layers in 2D mode
2. Switch to "3D Globe View"
3. Verify layers still visible
4. Switch to "Columbus View"
5. Return to 2D

### Test 8: Zoom Level Behavior

**Expected Behavior:**
- ✅ Tile count changes with zoom
- ✅ Maximum 16 tiles visible (4x4 grid)
- ✅ Proper tile coordinate calculation

**Steps:**
1. Enable a vector layer at world view
2. Count visible rectangles (should be ~4-16)
3. Zoom in to a region
4. Count rectangles again (should adapt but not exceed 16)
5. Check console for "Loading X visible vector tiles"

### Test 9: Raster Overlay Layers

**Expected Behavior:**
- ✅ Overlay checkboxes work independently
- ✅ Multiple overlays can be active
- ✅ Opacity controls appear when checked

**Steps:**
1. Select a base raster layer
2. Enable raster overlays (separate from vector)
3. Adjust overlay opacity
4. Verify overlays stack correctly

### Test 10: Error Handling

**Expected Behavior:**
- ✅ Graceful handling of missing tiles
- ✅ Console warnings but no crashes
- ✅ Status indicator shows errors

**Steps:**
1. Try loading layers at extreme zoom levels
2. Disable network temporarily (DevTools)
3. Try loading a layer
4. Re-enable network
5. Verify app recovers

## Performance Benchmarks

### Expected Performance:
- **Initial Load:** < 2 seconds (no layers)
- **Raster Layer Load:** 2-5 seconds
- **Vector Layer Load:** 1-3 seconds (16 tiles)
- **Frame Rate:** 30-60 FPS with 1-2 layers
- **Memory Usage:** < 500 MB with 3-4 layers active

### Check Performance:
```javascript
// In browser console
console.log('Frame rate:', viewer.scene.frameRateMonitor.lastFramesPerSecond);
console.log('Entities:', viewer.entities.values.length);
console.log('Imagery layers:', viewer.imageryLayers.length);
console.log('Active tiles:', AppState.vectorRenderer?.activeTiles.size);
```

## Known Limitations

### Current Implementation:
1. **Placeholder Visualization**: Shows tile boundaries, not actual features
2. **No Feature Interaction**: Can't click features for properties
3. **Limited Zoom**: Vector tiles capped at zoom 14
4. **Tile Limit**: Maximum 16 tiles visible at once

### Why Placeholders?
The current implementation demonstrates:
- ✅ Successful tile fetching from tileserver
- ✅ Correct tile coordinate calculation
- ✅ Proper Cesium integration
- ✅ Layer management and UI

**To render actual features:** Add MVT parsing library (see VECTOR_LAYER_IMPLEMENTATION.md)

## Troubleshooting

### Issue: Vector Layers Section Missing
- **Check:** Browser console for JavaScript errors
- **Solution:** Clear browser cache, hard reload (Ctrl+Shift+R)

### Issue: No Layers in Dropdowns
- **Check:** Tileserver accessibility: `curl https://mbtiles.deepgis.org/data.json`
- **Check:** Console for "Error loading available layers"
- **Solution:** Verify tileserver is running and accessible

### Issue: Vector Rectangles Not Appearing
- **Check:** Console for "Loading vector layer" message
- **Check:** Zoom level (may need to zoom in more)
- **Check:** View mode (try 2D mode)
- **Solution:** Enable a base raster first to see coordinates

### Issue: Performance Degradation
- **Check:** How many layers are active
- **Solution:** Disable some layers, reduce zoom level
- **Config:** Adjust `MAX_TILES_PER_DIMENSION` in config.js

### Issue: CORS Errors
- **Check:** Browser console for CORS messages
- **Check:** Tileserver CORS configuration
- **Solution:** Contact admin to add CORS headers

## Verification Checklist

Before marking implementation as complete:

- [ ] Page loads without errors
- [ ] No auto-load (user selects manually)
- [ ] Base raster dropdown populated
- [ ] Raster overlay checkboxes populated
- [ ] Vector layer checkboxes populated
- [ ] Raster layer loads and displays
- [ ] Vector layer loads (rectangles visible)
- [ ] Opacity sliders functional
- [ ] Multiple layers can be active
- [ ] Layer removal works
- [ ] View mode switching works
- [ ] No JavaScript errors in console
- [ ] Performance acceptable (>30 FPS)
- [ ] Status indicator updates correctly

## Success Metrics

✅ **Implementation Complete** when:
1. All verification checklist items pass
2. User can manually select and load layers
3. Vector layer tiles are fetched and visualized
4. Performance remains acceptable
5. No critical console errors

## Next Steps for Production

1. **Add MVT Parsing** (see VECTOR_LAYER_IMPLEMENTATION.md)
   ```bash
   npm install @mapbox/vector-tile pbf
   ```

2. **Render Actual Features**
   - Polygons, lines, points
   - Property-based styling
   - Click interaction

3. **Optimize Performance**
   - Tile caching strategies
   - Feature clustering
   - LOD (Level of Detail) management

4. **User Enhancements**
   - Layer info panels
   - Legend generation
   - Search/filter features

## Questions?

See detailed documentation:
- **VECTOR_LAYER_IMPLEMENTATION.md** - Architecture and API reference
- **config.js** - Configuration options
- **vector-tiles.js** - Implementation details

Console debugging:
```javascript
// Check state
console.log(AppState.currentLayers);
console.log(AppState.vectorRenderer);
console.log(CONFIG.VECTOR_TILES);
```

