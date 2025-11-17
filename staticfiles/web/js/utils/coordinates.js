/**
 * Coordinate and View Calculation Utilities
 */
import { CONFIG } from '../config.js';

export const CoordinateUtils = {
  /**
   * Calculate height from zoom level
   */
  zoomToHeight: (zoom) => {
    return CONFIG.DEFAULT_ZOOM_HEIGHT_BASE / Math.pow(2, zoom);
  },
  
  /**
   * Validate and clamp zoom level to be within [minzoom, maxzoom] range
   * @param {number} zoom - The zoom level to validate
   * @param {number} minzoom - Minimum allowed zoom (default: 0)
   * @param {number} maxzoom - Maximum allowed zoom (default: 22)
   * @returns {number} - Clamped zoom level within valid range
   */
  validateZoom: (zoom, minzoom = 0, maxzoom = 22) => {
    if (zoom === null || zoom === undefined || isNaN(zoom)) {
      return Math.min(maxzoom, Math.max(minzoom, CONFIG.DEFAULT_ZOOM_LEVEL));
    }
    return Math.min(maxzoom, Math.max(minzoom, zoom));
  },
  
  /**
   * Calculate destination from layer center coordinates
   */
  centerToDestination: (center, defaultZoom = 15) => {
    if (!center || !Array.isArray(center) || center.length < 2) return null;
    const [longitude, latitude, zoom] = center;
    const targetZoom = zoom !== undefined && zoom !== null ? zoom : defaultZoom;
    const height = CoordinateUtils.zoomToHeight(targetZoom);
    return Cesium.Cartesian3.fromDegrees(longitude, latitude, height);
  },
  
  /**
   * Calculate destination from layer bounds
   * Prioritizes defaultZoom if provided, otherwise calculates from bounds size
   * @param {Array} bounds - [west, south, east, north]
   * @param {number} defaultZoom - Preferred zoom level
   * @param {number} minzoom - Minimum allowed zoom (for validation)
   * @param {number} maxzoom - Maximum allowed zoom (for validation)
   */
  boundsToDestination: (bounds, defaultZoom = null, minzoom = 0, maxzoom = 22) => {
    if (!bounds || !Array.isArray(bounds) || bounds.length !== 4) return null;
    
    const [west, south, east, north] = bounds;
    const centerLon = (west + east) / 2;
    const centerLat = (south + north) / 2;
    
    // Check for world bounds
    const isWorldBounds = Math.abs(west - (-180)) < 0.01 && 
                         Math.abs(east - 180) < 0.01 &&
                         Math.abs(south - (-85.0511)) < 0.01 && 
                         Math.abs(north - 85.0511) < 0.01;
    
    // Use defaultZoom if provided, otherwise calculate from bounds
    let targetZoom = defaultZoom;
    if (!targetZoom) {
      if (isWorldBounds) {
        targetZoom = 2;
      } else {
        const lonDiff = Math.abs(east - west);
        const latDiff = Math.abs(north - south);
        const maxDiff = Math.max(lonDiff, latDiff);
        
        if (maxDiff < 0.1) targetZoom = 15;
        else if (maxDiff < 1) targetZoom = 12;
        else if (maxDiff < 10) targetZoom = 8;
        else targetZoom = 5;
      }
    }
    
    // Validate and clamp zoom to be within [minzoom, maxzoom] range
    targetZoom = CoordinateUtils.validateZoom(targetZoom, minzoom, maxzoom);
    
    const height = CoordinateUtils.zoomToHeight(targetZoom);
    return {
      destination: Cesium.Cartesian3.fromDegrees(centerLon, centerLat, height),
      zoom: targetZoom,
      isWorldBounds: isWorldBounds,
      bounds: bounds // Include bounds for fitting
    };
  },
  
  /**
   * Get destination from layer info (prioritizes defaultzoom and bounds)
   * Uses layer's defaultzoom if available, otherwise maxzoom, then CONFIG.DEFAULT_ZOOM_LEVEL
   * Validates zoom against [minzoom, maxzoom] range
   */
  getLayerDestination: (layerInfo) => {
    // Get minzoom and maxzoom with defaults
    const minzoom = layerInfo.minzoom || 0;
    const maxzoom = layerInfo.maxzoom || 22;
    
    // Determine target zoom with priority: defaultzoom → maxzoom → DEFAULT_ZOOM_LEVEL → minzoom → 15
    // This ensures we prefer layer-specific values over system defaults
    let optimalZoom = layerInfo.defaultzoom || 
                     layerInfo.maxzoom || 
                     CONFIG.DEFAULT_ZOOM_LEVEL || 
                     minzoom || 
                     15;
    
    // Validate and clamp zoom to be within [minzoom, maxzoom] range
    const targetZoom = CoordinateUtils.validateZoom(optimalZoom, minzoom, maxzoom);
    
    // Log if zoom was adjusted
    if (optimalZoom !== targetZoom) {
      console.log(`Zoom level adjusted from ${optimalZoom} to ${targetZoom} to fit within [${minzoom}, ${maxzoom}] range`);
    }
    
    // Try center first (if center has zoom in its array, use that; otherwise use targetZoom)
    let destination = null;
    let usedZoom = targetZoom;
    
    if (layerInfo.center && Array.isArray(layerInfo.center) && layerInfo.center.length >= 2) {
      // If center has zoom level (3rd element), use it; otherwise use targetZoom
      let centerZoom = layerInfo.center.length >= 3 ? layerInfo.center[2] : targetZoom;
      centerZoom = centerZoom !== undefined && centerZoom !== null ? centerZoom : targetZoom;
      // Validate center zoom against layer's zoom range
      usedZoom = CoordinateUtils.validateZoom(centerZoom, minzoom, maxzoom);
      destination = CoordinateUtils.centerToDestination(layerInfo.center, usedZoom);
    }
    
    if (destination) {
      return { 
        destination, 
        source: 'center',
        zoom: usedZoom,
        bounds: layerInfo.bounds
      };
    }
    
    // Fallback to bounds - pass minzoom/maxzoom for validation
    const boundsResult = CoordinateUtils.boundsToDestination(
      layerInfo.bounds,
      targetZoom, // Use calculated target zoom
      minzoom,    // Pass minzoom for validation
      maxzoom     // Pass maxzoom for validation
    );
    
    if (boundsResult) {
      return { 
        destination: boundsResult.destination, 
        source: 'bounds', 
        zoom: boundsResult.zoom,
        bounds: boundsResult.bounds,
        isWorldBounds: boundsResult.isWorldBounds
      };
    }
    
    // Final fallback - use validated zoom
    return { 
      destination: Cesium.Cartesian3.fromDegrees(0, 0, 10000000),
      source: 'fallback',
      zoom: targetZoom
    };
  },
  
  /**
   * Cap camera height to safe maximum
   */
  capCameraHeight: (viewer, maxHeight = CONFIG.MAX_SAFE_CAMERA_HEIGHT) => {
    const cameraHeight = viewer.camera.positionCartographic.height;
    if (cameraHeight > maxHeight) {
      const pos = viewer.camera.positionCartographic;
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromRadians(pos.longitude, pos.latitude, maxHeight)
      });
      return true; // Height was capped
    }
    return false; // Height was OK
  }
};

