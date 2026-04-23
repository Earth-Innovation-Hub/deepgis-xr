/**
 * Main Entry Point
 * Implements lazy loading and code splitting
 */
// CSS is loaded separately via <link> tag in HTML template
import { CONFIG } from './config.js';
import { AppState } from './state.js';
import { initializeCesium, toggleOSMBuildings } from './core/cesium-init.js';
import featureLayers, { setFeatureLayerEnabled, renderFeatureLayerToggles } from './core/feature-layers.js';
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
      try {
        // Import path: go up from js/ to web/, then into features/
        const webxrModule = await import('../features/webxr.js');
      AppState.features.webxr = webxrModule.default;
      return webxrModule;
      } catch (error) {
        console.warn('Failed to load WebXR module:', error);
        // Return a fallback module with error handling
        return {
          checkWebXRSupport: async () => {
            const statusElement = document.getElementById('vrStatus');
            if (statusElement) {
              statusElement.textContent = 'VR Status: WebXR module not available';
              statusElement.style.color = '#ef4444';
            }
            return false;
          },
          enterWebXR: async () => {
            alert('WebXR module not available. Please check the console for details.');
          },
          exitWebXR: async () => {
            // No-op if module not loaded
          }
        };
      }
    }
    return AppState.features.webxr;
  },
  
  models: async () => {
    if (!AppState.features.models) {
      try {
        const modelsModule = await import('../features/models.js');
      AppState.features.models = modelsModule.default;
      return modelsModule;
      } catch (error) {
        console.warn('Failed to load Models module:', error);
        return {
          loadGLTFModel: () => console.warn('Models module not available'),
          removeModels: () => console.warn('Models module not available')
        };
      }
    }
    return AppState.features.models;
  },
  
  measurements: async () => {
    if (!AppState.features.measurements) {
      try {
        const measurementsModule = await import('../features/measurements.js');
      AppState.features.measurements = measurementsModule.default;
      return measurementsModule;
      } catch (error) {
        console.warn('Failed to load Measurements module:', error);
        return {
          startDistanceMeasurement: () => console.warn('Measurements module not available'),
          startAreaMeasurement: () => console.warn('Measurements module not available'),
          startHeightMeasurement: () => console.warn('Measurements module not available'),
          clearAllMeasurements: () => console.warn('Measurements module not available')
        };
      }
    }
    return AppState.features.measurements;
  },
  
  debug: async () => {
    if (!AppState.features.debug) {
      try {
        const debugModule = await import('../features/debug-console.js');
      AppState.features.debug = debugModule.default;
      return debugModule;
      } catch (error) {
        console.warn('Failed to load Debug module:', error);
        return { initializeDebugConsole: () => {} };
      }
    }
    return AppState.features.debug;
  },
  
  statistics: async () => {
    if (!AppState.features.statistics) {
      try {
        const statisticsModule = await import('../features/statistics.js');
      AppState.features.statistics = statisticsModule.default;
      return statisticsModule;
      } catch (error) {
        console.warn('Failed to load Statistics module:', error);
        return { initializeHistogram: () => {} };
      }
    }
    return AppState.features.statistics;
  },
  
  navigation: async () => {
    if (!AppState.features.navigation) {
      try {
      const navigationModule = await import('./widgets/navigation.js');
      AppState.features.navigation = navigationModule.default;
      return navigationModule;
      } catch (error) {
        console.warn('Failed to load Navigation module:', error);
        return { initializeNavigation: () => {} };
      }
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
  },
  
  weatherStations: async () => {
    if (!AppState.features.weatherStations) {
      try {
        const { NWSWeatherStationLayer } = await import('./utils/nws-weather-stations.js');
        AppState.features.weatherStations = { NWSWeatherStationLayer };
        return AppState.features.weatherStations;
      } catch (error) {
        console.warn('Failed to load Weather Stations module:', error);
        return { 
          NWSWeatherStationLayer: null,
          initializeWeatherStations: () => console.warn('Weather Stations module not available')
        };
      }
    }
    return AppState.features.weatherStations;
  }
};

