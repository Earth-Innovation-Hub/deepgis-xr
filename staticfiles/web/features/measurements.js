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
 */
function formatArea(squareMeters) {
  if (squareMeters >= 1000000) {
    return `${(squareMeters / 1000000).toFixed(4)} km²`;
  } else if (squareMeters >= 10000) {
    return `${(squareMeters / 10000).toFixed(4)} ha`;
  } else {
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
      <span style="margin-right: 6px;">${icon}</span>${index + 1}. ${text}
    </div>`;
  }).join('');
}

/**
 * Calculate spherical polygon area using spherical excess formula
 * This is more accurate than planar approximation for large polygons
 */
function calculateSphericalPolygonArea(positions, ellipsoid) {
  if (positions.length < 3) return 0;
  
  const cartographics = positions.map(pos => Cesium.Cartographic.fromCartesian(pos, ellipsoid));
  
  // Use the Girard formula for spherical excess
  // Area = R² * |spherical excess|
  // For a spherical polygon, the spherical excess is the sum of angles - (n-2)*π
  
  const n = cartographics.length;
  let sphericalExcess = 0;
  
  // Calculate using the shoelace-like formula for spherical coordinates
  // This uses a more accurate method based on the cross-track distance
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const k = (i + 2) % n;
    
    const lat1 = cartographics[i].latitude;
    const lon1 = cartographics[i].longitude;
    const lat2 = cartographics[j].latitude;
    const lon2 = cartographics[j].longitude;
    const lat3 = cartographics[k].latitude;
    const lon3 = cartographics[k].longitude;
    
    // Calculate the angle at vertex j
    const bearing1 = calculateBearing(lat2, lon2, lat1, lon1);
    const bearing2 = calculateBearing(lat2, lon2, lat3, lon3);
    
    let angle = bearing2 - bearing1;
    while (angle < 0) angle += 2 * Math.PI;
    while (angle > 2 * Math.PI) angle -= 2 * Math.PI;
    
    if (angle > Math.PI) angle = 2 * Math.PI - angle;
    
    sphericalExcess += angle;
  }
  
  // Spherical excess = sum of angles - (n-2) * π
  sphericalExcess = Math.abs(sphericalExcess - (n - 2) * Math.PI);
  
  // Area = R² * spherical excess
  // Use the semi-major axis of the ellipsoid
  const radius = ellipsoid.maximumRadius;
  const area = radius * radius * sphericalExcess;
  
  return area;
}

/**
 * Calculate bearing between two points in radians
 */
function calculateBearing(lat1, lon1, lat2, lon2) {
  const dLon = lon2 - lon1;
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return Math.atan2(y, x);
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

