/**
 * 3D Model Loading Feature Module
 * Lazy loaded when model functionality is needed
 */
import { AppState } from '../state.js';
import { CONFIG } from '../config.js';

/**
 * Load GLTF/GLB model
 */
export async function loadGLTFModel(viewer) {
  const modelUrl = document.getElementById('modelUrl')?.value?.trim();
  if (!modelUrl) {
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('Model URL not available');
    }
    return;
  }

  const locationOption = document.getElementById('modelLocation')?.value || 'current_view';
  const scale = parseFloat(document.getElementById('modelScale')?.value || '1.0');

  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Loading 3D model...');
  }

  try {
    let modelPosition;
    let shouldZoomToLocation = false;

    switch (locationOption) {
      case 'mount_everest':
        modelPosition = Cesium.Cartesian3.fromDegrees(86.9250, 27.9881, 8848);
        shouldZoomToLocation = true;
        break;
      
      case 'custom':
        const customLon = parseFloat(document.getElementById('customLon')?.value);
        const customLat = parseFloat(document.getElementById('customLat')?.value);
        const customAlt = parseFloat(document.getElementById('customAlt')?.value || '0');
        
        if (isNaN(customLon) || isNaN(customLat)) {
          if (typeof window.updateStatusIndicator === 'function') {
            window.updateStatusIndicator('Please enter valid custom coordinates');
          }
          return;
        }
        
        modelPosition = Cesium.Cartesian3.fromDegrees(customLon, customLat, customAlt);
        shouldZoomToLocation = true;
        break;
      
      case 'current_view':
      default:
        const cameraPosition = viewer.camera.positionCartographic;
        modelPosition = Cesium.Cartesian3.fromRadians(
          cameraPosition.longitude,
          cameraPosition.latitude,
          0
        );
        break;
    }

    // Check if it's an Ion Asset ID
    if (/^\d+$/.test(modelUrl)) {
      const ionAssetId = parseInt(modelUrl);
      const tileset = await Cesium.Cesium3DTileset.fromIonAssetId(ionAssetId);
      
      const transform = Cesium.Transforms.eastNorthUpToFixedFrame(modelPosition);
      const scaleMatrix = Cesium.Matrix4.fromUniformScale(scale);
      tileset.modelMatrix = Cesium.Matrix4.multiply(transform, scaleMatrix, new Cesium.Matrix4());
      
      viewer.scene.primitives.add(tileset);
      AppState.currentLayers.models.push(tileset);
      
      if (shouldZoomToLocation) {
        viewer.camera.setView({
          destination: Cesium.Cartesian3.fromDegrees(
            Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(modelPosition).longitude),
            Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(modelPosition).latitude),
            1000
          )
        });
      } else {
        viewer.zoomTo(tileset);
      }
      
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator(`Ion 3D Tileset ${ionAssetId} loaded successfully`);
      }
      if (typeof window.showSnackBar === 'function') {
        window.showSnackBar(`3D Tileset loaded from Cesium Ion (Asset ID: ${ionAssetId})`);
      }
      
    } else {
      // Load as regular GLTF/GLB model
      const entity = viewer.entities.add({
        name: 'GLTF Model - Navagunjara Digital Twin',
        position: modelPosition,
        model: {
          uri: modelUrl,
          scale: scale,
          minimumPixelSize: 64,
          maximumScale: 10000,
          runAnimations: true,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          silhouetteColor: Cesium.Color.YELLOW,
          silhouetteSize: 2.0,
          show: true,
          distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0.0, 50000.0),
          incrementallyLoadTextures: true,
          backFaceCulling: false,
          shadows: Cesium.ShadowMode.ENABLED
        }
      });

      await entity.model.readyPromise;
      
      AppState.currentLayers.models.push(entity);
      
      if (shouldZoomToLocation) {
        viewer.camera.setView({
          destination: Cesium.Cartesian3.fromDegrees(
            Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(modelPosition).longitude),
            Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(modelPosition).latitude),
            500
          ),
          orientation: {
            heading: Cesium.Math.toRadians(0),
            pitch: Cesium.Math.toRadians(0),
            roll: 0.0
          }
        });
      } else {
        viewer.zoomTo(entity, new Cesium.HeadingPitchRange(0, 0, 200));
      }
      
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('3D model loaded successfully');
      }
      if (typeof window.showSnackBar === 'function') {
        window.showSnackBar('3D model loaded successfully');
      }
    }

  } catch (error) {
    console.error('Error loading model:', error);
    
    let errorMessage = 'Unknown error occurred';
    if (error.message.includes('CORS')) {
      errorMessage = 'CORS policy blocked the model loading';
    } else if (error.message.includes('404')) {
      errorMessage = 'Model file not found (404)';
    } else if (error.message.includes('timeout')) {
      errorMessage = 'Model loading timed out';
    }
    
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator(`Error: ${errorMessage}`);
    }
    if (typeof window.showSnackBar === 'function') {
      window.showSnackBar(`Failed to load 3D model: ${errorMessage}`, 'error');
    }
  }
}

/**
 * Remove all models
 */
export function removeModels(viewer) {
  AppState.currentLayers.models.forEach(model => {
    if (model.entities) {
      viewer.entities.remove(model);
    } else {
      viewer.scene.primitives.remove(model);
    }
  });
  AppState.currentLayers.models = [];
  
  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('3D models removed');
  }
}

// Export default object for lazy loading
export default {
  loadGLTFModel,
  removeModels
};