// Expose lazy loaders globally
window.lazyLoadFeature = async (featureName) => {
  if (lazyLoaders[featureName]) {
    return await lazyLoaders[featureName]();
  }
  throw new Error(`Unknown feature: ${featureName}`);
};

// Expose feature-layer togglers to inline (non-module) template scripts.
// Templates (e.g. label_search.html, label_topology.html) run outside the
// module graph, so they cannot import these directly. Keeping one
// canonical implementation here prevents duplicates like the pre-refactor
// double-instantiated OSM Buildings tileset.
window.toggleOSMBuildings = (enabled) => toggleOSMBuildings(window.viewer || AppState.viewer, enabled);

// Tier-D feature-layer registry. Pages can render a full toggle column
// with `window.FeatureLayers.renderToggles(container, ['osm-buildings', ...])`
// or drive individual layers with `window.FeatureLayers.set(id, bool)`.
window.FeatureLayers = {
  registry: featureLayers,
  set: (id, enabled) => setFeatureLayerEnabled(id, window.viewer || AppState.viewer, enabled),
  renderToggles: (container, ids) => renderFeatureLayerToggles(container, ids, {
    getViewer: () => window.viewer || AppState.viewer
  })
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
    
    // Store viewer globally for other modules
    window.viewer = viewer;
    AppState.viewer = viewer;
    
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
    
    // Initialize weather stations widget
    try {
      const { default: WeatherStationsWidget } = await import('./widgets/weather-stations.js');
      window.weatherStationsWidget = new WeatherStationsWidget(viewer);
      console.log('Weather Stations Widget initialized');
    } catch (error) {
      console.warn('Failed to initialize Weather Stations Widget:', error);
    }
    
    // Set up event handlers
    setupEventHandlers(viewer);
    
    // Start performance monitoring
    startPerformanceMonitoring(viewer);
    
    // Initialize Mission Planner if available
    if (typeof MissionPlanner !== 'undefined') {
      try {
        window.missionPlanner = new MissionPlanner(viewer);
        console.log('Mission Planner initialized');
      } catch (error) {
        console.warn('Failed to initialize Mission Planner:', error);
      }
    }
    
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
  const element = document.getElementById(elementId);
  if (!element) {
    console.warn(`Element ${elementId} not found, skipping event handler`);
    return;
  }
  
  element.addEventListener('click', async () => {
    try {
      const module = await loaderFn();
      if (module && module[methodName] && typeof module[methodName] === 'function') {
        await module[methodName](...args);
      } else {
        console.warn(`Method ${methodName} not found in lazy-loaded module for ${elementId}`);
        // Show user-friendly error for WebXR
        if (elementId === 'checkVRSupport') {
          const statusElement = document.getElementById('vrStatus');
          if (statusElement) {
            statusElement.textContent = 'VR Status: WebXR module not available';
            statusElement.style.color = '#ef4444';
          }
        }
      }
    } catch (error) {
      console.error(`Error loading feature from ${elementId}:`, error);
      // Show user-friendly error for WebXR
      if (elementId === 'checkVRSupport') {
        const statusElement = document.getElementById('vrStatus');
        if (statusElement) {
          statusElement.textContent = 'VR Status: Error loading WebXR module';
          statusElement.style.color = '#ef4444';
        }
      } else if (typeof updateStatusIndicator === 'function') {
      updateStatusIndicator(`Error: ${error.message}`);
      }
    }
  });
}

