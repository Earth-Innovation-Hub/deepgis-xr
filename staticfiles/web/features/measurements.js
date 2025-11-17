/**
 * Measurement Tools Feature Module
 * Lazy loaded when measurement functionality is needed
 */
import { AppState } from '../state.js';
import { CONFIG } from '../config.js';

/**
 * Start distance measurement
 */
export function startDistanceMeasurement(viewer) {
  clearActiveHandlers();
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Click two points to measure distance');
  }
  
  let clickCount = 0;
  let startPoint, endPoint;
  let polyline;

  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  
  handler.setInputAction((click) => {
    const position = viewer.camera.pickEllipsoid(click.position, viewer.scene.globe.ellipsoid);
    if (!position) return;

    clickCount++;

    if (clickCount === 1) {
      startPoint = position;
      polyline = viewer.entities.add({
        polyline: {
          positions: [startPoint, startPoint],
          width: 3,
          material: Cesium.Color.YELLOW,
          clampToGround: true
        }
      });
    } else if (clickCount === 2) {
      endPoint = position;
      
      polyline.polyline.positions = [startPoint, endPoint];
      polyline.polyline.material = Cesium.Color.RED;

      const distance = Cesium.Cartesian3.distance(startPoint, endPoint);
      const midpoint = Cesium.Cartesian3.midpoint(startPoint, endPoint, new Cesium.Cartesian3());

      const label = viewer.entities.add({
        position: midpoint,
        label: {
          text: `${distance.toFixed(2)} m`,
          font: '14pt sans-serif',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -20)
        }
      });

      AppState.measurements.push({
        type: 'distance',
        value: distance,
        entities: [polyline, label]
      });

      updateMeasurementsList();
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('Distance measured');
      }
      handler.destroy();
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  handler.setInputAction((movement) => {
    if (clickCount === 1 && polyline) {
      const position = viewer.camera.pickEllipsoid(movement.endPosition, viewer.scene.globe.ellipsoid);
      if (position) {
        polyline.polyline.positions = [startPoint, position];
      }
    }
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
}

/**
 * Start area measurement
 */
export function startAreaMeasurement(viewer) {
  clearActiveHandlers();
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Click points to create polygon, double-click to finish');
  }
  
  let positions = [];
  let polygon;

  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  
  handler.setInputAction((click) => {
    const position = viewer.camera.pickEllipsoid(click.position, viewer.scene.globe.ellipsoid);
    if (!position) return;

    positions.push(position);

    if (positions.length === 1) {
      polygon = viewer.entities.add({
        polygon: {
          hierarchy: new Cesium.CallbackProperty(() => new Cesium.PolygonHierarchy(positions), false),
          material: Cesium.Color.BLUE.withAlpha(0.3),
          outline: true,
          outlineColor: Cesium.Color.BLUE,
          height: 0
        }
      });
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  handler.setInputAction((doubleClick) => {
    if (positions.length < 3) {
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('Need at least 3 points for area measurement');
      }
      return;
    }

    const area = calculatePolygonArea(positions);
    const center = Cesium.BoundingSphere.fromPoints(positions).center;

    const label = viewer.entities.add({
      position: center,
      label: {
        text: `${area.toFixed(2)} m²`,
        font: '14pt sans-serif',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE
      }
    });

    AppState.measurements.push({
      type: 'area',
      value: area,
      entities: [polygon, label]
    });

    updateMeasurementsList();
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('Area measured');
    }
    handler.destroy();
  }, Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
}

/**
 * Start height measurement
 */
export function startHeightMeasurement(viewer) {
  clearActiveHandlers();
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Click a point to measure height');
  }
  
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  
  handler.setInputAction((click) => {
    const position = viewer.camera.pickEllipsoid(click.position, viewer.scene.globe.ellipsoid);
    if (!position) return;

    const cartographic = Cesium.Cartographic.fromCartesian(position);
    const longitude = Cesium.Math.toDegrees(cartographic.longitude);
    const latitude = Cesium.Math.toDegrees(cartographic.latitude);
    
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
            pixelSize: 10,
            color: Cesium.Color.YELLOW,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2
          }
        });

        const label = viewer.entities.add({
          position: position,
          label: {
            text: `Height: ${height.toFixed(2)} m`,
            font: '14pt sans-serif',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -30)
          }
        });

        AppState.measurements.push({
          type: 'height',
          value: height,
          entities: [point, label]
        });

        updateMeasurementsList();
        if (typeof window.updateStatusIndicator === 'function') {
          window.updateStatusIndicator('Height measured');
        }
      })
      .catch(error => {
        console.error('Error measuring height:', error);
        if (typeof window.updateStatusIndicator === 'function') {
          window.updateStatusIndicator('Error measuring height');
        }
      });

    handler.destroy();
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
}

/**
 * Clear all measurements
 */
export function clearAllMeasurements(viewer) {
  AppState.measurements.forEach(measurement => {
    measurement.entities.forEach(entity => {
      viewer.entities.remove(entity);
    });
  });
  AppState.measurements = [];
  updateMeasurementsList();
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Measurements cleared');
  }
}

function clearActiveHandlers() {
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Ready');
  }
}

function updateMeasurementsList() {
  const container = document.getElementById('measurementsList');
  if (!container) return;
  
  if (AppState.measurements.length === 0) {
    container.innerHTML = '<small>No measurements yet</small>';
    return;
  }

  container.innerHTML = AppState.measurements.map((measurement, index) => {
    let text = '';
    switch (measurement.type) {
      case 'distance':
        text = `Distance: ${measurement.value.toFixed(2)} m`;
        break;
      case 'area':
        text = `Area: ${measurement.value.toFixed(2)} m²`;
        break;
      case 'height':
        text = `Height: ${measurement.value.toFixed(2)} m`;
        break;
    }
    return `<div class="measurement-item">${index + 1}. ${text}</div>`;
  }).join('');
}

function calculatePolygonArea(positions) {
  let area = 0;
  const cartographics = positions.map(pos => Cesium.Cartographic.fromCartesian(pos));
  
  for (let i = 0; i < cartographics.length; i++) {
    const j = (i + 1) % cartographics.length;
    area += cartographics[i].longitude * cartographics[j].latitude;
    area -= cartographics[j].longitude * cartographics[i].latitude;
  }
  
  return Math.abs(area) * 6378137 * 6378137 / 2;
}

// Export default object for lazy loading
export default {
  startDistanceMeasurement,
  startAreaMeasurement,
  startHeightMeasurement,
  clearAllMeasurements
};

