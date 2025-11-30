/**
 * Measurement Tools Feature Module
 * Lazy loaded when measurement functionality is needed
 * 
 * Uses proper geodesic calculations for accurate Earth surface measurements
 */
import { AppState } from '../js/state.js';
import { CONFIG } from '../js/config.js';

// Active handler reference for cleanup
let activeHandler = null;

/**
 * Calculate geodesic (surface) distance between two points
 * Uses Cesium's EllipsoidGeodesic for accurate great-circle distance
 */
function calculateGeodesicDistance(startCartesian, endCartesian, ellipsoid) {
  const startCartographic = Cesium.Cartographic.fromCartesian(startCartesian, ellipsoid);
  const endCartographic = Cesium.Cartographic.fromCartesian(endCartesian, ellipsoid);
  
  const geodesic = new Cesium.EllipsoidGeodesic(startCartographic, endCartographic, ellipsoid);
  return geodesic.surfaceDistance;
}

/**
 * Format distance with appropriate units
 */
function formatDistance(meters) {
  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(3)} km`;
  } else {
    return `${meters.toFixed(2)} m`;
  }
}

/**
 * Format area with appropriate units
 * Consistent formatting for both viewport labels and widget list
 */
function formatArea(squareMeters) {
  // Handle invalid/NaN values
  if (!isFinite(squareMeters) || squareMeters < 0) {
    return '0.00 m²';
  }
  
  if (squareMeters >= 1000000) {
    // >= 1 km², show in km²
    const km2 = squareMeters / 1000000;
    // For large areas (>= 10 km²), use 2 decimals; for smaller, use 4 decimals
    return km2 >= 10 
      ? `${km2.toFixed(2)} km²` 
      : `${km2.toFixed(4)} km²`;
  } else if (squareMeters >= 100000) {
    // >= 10 ha, show in hectares with 2 decimals
    return `${(squareMeters / 10000).toFixed(2)} ha`;
  } else if (squareMeters >= 1000) {
    // >= 1000 m², show with comma separator and 1 decimal
    return `${squareMeters.toLocaleString('en-US', { maximumFractionDigits: 1 })} m²`;
  } else {
    // < 1000 m², show with 2 decimals
    return `${squareMeters.toFixed(2)} m²`;
  }
}

/**
 * Start distance measurement
 * Uses geodesic (great-circle) distance calculation
 */
export function startDistanceMeasurement(viewer) {
  clearActiveHandlers();
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Click two points to measure geodesic distance (ESC to cancel)');
  }
  
  let clickCount = 0;
  let startPoint, endPoint;
  let startCartographic;
  let polyline;
  const ellipsoid = viewer.scene.globe.ellipsoid;

  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  activeHandler = handler;
  
  // ESC key to cancel
  const escHandler = (e) => {
    if (e.key === 'Escape') {
      if (polyline) viewer.entities.remove(polyline);
      handler.destroy();
      activeHandler = null;
      document.removeEventListener('keydown', escHandler);
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('Measurement cancelled');
      }
    }
  };
  document.addEventListener('keydown', escHandler);
  
  handler.setInputAction((click) => {
    const position = viewer.camera.pickEllipsoid(click.position, ellipsoid);
    if (!position) return;

    clickCount++;

    if (clickCount === 1) {
      startPoint = position;
      startCartographic = Cesium.Cartographic.fromCartesian(position, ellipsoid);
      polyline = viewer.entities.add({
        polyline: {
          positions: [startPoint, startPoint],
          width: 3,
          material: Cesium.Color.YELLOW,
          clampToGround: true,
          arcType: Cesium.ArcType.GEODESIC  // Draw as geodesic curve
        }
      });
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('Click second point to complete measurement');
      }
    } else if (clickCount === 2) {
      endPoint = position;
      
      polyline.polyline.positions = [startPoint, endPoint];
      polyline.polyline.material = Cesium.Color.RED;

      // Calculate geodesic (surface) distance
      const geodesicDistance = calculateGeodesicDistance(startPoint, endPoint, ellipsoid);
      
      // Also calculate straight-line distance for comparison
      const straightLineDistance = Cesium.Cartesian3.distance(startPoint, endPoint);
      
      const midpoint = Cesium.Cartesian3.midpoint(startPoint, endPoint, new Cesium.Cartesian3());

      const label = viewer.entities.add({
        position: midpoint,
        label: {
          text: `${formatDistance(geodesicDistance)}\n(geodesic)`,
          font: '14pt sans-serif',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -20),
          showBackground: true,
          backgroundColor: Cesium.Color.BLACK.withAlpha(0.6)
        }
      });

      AppState.measurements.push({
        type: 'distance',
        value: geodesicDistance,
        straightLineDistance: straightLineDistance,
        entities: [polyline, label]
      });

      updateMeasurementsList();
      document.removeEventListener('keydown', escHandler);
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator(`Distance: ${formatDistance(geodesicDistance)}`);
      }
      handler.destroy();
      activeHandler = null;
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  handler.setInputAction((movement) => {
    if (clickCount === 1 && polyline) {
      const position = viewer.camera.pickEllipsoid(movement.endPosition, ellipsoid);
      if (position) {
        polyline.polyline.positions = [startPoint, position];
        
        // Show live distance preview
        const previewDistance = calculateGeodesicDistance(startPoint, position, ellipsoid);
        if (typeof window.updateStatusIndicator === 'function') {
          window.updateStatusIndicator(`Distance: ${formatDistance(previewDistance)} (click to confirm)`);
        }
      }
    }
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
}

/**
 * Start area measurement
 * Uses spherical excess formula for accurate geodesic area
 */
export function startAreaMeasurement(viewer) {
  clearActiveHandlers();
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Click points to create polygon, double-click to finish (ESC to cancel)');
  }
  
  let positions = [];
  let polygon;
  let polyline;
  const ellipsoid = viewer.scene.globe.ellipsoid;

  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  activeHandler = handler;
  
  // ESC key to cancel
  const escHandler = (e) => {
    if (e.key === 'Escape') {
      if (polygon) viewer.entities.remove(polygon);
      if (polyline) viewer.entities.remove(polyline);
      handler.destroy();
      activeHandler = null;
      document.removeEventListener('keydown', escHandler);
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('Measurement cancelled');
      }
    }
  };
  document.addEventListener('keydown', escHandler);
  
  handler.setInputAction((click) => {
    const position = viewer.camera.pickEllipsoid(click.position, ellipsoid);
    if (!position) return;

    positions.push(position);

    if (positions.length === 1) {
      // Start with a polyline to show the path
      polyline = viewer.entities.add({
        polyline: {
          positions: new Cesium.CallbackProperty(() => {
            return positions.length > 1 ? positions : [positions[0], positions[0]];
          }, false),
          width: 2,
          material: Cesium.Color.CYAN,
          clampToGround: true
        }
      });
    } else if (positions.length >= 3) {
      // Create polygon once we have 3+ points
      if (!polygon) {
        if (polyline) viewer.entities.remove(polyline);
        polygon = viewer.entities.add({
          polygon: {
            hierarchy: new Cesium.CallbackProperty(() => new Cesium.PolygonHierarchy(positions), false),
            material: Cesium.Color.BLUE.withAlpha(0.3),
            outline: true,
            outlineColor: Cesium.Color.CYAN,
            outlineWidth: 2,
            height: 0
          }
        });
      }
      
      // Show live area preview
      const previewArea = calculateSphericalPolygonArea(positions, ellipsoid);
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator(`Area: ${formatArea(previewArea)} (${positions.length} points, double-click to finish)`);
      }
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  handler.setInputAction((doubleClick) => {
    if (positions.length < 3) {
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('Need at least 3 points for area measurement');
      }
      return;
    }

    // Calculate proper spherical area
    const area = calculateSphericalPolygonArea(positions, ellipsoid);
    
    // Also calculate perimeter
    const perimeter = calculatePolygonPerimeter(positions, ellipsoid);
    
    const center = Cesium.BoundingSphere.fromPoints(positions).center;

    // Finalize polygon appearance
    if (polygon) {
      polygon.polygon.material = Cesium.Color.BLUE.withAlpha(0.4);
      polygon.polygon.outlineColor = Cesium.Color.YELLOW;
    }

    const label = viewer.entities.add({
      position: center,
      label: {
        text: `Area: ${formatArea(area)}\nPerimeter: ${formatDistance(perimeter)}`,
        font: '14pt sans-serif',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        showBackground: true,
        backgroundColor: Cesium.Color.BLACK.withAlpha(0.6)
      }
    });

    AppState.measurements.push({
      type: 'area',
      value: area,
      perimeter: perimeter,
      numPoints: positions.length,
      entities: [polygon, label]
    });

    updateMeasurementsList();
    document.removeEventListener('keydown', escHandler);
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator(`Area: ${formatArea(area)}`);
    }
    handler.destroy();
    activeHandler = null;
  }, Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
}

/**
 * Start height/elevation measurement
 * Samples terrain elevation at clicked point
 */
export function startHeightMeasurement(viewer) {
  clearActiveHandlers();
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Click a point to measure elevation (ESC to cancel)');
  }
  
  const ellipsoid = viewer.scene.globe.ellipsoid;
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  activeHandler = handler;
  
  // ESC key to cancel
  const escHandler = (e) => {
    if (e.key === 'Escape') {
      handler.destroy();
      activeHandler = null;
      document.removeEventListener('keydown', escHandler);
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('Measurement cancelled');
      }
    }
  };
  document.addEventListener('keydown', escHandler);
  
  handler.setInputAction((click) => {
    const position = viewer.camera.pickEllipsoid(click.position, ellipsoid);
    if (!position) return;

    const cartographic = Cesium.Cartographic.fromCartesian(position, ellipsoid);
    const longitude = Cesium.Math.toDegrees(cartographic.longitude);
    const latitude = Cesium.Math.toDegrees(cartographic.latitude);
    
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('Sampling elevation...');
    }
    
    // Try to get elevation from custom server first
    fetch(`${CONFIG.SERVERS.TOPOLOGY_SERVER}/elevation?lon=${longitude}&lat=${latitude}`)
      .then(response => response.json())
      .then(data => {
        let height = 0;
        if (data.elevations && Object.keys(data.elevations).length > 0) {
          const firstDataset = Object.keys(data.elevations)[0];
          height = data.elevations[firstDataset] || 0;
        } else {
          return Cesium.sampleTerrain(viewer.terrainProvider, 11, [cartographic]);
        }
        return [{ height }];
      })
      .catch(() => {
        return Cesium.sampleTerrain(viewer.terrainProvider, 11, [cartographic]);
      })
      .then((results) => {
        const height = results[0].height || 0;
        
        const point = viewer.entities.add({
          position: position,
          point: {
            pixelSize: 12,
            color: Cesium.Color.YELLOW,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2
          }
        });

        const label = viewer.entities.add({
          position: position,
          label: {
            text: `Elevation: ${height.toFixed(2)} m\nLat: ${latitude.toFixed(6)}°\nLon: ${longitude.toFixed(6)}°`,
            font: '12pt sans-serif',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -30),
            showBackground: true,
            backgroundColor: Cesium.Color.BLACK.withAlpha(0.6)
          }
        });

        AppState.measurements.push({
          type: 'height',
          value: height,
          latitude: latitude,
          longitude: longitude,
          entities: [point, label]
        });

        updateMeasurementsList();
        document.removeEventListener('keydown', escHandler);
        if (typeof window.updateStatusIndicator === 'function') {
          window.updateStatusIndicator(`Elevation: ${height.toFixed(2)} m`);
        }
      })
      .catch(error => {
        console.error('Error measuring height:', error);
        document.removeEventListener('keydown', escHandler);
        if (typeof window.updateStatusIndicator === 'function') {
          window.updateStatusIndicator('Error measuring elevation');
        }
      });

    handler.destroy();
    activeHandler = null;
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
}

/**
 * Clear all measurements
 */
export function clearAllMeasurements(viewer) {
  // Clear any active measurement handler
  clearActiveHandlers();
  
  // Remove all measurement entities
  AppState.measurements.forEach(measurement => {
    measurement.entities.forEach(entity => {
      if (entity) {
        viewer.entities.remove(entity);
      }
    });
  });
  
  AppState.measurements = [];
  updateMeasurementsList();
  
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('All measurements cleared');
  }
  
  console.log('[Measurements] Cleared all measurements');
}

function clearActiveHandlers() {
  if (activeHandler) {
    activeHandler.destroy();
    activeHandler = null;
  }
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Ready');
  }
}

function updateMeasurementsList() {
  const container = document.getElementById('measurementsList');
  if (!container) return;
  
  if (AppState.measurements.length === 0) {
    container.innerHTML = '<small style="color: #94a3b8;">No measurements yet</small>';
    return;
  }

  container.innerHTML = AppState.measurements.map((measurement, index) => {
    let text = '';
    let icon = '';
    switch (measurement.type) {
      case 'distance':
        icon = '📏';
        text = `${formatDistance(measurement.value)}`;
        break;
      case 'area':
        icon = '📐';
        text = `${formatArea(measurement.value)}`;
        break;
      case 'height':
        icon = '📍';
        text = `${measurement.value.toFixed(2)} m`;
        break;
    }
    return `<div class="measurement-item" style="padding: 4px 8px; margin: 2px 0; background: rgba(0,0,0,0.3); border-radius: 4px; font-size: 0.85rem;">
      <span style="margin-right: 6px;">${icon}</span><span style="margin-right: 4px;">${index + 1}</span>${text}
    </div>`;
  }).join('');
}

/**
 * Calculate polygon area using simple planar approximation
 * Projects lat/lon to local tangent plane and uses Shoelace formula
 */
function calculateSphericalPolygonArea(positions, ellipsoid) {
  if (positions.length < 3) return 0;
  
  // Convert to cartographic (lat/lon in radians)
  const cartographics = positions.map(pos => 
    Cesium.Cartographic.fromCartesian(pos, ellipsoid)
  );
  
  // Remove duplicate last point if closed
  if (cartographics.length > 0) {
    const first = cartographics[0];
    const last = cartographics[cartographics.length - 1];
    if (Math.abs(first.longitude - last.longitude) < 1e-10 && 
        Math.abs(first.latitude - last.latitude) < 1e-10) {
      cartographics.pop();
    }
  }
  
  if (cartographics.length < 3) return 0;
  
  // Use first point as origin for projection (simpler and more stable)
  const origin = cartographics[0];
  const R = ellipsoid.maximumRadius;
  const cosLat = Math.cos(origin.latitude);
  
  // Project to local tangent plane: x = R * Δlon * cos(lat), y = R * Δlat
  // All in meters
  const points2D = cartographics.map(c => ({
    x: R * (c.longitude - origin.longitude) * cosLat,
    y: R * (c.latitude - origin.latitude)
  }));
  
  // Shoelace formula: Area = 0.5 * |Σ(x_i * y_{i+1} - x_{i+1} * y_i)|
  let area = 0;
  const n = points2D.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    area += points2D[i].x * points2D[j].y;
    area -= points2D[j].x * points2D[i].y;
  }
  
  const calculatedArea = Math.abs(area) / 2;
  
  // Sanity check: return 0 if area is clearly wrong
  if (!isFinite(calculatedArea) || calculatedArea <= 0 || calculatedArea > 1000000000000) {
    console.warn('[Measurements] Invalid area:', calculatedArea, 'm²');
    return 0;
  }
  
  return calculatedArea;
}

/**
 * Calculate polygon perimeter using geodesic distances
 */
function calculatePolygonPerimeter(positions, ellipsoid) {
  if (positions.length < 2) return 0;
  
  let perimeter = 0;
  for (let i = 0; i < positions.length; i++) {
    const j = (i + 1) % positions.length;
    perimeter += calculateGeodesicDistance(positions[i], positions[j], ellipsoid);
  }
  
  return perimeter;
}

// Export default object for lazy loading
export default {
  startDistanceMeasurement,
  startAreaMeasurement,
  startHeightMeasurement,
  clearAllMeasurements
};