// Set perspective view (N/S/E/W) with angled view at 5km altitude
function setPerspectiveView(viewer, headingDegrees, direction) {
  try {
    if (!viewer || !viewer.camera) {
      console.error('Viewer or camera not available');
      return;
    }
    
    // First, switch to 3D globe view mode
    CameraUtils.setViewMode(viewer, '3D', () => {});
    
    // Get current viewport center (what's visible in the center of the screen)
    // This maintains the same lat/lon that the user is currently viewing
    let longitude, latitude;
    
    // Get the center of the viewport by picking the ellipsoid at screen center
    const centerX = viewer.canvas.clientWidth / 2;
    const centerY = viewer.canvas.clientHeight / 2;
    const centerCartesian = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(centerX, centerY));
    
    if (centerCartesian) {
      // Use the viewport center point - this is what the user is actually looking at
      const cartographic = Cesium.Cartographic.fromCartesian(centerCartesian);
      longitude = cartographic.longitude;
      latitude = cartographic.latitude;
    } else {
      // Fallback: use camera position if pickEllipsoid fails (e.g., in 2D mode)
      const currentPosition = viewer.camera.position;
      if (currentPosition) {
        const cartographic = Cesium.Cartographic.fromCartesian(currentPosition);
        longitude = cartographic.longitude;
        latitude = cartographic.latitude;
      } else if (viewer.camera.positionCartographic) {
        longitude = viewer.camera.positionCartographic.longitude;
        latitude = viewer.camera.positionCartographic.latitude;
      } else {
        console.warn('Could not determine viewport center, using fallback');
        // Last resort: use camera's current cartographic position
        const cartographic = Cesium.Cartographic.fromCartesian(viewer.camera.position);
        longitude = cartographic.longitude;
        latitude = cartographic.latitude;
      }
    }
    
    // Set altitude similar to example view (~1640m) for natural perspective
    const altitude = 1640;
    
    // Set pitch similar to example view (~-8.9°) for natural viewing angle
    const pitch = Cesium.Math.toRadians(-8.9);
    
    // Fly to the new position with perspective angle
    // Keep the same lat/lon (viewport center), just change heading and altitude
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromRadians(
        longitude,
        latitude,
        altitude
      ),
      orientation: {
        heading: Cesium.Math.toRadians(headingDegrees),
        pitch: pitch,
        roll: 0.0
      },
      duration: 1.5
    });
    
    updateStatusIndicator(`View: ${direction} (${headingDegrees}°) at 1.6km`);
  } catch (error) {
    console.error('Error setting perspective view:', error);
    updateStatusIndicator(`Error: Could not set ${direction} view`);
  }
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

  // Perspective view controls (N/S/E/W)
  document.getElementById('viewNorth')?.addEventListener('click', () => {
    setPerspectiveView(viewer, 0, 'North');
  });

  document.getElementById('viewSouth')?.addEventListener('click', () => {
    setPerspectiveView(viewer, 180, 'South');
  });

  document.getElementById('viewEast')?.addEventListener('click', () => {
    setPerspectiveView(viewer, 90, 'East');
  });

  document.getElementById('viewWest')?.addEventListener('click', () => {
    setPerspectiveView(viewer, 270, 'West');
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

  // Model controls - using helper function to reduce duplication
  addLazyEventHandler('loadModel', lazyLoaders.models, 'loadGLTFModel', [viewer]);
  addLazyEventHandler('quickLoadModel', lazyLoaders.models, 'quickLoadAtCurrentLocation', [viewer]);
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

  // Preset model buttons
  document.querySelectorAll('.preset-model-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const url = e.currentTarget.dataset.url;
      const modelUrlInput = document.getElementById('modelUrl');
      if (modelUrlInput && url) {
        modelUrlInput.value = url;
        // Visual feedback
        e.currentTarget.classList.add('active');
        setTimeout(() => e.currentTarget.classList.remove('active'), 200);
        if (typeof window.showSnackBar === 'function') {
          window.showSnackBar(`Model preset selected: ${e.currentTarget.textContent.trim()}`, 'info');
        }
      }
    });
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
  
  // LiDAR search handler
  const searchLidarBtn = document.getElementById('searchLidar');
  if (searchLidarBtn) {
    searchLidarBtn.addEventListener('click', async () => {
      try {
        const { OpenTopographyLidarSearch } = await import('./utils/opentopography-lidar.js');
        const lidarSearch = new OpenTopographyLidarSearch(viewer);
        
        const statusEl = document.getElementById('lidarSearchStatus');
        const contentEl = document.getElementById('lidarSearchContent');
        const resultsEl = document.getElementById('lidarSearchResults');
        
        if (statusEl) statusEl.textContent = 'Searching for LiDAR datasets...';
        if (resultsEl) resultsEl.style.display = 'block';
        
        const bounds = lidarSearch.getViewportBounds();
        const area = lidarSearch.getViewportArea(bounds);
        const formattedBounds = lidarSearch.formatBounds(bounds);
        
        const results = await lidarSearch.searchViewport();
        
        if (statusEl) {
          statusEl.innerHTML = `
            <strong>Viewport Area:</strong> ${area.toFixed(2)} km²<br>
            <strong>Bounds:</strong> ${formattedBounds.south}°N to ${formattedBounds.north}°N, 
            ${formattedBounds.west}°W to ${formattedBounds.east}°W
          `;
        }
        
        if (contentEl) {
          if (results.count > 0) {
            contentEl.innerHTML = `
              <div style="color: #10b981; margin-bottom: 8px;">
                <strong>Found ${results.count} dataset(s):</strong>
              </div>
              <div style="max-height: 200px; overflow-y: auto;">
                ${results.datasets.map((ds, i) => `
                  <div style="padding: 6px; margin: 4px 0; background: rgba(0,0,0,0.2); border-radius: 4px;">
                    <strong>${ds.name || `Dataset ${i + 1}`}</strong><br>
                    ${ds.description ? `<small>${ds.description}</small><br>` : ''}
                    ${ds.resolution ? `<small>Resolution: ${ds.resolution}</small><br>` : ''}
                    ${ds.year ? `<small>Year: ${ds.year}</small>` : ''}
                  </div>
                `).join('')}
              </div>
            `;
          } else {
            contentEl.innerHTML = `
              <div style="color: #fbbf24; margin-bottom: 8px;">
                <strong>No datasets found in this area</strong>
              </div>
              ${results.portal_url ? `
                <a href="${results.portal_url}" target="_blank" 
                   style="color: #60a5fa; text-decoration: underline; font-size: 0.75rem;">
                  Search OpenTopography Portal →
                </a>
              ` : ''}
              ${results.message ? `<div style="margin-top: 4px; font-size: 0.75rem; color: #94a3b8;">${results.message}</div>` : ''}
            `;
          }
        }
        
        showSnackBar(`Found ${results.count} LiDAR dataset(s)`, results.count > 0 ? 'success' : 'info');
      } catch (error) {
        console.error('Error searching LiDAR data:', error);
        const statusEl = document.getElementById('lidarSearchStatus');
        const contentEl = document.getElementById('lidarSearchContent');
        if (statusEl) statusEl.textContent = 'Error searching for datasets';
        if (contentEl) contentEl.innerHTML = `<div style="color: #ef4444;">${error.message}</div>`;
        showSnackBar('Error searching LiDAR data', 'error');
      }
    });
  }
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

  // Window resize handler (debounced to avoid excessive calls during drag-resize)
  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
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
      
      viewer.resize();
    }, 250);
  });
}

// Performance monitoring - samples FPS every second using Cesium's postRender event
function startPerformanceMonitoring(viewer) {
  const perfEl = document.getElementById('performanceIndicator');
  if (!perfEl) return; // Don't start monitoring if indicator doesn't exist
  
  let frameCount = 0;
  
  // Count frames via Cesium's render loop (no extra rAF needed)
  viewer.scene.postRender.addEventListener(() => {
    frameCount++;
  });
  
  // Sample FPS every second
  setInterval(() => {
    perfEl.textContent = `FPS: ${frameCount}`;
    frameCount = 0;
  }, 1000);
}

// Export for use in other modules
export { AppState, CONFIG, lazyLoaders };

