# Raster Layer Timeout Analysis

## Problem Summary

Raster layers are timing out during tile loading, and in some cases causing browser crashes (SIGILL error). The console shows successful initialization but tiles fail to load or the browser crashes.

## Root Causes Identified

### 1. **Missing Tile Request Timeout Configuration**
**Location**: `staticfiles/web/js/utils/layers.js` - `createImageryProvider()`

**Issue**: 
- Cesium's `UrlTemplateImageryProvider` doesn't have explicit timeout configuration
- Cesium uses `Resource` class for HTTP requests, which has a default timeout (typically 60 seconds)
- No custom timeout is set for tile requests
- Slow tile servers or network issues can cause indefinite hangs

**Impact**: 
- Tiles may hang indefinitely waiting for server response
- Browser may crash if too many pending requests accumulate
- No user feedback when tiles fail to load

### 2. **Metadata Fetch Timeout Too Short**
**Location**: `staticfiles/web/js/core/layer-management.js` - `fetchLayerMetadata()`

**Issue**:
- Current timeout: 5 seconds (`CONFIG.TIMEOUTS.METADATA_FETCH`)
- May be insufficient for slow servers or high latency connections

**Impact**:
- Metadata fetch may timeout before server responds
- Layer loading fails before tiles are even requested

### 3. **No Retry Mechanism for Failed Tiles**
**Location**: `staticfiles/web/js/utils/layers.js` - `createImageryProvider()`

**Issue**:
- Failed tile requests are not retried
- Temporary network issues cause permanent tile failures
- Only error handler is registered, but no retry logic

**Impact**:
- Single network hiccup causes permanent tile gaps
- Poor user experience with incomplete tile coverage

### 4. **No Request Rate Limiting**
**Location**: `staticfiles/web/js/core/layer-management.js` - `loadBaseRasterLayer()`

**Issue**:
- All tiles requested simultaneously when layer loads
- No throttling or rate limiting
- Can overwhelm server or browser

**Impact**:
- Server may reject or slow down requests
- Browser memory exhaustion
- Browser crash (SIGILL) from too many concurrent requests

### 5. **Missing Error Recovery**
**Location**: `staticfiles/web/js/core/layer-management.js` - `loadBaseRasterLayer()`

**Issue**:
- No fallback mechanism if primary tile URL fails
- No alternative tile sources configured
- Error handler exists but doesn't recover

**Impact**:
- Single point of failure
- No graceful degradation

## Recommended Fixes

### Fix 1: Add Explicit Timeout to Tile Requests
Configure Cesium Resource timeout for tile requests:

```javascript
// In layers.js - createImageryProvider()
const provider = new Cesium.UrlTemplateImageryProvider({
  url: tileUrl,
  maximumLevel: safeMaxZoom,
  minimumLevel: layerInfo.minzoom || 0,
  credit: new Cesium.Credit('DeepGIS TileServer'),
  enablePick: false,
  tileWidth: CONFIG.TILE_DIMENSIONS.width,
  tileHeight: CONFIG.TILE_DIMENSIONS.height,
  tilingScheme: new Cesium.WebMercatorTilingScheme(),
  // Add timeout configuration
  requestTimeout: CONFIG.TIMEOUTS.TILE_REQUEST || 30000, // 30 seconds default
  ...options
});
```

### Fix 2: Increase Metadata Fetch Timeout
Update config to allow more time for metadata:

```javascript
// In config.js
TIMEOUTS: {
  METADATA_FETCH: 10000, // Increase from 5000 to 10000 (10 seconds)
  TILE_REQUEST: 30000,   // New: 30 seconds for tile requests
  AUTO_LOAD_DELAY: 500,
  AUTO_LOAD_RETRY_INTERVAL: 100,
  AUTO_LOAD_MAX_RETRIES: 50
}
```

### Fix 3: Add Retry Logic for Failed Tiles
Implement retry mechanism with exponential backoff:

```javascript
// In layers.js - createImageryProvider()
// Wrap provider with retry logic
const originalRequestImage = provider.requestImage.bind(provider);
let retryCounts = new Map();

provider.requestImage = function(x, y, level, request) {
  const key = `${level}/${x}/${y}`;
  const retryCount = retryCounts.get(key) || 0;
  
  return originalRequestImage(x, y, level, request)
    .catch(error => {
      if (retryCount < 3) {
        retryCounts.set(key, retryCount + 1);
        const delay = Math.pow(2, retryCount) * 1000; // Exponential backoff
        return new Promise(resolve => {
          setTimeout(() => {
            resolve(originalRequestImage(x, y, level, request));
          }, delay);
        });
      }
      throw error;
    });
};
```

### Fix 4: Add Request Rate Limiting
Limit concurrent tile requests:

```javascript
// In config.js
MEMORY: {
  // ... existing config
  TILE_LOADING: {
    MAX_CONCURRENT_REQUESTS: 10,  // Limit concurrent tile requests
    REQUEST_DELAY: 50              // Delay between request batches (ms)
  }
}
```

### Fix 5: Improve Error Handling and Recovery
Add better error messages and fallback mechanisms:

```javascript
// In layer-management.js - loadBaseRasterLayer()
const providerOptions = {
  onError: (error) => {
    console.warn(`Tile loading error for ${layerInfo.name}:`, error);
    
    // Track error rate
    if (!window.tileErrorCount) window.tileErrorCount = 0;
    window.tileErrorCount++;
    
    // Warn user if error rate is high
    if (window.tileErrorCount > 10 && window.tileErrorCount % 10 === 0) {
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator(`Warning: ${window.tileErrorCount} tiles failed to load`);
      }
    }
  }
};
```

## Implementation Priority

1. **High Priority**: Fix 1 (Add timeout) + Fix 2 (Increase metadata timeout)
2. **Medium Priority**: Fix 3 (Retry logic)
3. **Low Priority**: Fix 4 (Rate limiting) + Fix 5 (Better error handling)

## Testing Recommendations

1. Test with slow network connection (throttle to 3G)
2. Test with server that has high latency
3. Test with server that occasionally returns errors
4. Monitor browser memory usage during tile loading
5. Test with layers that have very high maxzoom (23+)

## Additional Considerations

- **Browser Memory**: High zoom layers can cause memory exhaustion. Current memory caps (13 for zoom 23+) help but may need further reduction.
- **Server Performance**: Tile server may need optimization if it's timing out frequently.
- **Network Configuration**: Check nginx/proxy timeouts match or exceed client timeouts.

