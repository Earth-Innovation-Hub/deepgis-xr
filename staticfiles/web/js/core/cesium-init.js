/**
 * Cesium Initialization Module
 * Handles Cesium viewer setup and configuration
 */
import { CONFIG } from '../config.js';
import { AppState } from '../state.js';
import { CoordinateUtils } from '../utils/coordinates.js';
import { ErrorHandler } from '../utils/errors.js';
import { handleMemoryError } from './memory-manager.js';

/**
 * Debug function to check Cesium API availability
 */
export function debugCesiumAPI() {
  console.log('=== Cesium API Compatibility Check ===');
  console.log('Cesium version:', Cesium.VERSION || 'Unknown');
  
  const apiChecks = [
    'createWorldTerrain',
    'createWorldTerrainAsync',
    'createWorldImagery', 
    'createWorldImageryAsync',
    'IonWorldImageryStyle',
    'Cesium3DTileset.fromIonAssetId'
  ];
  
  apiChecks.forEach(api => {
    const path = api.split('.');
    let obj = Cesium;
    let available = true;
    
    for (const prop of path) {
      if (obj && typeof obj === 'object' && prop in obj) {
        obj = obj[prop];
      } else {
        available = false;
        break;
      }
    }
    
    console.log(`${api}: ${available ? '✓ Available' : '✗ Not Available'}`);
  });
  
  console.log('Ion Access Token:', Cesium.Ion.defaultAccessToken ? 'Set' : 'Not Set');
  console.log('=====================================');
}

/**
 * Initialize Cesium viewer
 */
