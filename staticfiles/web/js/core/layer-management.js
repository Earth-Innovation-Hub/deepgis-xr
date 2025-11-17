/**
 * Layer Management Module
 * Handles layer initialization, loading, and toggling
 */
import { CONFIG } from '../config.js';
import { AppState } from '../state.js';
import { LayerUtils } from '../utils/layers.js';
import { CoordinateUtils } from '../utils/coordinates.js';
import { CameraUtils } from '../utils/camera.js';
import { ErrorHandler } from '../utils/errors.js';
import { checkLayerMemorySafety, optimizeMemorySettings } from './memory-manager.js';
import { addProgressiveZoomLayers } from '../utils/chunked-loading.js';
import { VectorLayerRenderer } from '../utils/vector-tiles.js';

/**
 * Helper: Safe window function call with fallback
 * Eliminates repeated typeof checks
 */
const safeCall = (fnName, ...args) => {
  if (typeof window[fnName] === 'function') {
    try {
      window[fnName](...args);
    } catch (e) {
      console.warn(`Error calling ${fnName}:`, e);
    }
  }
};

/**
 * Helper: Update status indicator (safe)
 */
const updateStatus = (message) => safeCall('updateStatusIndicator', message);

/**
 * Helper: Log layer operation (safe)
 */
const logLayerOp = (...args) => safeCall('logLayerOperation', ...args);

/**
 * Helper: Uncheck checkbox by ID
 */
const uncheckBox = (id) => {
  const checkbox = document.getElementById(id);
  if (checkbox) checkbox.checked = false;
};

/**
 * Helper: Add debug log entry (safe)
 */
const debugLog = (...args) => safeCall('addDebugLogEntry', ...args);

/**
 * Position camera based on layer metadata (bounds/center/zoom)
 * Enhanced with sophisticated zoom selection and bounds handling from base raster layer
 * @param {Object} viewer - Cesium viewer
 * @param {Object} layerInfo - Layer information
 * @param {Object} metadata - Layer metadata
 * @param {Object} options - Configuration options
 * @returns {Object} - { targetCenter, targetZoom, targetBounds }
 */
