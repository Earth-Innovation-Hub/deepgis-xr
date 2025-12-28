/**
 * Global Application State
 * Centralized state management for the DeepGIS Topology Viewer
 */
import { CONFIG } from './config.js';

export const AppState = {
  viewer: null,
  currentLayers: {
    baseRaster: null,
    overlays: {},
    vectors: {},  // Vector layer tracking
    terrain: null,
    models: [],
    osmBuildings: null  // OSM 3D Buildings tileset
  },
  availableLayers: {},
  measurements: [],
  histogram_chart: null,
  isInitialized: false,
  errorLog: [],
  debugMode: false,
  vectorRenderer: null,  // Vector layer renderer instance
  performanceMetrics: {
    layerLoadTimes: [],
    tileLoadCounts: {},
    memorySnapshots: []
  },
  webxr: {
    session: null,
    referenceSpace: null,
    gl: null,
    baseLayer: null,
    isSupported: false,
    vrSupported: false,
    arSupported: false,
    isInSession: false,
    isReady: false,
    sessionMode: null, // 'immersive-vr' or 'immersive-ar'
    frameOfRef: null,
    initialPosition: null,
    initialOrientation: null
  },
  // Utility modules (will be lazy loaded)
  utils: null,
  // Feature modules (lazy loaded)
  features: {
    webxr: null,
    models: null,
    measurements: null,
    debug: null,
    statistics: null
  }
};

// Expose to window for backward compatibility during migration
window.DeepGISTopology = AppState;