export async function initializeCesium(updateLoadingStatus) {
  try {
    updateLoadingStatus?.('Configuring Cesium...', 20);
    
    // Debug Cesium API availability
    debugCesiumAPI();

    updateLoadingStatus?.('Creating viewer...', 40);

    // Create the Cesium viewer with OpenStreetMap as default base layer
    let defaultImageryProvider;
    try {
      defaultImageryProvider = await Cesium.OpenStreetMapImageryProvider.fromUrl(
        'https://a.tile.openstreetmap.org/'
      );
      console.log('Using OpenStreetMap as default base layer');
    } catch (error) {
      console.warn('Failed to create OpenStreetMap provider, using Ion fallback:', error);
      try {
        // Use async Ion provider creation
        defaultImageryProvider = await Cesium.IonImageryProvider.fromAssetId(2);
        console.log('Using Ion imagery provider as fallback');
      } catch (ionError) {
        console.warn('Failed to create fallback imagery provider, viewer will start without base imagery');
        defaultImageryProvider = null;
      }
    }
    
    const viewer = new Cesium.Viewer('cesiumContainer', {
      animation: false,
      baseLayerPicker: false,
      imageryProvider: defaultImageryProvider || undefined,
      fullscreenButton: true,
      geocoder: true,
      homeButton: true,
      infoBox: true,
      sceneModePicker: true,
      selectionIndicator: true,
      timeline: false,
      navigationHelpButton: true,
      navigationInstructionsInitiallyVisible: false,
      scene3DOnly: false,
      requestRenderMode: true,
      maximumRenderTimeChange: Infinity
    });
    
    // Track default base map layer
    if (viewer.imageryLayers.length > 0) {
      AppState.currentLayers.defaultBaseMap = viewer.imageryLayers.get(0);
    }

    AppState.viewer = viewer;

    // Configure Cesium for memory optimization
    if (viewer.scene.globe) {
      viewer.scene.globe.tileCacheSize = CONFIG.MEMORY.TILE_CACHE_SIZE;
      
      if (viewer.scene.globe._surface) {
        viewer.scene.globe._surface._tileLoadQueueHigh.length = 0;
      }
    }
    
    viewer.scene.globe.maximumScreenSpaceError = CONFIG.MEMORY.MAX_SCREEN_SPACE_ERROR;
    
    if (viewer.scene.globe.terrainProvider) {
      viewer.scene.globe.terrainProvider.errorEvent.addEventListener((error) => {
        console.warn('Terrain provider error:', error);
      });
    }
    
    // Add event listeners
    viewer.camera.changed.addEventListener(() => {
      viewer.scene.requestRender();
    });
    viewer.scene.globe.tileLoadProgressEvent.addEventListener(() => {
      viewer.scene.requestRender();
    });

    // Set up error handling for render errors (including out of memory)
    if (viewer.scene.renderError) {
      viewer.scene.renderError.addEventListener((error) => {
        console.error('Cesium render error:', error);
        handleMemoryError(error, viewer);
      });
    }
    
    // Global error handler as fallback for out of memory errors
    window.addEventListener('error', (event) => {
      if (event.message && (event.message.includes('out of memory') || event.message.includes('memory'))) {
        console.error('Global out of memory error detected!');
        handleMemoryError(event.message, viewer);
      }
    });
    
    // Also listen for unhandled promise rejections that might indicate memory issues
    window.addEventListener('unhandledrejection', (event) => {
      const reason = event.reason?.message || String(event.reason || '');
      if (reason.includes('out of memory') || reason.includes('memory')) {
        console.error('Unhandled promise rejection - possible memory issue:', reason);
        handleMemoryError(reason, viewer);
      }
    });

    updateLoadingStatus?.('Setting up scene...', 60);

    // Set up terrain provider with request deduplication
    try {
      let terrainProvider;
      if (typeof Cesium.createWorldTerrainAsync === 'function') {
        terrainProvider = await Cesium.createWorldTerrainAsync();
        console.log('Ion world terrain loaded successfully (async)');
      } else if (typeof Cesium.createWorldTerrain === 'function') {
        terrainProvider = Cesium.createWorldTerrain();
        console.log('Ion world terrain loaded successfully (sync)');
      } else {
        terrainProvider = new Cesium.CesiumTerrainProvider({
          url: Cesium.IonResource.fromAssetId(1)
        });
        console.log('Ion terrain loaded using CesiumTerrainProvider');
      }
      
      // Configure terrain provider to reduce redundant requests
      if (terrainProvider && terrainProvider.ready) {
        await terrainProvider.ready;
      }
      
      // Set terrain provider
      viewer.terrainProvider = terrainProvider;
      
      // Monitor terrain requests to detect excessive requests (debug only)
      // Note: This is a best-effort monitoring - Cesium may use internal mechanisms
      if (viewer.scene.globe && viewer.scene.globe.terrainProvider && 
          typeof viewer.scene.globe.terrainProvider.requestTileGeometry === 'function') {
        try {
          const requestCounts = new Map();
          const originalRequestTileGeometry = viewer.scene.globe.terrainProvider.requestTileGeometry.bind(viewer.scene.globe.terrainProvider);
          
          viewer.scene.globe.terrainProvider.requestTileGeometry = function(...args) {
            try {
              const key = args[0]?.x !== undefined && args[0]?.y !== undefined && args[0]?.level !== undefined
                ? `${args[0].level}/${args[0].x}/${args[0].y}`
                : JSON.stringify(args[0]);
              const count = (requestCounts.get(key) || 0) + 1;
              requestCounts.set(key, count);
              
              if (count > 5 && count % 5 === 0) {
                console.warn(`⚠️ Terrain tile requested ${count} times:`, key);
              }
            } catch (e) {
              // Silently fail monitoring - don't break terrain loading
            }
            
            return originalRequestTileGeometry(...args);
          };
        } catch (e) {
          console.warn('Could not set up terrain request monitoring:', e);
        }
      }
    } catch (error) {
      console.warn('Failed to load Ion terrain, using basic terrain:', error);
      viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
    }

    // Configure the scene
    viewer.scene.globe.enableLighting = true;
    viewer.scene.fog.enabled = true;
    viewer.scene.fog.density = 0.0001;
    viewer.scene.globe.baseColor = Cesium.Color.BLACK.withAlpha(0.0);
    
    // Ensure default imagery layer is visible
    setTimeout(async () => {
      if (viewer.imageryLayers.length > 0) {
        const defaultLayer = viewer.imageryLayers.get(0);
        defaultLayer.show = true;
        console.log('Default imagery layer verified:', defaultLayer.imageryProvider?.credit?.html || 'Ion Imagery');
      } else {
        console.warn('No default imagery layer found after initialization, attempting to add Ion imagery');
        try {
          // Use async Ion provider creation
          const fallbackProvider = await Cesium.IonImageryProvider.fromAssetId(2);
          viewer.imageryLayers.addImageryProvider(fallbackProvider);
          console.log('Fallback Ion imagery added successfully');
        } catch (error) {
          console.warn('Could not add fallback imagery provider:', error);
        }
      }
      
      viewer.scene.mode = Cesium.SceneMode.SCENE2D;
      console.log('Initialized map in 2D mode');
      
      // Apply 2D-specific optimizations
      if (viewer.scene.mode === Cesium.SceneMode.SCENE2D) {
        // Reduce tile cache (2D needs fewer tiles than 3D perspective)
        viewer.scene.globe.tileCacheSize = 150;
        
        // Disable terrain depth testing (not needed in flat 2D view)
        viewer.scene.globe.depthTestAgainstTerrain = false;
        
        // Optimize screen space error for better quality in 2D
        viewer.scene.globe.maximumScreenSpaceError = 4;
        
        // Disable preload siblings (2D panning is predictable, no need to preload)
        viewer.scene.globe.preloadSiblings = false;
        
        // Disable preload ancestors (not needed in flat view)
        viewer.scene.globe.preloadAncestors = false;
        
        console.log('Applied 2D mode optimizations:', {
          tileCacheSize: 150,
          depthTestAgainstTerrain: false,
          maximumScreenSpaceError: 4,
          preloadSiblings: false,
          preloadAncestors: false
        });
      }
      
      // Set initial view - will be updated when a layer is loaded
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(0, 0, 20000000)
      });
    }, 100);

    updateLoadingStatus?.('Setting up event handlers...', 80);

    return viewer;

  } catch (error) {
    console.error('Error initializing Cesium:', error);
    ErrorHandler.handleLayerError(error, null, null, null, 'initializeCesium');
    throw error;
  }
}

// Memory error handling is now in memory-manager.js module