async function positionCameraForLayer(viewer, layerInfo, metadata, options = {}) {
  const {
    layerType = 'raster',
    fallbackZoom = CONFIG.DEFAULT_ZOOM_LEVEL || 15,
    checkAltitude = true,
    maxBoundsSize = 30,  // degrees - allows larger areas (world bounds still filtered)
    verifyHeight = false  // verify camera height after positioning
  } = options;
  
  const currentHeight = viewer.camera.positionCartographic.height;
  const isAtDefaultAltitude = currentHeight > 10000000; // > 10,000 km
  
  console.log(`Current camera height: ${(currentHeight/1000).toFixed(0)} km`);
  
  // Only reposition if at default altitude or if metadata has positioning info
  if (!checkAltitude || isAtDefaultAltitude || metadata.center || metadata.bounds) {
    let targetZoom = null;
    let targetCenter = null;
    let targetBounds = null;
    
    // ENHANCED: Calculate safe max zoom using LayerUtils
    const safeMaxZoom = metadata.maxzoom !== undefined 
      ? LayerUtils.calculateSafeMaxZoom(metadata.maxzoom)
      : CONFIG.MEMORY.MAX_ZOOM_CAPS.DEFAULT;
    
    console.log(`Safe max zoom calculated: ${safeMaxZoom} (native: ${metadata.maxzoom || 'N/A'})`);
    
    // Warning for layers with very high native maxzoom
    if (metadata.maxzoom && metadata.maxzoom > 20) {
      console.warn(`⚠️  Layer has very high maxzoom (${metadata.maxzoom}). Capped to ${safeMaxZoom} for memory safety.`);
      console.warn(`💡 This may affect detail at high zoom levels. Consider regenerating MBTiles with lower maxzoom.`);
      
      // Show message to user
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator(`⚠️  High zoom layer detected (Z${metadata.maxzoom}). Limited to Z${safeMaxZoom} for memory safety.`);
      }
    }
    
    // ENHANCED: Determine target zoom with priority chain
    // Priority: center[2] > defaultzoom > (safeMaxZoom - 2) > minzoom > fallback
    if (metadata.center && Array.isArray(metadata.center) && metadata.center.length >= 3) {
      targetZoom = Math.min(metadata.center[2], safeMaxZoom);
      targetCenter = [metadata.center[0], metadata.center[1]];
      console.log(`Using center from metadata: [${targetCenter[0]}, ${targetCenter[1]}] at zoom ${targetZoom}`);
    } else if (metadata.defaultzoom !== undefined && metadata.defaultzoom !== null) {
      // Cap defaultzoom at safeMaxZoom
      targetZoom = Math.min(metadata.defaultzoom, safeMaxZoom);
      console.log(`Using defaultzoom from metadata (capped): ${targetZoom}`);
    } else if (metadata.maxzoom !== undefined && metadata.maxzoom !== null) {
      // Use safeMaxZoom - 2 for initial positioning (more conservative)
      targetZoom = Math.max(safeMaxZoom - 2, metadata.minzoom || 0);
      console.log(`Using safe maxzoom - 2 for positioning: ${targetZoom}`);
    } else if (metadata.minzoom !== undefined && metadata.minzoom !== null) {
      targetZoom = metadata.minzoom + 2; // Start 2 levels above minzoom
      console.log(`Using minzoom + 2 from metadata: ${targetZoom}`);
    } else {
      targetZoom = Math.min(fallbackZoom, safeMaxZoom);
      console.log(`Using ${layerType} fallback zoom level (capped): ${targetZoom}`);
    }
    
    // Validate zoom is within layer's SAFE available range (use safeMaxZoom, not native maxZoom)
    const minZoom = metadata.minzoom || 0;
    targetZoom = CoordinateUtils.validateZoom(targetZoom, minZoom, safeMaxZoom);
    
    console.log(`Final target zoom for positioning: ${targetZoom} (range: ${minZoom}-${safeMaxZoom})`);
    
    // Determine center from metadata (if not already set from center[2])
    if (!targetCenter && metadata.center && Array.isArray(metadata.center) && metadata.center.length >= 2) {
      targetCenter = [metadata.center[0], metadata.center[1]];
    } else if (!targetCenter && metadata.bounds && Array.isArray(metadata.bounds) && metadata.bounds.length === 4) {
      targetBounds = metadata.bounds;
      targetCenter = [
        (metadata.bounds[0] + metadata.bounds[2]) / 2,
        (metadata.bounds[1] + metadata.bounds[3]) / 2
      ];
      console.log(`Calculated center from bounds: [${targetCenter[0]}, ${targetCenter[1]}]`);
    }
    
    // Set camera view with determined center and zoom
    if (targetCenter) {
      // Switch to 2D mode
      viewer.scene.mode = Cesium.SceneMode.SCENE2D;
      console.log(`Switched to 2D mode for ${layerType} layer`);
      
      // Calculate camera height for target zoom
      const height = CoordinateUtils.zoomToHeight(targetZoom);
      const destination = Cesium.Cartesian3.fromDegrees(targetCenter[0], targetCenter[1], height);
      
      const viewOptions = {
        maxHeight: CONFIG.MAX_2D_VIEW_HEIGHT
      };
      
      // ENHANCED: Check if bounds are world bounds and filter them out
      if (targetBounds) {
        const [west, south, east, north] = targetBounds;
        const boundsWidth = Math.abs(east - west);
        const boundsHeight = Math.abs(north - south);
        const maxDiff = Math.max(boundsWidth, boundsHeight);
        
        // Check if bounds are world bounds (within 0.01 degrees of full extent)
        const isWorldBounds = Math.abs(west - (-180)) < 0.01 && 
                             Math.abs(east - 180) < 0.01 &&
                             Math.abs(south - (-85.0511)) < 0.01 && 
                             Math.abs(north - 85.0511) < 0.01;
        
        // Only use bounds if they're reasonable size and not world bounds
        if (!isWorldBounds && maxDiff < maxBoundsSize) {
          viewOptions.bounds = targetBounds;
          viewOptions.duration = 1.5;
          console.log(`Setting view to bounds: [${west}, ${south}, ${east}, ${north}] at zoom ${targetZoom}`);
        } else {
          console.log(`Bounds too large (${maxDiff.toFixed(2)}°) or world bounds, using center point at zoom ${targetZoom}`);
        }
      }
      
      // Set camera view and wait for transition to complete
      console.log(`Positioning camera to center [${targetCenter[0]}, ${targetCenter[1]}] at zoom ${targetZoom}...`);
      await CameraUtils.setCameraView(viewer, destination, viewOptions);
      console.log(`✓ Camera view set and transition completed`);
      
      // ENHANCED: Verify camera height if requested
      if (verifyHeight) {
        const currentHeight = viewer.camera.positionCartographic.height;
        const expectedHeight = CoordinateUtils.zoomToHeight(targetZoom);
        const heightDiff = Math.abs(currentHeight - expectedHeight);
        
        if (heightDiff > expectedHeight * 0.1) {
          console.log(`Camera height adjustment needed (current: ${currentHeight.toFixed(0)}, expected: ${expectedHeight.toFixed(0)})`);
          await new Promise(resolve => setTimeout(resolve, 200));
          viewer.scene.requestRender();
        }
      }
      
      console.log(`✓ Camera positioned for ${layerType} layer. Zoom: ${targetZoom}, Height: ${viewer.camera.positionCartographic.height.toFixed(0)} m`);
      
      return { targetCenter, targetZoom, targetBounds };
    } else {
      // ENHANCED: Fallback when no center is available
      const height = CoordinateUtils.zoomToHeight(targetZoom);
      console.log(`Setting fallback camera view at zoom ${targetZoom}...`);
      await CameraUtils.setCameraView(viewer, Cesium.Cartesian3.fromDegrees(0, 0, height), {
        maxHeight: CONFIG.MAX_2D_VIEW_HEIGHT
      });
      console.log(`✓ Fallback camera view set and transition completed`);
      
      return { targetCenter: [0, 0], targetZoom, targetBounds: null };
    }
  }
  
  return { targetCenter: null, targetZoom: null, targetBounds: null };
}

/**
 * Get or create a shared data source for layer bounding boxes
 * @param {Object} viewer - Cesium viewer
 * @param {String} dataSourceName - Name for the data source
 * @param {String} stateKey - AppState key to store the data source
 * @returns {Object} - Cesium DataSource
 */
async function getOrCreateDataSource(viewer, dataSourceName, stateKey) {
  let dataSource = AppState[stateKey];
  if (!dataSource) {
    dataSource = new Cesium.CustomDataSource(dataSourceName);
    await viewer.dataSources.add(dataSource);
    AppState[stateKey] = dataSource;
    console.log(`Created data source: ${dataSourceName}`);
  }
  return dataSource;
}

/**
 * Remove entities from a data source by layer ID
 * @param {Object} dataSource - Cesium data source
 * @param {String} layerId - Layer identifier
 * @param {String} layerType - Type of layer (overlay, vector, etc.)
 */
function removeLayerEntities(dataSource, layerId, layerType) {
  if (!dataSource) return;
  
  const entityIds = [`${layerType}_bbox_${layerId}`, `${layerType}_center_${layerId}`];
  entityIds.forEach(id => {
    const entity = dataSource.entities.getById(id);
    if (entity) {
      dataSource.entities.remove(entity);
      console.log(`Removed entity: ${id}`);
    }
  });
}

