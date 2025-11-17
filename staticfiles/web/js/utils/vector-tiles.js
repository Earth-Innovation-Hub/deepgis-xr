/**
 * Vector Tile Utilities
 * Handles loading and rendering of Mapbox Vector Tiles (MVT/PBF) in Cesium
 */
import { CONFIG } from '../config.js';
import { AppState } from '../state.js';

/**
 * Parse vector tile PBF data
 * Uses minimal inline PBF parsing to avoid external dependencies
 */
class VectorTileParser {
  constructor() {
    this.cache = new Map();
  }

  /**
   * Fetch and parse a vector tile
   * @param {string} url - Tile URL
   * @returns {Promise<Object>} Parsed tile data
   */
  async fetchAndParseTile(url) {
    if (this.cache.has(url)) {
      return this.cache.get(url);
    }

    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Failed to fetch tile: ${response.status}`);
      }

      const arrayBuffer = await response.arrayBuffer();
      const features = await this.parseVectorTile(arrayBuffer);
      
      this.cache.set(url, features);
      return features;
    } catch (error) {
      console.warn(`Error fetching vector tile from ${url}:`, error);
      return null;
    }
  }

  /**
   * Parse vector tile from ArrayBuffer
   * For production use, consider using @mapbox/vector-tile library
   * This is a simplified parser for demonstration
   */
  async parseVectorTile(arrayBuffer) {
    // For now, return a placeholder structure
    // In production, you would use proper MVT parsing with libraries like:
    // - @mapbox/vector-tile + pbf
    // - geobuf
    console.log('Vector tile received, size:', arrayBuffer.byteLength, 'bytes');
    
    return {
      features: [],
      layers: {},
      parsed: false,
      rawData: arrayBuffer
    };
  }

  clearCache() {
    this.cache.clear();
  }
}

/**
 * Vector Layer Renderer for Cesium
 * Converts vector tile features to Cesium entities
 */
export class VectorLayerRenderer {
  constructor(viewer) {
    this.viewer = viewer;
    this.parser = new VectorTileParser();
    this.dataSourcesByLayer = new Map();
    this.activeTiles = new Map();
    this.maxCachedTiles = CONFIG.VECTOR_TILES.MAX_CACHED_TILES || 100;
  }

  /**
   * Load vector layer with progressive tile loading
   * 
   * URL Flow (consistent with bounding box):
   * 1. layerInfo.metadata comes from fetchLayerMetadata() in layer-management.js
   * 2. fetchLayerMetadata() normalizes metadata.tiles URLs (removes double protocols, localhost, etc.)
   * 3. getTileUrlTemplate() uses the normalized metadata.tiles[0] URL
   * 4. loadTiles() replaces {z}/{x}/{y} placeholders with actual tile coordinates
   * 
   * @param {string} layerId - Layer identifier
   * @param {Object} layerInfo - Layer metadata (must have layerInfo.metadata.tiles)
   */
  async loadVectorLayer(layerId, layerInfo) {
    try {
      console.log(`[loadVectorLayer] Loading vector layer: ${layerInfo.name} (${layerId})`);
      console.log(`[loadVectorLayer] Layer info has metadata: ${!!layerInfo.metadata}`);

      // Create a data source for this layer
      const dataSource = new Cesium.CustomDataSource(layerId);
      await this.viewer.dataSources.add(dataSource);
      this.dataSourcesByLayer.set(layerId, dataSource);

      // Store layer info for updates
      dataSource._layerInfo = layerInfo;
      dataSource._layerId = layerId;

      // Get visible tile coordinates based on current view
      const visibleTiles = this.getVisibleTiles(layerInfo);
      
      console.log(`[loadVectorLayer] Loading ${visibleTiles.length} visible vector tiles for layer ${layerId}`);

      // Load tiles progressively
      await this.loadTiles(layerId, layerInfo, visibleTiles, dataSource);

      // Add camera change listener for dynamic tile loading
      this.setupCameraListener(layerId);

      console.log(`[loadVectorLayer] ✓ Vector layer loaded successfully: ${layerId}`);
      return dataSource;
    } catch (error) {
      console.error(`[loadVectorLayer] ✗ Error loading vector layer ${layerId}:`, error);
      throw error;
    }
  }

  /**
   * Setup camera change listener for dynamic tile loading
   */
  setupCameraListener(layerId) {
    if (this.cameraListener) return; // Only one listener needed for all layers

    let updateTimeout = null;
    const updateDelay = 500; // ms

    this.cameraListener = this.viewer.camera.changed.addEventListener(() => {
      // Debounce camera updates
      if (updateTimeout) {
        clearTimeout(updateTimeout);
      }

      updateTimeout = setTimeout(() => {
        this.updateVisibleTiles();
      }, updateDelay);
    });
  }

  /**
   * Update visible tiles for all active layers
   */
  async updateVisibleTiles() {
    for (const [layerId, dataSource] of this.dataSourcesByLayer.entries()) {
      if (!dataSource._layerInfo) continue;

      const visibleTiles = this.getVisibleTiles(dataSource._layerInfo);
      const existingTileKeys = new Set(
        Array.from(this.activeTiles.keys())
          .filter(key => key.startsWith(`${layerId}/`))
      );

      // Only load new tiles that aren't already loaded
      const newTiles = visibleTiles.filter(tile => {
        const key = `${layerId}/${tile.z}/${tile.x}/${tile.y}`;
        return !existingTileKeys.has(key);
      });

      if (newTiles.length > 0) {
        console.log(`Loading ${newTiles.length} additional tiles for ${layerId}`);
        await this.loadTiles(layerId, dataSource._layerInfo, newTiles, dataSource);
      }
    }
  }

  /**
   * Get visible tile coordinates for current view
   */
  getVisibleTiles(layerInfo) {
    const tiles = [];
    const camera = this.viewer.camera;
    const scene = this.viewer.scene;
    
    console.log(`[getVisibleTiles] Starting for layer:`, layerInfo.name);
    
    // Try primary method: computeViewRectangle
    let rectangle = null;
    let rectMethod = 'unknown';
    
    try {
      rectangle = camera.computeViewRectangle(scene.globe.ellipsoid);
      if (rectangle) {
        rectMethod = 'computeViewRectangle';
        console.log(`[getVisibleTiles] ✓ Primary method succeeded`);
      }
    } catch (e) {
      console.warn('[getVisibleTiles] Primary method failed:', e.message);
    }

    // Fallback 1: Calculate view bounds from canvas corners
    if (!rectangle) {
      console.log('[getVisibleTiles] Trying canvas corner fallback...');
      rectangle = this.computeViewRectangleFallback();
      if (rectangle) {
        rectMethod = 'canvasCornerSampling';
        console.log(`[getVisibleTiles] ✓ Canvas corner fallback succeeded`);
      } else {
        console.warn('[getVisibleTiles] Canvas corner fallback failed');
      }
    }

    // Fallback 2: Use layer bounds
    if (!rectangle && layerInfo.bounds) {
      console.log('[getVisibleTiles] Trying layer bounds fallback...');
      const [west, south, east, north] = layerInfo.bounds;
      rectangle = Cesium.Rectangle.fromDegrees(west, south, east, north);
      rectMethod = 'layerBounds';
      console.log(`[getVisibleTiles] ✓ Layer bounds fallback: [${west}, ${south}, ${east}, ${north}]`);
    }

    // Fallback 3: Use camera position
    if (!rectangle) {
      console.log('[getVisibleTiles] Trying camera position fallback...');
      const cameraPos = camera.positionCartographic;
      if (cameraPos) {
        const lon = Cesium.Math.toDegrees(cameraPos.longitude);
        const lat = Cesium.Math.toDegrees(cameraPos.latitude);
        const offset = 1.0; // Increased to ~111km for better coverage
        rectangle = Cesium.Rectangle.fromDegrees(
          lon - offset, lat - offset,
          lon + offset, lat + offset
        );
        rectMethod = 'cameraPosition';
        console.log(`[getVisibleTiles] ✓ Camera position fallback: [${lon.toFixed(4)}, ${lat.toFixed(4)}]`);
      } else {
        console.error('[getVisibleTiles] ✗ All methods failed - no camera position');
        return tiles;
      }
    }

    if (!rectangle) {
      console.error('[getVisibleTiles] ✗ All fallback methods failed');
      return tiles;
    }

    const west = Cesium.Math.toDegrees(rectangle.west);
    const south = Cesium.Math.toDegrees(rectangle.south);
    const east = Cesium.Math.toDegrees(rectangle.east);
    const north = Cesium.Math.toDegrees(rectangle.north);

    // Determine appropriate zoom level based on camera height
    const height = camera.positionCartographic ? camera.positionCartographic.height : 10000000;
    const zoom = this.calculateZoomLevel(height, layerInfo);

    console.log(`[getVisibleTiles] Method: ${rectMethod}`);
    console.log(`[getVisibleTiles] Bounds: W=${west.toFixed(4)}, S=${south.toFixed(4)}, E=${east.toFixed(4)}, N=${north.toFixed(4)}`);
    console.log(`[getVisibleTiles] Height: ${(height/1000).toFixed(1)}km, Zoom: ${zoom}, Range: ${layerInfo.minzoom}-${layerInfo.maxzoom}`);

    // Calculate tile coordinates covering the view
    const minTile = this.lonLatToTile(west, north, zoom);
    const maxTile = this.lonLatToTile(east, south, zoom);

    console.log(`[getVisibleTiles] Tile range: (${minTile.x},${minTile.y}) to (${maxTile.x},${maxTile.y})`);

    // Limit number of tiles to prevent overload
    const maxTilesPerDimension = CONFIG.VECTOR_TILES.MAX_TILES_PER_DIMENSION || 4;
    const tileCountX = Math.min(Math.max(maxTile.x - minTile.x + 1, 1), maxTilesPerDimension);
    const tileCountY = Math.min(Math.max(maxTile.y - minTile.y + 1, 1), maxTilesPerDimension);

    console.log(`[getVisibleTiles] Tile count: ${tileCountX} x ${tileCountY} = ${tileCountX * tileCountY} tiles`);

    for (let x = minTile.x; x < minTile.x + tileCountX; x++) {
      for (let y = minTile.y; y < minTile.y + tileCountY; y++) {
        tiles.push({ x, y, z: zoom });
      }
    }

    console.log(`[getVisibleTiles] ✓ Generated ${tiles.length} tiles`);
    return tiles;
  }

  /**
   * Fallback method to compute view rectangle from canvas corners
   */
  computeViewRectangleFallback() {
    try {
      const scene = this.viewer.scene;
      const canvas = scene.canvas;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;

      console.log(`[Fallback] Canvas size: ${width}x${height}`);

      // Sample multiple points across the canvas
      const samplePoints = [
        { x: 0, y: 0 },           // top-left
        { x: width, y: 0 },       // top-right
        { x: 0, y: height },      // bottom-left
        { x: width, y: height },  // bottom-right
        { x: width / 2, y: height / 2 }  // center
      ];

      const positions = [];
      
      for (const point of samplePoints) {
        try {
          const cartesian = scene.camera.pickEllipsoid(
            new Cesium.Cartesian2(point.x, point.y),
            scene.globe.ellipsoid
          );
          
          if (cartesian) {
            const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
            positions.push(cartographic);
          }
        } catch (e) {
          console.warn(`[Fallback] Failed to pick point (${point.x}, ${point.y}):`, e.message);
        }
      }

      console.log(`[Fallback] Sampled ${positions.length}/5 points`);

      if (positions.length === 0) {
        console.warn('[Fallback] No valid canvas positions found');
        return null;
      }

      // Find bounds from sampled positions
      let minLon = positions[0].longitude;
      let maxLon = positions[0].longitude;
      let minLat = positions[0].latitude;
      let maxLat = positions[0].latitude;

      for (const pos of positions) {
        minLon = Math.min(minLon, pos.longitude);
        maxLon = Math.max(maxLon, pos.longitude);
        minLat = Math.min(minLat, pos.latitude);
        maxLat = Math.max(maxLat, pos.latitude);
      }

      const rect = new Cesium.Rectangle(minLon, minLat, maxLon, maxLat);
      console.log(`[Fallback] Created rectangle from sampled points`);
      return rect;
    } catch (e) {
      console.error('[Fallback] Exception in computeViewRectangleFallback:', e);
      return null;
    }
  }

  /**
   * Calculate appropriate zoom level based on camera height
   */
  calculateZoomLevel(height, layerInfo) {
    const minZoom = layerInfo.minzoom || 0;
    const maxZoom = Math.min(layerInfo.maxzoom || 14, CONFIG.VECTOR_TILES.MAX_ZOOM || 14);
    
    // Approximate zoom calculation based on height
    // Lower height = higher zoom
    let zoom = Math.floor(Math.log2(40075016.686 / (height * 0.001)));
    zoom = Math.max(minZoom, Math.min(maxZoom, zoom));
    
    return zoom;
  }

  /**
   * Convert lon/lat to tile coordinates
   */
  lonLatToTile(lon, lat, zoom) {
    const n = Math.pow(2, zoom);
    const x = Math.floor((lon + 180) / 360 * n);
    const latRad = lat * Math.PI / 180;
    const y = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);
    return { x, y };
  }

  /**
   * Convert tile coordinates to lon/lat bounds
   */
  tileToBounds(x, y, zoom) {
    const n = Math.pow(2, zoom);
    const lonMin = x / n * 360 - 180;
    const lonMax = (x + 1) / n * 360 - 180;
    
    const latMinRad = Math.atan(Math.sinh(Math.PI * (1 - 2 * (y + 1) / n)));
    const latMaxRad = Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n)));
    
    const latMin = latMinRad * 180 / Math.PI;
    const latMax = latMaxRad * 180 / Math.PI;
    
    return { west: lonMin, south: latMin, east: lonMax, north: latMax };
  }

  /**
   * Load tiles and render features
   */
  async loadTiles(layerId, layerInfo, tiles, dataSource) {
    const tileUrlTemplate = this.getTileUrlTemplate(layerId, layerInfo);
    
    console.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
    console.log(`[loadTiles] Starting to load ${tiles.length} vector tiles for layer: ${layerId}`);
    console.log(`[loadTiles] Layer name: ${layerInfo.name}`);
    console.log(`[loadTiles] URL template: ${tileUrlTemplate}`);
    console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`);
    
