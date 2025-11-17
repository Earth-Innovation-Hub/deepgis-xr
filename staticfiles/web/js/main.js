/**
 * Main Entry Point
 * Implements lazy loading and code splitting
 */
// CSS is loaded separately via <link> tag in HTML template
import { CONFIG } from './config.js';
import { AppState } from './state.js';
import { initializeCesium } from './core/cesium-init.js';
import { initializeAvailableLayers, loadBaseRasterLayer, toggleOverlayLayer } from './core/layer-management.js';
import { toggleTerrain, changeBaseMap } from './core/base-map.js';
import { updateStatusIndicator, showSnackBar, logLayerOperation } from './core/ui-helpers.js';
import { optimizeMemorySettings } from './core/memory-manager.js';
import { CoordinateUtils } from './utils/coordinates.js';
import { LayerUtils } from './utils/layers.js';
import { ErrorHandler } from './utils/errors.js';
import { CameraUtils } from './utils/camera.js';

// Set Cesium Ion token
Cesium.Ion.defaultAccessToken = CONFIG.CESIUM_ION_TOKEN;

// Suppress console errors for missing source maps
const originalConsoleError = console.error;
console.error = function(...args) {
  const message = args.join(' ');
  if (message.includes('Source map') || message.includes('sourcemap') || message.includes('.map')) {
    return;
  }
  originalConsoleError.apply(console, args);
};

// Initialize utility modules in AppState
AppState.utils = {
  coordinate: CoordinateUtils,
  layer: LayerUtils,
  error: ErrorHandler,
  camera: CameraUtils,
  config: CONFIG
};

// Lazy loading functions for heavy features
const lazyLoaders = {
  webxr: async () => {
    if (!AppState.features.webxr) {
      const webxrModule = await import('./features/webxr.js');
      AppState.features.webxr = webxrModule.default;
      return webxrModule;
    }
    return AppState.features.webxr;
  },
  
  models: async () => {
    if (!AppState.features.models) {
      const modelsModule = await import('./features/models.js');
      AppState.features.models = modelsModule.default;
      return modelsModule;
    }
    return AppState.features.models;
  },
  
  measurements: async () => {
    if (!AppState.features.measurements) {
      const measurementsModule = await import('./features/measurements.js');
      AppState.features.measurements = measurementsModule.default;
      return measurementsModule;
    }
    return AppState.features.measurements;
  },
  
  debug: async () => {
    if (!AppState.features.debug) {
      const debugModule = await import('./features/debug-console.js');
      AppState.features.debug = debugModule.default;
      return debugModule;
    }
    return AppState.features.debug;
  },
  
  statistics: async () => {
    if (!AppState.features.statistics) {
      const statisticsModule = await import('./features/statistics.js');
      AppState.features.statistics = statisticsModule.default;
      return statisticsModule;
    }
    return AppState.features.statistics;
  },
  
  navigation: async () => {
    if (!AppState.features.navigation) {
      const navigationModule = await import('./widgets/navigation.js');
      AppState.features.navigation = navigationModule.default;
      return navigationModule;
    }
    return AppState.features.navigation;
  },
  
  astronomy: async () => {
    if (!AppState.features.astronomy) {
      const astronomyModule = await import('./utils/astronomy.js');
      AppState.features.astronomy = astronomyModule.default;
      return astronomyModule;
    }
    return AppState.features.astronomy;
  }
};

// Expose lazy loaders globally
window.lazyLoadFeature = async (featureName) => {
  if (lazyLoaders[featureName]) {
    return await lazyLoaders[featureName]();
  }
  throw new Error(`Unknown feature: ${featureName}`);
};

// Update loading status helper
function updateLoadingStatus(message, progress) {
  const statusEl = document.getElementById('loadingStatus');
  const barEl = document.getElementById('loadingBar');
  if (statusEl) statusEl.textContent = message;
  if (barEl) barEl.style.width = progress + '%';
}

// Initialize application
document.addEventListener('DOMContentLoaded', async () => {
  try {
    // Initialize Cesium
    const viewer = await initializeCesium(updateLoadingStatus);
    
    updateLoadingStatus('Loading available data...', 90);
    
    // Initialize available layers
    await initializeAvailableLayers();
    
    AppState.isInitialized = true;
    
    updateLoadingStatus('Complete!', 100);
    
    // Hide loading overlay
    setTimeout(() => {
      const overlay = document.getElementById('loadingOverlay');
      if (overlay) overlay.style.display = 'none';
      
      const statusIndicator = document.getElementById('statusIndicator');
      if (statusIndicator) statusIndicator.textContent = 'Ready';
    }, 500);
    
    // Optimize initial memory settings
    optimizeMemorySettings(viewer);
    
    // Lazy load navigation widgets
    const navigationModule = await lazyLoaders.navigation();
    if (navigationModule.initializeNavigation) {
      navigationModule.initializeNavigation(viewer);
    }
    
    // Set up event handlers
    setupEventHandlers(viewer);
    
    // Start performance monitoring
    startPerformanceMonitoring(viewer);
    
  } catch (error) {
    console.error('Failed to initialize application:', error);
    const statusEl = document.getElementById('loadingStatus');
    if (statusEl) statusEl.textContent = 'Failed to initialize: ' + error.message;
  }
});

