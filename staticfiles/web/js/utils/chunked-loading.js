/**
 * Chunked Tile Loading Utility
 * Loads tiles progressively in chunks to prevent memory issues
 */
import { CONFIG } from '../config.js';
import { AppState } from '../state.js';

/**
 * Create a chunked imagery provider that loads tiles progressively
 * Starts at lower zoom and gradually increases to target zoom
 */
export function createChunkedImageryProvider(tileUrl, layerInfo, targetMaxZoom, options = {}) {
  const chunkConfig = CONFIG.MEMORY.CHUNKED_LOADING;
  
  // If chunked loading is disabled, create normal provider
  if (!chunkConfig.ENABLED) {
    return new Cesium.UrlTemplateImageryProvider({
      url: tileUrl,
      maximumLevel: targetMaxZoom,
      minimumLevel: layerInfo.minzoom || 0,
      credit: new Cesium.Credit('DeepGIS TileServer'),
      enablePick: false,
      tileWidth: CONFIG.TILE_DIMENSIONS.width,
      tileHeight: CONFIG.TILE_DIMENSIONS.height,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      ...options
    });
  }
  
  // Start with initial max zoom (lower than target)
  let currentMaxZoom = Math.min(
    chunkConfig.INITIAL_MAX_ZOOM,
    targetMaxZoom
  );
  
  console.log(`Chunked loading: Starting at zoom ${currentMaxZoom}, target: ${targetMaxZoom}`);
  
  // Create provider with initial zoom
  const provider = new Cesium.UrlTemplateImageryProvider({
    url: tileUrl,
    maximumLevel: currentMaxZoom,
    minimumLevel: layerInfo.minzoom || 0,
    credit: new Cesium.Credit('DeepGIS TileServer'),
    enablePick: false,
    tileWidth: CONFIG.TILE_DIMENSIONS.width,
    tileHeight: CONFIG.TILE_DIMENSIONS.height,
    tilingScheme: new Cesium.WebMercatorTilingScheme(),
    ...options
  });
  
  // Track loading state
  let isProgressiveLoading = false;
  let tileLoadCount = 0;
  let lastTileLoadTime = performance.now();
  
  // Monitor tile loading progress
  if (AppState.viewer && AppState.viewer.scene && AppState.viewer.scene.globe) {
    const globe = AppState.viewer.scene.globe;
    
    // Listen to tile load progress
    const progressListener = globe.tileLoadProgressEvent.addEventListener(() => {
      tileLoadCount++;
      lastTileLoadTime = performance.now();
    });
    
    // Progressive zoom increase function
    const increaseZoomLevel = () => {
      if (currentMaxZoom >= targetMaxZoom) {
        // Reached target zoom
        console.log(`Chunked loading: Reached target zoom ${targetMaxZoom}`);
        return;
      }
      
      // Check if we should wait for more tiles to load
      const timeSinceLastTile = performance.now() - lastTileLoadTime;
      const tilesLoaded = tileLoadCount;
      
      // If tiles are still loading (within last 200ms) or we haven't loaded enough, wait
      if (timeSinceLastTile < 200 || tilesLoaded < chunkConfig.MAX_TILES_PER_CHUNK) {
        // Schedule next check
        setTimeout(increaseZoomLevel, chunkConfig.DELAY_BETWEEN_CHUNKS);
        return;
      }
      
      // Increase zoom level
      const nextZoom = Math.min(
        currentMaxZoom + chunkConfig.ZOOM_INCREMENT,
        targetMaxZoom
      );
      
      if (nextZoom > currentMaxZoom) {
        currentMaxZoom = nextZoom;
        console.log(`Chunked loading: Increasing to zoom ${currentMaxZoom} (target: ${targetMaxZoom})`);
        
        // Update provider's maximum level
        // Note: Cesium doesn't allow changing maximumLevel after creation,
        // so we need to recreate the provider
        // For now, we'll use a workaround by updating the internal property
        try {
          if (provider._maximumLevel !== undefined) {
            provider._maximumLevel = currentMaxZoom;
          }
          // Force Cesium to recognize the new max level
          if (provider._tilingScheme) {
            provider._tilingScheme = provider._tilingScheme; // Trigger update
          }
        } catch (e) {
          console.warn('Could not update provider max zoom, will continue with current level:', e);
        }
        
        // Reset tile count for next chunk
        tileLoadCount = 0;
        
        // Schedule next increase
        setTimeout(increaseZoomLevel, chunkConfig.DELAY_BETWEEN_CHUNKS);
      }
    };
    
    // Start progressive loading after initial delay
    setTimeout(() => {
      if (currentMaxZoom < targetMaxZoom) {
        isProgressiveLoading = true;
        console.log(`Chunked loading: Starting progressive zoom increase`);
        increaseZoomLevel();
      }
    }, chunkConfig.DELAY_BETWEEN_CHUNKS);
  }
  
  return provider;
}