    let loadedCount = 0;
    const featureStyler = CONFIG.VECTOR_TILES.FEATURE_STYLES?.[layerId] || CONFIG.VECTOR_TILES.DEFAULT_STYLE;

    for (const tile of tiles) {
      const tileKey = `${layerId}/${tile.z}/${tile.x}/${tile.y}`;
      
      // Skip if already loaded
      if (this.activeTiles.has(tileKey)) {
        console.log(`[loadTiles] ⏭️  Skipping already loaded tile: ${tileKey}`);
        continue;
      }

      const url = tileUrlTemplate
        .replace('{z}', tile.z)
        .replace('{x}', tile.x)
        .replace('{y}', tile.y);

      console.log(`[loadTiles] 📍 Tile ${tileKey}`);
      console.log(`[loadTiles]    URL: ${url}`);

      try {
        // For now, create a bounding box visualization since we don't have full MVT parsing
        const bounds = this.tileToBounds(tile.x, tile.y, tile.z);
        console.log(`[loadTiles]    Bounds: W=${bounds.west.toFixed(4)}, S=${bounds.south.toFixed(4)}, E=${bounds.east.toFixed(4)}, N=${bounds.north.toFixed(4)}`);
        
        this.renderTileBoundingBox(dataSource, tile, bounds, featureStyler);
        
        this.activeTiles.set(tileKey, { tile, bounds, url });
        loadedCount++;
        
        console.log(`[loadTiles] ✓ Tile ${tileKey} visualized (bounding box)`);

        // Note: With proper MVT parsing (using @mapbox/vector-tile):
        // const features = await this.parser.fetchAndParseTile(url);
        // if (features && features.parsed) {
        //   this.renderFeatures(dataSource, features, tile, featureStyler);
        // }

      } catch (error) {
        console.error(`[loadTiles] ✗ Error loading tile ${tileKey}:`, error);
      }
    }

