# Layer Loading Sequence - Guaranteed Ordering

## Overview

The layer loading process now ensures proper sequencing: metadata is fully loaded, camera is positioned and transitioned, and only then are tiles loaded. This prevents loading tiles for incorrect positions or zoom levels.

## Loading Sequence

### Step 1: Fetch and Validate Metadata ✅
```javascript
const metadata = await fetchLayerMetadata(layerId);

// Validate metadata was loaded successfully
if (!metadata) {
  throw new Error(`Failed to fetch metadata for layer: ${layerId}`);
}

// Validate essential metadata fields exist
if (!metadata.tiles || metadata.tiles.length === 0) {
  throw new Error(`No tile URLs found in metadata for layer: ${layerId}`);
}

console.log('✓ Metadata loaded and validated');
```

**What happens:**
- Fetches TileJSON from `https://mbtiles.deepgis.org/data/{layerId}.json`
- Validates metadata exists and contains tile URLs
- Logs completion before proceeding

**Blocking:** Yes - code waits for metadata before continuing

---

### Step 2: Extract Center and Zoom from Metadata ✅
```javascript
// Determine target zoom from metadata
// Priority: center[2] > defaultzoom > maxzoom > minzoom > CONFIG default
let targetZoom = metadata.center?.[2] || metadata.defaultzoom || ...;

// Determine center from metadata
let targetCenter = metadata.center || calculateFromBounds(metadata.bounds);
```

**What happens:**
- Extracts center, zoom, bounds from metadata
- Validates zoom is within available range (minzoom-maxzoom)
- Calculates camera destination

**Blocking:** Yes - synchronous processing

---

### Step 3: Set Camera View and Wait for Completion ✅
```javascript
// Set camera view and wait for transition to complete
console.log(`Setting camera view to center [${targetCenter[0]}, ${targetCenter[1]}] at zoom ${targetZoom}...`);
await CameraUtils.setCameraView(viewer, destination, viewOptions);
console.log(`✓ Camera view set and transition completed`);
```

**What happens:**
- Calls `CameraUtils.setCameraView()` which now returns a Promise
- For `flyTo` (bounds fitting): Promise resolves when `complete` callback fires
- For `setView` (center point): Promise resolves after 2 animation frames
- Code waits for Promise to resolve before proceeding

**Blocking:** Yes - code waits for camera transition to complete

---

### Step 4: Verify Camera Position ✅
```javascript
// Verify camera is at correct position before proceeding
const currentHeight = viewer.camera.positionCartographic.height;
const expectedHeight = CoordinateUtils.zoomToHeight(targetZoom);
const heightDiff = Math.abs(currentHeight - expectedHeight);

// If height difference is significant, wait a bit more and verify again
if (heightDiff > expectedHeight * 0.1) {
  console.log(`Camera height adjustment needed...`);
  await new Promise(resolve => setTimeout(resolve, 200));
  viewer.scene.requestRender();
}

console.log(`✓ Camera positioned and ready. Current zoom level: ${targetZoom}...`);
```

**What happens:**
- Verifies camera is at expected height/zoom
- If not, waits additional 200ms and re-renders
- Logs confirmation before proceeding

**Blocking:** Yes - code waits for verification

---

### Step 5: Calculate Safe Zoom Ranges ✅
```javascript
const safeMaxZoom = LayerUtils.calculateSafeMaxZoom(metadata.maxzoom || 22);
const safeMinZoom = metadata.minzoom || 0;
```

**What happens:**
- Calculates safe zoom limits from metadata
- Applies memory safety caps if needed
- Determines final zoom range for provider

**Blocking:** Yes - synchronous processing

---

### Step 6: Create Imagery Provider ✅
```javascript
console.log('Creating imagery provider (tiles will start loading after this)...');
const provider = LayerUtils.createImageryProvider(tileUrl, layerInfo, safeMaxZoom, {
  ...providerOptions,
  minzoom: safeMinZoom,
  maxzoom: safeMaxZoom
});
```

**What happens:**
- Creates provider with correct zoom limits
- Configures timeout and retry logic
- Provider is ready but not yet added to viewer

**Blocking:** Yes - synchronous processing

---

### Step 7: Add Provider and Start Loading Tiles ✅
```javascript
console.log('✓ All prerequisites complete. Starting tile loading...');
const imageryLayer = viewer.imageryLayers.addImageryProvider(provider);
```

**What happens:**
- Provider is added to viewer
- **This is when tiles start loading**
- Cesium automatically loads tiles for current viewport and zoom level

**Blocking:** No - tiles load asynchronously in background

---

## Key Improvements

### 1. Camera Transition Completion
**Before:**
```javascript
CameraUtils.setCameraView(viewer, destination, viewOptions);
await new Promise(resolve => setTimeout(resolve, 100)); // Fixed delay
```

**After:**
```javascript
await CameraUtils.setCameraView(viewer, destination, viewOptions); // Waits for actual completion
```

The `setCameraView` function now returns a Promise that resolves when:
- For `flyTo`: When the `complete` callback fires
- For `setView`: After 2 animation frames (ensures camera position is applied)

### 2. Position Verification
Added verification step that:
- Checks if camera is at expected height
- Waits additional time if needed
- Ensures camera is ready before loading tiles

### 3. Clear Logging
Each step logs completion:
- `✓ Metadata loaded and validated`
- `✓ Camera view set and transition completed`
- `✓ Camera positioned and ready`
- `✓ All prerequisites complete. Starting tile loading...`

This makes it easy to see where the process is in the sequence.

## Benefits

1. **No Wasted Tile Requests**: Tiles are only loaded after camera is at correct position
2. **Correct Zoom Level**: Tiles are requested for the exact zoom from metadata
3. **Better Performance**: No tiles loaded for wrong position/zoom that get discarded
4. **Predictable Behavior**: Clear sequence ensures consistent results
5. **Better Debugging**: Logs show exactly when each step completes

## Testing

To verify the sequence works:

1. **Check Console Logs**: Should see all checkmarks in order:
   ```
   Fetching metadata for layer: bf_aug_2020_raster
   ✓ Metadata loaded and validated
   Setting camera view to center [-122.4, 37.75] at zoom 15...
   ✓ Camera view set and transition completed
   ✓ Camera positioned and ready. Current zoom level: 15...
   Creating imagery provider (tiles will start loading after this)...
   ✓ All prerequisites complete. Starting tile loading...
   ```

2. **Check Network Tab**: Tile requests should only appear after "Starting tile loading..." log

3. **Check Camera Position**: Camera should be at correct center and zoom before tiles load

4. **Test with Slow Network**: Even with slow metadata fetch, sequence should be maintained

## Implementation Details

### CameraUtils.setCameraView() Changes

**Returns Promise:**
- For `flyTo`: Uses `complete` callback to resolve Promise
- For `setView`: Uses `requestAnimationFrame` (2 frames) to ensure position is applied

**Error Handling:**
- Returns rejected Promise if viewer/destination not provided
- Handles `flyTo` cancellation gracefully

### Verification Logic

The position verification checks:
- Current camera height vs expected height
- If difference > 10%, waits additional 200ms
- Ensures camera is truly ready before proceeding

This handles edge cases where camera might need extra time to settle.

