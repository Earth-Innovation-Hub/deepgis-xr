/**
 * Memory Management Module
 * Handles memory optimization and out-of-memory error recovery
 */
import { CONFIG } from '../config.js';
import { AppState } from '../state.js';
import { LayerUtils } from '../utils/layers.js';

/**
 * Handle out-of-memory errors with aggressive cleanup
 */
export function handleMemoryError(error, viewer) {
  if (!viewer) return;
  
  const errorMessage = error.toString ? error.toString() : String(error);
  
  if (errorMessage.includes('out of memory') || errorMessage.includes('memory')) {
    console.error('⚠️ Out of memory error detected! Performing aggressive cleanup...');
    
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('Out of memory - performing cleanup...');
    }
    
    // Step 1: Remove all overlay layers
    const overlayIds = Object.keys(AppState.currentLayers.overlays);
    overlayIds.forEach(layerId => {
      const imageryLayer = AppState.currentLayers.overlays[layerId];
      if (imageryLayer) {
        viewer.imageryLayers.remove(imageryLayer);
        LayerUtils.disposeLayer(imageryLayer);
      }
      
      // Uncheck checkbox
      const checkbox = document.getElementById(`overlay_${layerId}`);
      if (checkbox) checkbox.checked = false;
    });
    AppState.currentLayers.overlays = {};
    console.log(`Removed ${overlayIds.length} overlay layers`);
    
    // Step 2: Check if base layer has high zoom and remove it
    if (AppState.currentLayers.baseRaster) {
      const baseLayer = AppState.currentLayers.baseRaster;
      const layerInfo = Object.values(AppState.availableLayers).find(
        l => l.id === baseLayer.imageryProvider?._url?.match(/data\/([^\/]+)/)?.[1]
      );
      
      // If base layer has very high maxzoom (>= 23), remove it
      if (layerInfo && layerInfo.maxzoom >= 23) {
        console.warn('⚠️ Removing very high-zoom base layer due to memory error');
        LayerUtils.removeLayer(viewer, baseLayer);
        AppState.currentLayers.baseRaster = null;
        
        // Reset dropdown
        const rasterSelect = document.getElementById('rasterLayerSelect');
        if (rasterSelect) {
          rasterSelect.value = '';
          if (typeof window.updateStatusIndicator === 'function') {
            window.updateStatusIndicator('High-zoom layer removed due to memory constraints');
          }
        }
      }
    }
    
    // Step 3: Aggressively reduce Cesium memory settings
    if (viewer.scene && viewer.scene.globe) {
      try {
        // Reduce tile cache significantly
        viewer.scene.globe.tileCacheSize = 100;
        
        // Increase screen space error to reduce detail
        viewer.scene.globe.maximumScreenSpaceError = 10;
        
        // Clear tile load queues
        if (viewer.scene.globe._surface) {
          viewer.scene.globe._surface._tileLoadQueueHigh.length = 0;
          viewer.scene.globe._surface._tileLoadQueueMedium.length = 0;
          viewer.scene.globe._surface._tileLoadQueueLow.length = 0;
        }
        
        console.log('Reduced tile cache to 100 and increased screen space error to 10');
      } catch (e) {
        console.warn('Could not reduce memory settings:', e);
      }
    }
    
    // Step 4: Force garbage collection if available
    if (window.gc) {
      window.gc();
      console.log('Forced garbage collection');
    }
    
    // Step 5: Show user-friendly message with recommendations
    setTimeout(() => {
      const message = 'Memory cleared. Please select a layer with maxzoom < 20, or refresh the page.';
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator(message);
      }
      if (typeof window.showSnackBar === 'function') {
        window.showSnackBar(
          'Out of memory error. High-zoom layers cleared. Please select a layer with maxzoom < 20.',
          'warning'
        );
      }
    }, 1000);
  }
}

/**
 * Pre-check layer before loading to warn about potential memory issues
 */
export function checkLayerMemorySafety(layerInfo) {
  if (!layerInfo) return { safe: true, warning: null };
  
  const maxzoom = layerInfo.maxzoom || 22;
  const safeMaxZoom = LayerUtils.calculateSafeMaxZoom(maxzoom);
  
  if (maxzoom >= 23) {
    return {
      safe: true,  // Will be capped, so technically safe
      warning: `This layer has very high native zoom (${maxzoom}). It will be capped at ${safeMaxZoom} for memory safety.`,
      recommended: 'Consider using a lower-zoom variant if available.'
    };
  } else if (maxzoom >= 20) {
    return {
      safe: true,
      warning: `This layer has high native zoom (${maxzoom}). It will be capped at ${safeMaxZoom} for memory safety.`,
      recommended: null
    };
  }
  
  return { safe: true, warning: null };
}

/**
 * Optimize viewer memory settings based on current load
 */
export function optimizeMemorySettings(viewer) {
  if (!viewer || !viewer.scene || !viewer.scene.globe) return;
  
  const overlayCount = Object.keys(AppState.currentLayers.overlays).length;
  const hasHighZoomLayer = AppState.currentLayers.baseRaster && 
    Object.values(AppState.availableLayers).some(l => 
      l.maxzoom >= 20 && 
      l.id === AppState.currentLayers.baseRaster?.imageryProvider?._url?.match(/data\/([^\/]+)/)?.[1]
    );
  
  // Check camera height - if too high, reduce memory usage
  const cameraHeight = viewer.camera.positionCartographic.height;
  const isHighAltitude = cameraHeight > CONFIG.MAX_2D_VIEW_HEIGHT;
  
  // Adjust settings based on current load
  if (hasHighZoomLayer || overlayCount > 1 || isHighAltitude) {
    // More conservative settings when high-zoom layers are active or camera is too high
    const cacheSize = Math.min(CONFIG.MEMORY.TILE_CACHE_SIZE, 200);
    const screenSpaceError = Math.max(CONFIG.MEMORY.MAX_SCREEN_SPACE_ERROR, 8); // Increased to 8 for high altitude
    
    viewer.scene.globe.tileCacheSize = cacheSize;
    viewer.scene.globe.maximumScreenSpaceError = screenSpaceError;
    
    const reason = isHighAltitude ? 'high camera altitude' : 
                  hasHighZoomLayer ? 'high-zoom layer' : 
                  'multiple overlays';
    console.log(`Applied conservative memory settings (cache: ${cacheSize}, error: ${screenSpaceError}) due to ${reason}`);
    
    // If camera is too high, cap it immediately
    if (isHighAltitude) {
      console.warn(`Camera altitude (${(cameraHeight / 1000).toFixed(0)} km) is too high, capping to ${(CONFIG.MAX_2D_VIEW_HEIGHT / 1000).toFixed(0)} km`);
      const pos = viewer.camera.positionCartographic;
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromRadians(pos.longitude, pos.latitude, CONFIG.MAX_2D_VIEW_HEIGHT)
      });
    }
  } else {
    // Normal settings
    viewer.scene.globe.tileCacheSize = CONFIG.MEMORY.TILE_CACHE_SIZE;
    viewer.scene.globe.maximumScreenSpaceError = CONFIG.MEMORY.MAX_SCREEN_SPACE_ERROR;
  }
}

export default {
  handleMemoryError,
  checkLayerMemorySafety,
  optimizeMemorySettings
};