/**
 * Create bounding box visualization for any layer type
 * @param {Object} viewer - Cesium viewer
 * @param {String} layerId - Layer identifier
 * @param {Object} layerInfo - Layer information
 * @param {Object} metadata - Layer metadata
 * @param {Object} options - Configuration options
 * @returns {Object} - { dataSource, entity, centerEntity }
 */
async function createBoundingBoxVisualization(viewer, layerId, layerInfo, metadata, options = {}) {
  const {
    layerType = 'raster',  // 'raster', 'overlay', 'vector'
    dataSourceName = `layer_bbox_${layerId}`,
    sharedDataSource = null,  // Use existing data source if provided
    color = Cesium.Color.CYAN,
    targetCenter = null,
    targetZoom = null
  } = options;
  
  console.log(`Creating bounding box visualization for ${layerType} layer...`);
  
  // Get or create data source
  let dataSource = sharedDataSource;
  if (!dataSource) {
    dataSource = new Cesium.CustomDataSource(dataSourceName);
    await viewer.dataSources.add(dataSource);
  }
  
  // Get bounds from metadata
  const bounds = metadata.bounds || layerInfo.bounds;
  if (!bounds || bounds.length !== 4) {
    throw new Error('No valid bounds found in metadata');
  }
  
  const [west, south, east, north] = bounds;
  console.log(`Drawing bounding box: W=${west}, S=${south}, E=${east}, N=${north}`);
  
  // Calculate bounds size
  const widthDeg = Math.abs(east - west);
  const heightDeg = Math.abs(north - south);
  const widthKm = widthDeg * 111.32; // Approximate km per degree at equator
  const heightKm = heightDeg * 111.32;
  
  console.log(`Bounds size: ${widthDeg.toFixed(6)}° × ${heightDeg.toFixed(6)}° (${widthKm.toFixed(2)} km × ${heightKm.toFixed(2)} km)`);
  
  // Calculate center
  const centerLon = targetCenter ? targetCenter[0] : (west + east) / 2;
  const centerLat = targetCenter ? targetCenter[1] : (south + north) / 2;
  
  // Create rectangle entity for the bounding box (border only, no fill)
  const entity = dataSource.entities.add({
    id: `${layerType}_bbox_${layerId}`,
    name: `${layerInfo.name} - ${layerType.charAt(0).toUpperCase() + layerType.slice(1)} Bounding Box`,
    rectangle: {
      coordinates: Cesium.Rectangle.fromDegrees(west, south, east, north),
      fill: false,
      outline: true,
      outlineColor: color,
      outlineWidth: 3,
      height: 0
    },
    description: `
      <h3>${layerInfo.name}</h3>
      <p><strong>Layer ID:</strong> ${layerId}</p>
      <p><strong>Type:</strong> ${layerType.charAt(0).toUpperCase() + layerType.slice(1)}</p>
      <p><strong>Bounds:</strong></p>
      <ul>
        <li>West: ${west.toFixed(6)}°</li>
        <li>South: ${south.toFixed(6)}°</li>
        <li>East: ${east.toFixed(6)}°</li>
        <li>North: ${north.toFixed(6)}°</li>
      </ul>
      <p><strong>Size:</strong> ${widthKm.toFixed(2)} km × ${heightKm.toFixed(2)} km</p>
      <p><strong>Center:</strong> ${centerLon.toFixed(6)}°, ${centerLat.toFixed(6)}°</p>
      <p><strong>Zoom Range:</strong> ${metadata.minzoom || 0} - ${metadata.maxzoom || 22}</p>
      ${targetZoom ? `<p><strong>Recommended Zoom:</strong> ${targetZoom}</p>` : ''}
    `
  });
  
  // Determine marker color based on layer type
  const markerColor = layerType === 'raster' ? Cesium.Color.RED :
                      layerType === 'overlay' ? Cesium.Color.MAGENTA :
                      Cesium.Color.YELLOW;
  
  // Add center point marker
  const centerEntity = dataSource.entities.add({
    id: `${layerType}_center_${layerId}`,
    name: `${layerInfo.name} - Center`,
    position: Cesium.Cartesian3.fromDegrees(centerLon, centerLat, 0),
    point: {
      pixelSize: 10,
      color: markerColor,
      outlineColor: layerType === 'vector' ? Cesium.Color.BLACK : Cesium.Color.WHITE,
      outlineWidth: 2
    },
    label: {
      text: layerInfo.name + (layerType === 'overlay' ? ' (Overlay)' : ''),
      font: '14pt sans-serif',
      fillColor: Cesium.Color.WHITE,
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 2,
      style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      pixelOffset: new Cesium.Cartesian2(0, -15)
    }
  });
  
  console.log(`✓ Bounding box created for ${layerInfo.name}`);
  
  return { dataSource, entity, centerEntity };
}

/**
 * Fetch layer metadata from individual JSON file
 */
