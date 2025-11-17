/**
 * Layer Management Utilities
 */
import { CONFIG } from '../config.js';
import { AppState } from '../state.js';
import { addProgressiveZoomLayers, createLayeredChunkedProvider } from './chunked-loading.js';

export const LayerUtils = {
  /**
   * Calculate safe max zoom based on layer's maxzoom
   */
  calculateSafeMaxZoom: (maxzoom) => {
    const caps = CONFIG.MEMORY.MAX_ZOOM_CAPS;
    let maxZoomCap = caps.DEFAULT;
    
    // More aggressive capping for very high zoom layers
    if (maxzoom >= 23) {
      maxZoomCap = caps.VERY_HIGH;  // Now 13 instead of 16
    } else if (maxzoom >= 20) {
      maxZoomCap = caps.HIGH;  // Now 16 instead of 17
    }
    
    const safeMaxZoom = Math.min(maxzoom || 22, maxZoomCap);
    if (maxzoom && maxzoom > maxZoomCap) {
      console.warn(`Capping max zoom from ${maxzoom} to ${safeMaxZoom} for memory safety`);
      // Additional warning for very high zoom layers
      if (maxzoom >= 23) {
        console.warn(`⚠️ Layer has very high native zoom (${maxzoom}). Consider using a lower-zoom variant if available.`);
      }
    }
    return safeMaxZoom;
  },
  
  /**
   * Update layerInfo with metadata (merge, don't replace)
   */
  mergeMetadata: (layerInfo, metadata) => {
    if (!metadata) return layerInfo;
    
    const fields = ['bounds', 'center', 'minzoom', 'maxzoom', 'defaultzoom', 'name'];
    fields.forEach(field => {
      if (metadata[field] !== undefined) {
        layerInfo[field] = metadata[field];
      }
    });
    return layerInfo;
  },
  
  /**
   * Get tile URL from metadata or construct default
   * Handles TileServer GL format URLs properly
   */
  getTileUrl: (layerId, metadata) => {
    if (metadata && metadata.tiles && metadata.tiles.length > 0) {
      // First, filter out malformed URLs (e.g., double protocols like "https://http://...")
      const validUrls = metadata.tiles.filter(url => {
        try {
          // Test URL validity by replacing template variables with dummy values
          const testUrl = url.replace('{z}', '0').replace('{x}', '0').replace('{y}', '0');
          new URL(testUrl);
          return true;
        } catch {
          console.warn(`[LayerUtils] Skipping malformed tile URL: ${url}`);
          return false;
        }
      });
      
      if (validUrls.length === 0) {
        console.error(`[LayerUtils] No valid tile URLs found in metadata for layer: ${layerId}`);
        return `${CONFIG.SERVERS.MBTILES_SERVER}/data/${layerId}/{z}/{x}/{y}.png`;
      }
      
      // Prefer HTTPS URLs from mbtiles.deepgis.org (TileServer GL format)
      let tileUrl = validUrls.find(url => url.startsWith('https://mbtiles.deepgis.org')) 
        || validUrls.find(url => url.startsWith('https://'))
        || validUrls[0];
      
      // Ensure URL uses proper TileServer GL format: /data/{layerId}/{z}/{x}/{y}.{ext}
      // TileServer GL typically provides URLs like: https://mbtiles.deepgis.org/data/{layerId}/{z}/{x}/{y}.png
      if (tileUrl && !tileUrl.includes('{z}')) {
        // If URL doesn't have template variables, it might be a base URL
        // Construct proper template URL
        const ext = metadata.format === 'pbf' ? 'pbf' : 'png';
        tileUrl = `${CONFIG.SERVERS.MBTILES_SERVER}/data/${layerId}/{z}/{x}/{y}.${ext}`;
      }
      
      // Normalize URL to ensure it uses TileServer GL format
      if (tileUrl && !tileUrl.includes(CONFIG.SERVERS.MBTILES_SERVER)) {
        // Replace any other server references with our configured server
        tileUrl = tileUrl.replace(/https?:\/\/[^\/]+/, CONFIG.SERVERS.MBTILES_SERVER);
      }
      
      return tileUrl;
    }
    // Fallback: construct URL manually using TileServer GL format
    return `${CONFIG.SERVERS.MBTILES_SERVER}/data/${layerId}/{z}/{x}/{y}.png`;
  },
  
  /**
   * Create Cesium imagery provider with standard configuration
   * Supports chunked loading if enabled in config
   * Includes timeout and retry logic for tile requests
   * Uses metadata minzoom/maxzoom to ensure only available tiles are requested
   */
  createImageryProvider: (tileUrl, layerInfo, safeMaxZoom, options = {}) => {
    // Use chunked loading if enabled and zoom is high enough
    if (CONFIG.MEMORY.CHUNKED_LOADING.ENABLED && safeMaxZoom > CONFIG.MEMORY.CHUNKED_LOADING.INITIAL_MAX_ZOOM) {
      return createLayeredChunkedProvider(tileUrl, layerInfo, safeMaxZoom, options);
    }
    
    const tileTimeout = CONFIG.TIMEOUTS.TILE_REQUEST || 30000;
    
    // Use minzoom/maxzoom from options if provided (from metadata), otherwise from layerInfo
    const minzoom = options.minzoom !== undefined ? options.minzoom : (layerInfo.minzoom || 0);
    const maxzoom = options.maxzoom !== undefined ? options.maxzoom : safeMaxZoom;
    
    // Ensure minzoom <= maxzoom
    const finalMinZoom = Math.min(minzoom, maxzoom);
    const finalMaxZoom = Math.max(minzoom, maxzoom);
    
    // Calculate estimated memory impact
    const zoomRange = finalMaxZoom - finalMinZoom;
    const estimatedTilesAtMaxZoom = Math.pow(4, zoomRange);
    const bytesPerTile = CONFIG.TILE_DIMENSIONS.width * CONFIG.TILE_DIMENSIONS.height * 4; // RGBA
    const estimatedMemoryMB = (estimatedTilesAtMaxZoom * bytesPerTile / 1048576).toFixed(1);
    
    console.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
    console.log(`[RASTER LAYER] Creating imagery provider`);
    console.log(`  URL template: ${tileUrl}`);
    console.log(`  Zoom range: ${finalMinZoom} to ${finalMaxZoom} (${zoomRange} levels)`);
    console.log(`  Tile size: ${CONFIG.TILE_DIMENSIONS.width}x${CONFIG.TILE_DIMENSIONS.height}px`);
    console.log(`  Estimated tiles per zoom: ~${estimatedTilesAtMaxZoom} at max zoom`);
    console.log(`  Est. memory at max zoom: ~${estimatedMemoryMB}MB`);
    
    // Warning for potentially excessive configurations
    if (finalMaxZoom > 18) {
      console.warn(`  ⚠️  WARNING: Max zoom ${finalMaxZoom} is very high! May cause memory issues.`);
      console.warn(`  💡 Recommendation: Cap at zoom 16-18 for better performance`);
    }
    if (estimatedTilesAtMaxZoom > 1000) {
      console.warn(`  ⚠️  WARNING: ~${estimatedTilesAtMaxZoom} tiles possible! High memory usage expected.`);
      console.warn(`  💡 Recommendation: Reduce zoom range or increase minzoom`);
    }
    if (parseFloat(estimatedMemoryMB) > 200) {
      console.warn(`  ⚠️  WARNING: Est. ${estimatedMemoryMB}MB memory! May cause browser crash.`);
      console.warn(`  💡 Recommendation: Reduce maxzoom or tile dimensions`);
    }
    
    console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`);
    
    // Standard provider
    // IMPORTANT: TileServer GL serves tiles in XYZ format (origin top-left, Y increases down)
    // Cesium's WebMercatorTilingScheme is compatible with XYZ format
    // Both use Web Mercator projection (EPSG:3857)
    // Zoom levels are the same in both Leaflet and Cesium (0-22+)
    const provider = new Cesium.UrlTemplateImageryProvider({
      url: tileUrl,  // Format: {z}/{x}/{y}.png (XYZ format)
      maximumLevel: finalMaxZoom,  // Only load tiles up to this zoom level
      minimumLevel: finalMinZoom,  // Only load tiles from this zoom level
      credit: new Cesium.Credit('DeepGIS TileServer'),
      enablePick: false,
      tileWidth: CONFIG.TILE_DIMENSIONS.width,
      tileHeight: CONFIG.TILE_DIMENSIONS.height,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),  // Standard Web Mercator (compatible with XYZ)
      // Remove minzoom/maxzoom from options to avoid conflicts
      ...Object.fromEntries(Object.entries(options).filter(([key]) => key !== 'minzoom' && key !== 'maxzoom'))
    });
    
    // Store the original requestImage method (before any wrapping)
    const originalRequestImage = provider.requestImage.bind(provider);
    
    // Tile tracking for comprehensive debugging
    const tileStats = {
      total: 0,
      requested: 0,
      succeeded: 0,
      failed: 0,
      cached: 0,
      byZoom: {},
      startTime: performance.now(),
      requestTimes: [],
      errors: []
    };
    
    // Track tiles in flight
    const tilesInFlight = new Map();
    
    // First, wrap with comprehensive debug logging
    provider.requestImage = function(x, y, level, request) {
      tileStats.requested++;
      tileStats.total++;
      
      // Track by zoom level
      if (!tileStats.byZoom[level]) {
        tileStats.byZoom[level] = { requested: 0, succeeded: 0, failed: 0 };
      }
      tileStats.byZoom[level].requested++;
      
      const tileKey = `${level}/${x}/${y}`;
      const requestStartTime = performance.now();
      tilesInFlight.set(tileKey, { startTime: requestStartTime, level, x, y });
      
      // Calculate expected geographic bounds for this tile
      const n = Math.pow(2, level);
      const lon_deg_min = x / n * 360.0 - 180.0;
      const lon_deg_max = (x + 1) / n * 360.0 - 180.0;
      
      // Calculate center GPS coordinates
      const lon_center = (lon_deg_min + lon_deg_max) / 2;
      
      // Calculate latitude bounds (Web Mercator)
      const lat_rad_max = Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n)));
      const lat_rad_min = Math.atan(Math.sinh(Math.PI * (1 - 2 * (y + 1) / n)));
      const lat_deg_max = lat_rad_max * 180 / Math.PI;
      const lat_deg_min = lat_rad_min * 180 / Math.PI;
      const lat_center = (lat_deg_min + lat_deg_max) / 2;
      
      const url = tileUrl.replace('{z}', level).replace('{x}', x).replace('{y}', y);
      
      // Log all tile requests with detailed info
      console.log(`\n[TILE REQUEST] ${tileKey}`);
      console.log(`  URL: ${url}`);
      console.log(`  GPS Center: ${lat_center.toFixed(6)}°, ${lon_center.toFixed(6)}°`);
      console.log(`  Bounds: W=${lon_deg_min.toFixed(4)}°, S=${lat_deg_min.toFixed(4)}°, E=${lon_deg_max.toFixed(4)}°, N=${lat_deg_max.toFixed(4)}°`);
      console.log(`  Total requested: ${tileStats.requested} | In flight: ${tilesInFlight.size}`);
      console.log(`  Success: ${tileStats.succeeded} | Failed: ${tileStats.failed}`);
      
      // Get memory info if available
      if (performance.memory) {
        const memMB = (performance.memory.usedJSHeapSize / 1048576).toFixed(1);
        const limitMB = (performance.memory.jsHeapSizeLimit / 1048576).toFixed(0);
        const pct = ((performance.memory.usedJSHeapSize / performance.memory.jsHeapSizeLimit) * 100).toFixed(1);
        console.log(`  Memory: ${memMB}MB / ${limitMB}MB (${pct}%)`);
        
        // Warning if memory is getting high
        if (pct > 80) {
          console.error(`  🚨 CRITICAL: Memory at ${pct}%! Browser may crash soon!`);
        } else if (pct > 60) {
          console.warn(`  ⚠️  WARNING: Memory at ${pct}%! Approaching limit.`);
        }
      }
      
      // Warning if too many tiles requested
      if (tileStats.requested > 200) {
        console.warn(`  ⚠️  ${tileStats.requested} tiles requested! This is excessive.`);
        console.warn(`  💡 Try: Reduce max zoom or start at higher camera altitude`);
      } else if (tileStats.requested > 100) {
        console.warn(`  ⚠️  ${tileStats.requested} tiles requested. Getting high.`);
      }
      
      // Warning if too many tiles in flight (network congestion)
      if (tilesInFlight.size > 50) {
        console.warn(`  ⚠️  ${tilesInFlight.size} tiles loading simultaneously! Network congestion.`);
      }
      
      // Call original and track result
      return originalRequestImage(x, y, level, request)
        .then(image => {
          const loadTime = performance.now() - requestStartTime;
          tileStats.succeeded++;
          tileStats.byZoom[level].succeeded++;
          tileStats.requestTimes.push(loadTime);
          tilesInFlight.delete(tileKey);
          
          // Estimate tile size
          let estimatedSize = 0;
          if (image && image.width && image.height) {
            // Rough estimate: 4 bytes per pixel (RGBA) for in-memory image
            estimatedSize = image.width * image.height * 4;
          }
          
          console.log(`[TILE SUCCESS] ${tileKey} - ${loadTime.toFixed(0)}ms`);
          if (estimatedSize > 0) {
            console.log(`  Est. memory: ${(estimatedSize / 1024).toFixed(1)}KB`);
          }
          
          // Log summary every 10 tiles
          if (tileStats.succeeded % 10 === 0) {
            const avgTime = tileStats.requestTimes.reduce((a, b) => a + b, 0) / tileStats.requestTimes.length;
            const elapsedSec = ((performance.now() - tileStats.startTime) / 1000).toFixed(1);
            
            console.log(`\n━━━ TILE LOADING SUMMARY ━━━`);
            console.log(`  Elapsed: ${elapsedSec}s`);
            console.log(`  Requested: ${tileStats.requested} | Success: ${tileStats.succeeded} | Failed: ${tileStats.failed}`);
            console.log(`  In flight: ${tilesInFlight.size}`);
            console.log(`  Avg load time: ${avgTime.toFixed(0)}ms`);
            console.log(`  Success rate: ${((tileStats.succeeded / tileStats.requested) * 100).toFixed(1)}%`);
            
            if (performance.memory) {
              const memMB = (performance.memory.usedJSHeapSize / 1048576).toFixed(1);
              const totalMB = (performance.memory.jsHeapSizeLimit / 1048576).toFixed(0);
              const pct = ((performance.memory.usedJSHeapSize / performance.memory.jsHeapSizeLimit) * 100).toFixed(1);
              console.log(`  Memory: ${memMB}MB / ${totalMB}MB (${pct}%)`);
            }
            
            // Show per-zoom breakdown
            console.log(`  By zoom level:`);
            Object.keys(tileStats.byZoom).sort((a, b) => a - b).forEach(z => {
              const stats = tileStats.byZoom[z];
              console.log(`    Z${z}: ${stats.succeeded}/${stats.requested} success`);
            });
            console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`);
          }
          
          return image;
        })
        .catch(error => {
          const loadTime = performance.now() - requestStartTime;
          tileStats.failed++;
          tileStats.byZoom[level].failed++;
          tilesInFlight.delete(tileKey);
          
          const errorMsg = error?.message || error?.toString() || 'Unknown error';
          tileStats.errors.push({ tile: tileKey, error: errorMsg, time: loadTime });
          
          console.error(`[TILE FAILED] ${tileKey} - ${loadTime.toFixed(0)}ms`);
          console.error(`  Error: ${errorMsg}`);
          console.error(`  Total failures: ${tileStats.failed}`);
          
          throw error;
        });
    };
    
    // Second, wrap with timeout and retry logic
    // Store the debug-wrapped method
    const debugWrappedRequestImage = provider.requestImage.bind(provider);
    const retryCounts = new Map();
    const maxRetries = 2; // Allow 2 retries (3 total attempts)
    
    provider.requestImage = function(x, y, level, request) {
      const key = `${level}/${x}/${y}`;
      const retryCount = retryCounts.get(key) || 0;
      
      // Create request with timeout if not provided
      if (!request) {
        request = new Cesium.Request({
          throttle: false,
          throttleByServer: true,
          type: Cesium.RequestType.IMAGERY
        });
      }
      
      // Set timeout on request (Cesium Request supports timeout property)
      if (request && typeof request.timeout === 'undefined') {
        // Use Resource's timeout mechanism
        if (request.url && Cesium.Resource) {
          // Wrap URL in Resource to set timeout
          const resource = new Cesium.Resource({
            url: request.url,
            timeout: tileTimeout
          });
          request.url = resource.url;
        }
      }
      
      // Attempt to load tile with timeout
      return debugWrappedRequestImage(x, y, level, request)
        .then(image => {
          // Success - clear retry count
          retryCounts.delete(key);
          return image;
        })
        .catch(error => {
          // Determine if error is retryable
          const isRetryable = retryCount < maxRetries && (
            error?.message?.includes('timeout') ||
            error?.message?.includes('network') ||
            error?.message?.includes('Failed to load') ||
            error?.name === 'NetworkError' ||
            error?.statusCode === 0 || // Network error
            (error?.statusCode >= 500 && error?.statusCode < 600) // Server error
          );
          
          if (isRetryable) {
            retryCounts.set(key, retryCount + 1);
            const delay = Math.pow(2, retryCount) * 1000; // Exponential backoff: 1s, 2s
            
            console.warn(`Tile request failed for ${key}, retrying (${retryCount + 1}/${maxRetries})...`, 
              error?.message || error?.toString() || 'Unknown error');
            
            return new Promise((resolve, reject) => {
              setTimeout(() => {
                // Retry with new request
                const retryRequest = new Cesium.Request({
                  throttle: false,
                  throttleByServer: true,
                  type: Cesium.RequestType.IMAGERY
                });
                
                debugWrappedRequestImage(x, y, level, retryRequest)
                  .then(resolve)
                  .catch(reject);
              }, delay);
            });
          }
          
          // Max retries reached or non-retryable error
          retryCounts.delete(key);
          
          // Call error handler if provided
          if (options.onError) {
            try {
              options.onError(error);
            } catch (e) {
              console.warn('Error in onError handler:', e);
            }
          }
          
          // Return undefined to indicate failed tile (Cesium will show missing tile)
          return undefined;
        });
    };
    
    // Add error event handler
    if (options.onError) {
      provider.errorEvent.addEventListener((error) => {
        try {
          options.onError(error);
        } catch (e) {
          console.warn('Error in errorEvent handler:', e);
        }
      });
    }
    
    // Add method to get statistics
    provider._getTileStats = () => tileStats;
    
    // Log final summary after a delay (when loading settles)
    setTimeout(() => {
      if (tileStats.requested > 0) {
        const elapsedSec = ((performance.now() - tileStats.startTime) / 1000).toFixed(1);
        const avgTime = tileStats.requestTimes.length > 0 
          ? (tileStats.requestTimes.reduce((a, b) => a + b, 0) / tileStats.requestTimes.length).toFixed(0)
          : 0;
        
        console.log(`\n═══════════════════════════════════════════════════`);
        console.log(`[FINAL TILE STATS] Raster Layer Loading Complete`);
        console.log(`═══════════════════════════════════════════════════`);
        console.log(`  Total time: ${elapsedSec}s`);
        console.log(`  Total requests: ${tileStats.requested}`);
        console.log(`  Succeeded: ${tileStats.succeeded} (${((tileStats.succeeded/tileStats.requested)*100).toFixed(1)}%)`);
        console.log(`  Failed: ${tileStats.failed}`);
        console.log(`  Avg load time: ${avgTime}ms`);
        
        if (performance.memory) {
          const memMB = (performance.memory.usedJSHeapSize / 1048576).toFixed(1);
          const totalMB = (performance.memory.jsHeapSizeLimit / 1048576).toFixed(0);
          const pct = ((performance.memory.usedJSHeapSize / performance.memory.jsHeapSizeLimit) * 100).toFixed(1);
          console.log(`  Memory used: ${memMB}MB / ${totalMB}MB (${pct}%)`);
          
          // Estimate tile memory
          const tileMemoryMB = (tileStats.succeeded * CONFIG.TILE_DIMENSIONS.width * CONFIG.TILE_DIMENSIONS.height * 4 / 1048576).toFixed(1);
          console.log(`  Est. tile memory: ${tileMemoryMB}MB`);
        }
        
        console.log(`\n  Breakdown by zoom level:`);
        Object.keys(tileStats.byZoom).sort((a, b) => a - b).forEach(z => {
          const stats = tileStats.byZoom[z];
          const successRate = ((stats.succeeded / stats.requested) * 100).toFixed(0);
          console.log(`    Zoom ${z}: ${stats.succeeded}/${stats.requested} (${successRate}%)`);
        });
        
        if (tileStats.errors.length > 0) {
          console.log(`\n  Recent errors:`);
          tileStats.errors.slice(-5).forEach(err => {
            console.log(`    ${err.tile}: ${err.error}`);
          });
        }
        
        console.log(`═══════════════════════════════════════════════════\n`);
        
        // Store stats globally for inspection
        window._lastRasterTileStats = tileStats;
        console.log(`💡 Stats saved to: window._lastRasterTileStats`);
      }
    }, 5000); // 5 second delay to allow tiles to load
    
    return provider;
  },
  
  /**
   * Dispose layer provider resources
   */
  disposeLayer: (layer) => {
    if (!layer) return;
    if (layer.imageryProvider && layer.imageryProvider.destroy) {
      try {
        layer.imageryProvider.destroy();
      } catch (e) {
        console.warn('Error disposing layer provider:', e);
      }
    }
  },
  
  /**
   * Remove layer from viewer with proper cleanup
   */
  removeLayer: (viewer, layer) => {
    if (!viewer || !layer) return;
    viewer.imageryLayers.remove(layer);
    LayerUtils.disposeLayer(layer);
  }
};

