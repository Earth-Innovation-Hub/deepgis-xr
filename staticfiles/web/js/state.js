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
  // Hierarchical catalog (Site -> Dataset -> Timestep -> Product) loaded
  // from GET /api/v1/tile-catalog/. Populated by core/catalog.js. The
  // flat availableLayers above remains the source of truth for tile-
  // serving metadata (bounds, format, zoom range); this catalog adds
  // grouping, ordering, and per-product display metadata on top.
  catalog: {
    version: null,
    sites: [],            // [{slug, name, bounds, default_zoom, datasets: [...]}, ...]
    activeSiteSlug: null, // currently-selected Tier-1 site (null = none)
    productIndex: {},     // layer_id -> { site, dataset, timestep, product }
    orphanLayers: [],     // layer ids in availableLayers but not in catalog
    error: null,
  },
  // UI mode for layer comparison: 'single' | 'swipe' | 'difference'
  comparisonMode: 'single',
  // Filter Tier-1 to layers whose bounds intersect the current camera viewport.
  viewportFilterEnabled: false,
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