async function fetchLayerMetadata(layerId) {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CONFIG.TIMEOUTS.METADATA_FETCH);
    
    const metadataUrl = `${CONFIG.SERVERS.MBTILES_SERVER}/data/${layerId}.json`;
    
    debugLog('info', `Fetching layer metadata: ${layerId}`, { url: metadataUrl });
    
    const response = await fetch(metadataUrl, {
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      console.warn(`Failed to fetch metadata for ${layerId}: ${response.status}`);
      return null;
    }
    const metadata = await response.json();
    
    // Normalize tile URLs - fix double protocols and localhost references
    if (metadata.tiles && Array.isArray(metadata.tiles)) {
      metadata.tiles = metadata.tiles
        .map(url => {
          // Replace localhost with actual server
          url = url.replace(/https?:\/\/localhost:\d+/, CONFIG.SERVERS.MBTILES_SERVER);
          
          // Fix double protocols (https://http:// or https://https://)
          url = url.replace(/^https?:\/\/(https?:\/\/)/, '$1');
          
          // Fix http://https:// or https://http:// patterns
          url = url.replace(/^https:\/\/(http:\/\/)/, 'http://');
          url = url.replace(/^http:\/\/(https:\/\/)/, 'https://');
          
          // Normalize multiple slashes before template variables
          url = url.replace(/\/+(\{[xyz]\})/g, '/$1');
          
          // Remove trailing slashes before template variables
          url = url.replace(/\/+$/, '');
          
          return url;
        })
        .filter(url => {
          try {
            // Validate URL by replacing template variables with test values
            const testUrl = url.replace(/\{[xyz]\}/g, '0');
            const urlObj = new URL(testUrl);
            return (urlObj.protocol === 'http:' || urlObj.protocol === 'https:') && 
                   !urlObj.hostname.includes('localhost') &&
                   !url.includes('://http://') &&
                   !url.includes('://https://');
          } catch {
            return false;
          }
        });
    }
    
    return metadata;
  } catch (error) {
    if (error.name === 'AbortError') {
      console.warn(`Metadata fetch timeout for ${layerId}`);
    } else {
      console.warn(`Error fetching metadata for ${layerId}:`, error);
    }
    return null;
  }
}

/**
 * Initialize available layers from tileserver
 */