/**
 * Helper function to create lazy-loaded event handler
 * Reduces duplication for feature toggle buttons
 * @param {String} elementId - DOM element ID
 * @param {Function} loaderFn - Lazy loader function
 * @param {String} methodName - Method name to call on loaded module
 * @param {Array} args - Arguments to pass to the method
 */
function addLazyEventHandler(elementId, loaderFn, methodName, args = []) {
  document.getElementById(elementId)?.addEventListener('click', async () => {
    try {
      const module = await loaderFn();
      if (module[methodName] && typeof module[methodName] === 'function') {
        module[methodName](...args);
      } else {
        console.warn(`Method ${methodName} not found in lazy-loaded module`);
      }
    } catch (error) {
      console.error(`Error loading feature from ${elementId}:`, error);
      updateStatusIndicator(`Error: ${error.message}`);
    }
  });
}

// Set up event handlers
function setupEventHandlers(viewer) {
  // View mode controls - using shared utility function
  document.getElementById('view2D')?.addEventListener('click', () => {
    CameraUtils.setViewMode(viewer, '2D', updateStatusIndicator);
  });

  document.getElementById('view3D')?.addEventListener('click', () => {
    CameraUtils.setViewMode(viewer, '3D', updateStatusIndicator);
  });

  document.getElementById('viewColumbus')?.addEventListener('click', () => {
    CameraUtils.setViewMode(viewer, 'COLUMBUS', updateStatusIndicator);
  });

  document.getElementById('homeView')?.addEventListener('click', () => {
    // Base raster layer dropdown removed - use default world view or first overlay
    const destination = CameraUtils.getHomeDestination(null);
    const statusMessage = 'Home View - World';
    
    viewer.camera.setView({ destination });
    updateStatusIndicator(statusMessage);
  });

  // Layer toggles
  document.getElementById('terrainToggle')?.addEventListener('change', async (e) => {
    try {
      await toggleTerrain(viewer, e.target.checked);
    } catch (error) {
      console.error('Error toggling terrain:', error);
      updateStatusIndicator('Error toggling terrain');
    }
  });

  document.getElementById('modelsToggle')?.addEventListener('change', (e) => {
    const modelControls = document.getElementById('modelControls');
    if (modelControls) {
      modelControls.style.display = e.target.checked ? 'block' : 'none';
    }
  });

  // Model controls - using helper function to reduce duplication
  addLazyEventHandler('loadModel', lazyLoaders.models, 'loadGLTFModel', [viewer]);
  addLazyEventHandler('removeModel', lazyLoaders.models, 'removeModels', [viewer]);

  // Model location selection
  document.getElementById('modelLocation')?.addEventListener('change', (e) => {
    const customInputs = document.getElementById('customLocationInputs');
    if (customInputs) {
      customInputs.style.display = e.target.value === 'custom' ? 'block' : 'none';
    }
  });

  // Model scale slider
  document.getElementById('modelScale')?.addEventListener('input', (e) => {
    const scaleValue = document.getElementById('scaleValue');
    if (scaleValue) {
      scaleValue.textContent = `Scale: ${e.target.value}x`;
    }
  });

  // Base map selection
  document.getElementById('baseMapSelect')?.addEventListener('change', (e) => {
    changeBaseMap(viewer, e.target.value);
  });

  // Base raster layer selection - DISABLED (removed duplication with overlays)
  // All raster layers now available only as overlays
  // document.getElementById('rasterLayerSelect')?.addEventListener('change', async (e) => {
  //   try {
  //     await loadBaseRasterLayer(viewer, e.target.value);
  //   } catch (error) {
  //     console.error('Error loading base raster layer:', error);
  //     updateStatusIndicator(`Error loading layer: ${error.message}`);
  //   }
  // });

  // Sidebar toggle
  document.getElementById('sidebarToggle')?.addEventListener('click', () => {
    const wrapper = document.getElementById('wrapper');
    if (wrapper) {
      wrapper.classList.toggle('show-sidebar');
      setTimeout(() => {
        viewer.resize();
      }, 300);
    }
  });

  // WebXR controls - using helper function to reduce duplication
  addLazyEventHandler('checkVRSupport', lazyLoaders.webxr, 'checkWebXRSupport');
  addLazyEventHandler('enterVR', lazyLoaders.webxr, 'enterWebXR');
  addLazyEventHandler('exitVR', lazyLoaders.webxr, 'exitWebXR');

  // Measurement tools - using helper function to reduce duplication
  addLazyEventHandler('measureDistance', lazyLoaders.measurements, 'startDistanceMeasurement', [viewer]);
  addLazyEventHandler('measureArea', lazyLoaders.measurements, 'startAreaMeasurement', [viewer]);
  addLazyEventHandler('measureHeight', lazyLoaders.measurements, 'startHeightMeasurement', [viewer]);
  addLazyEventHandler('clearMeasurements', lazyLoaders.measurements, 'clearAllMeasurements', [viewer]);

  // Fullscreen change detection
  const handleFullscreenChange = () => {
    const wrapper = document.getElementById('wrapper');
    const cesiumContainer = document.getElementById('cesiumContainer');
    const navigationWidgetGroup = document.getElementById('navigationWidgetGroup');
    const isFullscreen = !!(document.fullscreenElement || 
                           document.webkitFullscreenElement || 
                           document.mozFullScreenElement || 
                           document.msFullscreenElement);
    
    const isMobile = window.innerWidth <= 768;
    
    if (isFullscreen) {
      if (wrapper) wrapper.dataset.sidebarStateBeforeFullscreen = wrapper.classList.contains('show-sidebar') ? 'true' : 'false';
      if (wrapper) wrapper.classList.add('fullscreen-mode');
      
      if (cesiumContainer) {
        cesiumContainer.style.right = '0';
        cesiumContainer.style.left = '0';
        cesiumContainer.style.width = '100%';
      }
      
      if (isMobile) {
        if (navigationWidgetGroup) {
          navigationWidgetGroup.style.right = '15px';
          navigationWidgetGroup.style.top = '20px';
          navigationWidgetGroup.style.display = 'block';
        }
        updateStatusIndicator('Fullscreen mode - Mobile navigation active');
      } else {
        if (navigationWidgetGroup) navigationWidgetGroup.style.right = '15px';
        updateStatusIndicator('Fullscreen mode - Viewport expanded');
      }
    } else {
      if (wrapper) wrapper.classList.remove('fullscreen-mode');
      
      if (isMobile) {
        if (cesiumContainer) {
          cesiumContainer.style.right = '0';
          cesiumContainer.style.left = '0';
          cesiumContainer.style.width = '100%';
        }
        
        if (navigationWidgetGroup) {
          navigationWidgetGroup.style.right = '15px';
          navigationWidgetGroup.style.top = '20px';
          navigationWidgetGroup.style.display = 'block';
        }
        updateStatusIndicator('Mobile mode - Navigation dials active');
      } else {
        if (cesiumContainer) {
          cesiumContainer.style.right = '320px';
          cesiumContainer.style.left = '0';
          cesiumContainer.style.width = 'auto';
        }
        
        if (navigationWidgetGroup) navigationWidgetGroup.style.right = '350px';
        
        if (wrapper) {
          const wasShowingSidebar = wrapper.dataset.sidebarStateBeforeFullscreen === 'true';
          if (wasShowingSidebar) {
            wrapper.classList.add('show-sidebar');
          }
        }
        updateStatusIndicator('Desktop mode - Sidebar restored');
      }
    }
    
    setTimeout(() => {
      viewer.resize();
      setTimeout(() => {
        viewer.resize();
      }, 100);
    }, 300);
  };

  document.addEventListener('fullscreenchange', handleFullscreenChange);
  document.addEventListener('webkitfullscreenchange', handleFullscreenChange);
  document.addEventListener('mozfullscreenchange', handleFullscreenChange);
  document.addEventListener('MSFullscreenChange', handleFullscreenChange);

  // Window resize handler
  window.addEventListener('resize', () => {
    const isMobile = window.innerWidth <= 768;
    const cesiumContainer = document.getElementById('cesiumContainer');
    const navigationWidgetGroup = document.getElementById('navigationWidgetGroup');
    const wrapper = document.getElementById('wrapper');
    
    if (isMobile) {
      if (cesiumContainer) {
        cesiumContainer.style.right = '0';
        cesiumContainer.style.left = '0';
        cesiumContainer.style.width = '100%';
      }
      
      if (navigationWidgetGroup) {
        navigationWidgetGroup.style.right = '15px';
        navigationWidgetGroup.style.top = '20px';
        navigationWidgetGroup.style.display = 'block';
      }
      
      if (wrapper) wrapper.classList.remove('show-sidebar');
    } else {
      const isFullscreen = !!(document.fullscreenElement || 
                             document.webkitFullscreenElement || 
                             document.mozFullScreenElement || 
                             document.msFullscreenElement);
      
      if (!isFullscreen) {
        if (cesiumContainer) {
          cesiumContainer.style.right = '320px';
          cesiumContainer.style.left = '0';
          cesiumContainer.style.width = 'auto';
        }
        
        if (navigationWidgetGroup) {
          navigationWidgetGroup.style.right = '350px';
        }
      }
    }
    
    setTimeout(() => {
      viewer.resize();
    }, 100);
  });
}

// Performance monitoring
function startPerformanceMonitoring(viewer) {
  let lastTime = performance.now();
  let frameCount = 0;

  function updateFPS() {
    frameCount++;
    const currentTime = performance.now();
    
    if (currentTime - lastTime >= 1000) {
      const fps = Math.round((frameCount * 1000) / (currentTime - lastTime));
      const perfEl = document.getElementById('performanceIndicator');
      if (perfEl) perfEl.textContent = `FPS: ${fps}`;
      frameCount = 0;
      lastTime = currentTime;
    }
    
    requestAnimationFrame(updateFPS);
  }
  
  requestAnimationFrame(updateFPS);
}

// Export for use in other modules
export { AppState, CONFIG, lazyLoaders };

