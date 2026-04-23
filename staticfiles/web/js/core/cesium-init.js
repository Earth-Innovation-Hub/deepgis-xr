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
      maximumRenderTimeChange: Infinity,
      // Use Web Mercator projection (EPSG:3857) for 2D/Columbus views.
      // Default GeographicProjection (Plate Carree) stretches features horizontally
      // at non-equatorial latitudes, making circles appear elliptical.
      // Web Mercator is conformal (preserves local shapes), matching Google Maps/OSM.
      mapProjection: new Cesium.WebMercatorProjection(),
      // Request the discrete GPU on dual-GPU systems and keep software fallback as
      // a last resort. preserveDrawingBuffer:true is needed for screenshot/capture.
      // See refactor/tier-d0.5-fps-tuning.
      contextOptions: {
        preserveDrawingBuffer: true,
        webgl: {
          powerPreference: "high-performance",
          failIfMajorPerformanceCaveat: false
        }
      },
      // Render scale: cap at 1.5 even on DPR=2 displays. Without a cap, a 4K
      // Retina monitor renders at 8K-equivalent resolution (4x pixel work), which
      // by itself can drop FPS from 60 to single digits on iGPUs. 1.5 is a good
      // compromise: noticeably crisper than CSS pixels, ~56% of the GPU cost of
      // full DPR=2. Override with ?hidpi=1 to force native-pixel rendering.
      resolutionScale: (new URLSearchParams(window.location.search).get("hidpi") === "1")
        ? (window.devicePixelRatio || 1.0)
        : Math.min(window.devicePixelRatio || 1.0, 1.5),
      useBrowserRecommendedResolution: false
    });
    
    // Track default base map layer
    if (viewer.imageryLayers.length > 0) {
      AppState.currentLayers.defaultBaseMap = viewer.imageryLayers.get(0);
    }

    AppState.viewer = viewer;

    // Visible FPS / MS overlay (top-left of canvas). Cheap to render.
    // Toggle off via ?fps=0.
    if (new URLSearchParams(window.location.search).get("fps") !== "0") {
      viewer.scene.debugShowFramesPerSecond = true;
    }

    // Log the actual WebGL renderer the browser handed us. If this says
    // SwiftShader, llvmpipe, or Microsoft Basic Render, we are on a software
    // rasterizer and FPS will be unrecoverable until the OS/driver is fixed.
    try {
      const _gl = viewer.scene.context._gl || viewer.scene.context.canvas.getContext("webgl2") || viewer.scene.context.canvas.getContext("webgl");
      const _dbg = _gl && _gl.getExtension("WEBGL_debug_renderer_info");
      const _renderer = _dbg ? _gl.getParameter(_dbg.UNMASKED_RENDERER_WEBGL) : "unknown";
      const _vendor   = _dbg ? _gl.getParameter(_dbg.UNMASKED_VENDOR_WEBGL)   : "unknown";
      const _isSoft = /SwiftShader|llvmpipe|Software|Microsoft Basic/i.test(_renderer);
      console[_isSoft ? "warn" : "log"](`[GPU] vendor=${_vendor} renderer=${_renderer} software=${_isSoft}`);
      window.GPU_INFO = { vendor: _vendor, renderer: _renderer, isSoftware: _isSoft };
    } catch (e) {
      console.warn("[GPU] WEBGL_debug_renderer_info probe failed:", e);
    }

    // Configure Cesium for memory optimization
    if (viewer.scene.globe) {
      viewer.scene.globe.tileCacheSize = CONFIG.MEMORY.TILE_CACHE_SIZE;
      
      if (viewer.scene.globe._surface) {
        viewer.scene.globe._surface._tileLoadQueueHigh.length = 0;
      }
      
      // Set initial screen space error (will be overridden by mode-specific settings)
      // Only set if not in 2D mode to avoid overriding 2D quality settings
      if (viewer.scene.mode !== Cesium.SceneMode.SCENE2D) {
        viewer.scene.globe.maximumScreenSpaceError = CONFIG.MEMORY.MAX_SCREEN_SPACE_ERROR;
      }
    }
    
    if (viewer.scene.globe.terrainProvider) {
      viewer.scene.globe.terrainProvider.errorEvent.addEventListener((error) => {
        console.warn('Terrain provider error:', error);
      });
    }
    
    // Add event listeners
    viewer.camera.changed.addEventListener(() => {
      viewer.scene.requestRender();
    });
    // Render storm fix: tileLoadProgressEvent fires on every progress tick.
    // With requestRenderMode on a slow GPU, requesting a render on each tick
    // creates a self-stalling loop (each frame is slow -> tiles dont finish ->
    // event keeps firing -> repeat). Only request a render when tile loading
    // actually completes (count drops to 0).
    viewer.scene.globe.tileLoadProgressEvent.addEventListener((tilesRemaining) => {
      if (tilesRemaining === 0) {
        viewer.scene.requestRender();
      }
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
    // enableLighting=true enables per-pixel sun/atmosphere lighting on every
    // terrain tile. On weak GPUs it can cut FPS 3-5x. Off by default; opt in
    // via ?lighting=1 in the URL.
    const _enableLighting = new URLSearchParams(window.location.search).get("lighting") === "1";
    viewer.scene.globe.enableLighting = _enableLighting;
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
        // Fog and atmosphere are meaningless in flat 2D; disabling them removes
        // one full-screen pass.
        viewer.scene.fog.enabled = false;
        viewer.scene.skyAtmosphere.show = false;
        viewer.scene.globe.showGroundAtmosphere = false;

        // Reduce tile cache (2D needs fewer tiles than 3D perspective)
        viewer.scene.globe.tileCacheSize = 150;
        
        // Disable terrain depth testing (not needed in flat 2D view)
        viewer.scene.globe.depthTestAgainstTerrain = false;
        
        // Optimize screen space error for better quality in 2D
        // Lower value = higher quality (sharper tiles)
        viewer.scene.globe.maximumScreenSpaceError = 2; // Reduced from 4 for sharper rendering
        
        // Disable preload siblings (2D panning is predictable, no need to preload)
        viewer.scene.globe.preloadSiblings = false;
        
        // Disable preload ancestors (not needed in flat view)
        viewer.scene.globe.preloadAncestors = false;
        
        // Resolution scale is set once at viewer creation (capped at 1.5 unless
        // ?hidpi=1). Do NOT re-bump it here; that previously double-applied DPR
        // and was a major FPS regression on Retina/4K displays.
        
        console.log('Applied 2D mode optimizations:', {
          tileCacheSize: 150,
          depthTestAgainstTerrain: false,
          maximumScreenSpaceError: 2,
          preloadSiblings: false,
          preloadAncestors: false,
          resolutionScale: viewer.resolutionScale
        });
      }
      
      // Check for incoming location from URL hash (from map_label or previous session)
      const hash = window.location.hash;
      let initialPosition = null;
      
      if (hash) {
        const parts = hash.substring(1).split('/');
        if (parts.length >= 3) {
          const [p1, p2, p3] = parts.map(Number);
          // Format: lat/lng/alt (from map_label or 3D viewer)
          if (!isNaN(p1) && !isNaN(p2) && !isNaN(p3)) {
            initialPosition = {
              lat: p1,
              lng: p2,
              alt: p3 > 50 ? p3 : 1000 // Ensure minimum altitude
            };
            console.log(`Using location from hash: lat=${p1}, lng=${p2}, alt=${p3}`);
          }
        }
      }
      
      // Set initial view - will be updated when a layer is loaded
      if (initialPosition) {
        viewer.camera.setView({
          destination: Cesium.Cartesian3.fromDegrees(
            initialPosition.lng,
            initialPosition.lat,
            initialPosition.alt
          )
        });
        console.log(`Camera set to: lng=${initialPosition.lng}, lat=${initialPosition.lat}, alt=${initialPosition.alt}`);
      } else {
        // Default view - Tempe Town Lake, AZ (ASU area)
        viewer.camera.setView({
          destination: Cesium.Cartesian3.fromDegrees(-111.933884, 33.428187, 3322.5),
          orientation: {
            heading: Cesium.Math.toRadians(6.0), // 366° normalized to 6°
            pitch: Cesium.Math.toRadians(-90.0), // Looking straight down
            roll: 0.0
          }
        });
      }
    }, 100);

    updateLoadingStatus?.('Setting up event handlers...', 80);

    return viewer;

  } catch (error) {
    console.error('Error initializing Cesium:', error);
    ErrorHandler.handleLayerError(error, null, null, null, 'initializeCesium');
    throw error;
  }
}