export async function initializeAvailableLayers() {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    
    let response;
    try {
      response = await fetch(`${CONFIG.SERVERS.MBTILES_SERVER}/data.json`, {
        signal: controller.signal
      });
      clearTimeout(timeoutId);
    } catch (fetchError) {
      clearTimeout(timeoutId);
      if (fetchError.name === 'AbortError') {
        throw new Error('Tileserver request timeout - server may be unavailable');
      }
      throw fetchError;
    }
    
    if (!response.ok) {
      throw new Error(`Failed to fetch layers: ${response.status} ${response.statusText}`);
    }
    const data = await response.json();

    const rasterLayers = [];
    const vectorLayers = [];
    
    // Process all layers
    Object.entries(data).forEach(([key, info]) => {
      if (!info || typeof info !== 'object') return;
      
      const layerId = info.id || key;
      // Classify based on format first, then type
      // Vector layers have format 'pbf', raster layers have format 'png' or 'jpg'
      const isVector = info.format === 'pbf' || (info.format !== 'png' && info.format !== 'jpg' && info.type === 'vector');
      const layerType = isVector ? 'vector' : 'raster';
      
      const layerInfo = {
        id: layerId,
        name: info.name || layerId,
        format: info.format || (isVector ? 'pbf' : 'png'),
        minzoom: info.minzoom || 0,
        maxzoom: info.maxzoom || 22,
        defaultzoom: info.defaultzoom || info.maxzoom || CONFIG.DEFAULT_ZOOM_LEVEL || 15,
        bounds: info.bounds,
        center: info.center,
        type: layerType
      };

      AppState.availableLayers[layerId] = layerInfo;
      
      if (key !== layerId) {
        AppState.availableLayers[key] = layerInfo;
      }

      if (layerInfo.type === 'vector') {
        vectorLayers.push(layerInfo);
      } else {
        rasterLayers.push(layerInfo);
      }
    });

    // Note: Base raster layer dropdown has been removed to avoid duplication
    // All raster layers are now available only as overlays
    // Users can use standard Cesium basemaps (Ion, Bing, etc.) as the base layer
    
    // Populate overlay layers checkboxes (formerly duplicated in base layer dropdown)
    const overlayList = document.getElementById('overlayLayersList');
    if (overlayList) {
      overlayList.innerHTML = '';
      
      if (rasterLayers.length === 0) {
        overlayList.innerHTML = '<small class="text-muted">No overlay layers available</small>';
      } else {
        rasterLayers.forEach(layer => {
          const checkDiv = document.createElement('div');
          checkDiv.className = 'mb-2';
          checkDiv.innerHTML = `
            <div class="form-check">
              <input class="form-check-input overlay-layer-toggle" 
                     type="checkbox" 
                     id="overlay_${layer.id}" 
                     data-layer-id="${layer.id}">
              <label class="form-check-label d-flex align-items-center justify-content-between" 
                     for="overlay_${layer.id}" 
                     style="font-size: 0.9em; width: 100%;">
                <span><i class="fas fa-map me-1"></i>${layer.name}</span>
              </label>
            </div>
            <div class="opacity-slider ms-4 mt-1" id="opacity_container_${layer.id}" style="display: none;">
              <input type="range" 
                     class="form-range" 
                     id="opacity_${layer.id}" 
                     data-layer-id="${layer.id}" 
                     min="0" 
                     max="100" 
                     value="70" 
                     style="height: 4px;">
              <small class="text-muted">Opacity: <span id="opacity_value_${layer.id}">70%</span></small>
            </div>
          `;
          overlayList.appendChild(checkDiv);
        });

        // Add event listeners to overlay toggles
        document.querySelectorAll('.overlay-layer-toggle').forEach(checkbox => {
          checkbox.addEventListener('change', (e) => {
            const layerId = e.target.dataset.layerId;
            const opacityContainer = document.getElementById(`opacity_container_${layerId}`);
            
            if (e.target.checked) {
              opacityContainer.style.display = 'block';
            } else {
              opacityContainer.style.display = 'none';
            }
            
            toggleOverlayLayer(AppState.viewer, layerId, e.target.checked).catch(error => {
              console.error('Error toggling overlay layer:', error);
            });
          });
        });

        // Add event listeners to opacity sliders
        document.querySelectorAll('.opacity-slider input[type="range"]').forEach(slider => {
          slider.addEventListener('input', (e) => {
            const layerId = e.target.dataset.layerId;
            const value = e.target.value;
            
            document.getElementById(`opacity_value_${layerId}`).textContent = `${value}%`;
            
            const layer = AppState.currentLayers.overlays[layerId];
            if (layer) {
              layer.alpha = value / 100;
            }
          });
        });
      }
    }

    // Populate vector layers checkboxes
    const vectorList = document.getElementById('vectorLayersList');
    if (vectorList && CONFIG.VECTOR_TILES.ENABLED) {
      vectorList.innerHTML = '';
      
      if (vectorLayers.length === 0) {
        vectorList.innerHTML = '<small class="text-muted">No vector layers available</small>';
      } else {
        vectorLayers.forEach(layer => {
          const checkDiv = document.createElement('div');
          checkDiv.className = 'mb-2';
          checkDiv.innerHTML = `
            <div class="form-check">
              <input class="form-check-input vector-layer-toggle" 
                     type="checkbox" 
                     id="vector_${layer.id}" 
                     data-layer-id="${layer.id}">
              <label class="form-check-label d-flex align-items-center justify-content-between" 
                     for="vector_${layer.id}" 
                     style="font-size: 0.9em; width: 100%;">
                <span><i class="fas fa-vector-square me-1"></i>${layer.name}</span>
              </label>
            </div>
            <div class="opacity-slider ms-4 mt-1" id="vector_opacity_container_${layer.id}" style="display: none;">
              <input type="range" 
                     class="form-range" 
                     id="vector_opacity_${layer.id}" 
                     data-layer-id="${layer.id}" 
                     min="0" 
                     max="100" 
                     value="60" 
                     style="height: 4px;">
              <small class="text-muted">Opacity: <span id="vector_opacity_value_${layer.id}">60%</span></small>
            </div>
          `;
          vectorList.appendChild(checkDiv);
        });

        // Add event listeners to vector layer toggles
        document.querySelectorAll('.vector-layer-toggle').forEach(checkbox => {
          checkbox.addEventListener('change', (e) => {
            const layerId = e.target.dataset.layerId;
            const opacityContainer = document.getElementById(`vector_opacity_container_${layerId}`);
            
            if (e.target.checked) {
              opacityContainer.style.display = 'block';
            } else {
              opacityContainer.style.display = 'none';
            }
            
            toggleVectorLayer(AppState.viewer, layerId, e.target.checked).catch(error => {
              console.error('Error toggling vector layer:', error);
            });
          });
        });

        // Add event listeners to vector opacity sliders
        document.querySelectorAll('.vector-layer-toggle').forEach(checkbox => {
          const layerId = checkbox.dataset.layerId;
          const slider = document.getElementById(`vector_opacity_${layerId}`);
          
          if (slider) {
            slider.addEventListener('input', (e) => {
              const value = e.target.value;
              document.getElementById(`vector_opacity_value_${layerId}`).textContent = `${value}%`;
              
              if (AppState.vectorRenderer) {
                AppState.vectorRenderer.setLayerOpacity(layerId, value / 100);
              }
            });
          }
        });
      }
    }

    console.log(`Loaded ${rasterLayers.length} raster layers and ${vectorLayers.length} vector layers`);
    
    debugLog('info', `Initialized ${rasterLayers.length} raster and ${vectorLayers.length} vector layers`, {
      rasterLayers: rasterLayers.map(l => l.id),
      vectorLayers: vectorLayers.map(l => l.id)
    });

    // Don't auto-load any layers - let user select manually
    console.log('Layer list populated. User can now select layers manually.');
    updateStatus(`Ready - ${rasterLayers.length + vectorLayers.length} layers available`);

  } catch (error) {
    console.warn('Error loading available layers:', error);
    const overlayList = document.getElementById('overlayLayersList');
    if (overlayList) {
      overlayList.innerHTML = '<small class="text-danger">Error loading layers</small>';
    }
    
    // Ensure default imagery is still visible
    if (AppState.viewer && AppState.viewer.imageryLayers.length === 0) {
      console.warn('No imagery layers available, attempting to add Ion imagery fallback');
      try {
        const fallbackProvider = await Cesium.IonImageryProvider.fromAssetId(2);
        AppState.viewer.imageryLayers.addImageryProvider(fallbackProvider);
      } catch (error) {
        console.warn('Could not add fallback imagery provider:', error);
      }
    }
  }
}

/**
 * Load base raster layer
 * Improved implementation that:
 * 1. Fetches metadata FIRST from TileServer GL
 * 2. Sets map center and zoom from metadata BEFORE loading tiles
 * 3. Only loads tiles for the appropriate zoom level
 */