    console.log(`\n[loadTiles] ✓ Loaded ${loadedCount}/${tiles.length} vector tiles for layer ${layerId}`);
    
    // Summary: Show all tile URLs for easy access/debugging
    if (loadedCount > 0) {
      console.log(`\n━━━ TILE URL SUMMARY (for debugging) ━━━`);
      console.log(`Copy these URLs to test in browser:\n`);
      
      const summaryTiles = tiles.slice(0, Math.min(5, tiles.length)); // Show first 5
      summaryTiles.forEach(tile => {
        const url = tileUrlTemplate
          .replace('{z}', tile.z)
          .replace('{x}', tile.x)
          .replace('{y}', tile.y);
        
        console.log(`Tile ${tile.z}/${tile.x}/${tile.y}: ${url}`);
      });
      
      if (tiles.length > 5) {
        console.log(`... and ${tiles.length - 5} more tiles`);
      }
      console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`);
    }
  }

  /**
   * Get tile URL template for vector layer
   */
  getTileUrlTemplate(layerId, layerInfo) {
    const metadata = layerInfo.metadata;
    
    console.log(`[getTileUrlTemplate] Getting URL template for layer: ${layerId}`);
    console.log(`[getTileUrlTemplate] Metadata exists: ${!!metadata}`);
    console.log(`[getTileUrlTemplate] Metadata.tiles exists: ${!!(metadata && metadata.tiles)}`);
    
    if (metadata && metadata.tiles && metadata.tiles.length > 0) {
      console.log(`[getTileUrlTemplate] Found ${metadata.tiles.length} tile URLs in metadata`);
      console.log(`[getTileUrlTemplate] First URL: ${metadata.tiles[0]}`);
      
      // URLs are already normalized by fetchLayerMetadata()
      // Filter out any that might still be malformed
      const validUrls = metadata.tiles.filter(url => {
        try {
          const testUrl = url.replace('{z}', '0').replace('{x}', '0').replace('{y}', '0');
          new URL(testUrl);
          return true;
        } catch {
          console.warn(`[VectorTiles] Skipping malformed tile URL: ${url}`);
          return false;
        }
      });
      
      console.log(`[getTileUrlTemplate] Valid URLs after filtering: ${validUrls.length}`);
      
      if (validUrls.length > 0) {
        // Prefer HTTPS URLs from mbtiles.deepgis.org
        const selectedUrl = validUrls.find(url => url.startsWith('https://mbtiles.deepgis.org'))
          || validUrls.find(url => url.startsWith('https://'))
          || validUrls[0];
        
        console.log(`[getTileUrlTemplate] ✓ Selected URL template: ${selectedUrl}`);
        return selectedUrl;
      }
    }
    
    // Fallback: construct URL manually
    const fallbackUrl = `${CONFIG.SERVERS.MBTILES_SERVER}/data/${layerId}/{z}/{x}/{y}.pbf`;
    console.log(`[getTileUrlTemplate] ⚠️ Using fallback URL: ${fallbackUrl}`);
    return fallbackUrl;
  }

  /**
   * Render tile bounding box (placeholder visualization) - border only, no fill
   */
  renderTileBoundingBox(dataSource, tile, bounds, style) {
    const { west, south, east, north } = bounds;
    
    // Create rectangle entity for tile boundary (border only, no fill)
    const entity = dataSource.entities.add({
      name: `Tile ${tile.z}/${tile.x}/${tile.y}`,
      rectangle: {
        coordinates: Cesium.Rectangle.fromDegrees(west, south, east, north),
        fill: false,
        outline: true,
        outlineColor: new Cesium.Color(
          style.strokeColor.r,
          style.strokeColor.g,
          style.strokeColor.b,
          1.0
        ),
        outlineWidth: style.strokeWidth || 1,
        height: 0
      },
      description: `Vector tile: z=${tile.z}, x=${tile.x}, y=${tile.y}`
    });

    return entity;
  }

  /**
   * Render parsed vector tile features (for use with proper MVT parser)
   */
  renderFeatures(dataSource, features, tile, style) {
    // This would be implemented with proper feature rendering
    // when using a full MVT parser like @mapbox/vector-tile
    
    features.features.forEach((feature, idx) => {
      const geometry = feature.geometry;
      
      if (geometry.type === 'Polygon') {
        this.renderPolygon(dataSource, geometry, feature.properties, style);
      } else if (geometry.type === 'LineString') {
        this.renderLineString(dataSource, geometry, feature.properties, style);
      } else if (geometry.type === 'Point') {
        this.renderPoint(dataSource, geometry, feature.properties, style);
      }
    });
  }

  /**
   * Render polygon feature
   */
  renderPolygon(dataSource, geometry, properties, style) {
    const positions = geometry.coordinates[0].map(coord =>
      Cesium.Cartesian3.fromDegrees(coord[0], coord[1])
    );

    dataSource.entities.add({
      name: properties.name || 'Polygon',
      polygon: {
        hierarchy: new Cesium.PolygonHierarchy(positions),
        material: new Cesium.Color(
          style.fillColor.r,
          style.fillColor.g,
          style.fillColor.b,
          style.fillOpacity
        ),
        outline: true,
        outlineColor: new Cesium.Color(
          style.strokeColor.r,
          style.strokeColor.g,
          style.strokeColor.b,
          1.0
        ),
        outlineWidth: style.strokeWidth || 1
      },
      properties: properties
    });
  }

  /**
   * Render line string feature
   */
  renderLineString(dataSource, geometry, properties, style) {
    const positions = geometry.coordinates.map(coord =>
      Cesium.Cartesian3.fromDegrees(coord[0], coord[1])
    );

    dataSource.entities.add({
      name: properties.name || 'LineString',
      polyline: {
        positions: positions,
        width: style.strokeWidth || 2,
        material: new Cesium.Color(
          style.strokeColor.r,
          style.strokeColor.g,
          style.strokeColor.b,
          1.0
        )
      },
      properties: properties
    });
  }

  /**
   * Render point feature
   */
  renderPoint(dataSource, geometry, properties, style) {
    const position = Cesium.Cartesian3.fromDegrees(
      geometry.coordinates[0],
      geometry.coordinates[1]
    );

    dataSource.entities.add({
      name: properties.name || 'Point',
      position: position,
      point: {
        pixelSize: style.pointSize || 8,
        color: new Cesium.Color(
          style.fillColor.r,
          style.fillColor.g,
          style.fillColor.b,
          1.0
        ),
        outlineColor: new Cesium.Color(
          style.strokeColor.r,
          style.strokeColor.g,
          style.strokeColor.b,
          1.0
        ),
        outlineWidth: 1
      },
      properties: properties
    });
  }

  /**
   * Remove vector layer
   */
  async removeVectorLayer(layerId) {
    const dataSource = this.dataSourcesByLayer.get(layerId);
    if (dataSource) {
      await this.viewer.dataSources.remove(dataSource);
      this.dataSourcesByLayer.delete(layerId);

      // Clear cached tiles for this layer
      const tileKeys = Array.from(this.activeTiles.keys());
      tileKeys.forEach(key => {
        if (key.startsWith(`${layerId}/`)) {
          this.activeTiles.delete(key);
        }
      });

      // Remove camera listener if no layers remain
      if (this.dataSourcesByLayer.size === 0 && this.cameraListener) {
        this.cameraListener();
        this.cameraListener = null;
      }

      console.log(`Removed vector layer: ${layerId}`);
    }
  }

  /**
   * Update vector layer visibility
   */
  setLayerVisibility(layerId, visible) {
    const dataSource = this.dataSourcesByLayer.get(layerId);
    if (dataSource) {
      dataSource.show = visible;
    }
  }

  /**
   * Update vector layer opacity
   */
  setLayerOpacity(layerId, opacity) {
    const dataSource = this.dataSourcesByLayer.get(layerId);
    if (dataSource) {
      // Update all entities in the data source
      dataSource.entities.values.forEach(entity => {
        if (entity.polygon) {
          const currentColor = entity.polygon.material.color.getValue();
          entity.polygon.material.color = new Cesium.Color(
            currentColor.red,
            currentColor.green,
            currentColor.blue,
            opacity
          );
        }
      });
    }
  }

  /**
   * Cleanup all vector layers
   */
  cleanup() {
    this.dataSourcesByLayer.forEach((dataSource, layerId) => {
      this.viewer.dataSources.remove(dataSource);
    });
    this.dataSourcesByLayer.clear();
    this.activeTiles.clear();
    this.parser.clearCache();
    
    // Remove camera listener
    if (this.cameraListener) {
      this.cameraListener();
      this.cameraListener = null;
    }
  }
}

export default VectorLayerRenderer;