/**
 * Toggle OSM 3D Buildings layer
 * @param {Cesium.Viewer} viewer - The Cesium viewer instance
 * @param {boolean} enabled - Whether to enable or disable buildings
 * @returns {Promise<boolean>} - Success status
 */
export async function toggleOSMBuildings(viewer, enabled) {
  if (!viewer) {
    console.error('Viewer not initialized');
    return false;
  }
  
  try {
    if (enabled) {
      // Load OSM Buildings if not already loaded
      if (!AppState.currentLayers.osmBuildings) {
        console.log('Loading OSM 3D Buildings...');
        
        // Create OSM Buildings tileset
        const osmBuildings = await Cesium.createOsmBuildingsAsync();
        
        // Add to viewer
        viewer.scene.primitives.add(osmBuildings);
        
        // Store reference in AppState
        AppState.currentLayers.osmBuildings = osmBuildings;
        
        console.log('✓ OSM 3D Buildings loaded successfully');
        return true;
      } else {
        // Buildings already loaded, just show them
        AppState.currentLayers.osmBuildings.show = true;
        console.log('✓ OSM 3D Buildings enabled');
        return true;
      }
    } else {
      // Disable buildings
      if (AppState.currentLayers.osmBuildings) {
        AppState.currentLayers.osmBuildings.show = false;
        console.log('✓ OSM 3D Buildings disabled');
        return true;
      }
    }
    
    return true;
  } catch (error) {
    console.error('Failed to toggle OSM Buildings:', error);
    return false;
  }
}

// Memory error handling is now in memory-manager.js module