export async function loadBaseRasterLayer(viewer, layerId) {
  let layerInfo = null;
  
  if (!viewer) {
    console.warn('Cannot load base raster layer: viewer not available');
    return;
  }
  
  if (!viewer.scene || !viewer.imageryLayers) {
    console.warn('Cannot load base raster layer: viewer not fully initialized');
    return;
  }
  
  try {
    if (layerId) {
      layerInfo = AppState.availableLayers[layerId];
      if (!layerInfo) {
        console.warn(`Layer info not found for: ${layerId}`);
        updateStatus(`Layer not found: ${layerId}`);
        return;
      }
    }

    // Remove existing base raster (both tiles and bounding box)
    if (AppState.currentLayers.baseRaster) {
      const existingLayer = AppState.currentLayers.baseRaster;
      
      try {
        // Remove actual imagery layer if it exists
        if (existingLayer.imageryLayer) {
          viewer.imageryLayers.remove(existingLayer.imageryLayer);
          LayerUtils.disposeLayer(existingLayer.imageryLayer);
          console.log('✓ Removed base raster imagery layer');
        }

        // Remove bounding box if it exists
        if (existingLayer.boundingBoxDataSource) {
          viewer.dataSources.remove(existingLayer.boundingBoxDataSource);
          console.log('✓ Removed base raster bounding box');
        }
        
        // Legacy support: remove old-style data source
        if (existingLayer.dataSource) {
          viewer.dataSources.remove(existingLayer.dataSource);
          console.log('✓ Removed legacy data source');
        }
      } catch (error) {
        console.warn('Error removing existing base raster:', error);
      }
      
      AppState.currentLayers.baseRaster = null;
    }

    if (!layerId) {
      updateStatus('Base raster layer removed');
      return;
    }

    updateStatus(`Loading metadata for ${layerInfo.name}...`);
    const loadStartTime = performance.now();
    
    // STEP 1: Fetch metadata from TileServer GL FIRST
    // This is critical - we need metadata to determine center, zoom, and available zoom levels
    console.log(`Fetching metadata for layer: ${layerId}`);
    const metadata = await fetchLayerMetadata(layerId);
    
    // Validate metadata was loaded successfully
    if (!metadata) {
      throw new Error(`Failed to fetch metadata for layer: ${layerId}`);
    }
    
    // Validate essential metadata fields exist
    if (!metadata.tiles || metadata.tiles.length === 0) {
      throw new Error(`No tile URLs found in metadata for layer: ${layerId}`);
    }
    
    // Ensure metadata is complete before proceeding
    console.log('✓ Metadata loaded and validated');
    
    // STEP 2: Merge metadata into layerInfo to get complete layer information
    LayerUtils.mergeMetadata(layerInfo, metadata);
    
    // Log metadata information
    console.log('Layer metadata loaded:', {
      name: layerInfo.name,
      bounds: metadata.bounds,
      center: metadata.center,
      minzoom: metadata.minzoom,
      maxzoom: metadata.maxzoom,
      tileUrls: metadata.tiles.length
    });
    
    logLayerOp('Loading Base Raster', layerId, layerInfo, {
      maxzoom: metadata.maxzoom,
      minzoom: metadata.minzoom,
      bounds: metadata.bounds,
      center: metadata.center,
      hasMetadata: true
    });

    // STEP 3 & 4: Position camera using shared function with height verification
    const { targetCenter, targetZoom, targetBounds } = await positionCameraForLayer(viewer, layerInfo, metadata, {
      layerType: 'raster',
      checkAltitude: false,  // Always reposition for base raster layer
      verifyHeight: true     // Verify camera height for base layer
    });
    
    // Update status to indicate metadata and camera positioning are complete
    updateStatus(`Positioning complete. Loading tiles for ${layerInfo.name}...`);

    // STEP 5: Load actual raster tiles as imagery layer
    const tileUrl = metadata.tiles[0]; // Use normalized tile URL from metadata
    console.log(`Creating base raster imagery provider with URL: ${tileUrl}`);
    
    // Determine safe max zoom for this layer
    const safeMaxZoom = LayerUtils.calculateSafeMaxZoom(metadata.maxzoom || layerInfo.maxzoom || 22);
    
    // Create imagery provider for the base raster layer
    const imageryProvider = LayerUtils.createImageryProvider(tileUrl, layerInfo, safeMaxZoom, {
      minzoom: metadata.minzoom,
      maxzoom: metadata.maxzoom
    });
    
    // Add base raster as imagery layer
    const imageryLayer = viewer.imageryLayers.addImageryProvider(imageryProvider);
    imageryLayer.alpha = 1.0; // Fully opaque for base raster layer
    
    console.log(`✓ Base raster imagery layer added: ${layerInfo.name}`);

    // OPTION 2: Optionally create bounding box visualization (for debugging)
    let boundingBoxData = null;
    if (CONFIG.RASTER.SHOW_BOUNDING_BOX === true) {
      try {
        const bboxDataSource = new Cesium.CustomDataSource(`raster_bbox_${layerId}`);
        await viewer.dataSources.add(bboxDataSource);
        
        boundingBoxData = await createBoundingBoxVisualization(
          viewer, layerId, layerInfo, metadata,
          {
            layerType: 'raster',
            sharedDataSource: bboxDataSource,
            color: Cesium.Color.CYAN,
            targetCenter: targetCenter,
            targetZoom: targetZoom
          }
        );
        console.log(`✓ Bounding box created for base raster ${layerInfo.name}`);
      } catch (bboxError) {
        console.warn('Failed to create bounding box (non-critical):', bboxError);
        // Continue without bounding box
      }
    }
    
    // Store both the imagery layer and optional bounding box
    AppState.currentLayers.baseRaster = {
      imageryLayer: imageryLayer,          // Actual raster tiles
      boundingBoxDataSource: boundingBoxData?.dataSource,
      boundingBoxEntity: boundingBoxData?.entity,
      layerId: layerId,
      info: layerInfo
    };
    
    updateStatus(`Loaded: ${layerInfo.name} (zoom: ${targetZoom})`);

    const loadTime = performance.now() - loadStartTime;
    AppState.performanceMetrics.layerLoadTimes.push({
      layerId: layerId,
      layerName: layerInfo.name,
      loadTime: loadTime,
      timestamp: new Date().toISOString()
    });
    
    logLayerOp('Loaded Base Raster', layerId, layerInfo, {
      loadTime: `${loadTime.toFixed(2)}ms`,
      targetZoom: targetZoom,
      safeMaxZoom: safeMaxZoom,
      bounds: metadata.bounds || layerInfo.bounds,
      tileUrl: tileUrl,
      usedMetadata: true
    });
    
    console.log(`✓ Layer ${layerInfo.name} loaded successfully in ${loadTime.toFixed(2)}ms`);
    
  } catch (error) {
    console.error(`Error loading base raster layer ${layerId}:`, error);
    
    // Cleanup: Remove any partially added imagery layer
    if (AppState.currentLayers.baseRaster?.imageryLayer) {
      try {
        viewer.imageryLayers.remove(AppState.currentLayers.baseRaster.imageryLayer);
        LayerUtils.disposeLayer(AppState.currentLayers.baseRaster.imageryLayer);
        console.log('Cleaned up partially loaded base raster layer');
      } catch (cleanupError) {
        console.warn('Error during cleanup:', cleanupError);
      }
      AppState.currentLayers.baseRaster = null;
    }
    
    ErrorHandler.handleLayerError(error, layerId, layerInfo, viewer, 'loadBaseRasterLayer');
  }
}