/**
 * Alternative approach: Create multiple providers with increasing zoom levels
 * This is more reliable but uses more resources
 */
export function createLayeredChunkedProvider(tileUrl, layerInfo, targetMaxZoom, options = {}) {
  const chunkConfig = CONFIG.MEMORY.CHUNKED_LOADING;
  
  if (!chunkConfig.ENABLED || targetMaxZoom <= chunkConfig.INITIAL_MAX_ZOOM) {
    // No chunking needed
    return new Cesium.UrlTemplateImageryProvider({
      url: tileUrl,
      maximumLevel: targetMaxZoom,
      minimumLevel: layerInfo.minzoom || 0,
      credit: new Cesium.Credit('DeepGIS TileServer'),
      enablePick: false,
      tileWidth: CONFIG.TILE_DIMENSIONS.width,
      tileHeight: CONFIG.TILE_DIMENSIONS.height,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      ...options
    });
  }
  
  // Create base provider with initial zoom
  const baseProvider = new Cesium.UrlTemplateImageryProvider({
    url: tileUrl,
    maximumLevel: chunkConfig.INITIAL_MAX_ZOOM,
    minimumLevel: layerInfo.minzoom || 0,
    credit: new Cesium.Credit('DeepGIS TileServer'),
    enablePick: false,
    tileWidth: CONFIG.TILE_DIMENSIONS.width,
    tileHeight: CONFIG.TILE_DIMENSIONS.height,
    tilingScheme: new Cesium.WebMercatorTilingScheme(),
    ...options
  });
  
  console.log(`Layered chunked loading: Created base provider at zoom ${chunkConfig.INITIAL_MAX_ZOOM}`);
  
  // Store progressive loading info
  baseProvider._chunkedLoading = {
    targetZoom: targetMaxZoom,
    currentZoom: chunkConfig.INITIAL_MAX_ZOOM,
    nextZoom: Math.min(
      chunkConfig.INITIAL_MAX_ZOOM + chunkConfig.ZOOM_INCREMENT,
      targetMaxZoom
    ),
    delay: chunkConfig.DELAY_BETWEEN_CHUNKS,
    enabled: true
  };
  
  return baseProvider;
}

/**
 * Progressively add higher zoom level providers to viewer
 * This is called after the base layer is loaded
 */
export function addProgressiveZoomLayers(viewer, imageryLayer, tileUrl, layerInfo, targetMaxZoom, options = {}) {
  const chunkConfig = CONFIG.MEMORY.CHUNKED_LOADING;
  
  if (!chunkConfig.ENABLED || targetMaxZoom <= chunkConfig.INITIAL_MAX_ZOOM) {
    return; // No progressive loading needed
  }
  
  const baseProvider = imageryLayer.imageryProvider;
  if (!baseProvider._chunkedLoading) {
    return; // Not a chunked provider
  }
  
  let currentZoom = baseProvider._chunkedLoading.currentZoom;
  const targetZoom = baseProvider._chunkedLoading.targetZoom;
  
  const addNextZoomLevel = () => {
    if (currentZoom >= targetZoom) {
      console.log(`Progressive loading: Reached target zoom ${targetZoom}`);
      return;
    }
    
    const nextZoom = Math.min(
      currentZoom + chunkConfig.ZOOM_INCREMENT,
      targetZoom
    );
    
    console.log(`Progressive loading: Adding zoom level ${nextZoom}`);
    
    // Create new provider for next zoom range
    const nextProvider = new Cesium.UrlTemplateImageryProvider({
      url: tileUrl,
      maximumLevel: nextZoom,
      minimumLevel: currentZoom + 1, // Start from next level
      credit: new Cesium.Credit('DeepGIS TileServer'),
      enablePick: false,
      tileWidth: CONFIG.TILE_DIMENSIONS.width,
      tileHeight: CONFIG.TILE_DIMENSIONS.height,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      ...options
    });
    
    // Add as overlay (will be rendered on top)
    const nextLayer = viewer.imageryLayers.addImageryProvider(nextProvider);
    nextLayer.alpha = 1.0;
    
    currentZoom = nextZoom;
    
    // Schedule next zoom level
    if (currentZoom < targetZoom) {
      setTimeout(addNextZoomLevel, chunkConfig.DELAY_BETWEEN_CHUNKS);
    }
  };
  
  // Start progressive loading after delay
  setTimeout(addNextZoomLevel, chunkConfig.DELAY_BETWEEN_CHUNKS);
}

