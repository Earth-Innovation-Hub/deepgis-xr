/**
 * Application Configuration
 * Centralized configuration for the DeepGIS Topology Viewer
 */
export const CONFIG = {
  SIDEBAR_WIDTH: 320,
  MAX_OVERLAY_LAYERS: 3,
  MAX_SAFE_CAMERA_HEIGHT: 5000000, // 5,000 km
  MAX_2D_VIEW_HEIGHT: 10000000, // 10,000 km
  DEFAULT_ZOOM_HEIGHT_BASE: 40000000,
  DEFAULT_ZOOM_LEVEL: 20,  // Default zoom level for layer loading
  TILE_DIMENSIONS: { width: 256, height: 256 },
  MEMORY: {
    TILE_CACHE_SIZE: 300,  // Reduced from 500 to prevent memory issues
    MAX_SCREEN_SPACE_ERROR: 6,  // Increased from 4 to reduce tile detail
    MAX_ZOOM_CAPS: {
      DEFAULT: 18,
      HIGH: 16,      // For maxzoom >= 20 (reduced from 17)
      VERY_HIGH: 13  // For maxzoom >= 23 (reduced from 16 to 13 for aggressive memory safety)
    },
    // Chunked tile loading configuration
    CHUNKED_LOADING: {
      ENABLED: false,  // Disabled - was causing freezing
      INITIAL_MAX_ZOOM: 12,  // Start with lower zoom
      ZOOM_INCREMENT: 2,     // Increase zoom by 2 levels at a time
      DELAY_BETWEEN_CHUNKS: 500,  // ms delay between zoom level increases
      MAX_TILES_PER_CHUNK: 50     // Maximum tiles to load before next chunk
    },
    // Mode-specific settings for 2D/3D optimization
    MODE_SPECIFIC: {
      SCENE2D: {
        TILE_CACHE_SIZE: 150,          // Half of 3D cache (2D needs fewer tiles)
        MAX_SCREEN_SPACE_ERROR: 4,     // Lower = better quality (sharper tiles in 2D)
        PRELOAD_SIBLINGS: false,        // Disable (2D panning is predictable)
        PRELOAD_ANCESTORS: false,       // Disable (not needed in flat view)
        DEPTH_TEST_TERRAIN: false,      // Disable (no depth in 2D)
        DESCRIPTION: '2D flat map view - optimized for memory and quality'
      },
      SCENE3D: {
        TILE_CACHE_SIZE: 300,          // Full cache for 3D perspective
        MAX_SCREEN_SPACE_ERROR: 6,     // Higher = fewer tiles (acceptable in 3D)
        PRELOAD_SIBLINGS: true,         // Enable (needed for rotation)
        PRELOAD_ANCESTORS: true,        // Enable (LOD hierarchy)
        DEPTH_TEST_TERRAIN: true,       // Enable (3D depth testing)
        DESCRIPTION: '3D globe view - balanced performance and quality'
      },
      COLUMBUS_VIEW: {
        TILE_CACHE_SIZE: 225,          // Between 2D and 3D
        MAX_SCREEN_SPACE_ERROR: 5,     // Between 2D and 3D
        PRELOAD_SIBLINGS: true,         // Enable (similar to 3D)
        PRELOAD_ANCESTORS: false,       // Disable (flatter than 3D)
        DEPTH_TEST_TERRAIN: false,      // Disable (no globe curvature)
        DESCRIPTION: 'Columbus view (2.5D) - hybrid between 2D and 3D'
      }
    }
  },
  TIMEOUTS: {
    METADATA_FETCH: 10000,  // Increased from 5000 to 10000 (10 seconds) for slow servers
    TILE_REQUEST: 30000,    // 30 seconds for individual tile requests
    AUTO_LOAD_DELAY: 500,
    AUTO_LOAD_RETRY_INTERVAL: 100,
    AUTO_LOAD_MAX_RETRIES: 50
  },
  SERVERS: {
    MBTILES_SERVER: window.location.protocol === 'https:' 
      ? 'https://mbtiles.deepgis.org' 
      : 'http://mbtiles.deepgis.org',
    TOPOLOGY_SERVER: window.location.protocol === 'https:'
      ? 'https://localhost:8092'
      : 'http://localhost:8092'
  },
  CESIUM_ION_TOKEN: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI5MzIyMWMxOC03MTk5LTQyMmUtYTM5NC02NzVlYWU1NDg2NGYiLCJpZCI6MzA1OTgwLCJpYXQiOjE3NDgxMjcxNDZ9.AgxpEL6okIFIv0028AEmR2Mk9GeHCPLQyM3RjjBORNk',
  
  // Vector tile configuration
  VECTOR_TILES: {
    ENABLED: true,
    SHOW_BOUNDING_BOX: false,  // Show bounding box visualization for debugging
    MAX_ZOOM: 14,  // Maximum zoom level for vector tiles to prevent performance issues
    MAX_CACHED_TILES: 100,  // Maximum number of cached vector tiles
    MAX_TILES_PER_DIMENSION: 4,  // Maximum tiles to load per dimension (4x4 = 16 tiles max)
    
    // Default styling for vector features
    DEFAULT_STYLE: {
      fillColor: { r: 0.4, g: 0.6, b: 0.8 },  // Light blue
      fillOpacity: 0.5,
      strokeColor: { r: 0.2, g: 0.3, b: 0.5 },  // Darker blue
      strokeWidth: 2,
      pointSize: 8
    },
    
    // Layer-specific styles (can be customized per layer)
    FEATURE_STYLES: {
      'bf_aug_2020': {
        fillColor: { r: 0.8, g: 0.4, b: 0.2 },  // Orange
        fillOpacity: 0.6,
        strokeColor: { r: 0.5, g: 0.2, b: 0.1 },
        strokeWidth: 2
      },
      'bf_oct_2020': {
        fillColor: { r: 0.2, g: 0.8, b: 0.4 },  // Green
        fillOpacity: 0.6,
        strokeColor: { r: 0.1, g: 0.5, b: 0.2 },
        strokeWidth: 2
      },
      'bf_dec_2020_vector': {
        fillColor: { r: 0.6, g: 0.2, b: 0.8 },  // Purple
        fillOpacity: 0.6,
        strokeColor: { r: 0.3, g: 0.1, b: 0.5 },
        strokeWidth: 2
      },
      'bf_feb_2021_3d': {
        fillColor: { r: 0.8, g: 0.8, b: 0.2 },  // Yellow
        fillOpacity: 0.6,
        strokeColor: { r: 0.5, g: 0.5, b: 0.1 },
        strokeWidth: 2
      }
    }
  },
  
  // Raster layer configuration
  RASTER: {
    SHOW_BOUNDING_BOX: false  // Show bounding box visualization for debugging (default: false)
  }
};