/**
 * Toggle overlay layer - loads actual raster tiles as imagery layer
 */
export async function toggleOverlayLayer(viewer, layerId, enabled) {
  if (!viewer || !layerId) return;

  if (enabled) {
    const currentOverlayCount = Object.keys(AppState.currentLayers.overlays).length;
    
    if (currentOverlayCount >= CONFIG.MAX_OVERLAY_LAYERS) {
      const warning = `Maximum ${CONFIG.MAX_OVERLAY_LAYERS} overlay layers allowed. Please remove one first.`;
      console.warn(warning);
      updateStatus(warning);
      uncheckBox(`overlay_${layerId}`);
      return;
    }

    if (!AppState.currentLayers.overlays[layerId]) {
      const layerInfo = AppState.availableLayers[layerId];
      if (!layerInfo) return;

      try {
        logLayerOp('Loading Overlay', layerId, layerInfo);
        
        const metadata = await fetchLayerMetadata(layerId);
        
        // Validate metadata
        if (!metadata || !metadata.tiles || metadata.tiles.length === 0) {
          throw new Error(`No tile URLs found in metadata for overlay: ${layerId}`);
        }
        
        LayerUtils.mergeMetadata(layerInfo, metadata);

        // Position camera using shared function
        await positionCameraForLayer(viewer, layerInfo, metadata, {
          layerType: 'overlay'
        });

        updateStatus(`Camera positioned. Loading overlay tiles for ${layerInfo.name}...`);

        // OPTION 1: Load actual raster tiles as imagery layer
        const tileUrl = metadata.tiles[0]; // Use normalized tile URL from metadata
        console.log(`Creating overlay imagery provider with URL: ${tileUrl}`);
        
        // Determine safe max zoom for this overlay
        const safeMaxZoom = LayerUtils.calculateSafeMaxZoom(metadata.maxzoom || layerInfo.maxzoom || 22);
        
        // Create imagery provider for the overlay
        const imageryProvider = LayerUtils.createImageryProvider(tileUrl, layerInfo, safeMaxZoom, {
          minzoom: metadata.minzoom,
          maxzoom: metadata.maxzoom
        });
        
        // Add overlay as imagery layer on top of base map
        const imageryLayer = viewer.imageryLayers.addImageryProvider(imageryProvider);
        imageryLayer.alpha = 0.7; // Semi-transparent to see base map underneath
        
        console.log(`✓ Overlay imagery layer added: ${layerInfo.name}`);

        // OPTION 2: Optionally create bounding box visualization (for debugging)
        let boundingBoxData = null;
        if (CONFIG.RASTER.SHOW_BOUNDING_BOX === true) {
          try {
            const bboxDataSource = await getOrCreateDataSource(viewer, 'overlay_bounding_boxes', 'overlayBoundingBoxDataSource');
            
            boundingBoxData = await createBoundingBoxVisualization(
              viewer, layerId, layerInfo, metadata,
              {
                layerType: 'overlay',
                sharedDataSource: bboxDataSource,
                color: Cesium.Color.MAGENTA
              }
            );
            console.log(`✓ Bounding box created for overlay ${layerInfo.name}`);
          } catch (bboxError) {
            console.warn('Failed to create overlay bounding box (non-critical):', bboxError);
            // Continue without bounding box
          }
        }
        
        // Store both the imagery layer and optional bounding box
        AppState.currentLayers.overlays[layerId] = {
          imageryLayer: imageryLayer,          // Actual raster tiles
          boundingBoxDataSource: boundingBoxData?.dataSource,
          boundingBoxEntity: boundingBoxData?.entity,
          layerId: layerId,
          layerInfo: layerInfo
        };
        
        console.log(`✓ Added overlay layer: ${layerInfo.name}`);
        updateStatus(`Added overlay: ${layerInfo.name}`);
        logLayerOp('Added Overlay', layerId, layerInfo, {
          bounds: metadata.bounds || layerInfo.bounds,
          zoom: safeMaxZoom,
          alpha: 0.7
        });
      } catch (error) {
        // Cleanup: Remove any partially added overlay imagery layer
        if (AppState.currentLayers.overlays[layerId]?.imageryLayer) {
          try {
            viewer.imageryLayers.remove(AppState.currentLayers.overlays[layerId].imageryLayer);
            LayerUtils.disposeLayer(AppState.currentLayers.overlays[layerId].imageryLayer);
            console.log('Cleaned up partially loaded overlay layer');
          } catch (cleanupError) {
            console.warn('Error during overlay cleanup:', cleanupError);
          }
          delete AppState.currentLayers.overlays[layerId];
        }
        
        ErrorHandler.handleLayerError(error, layerId, layerInfo, viewer, 'loadOverlayLayer');
        uncheckBox(`overlay_${layerId}`);
      }
    }
  } else {
    // Remove overlay layer (both tiles and bounding box)
    if (AppState.currentLayers.overlays[layerId]) {
      const layerData = AppState.currentLayers.overlays[layerId];
      
      try {
        // Remove actual imagery layer if it exists
        if (layerData.imageryLayer) {
          viewer.imageryLayers.remove(layerData.imageryLayer);
          LayerUtils.disposeLayer(layerData.imageryLayer);
          console.log(`✓ Removed overlay imagery layer for ${layerId}`);
        }

        // Remove bounding box entities if they exist
        if (layerData.boundingBoxDataSource) {
          removeLayerEntities(layerData.boundingBoxDataSource, layerId, 'overlay');
          console.log(`✓ Removed bounding box for ${layerId}`);
        }
        
        delete AppState.currentLayers.overlays[layerId];
        
        const layerInfo = AppState.availableLayers[layerId];
        console.log(`✓ Removed overlay layer: ${layerInfo?.name || layerId}`);
        updateStatus(`Removed overlay: ${layerInfo?.name || layerId}`);
        logLayerOp('Removed Overlay', layerId, layerInfo);
      } catch (error) {
        console.error(`Error removing overlay layer ${layerId}:`, error);
      }
    }
  }
}

