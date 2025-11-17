/**
 * Camera and View Utilities
 */
import { CONFIG } from '../config.js';
import { CoordinateUtils } from './coordinates.js';
import { AppState } from '../state.js';

export const CameraUtils = {
  /**
   * Set camera view with safety checks
   * Supports fitting to bounds if provided in options
   * Returns a Promise that resolves when the camera transition is complete
   */
  setCameraView: (viewer, destination, options = {}) => {
    if (!viewer || !destination) {
      return Promise.reject(new Error('Viewer or destination not provided'));
    }
    
    // Clear tile cache before setting new view
    if (viewer.scene && viewer.scene.globe) {
      try {
        const oldCacheSize = viewer.scene.globe.tileCacheSize || CONFIG.MEMORY.TILE_CACHE_SIZE;
        viewer.scene.globe.tileCacheSize = 10;
        setTimeout(() => {
          viewer.scene.globe.tileCacheSize = oldCacheSize;
        }, 100);
      } catch (e) {
        // Ignore errors
      }
    }
    
    // If bounds are provided, fit camera to bounds instead of just centering
    // BUT: Only if bounds are reasonably sized to avoid memory issues
    if (options.bounds && Array.isArray(options.bounds) && options.bounds.length === 4) {
      const [west, south, east, north] = options.bounds;
      
      // Check for world bounds - use destination instead
      const isWorldBounds = Math.abs(west - (-180)) < 0.01 && 
                           Math.abs(east - 180) < 0.01 &&
                           Math.abs(south - (-85.0511)) < 0.01 && 
                           Math.abs(north - 85.0511) < 0.01;
      
      // Calculate bounds size to avoid fitting to very large areas
      const lonDiff = Math.abs(east - west);
      const latDiff = Math.abs(north - south);
      const maxDiff = Math.max(lonDiff, latDiff);
      
      // Only fit to bounds if:
      // 1. Not world bounds
      // 2. Bounds are reasonably sized (less than 30 degrees in any dimension)
      //    This prevents loading too many tiles at once
      const MAX_BOUNDS_SIZE = 30; // degrees
      const isReasonableSize = maxDiff < MAX_BOUNDS_SIZE;
      
      if (!isWorldBounds && isReasonableSize) {
        try {
          const duration = options.duration || 1.5;
          
          // Fit camera to bounds and return Promise that resolves when complete
          return new Promise((resolve, reject) => {
            viewer.camera.flyTo({
              destination: Cesium.Rectangle.fromDegrees(west, south, east, north),
              orientation: options.orientation || {
                heading: Cesium.Math.toRadians(0),
                pitch: Cesium.Math.toRadians(-90),
                roll: 0.0
              },
              duration: duration,
              complete: () => {
                // Cap height if needed after flyTo completes
                CoordinateUtils.capCameraHeight(viewer, options.maxHeight || CONFIG.MAX_SAFE_CAMERA_HEIGHT);
                viewer.scene.requestRender();
                resolve();
              },
              cancel: () => {
                reject(new Error('Camera flyTo was cancelled'));
              }
            });
          });
        } catch (e) {
          console.warn('Error fitting camera to bounds, falling back to destination:', e);
          // Fall through to destination-based view
        }
      } else {
        // Bounds too large - log and use destination instead
        if (!isReasonableSize) {
          console.warn(`Bounds too large (${maxDiff.toFixed(2)}°), using center point instead to avoid memory issues`);
        }
      }
    }
    
    // Set camera with orientation (standard destination-based view)
    // For setView, we need to wait a frame to ensure it's applied
    viewer.camera.setView({
      destination: destination,
      orientation: options.orientation || {
        heading: Cesium.Math.toRadians(0),
        pitch: Cesium.Math.toRadians(-90),
        roll: 0.0
      }
    });
    
    // Cap height if needed
    CoordinateUtils.capCameraHeight(viewer, options.maxHeight || CONFIG.MAX_SAFE_CAMERA_HEIGHT);
    
    // Request render
    viewer.scene.requestRender();
    
    // Return Promise that resolves after camera has settled
    // Wait for next frame to ensure camera position is applied
    return new Promise((resolve) => {
      // Use requestAnimationFrame to wait for render
      requestAnimationFrame(() => {
        // Wait one more frame to ensure camera is fully positioned
        requestAnimationFrame(() => {
          resolve();
        });
      });
    });
  },
  
  /**
   * Get home view destination from current layer
   */
  getHomeDestination: (layerId) => {
    if (!layerId || !AppState.availableLayers[layerId]) {
      return Cesium.Cartesian3.fromDegrees(0, 0, 20000000);
    }
    
    const layerInfo = AppState.availableLayers[layerId];
    const result = CoordinateUtils.getLayerDestination(layerInfo);
    return result.destination;
  },
  
  /**
   * Switch view mode with status update
   * @param {Object} viewer - Cesium viewer
   * @param {String} mode - View mode ('2D', '3D', 'COLUMBUS')
   * @param {Function} statusCallback - Optional callback for status updates
   */
  setViewMode: (viewer, mode, statusCallback = null) => {
    if (!viewer || !viewer.scene) {
      console.warn('Viewer or scene not available');
      return;
    }
    
    const modeMap = {
      '2D': {
        cesiumMode: Cesium.SceneMode.SCENE2D,
        statusMessage: '2D Map View'
      },
      '3D': {
        cesiumMode: Cesium.SceneMode.SCENE3D,
        statusMessage: '3D Globe View'
      },
      'COLUMBUS': {
        cesiumMode: Cesium.SceneMode.COLUMBUS_VIEW,
        statusMessage: 'Columbus View'
      }
    };
    
    const modeConfig = modeMap[mode.toUpperCase()];
    if (!modeConfig) {
      console.warn(`Unknown view mode: ${mode}`);
      return;
    }
    
    viewer.scene.mode = modeConfig.cesiumMode;
    console.log(`Switched to ${modeConfig.statusMessage}`);
    
    // Apply mode-specific optimization settings from CONFIG
    if (CONFIG && CONFIG.MEMORY && CONFIG.MEMORY.MODE_SPECIFIC) {
      // Map Cesium SceneMode to config key
      const modeSettingsMap = {
        [Cesium.SceneMode.SCENE2D]: 'SCENE2D',
        [Cesium.SceneMode.SCENE3D]: 'SCENE3D',
        [Cesium.SceneMode.COLUMBUS_VIEW]: 'COLUMBUS_VIEW'
      };
      
      const configKey = modeSettingsMap[modeConfig.cesiumMode];
      const modeSettings = CONFIG.MEMORY.MODE_SPECIFIC[configKey];
      
      if (modeSettings && viewer.scene.globe) {
        // Apply all mode-specific settings
        viewer.scene.globe.tileCacheSize = modeSettings.TILE_CACHE_SIZE;
        viewer.scene.globe.maximumScreenSpaceError = modeSettings.MAX_SCREEN_SPACE_ERROR;
        viewer.scene.globe.depthTestAgainstTerrain = modeSettings.DEPTH_TEST_TERRAIN;
        viewer.scene.globe.preloadSiblings = modeSettings.PRELOAD_SIBLINGS;
        viewer.scene.globe.preloadAncestors = modeSettings.PRELOAD_ANCESTORS;
        
        console.log(`Applied ${configKey} optimizations:`, {
          tileCacheSize: modeSettings.TILE_CACHE_SIZE,
          screenSpaceError: modeSettings.MAX_SCREEN_SPACE_ERROR,
          depthTest: modeSettings.DEPTH_TEST_TERRAIN,
          preloadSiblings: modeSettings.PRELOAD_SIBLINGS,
          preloadAncestors: modeSettings.PRELOAD_ANCESTORS
        });
      } else {
        console.warn('Mode-specific settings not found for', configKey);
      }
    }
    
    if (statusCallback && typeof statusCallback === 'function') {
      statusCallback(modeConfig.statusMessage);
    }
    
    return modeConfig.statusMessage;
  }
};