/**
 * Toggle vector layer
 */
export async function toggleVectorLayer(viewer, layerId, enabled) {
  if (!viewer || !layerId) return;

  if (!CONFIG.VECTOR_TILES.ENABLED) {
    console.warn('Vector tiles are disabled in configuration');
    return;
  }

  // Initialize vector renderer if not already done
  if (!AppState.vectorRenderer) {
    AppState.vectorRenderer = new VectorLayerRenderer(viewer);
    console.log('Initialized vector layer renderer');
  }

  if (enabled) {
    const layerInfo = AppState.availableLayers[layerId];
    if (!layerInfo) {
      console.warn(`Layer info not found for: ${layerId}`);
      return;
    }

    try {
      updateStatus(`Loading vector layer: ${layerInfo.name}...`);
      logLayerOp('Loading Vector Layer', layerId, layerInfo);

      // Fetch metadata
      const metadata = await fetchLayerMetadata(layerId);
      layerInfo.metadata = metadata;
      
      // Merge metadata into layerInfo
      LayerUtils.mergeMetadata(layerInfo, metadata);

      // Position camera using shared function
      // NOTE: Using same fallback zoom as raster layers for consistency
      await positionCameraForLayer(viewer, layerInfo, metadata, {
        layerType: 'vector',
        fallbackZoom: CONFIG.DEFAULT_ZOOM_LEVEL || 15
      });

      updateStatus(`Camera positioned. Loading tiles for ${layerInfo.name}...`);

      // OPTION 1: Load actual vector tiles using the renderer
      console.log(`Starting vector tile loading for ${layerId}...`);
      const vectorDataSource = await AppState.vectorRenderer.loadVectorLayer(layerId, layerInfo);
      console.log(`✓ Vector tiles loaded for ${layerInfo.name}`);

      // OPTION 2: Also create bounding box visualization (optional, for debugging)
      let boundingBoxData = null;
      if (CONFIG.VECTOR_TILES.SHOW_BOUNDING_BOX !== false) {
        const bboxDataSource = await getOrCreateDataSource(viewer, 'vector_bounding_boxes', 'vectorBoundingBoxDataSource');
        
        boundingBoxData = await createBoundingBoxVisualization(
          viewer, layerId, layerInfo, metadata,
          {
            layerType: 'vector',
            sharedDataSource: bboxDataSource,
            color: Cesium.Color.LIME
          }
        );
        console.log(`✓ Bounding box created for ${layerInfo.name}`);
      }

      // Store both the vector data source and bounding box info
      AppState.currentLayers.vectors[layerId] = {
        vectorDataSource: vectorDataSource,  // Actual vector tile data
        boundingBoxDataSource: boundingBoxData?.dataSource,
        boundingBoxEntity: boundingBoxData?.entity,
        layerId: layerId,
        layerInfo: layerInfo
      };

      console.log(`Loaded vector layer: ${layerInfo.name}`);
      updateStatus(`Loaded vector layer: ${layerInfo.name}`);
      logLayerOp('Loaded Vector Layer', layerId, layerInfo);
    } catch (error) {
      console.error(`Error loading vector layer ${layerId}:`, error);
      updateStatus(`Error loading vector layer: ${layerInfo.name}`);
      uncheckBox(`vector_${layerId}`);
    }
  } else {
    // Remove vector layer (both tiles and bounding box)
    const layerData = AppState.currentLayers.vectors[layerId];
    if (layerData) {
      try {
        // Remove actual vector tile data source
        if (layerData.vectorDataSource) {
          viewer.dataSources.remove(layerData.vectorDataSource);
          console.log(`✓ Removed vector data source for ${layerId}`);
        }

        // Remove from renderer tracking
        if (AppState.vectorRenderer && AppState.vectorRenderer.dataSourcesByLayer) {
          AppState.vectorRenderer.dataSourcesByLayer.delete(layerId);
          console.log(`✓ Removed from renderer tracking: ${layerId}`);
        }

        // Remove bounding box entities if they exist
        if (layerData.boundingBoxDataSource) {
          removeLayerEntities(layerData.boundingBoxDataSource, layerId, 'vector');
          console.log(`✓ Removed bounding box for ${layerId}`);
        }
        
        delete AppState.currentLayers.vectors[layerId];

        const layerInfo = AppState.availableLayers[layerId];
        console.log(`Removed vector layer: ${layerInfo?.name || layerId}`);
        updateStatus(`Removed vector layer: ${layerInfo?.name || layerId}`);
        logLayerOp('Removed Vector Layer', layerId, layerInfo);
      } catch (error) {
        console.error(`Error removing vector layer ${layerId}:`, error);
      }
    }
  }
}

export default {
  initializeAvailableLayers,
  loadBaseRasterLayer,
  toggleOverlayLayer,
  toggleVectorLayer,
  fetchLayerMetadata
};

