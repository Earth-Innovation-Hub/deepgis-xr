/**
 * 3D Model Loading Feature Module
 * Lazy loaded when model functionality is needed
 */
import { AppState } from '../js/state.js';
import { CONFIG } from '../js/config.js';

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
 * Quick load model at current camera location with true scale
 * Optimized for fastest loading with minimal configuration
 */
export async function quickLoadAtCurrentLocation(viewer, modelUrl = null) {
  // Use provided URL or get from input field
  const url = modelUrl || document.getElementById('modelUrl')?.value?.trim();
  
  if (!url) {
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('Model URL not available');
    }
    return;
  }

  if (typeof window.updateStatusIndicator === 'function') {
    window.updateStatusIndicator('Quick loading model at current location...');
  }

  try {
    // Get current camera position
    const cameraPosition = viewer.camera.positionCartographic;
    const modelPosition = Cesium.Cartesian3.fromRadians(
      cameraPosition.longitude,
      cameraPosition.latitude,
      0  // Place on ground
    );

    // Check if it's an Ion Asset ID
    if (/^\d+$/.test(url)) {
      const ionAssetId = parseInt(url);
      const tileset = await Cesium.Cesium3DTileset.fromIonAssetId(ionAssetId);
      
      const transform = Cesium.Transforms.eastNorthUpToFixedFrame(modelPosition);
      tileset.modelMatrix = transform;  // True scale (1:1)
      
      viewer.scene.primitives.add(tileset);
      AppState.currentLayers.models.push(tileset);
      
      viewer.zoomTo(tileset);
      
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator(`Ion 3D Tileset ${ionAssetId} loaded at current location (1:1 scale)`);
      }
      if (typeof window.showSnackBar === 'function') {
        window.showSnackBar(`3D Tileset loaded from Cesium Ion at current location`, 'success');
      }
      
    } else {
      // Load as regular GLTF/GLB model with optimized settings for speed
      const entity = viewer.entities.add({
        name: 'Quick Load Model',
        position: modelPosition,
        model: {
          uri: url,
          scale: 1.0,  // True scale (1:1)
          minimumPixelSize: 64,
          maximumScale: 10000,
          runAnimations: true,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          show: true,
          incrementallyLoadTextures: true,  // Fast progressive loading
          backFaceCulling: false,
          shadows: Cesium.ShadowMode.ENABLED
        }
      });

      // Wait for model to be ready
      await entity.model.readyPromise;
      
      AppState.currentLayers.models.push(entity);
      
      // Quick zoom to model
      viewer.zoomTo(entity, new Cesium.HeadingPitchRange(0, -45, 200));
      
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('Model loaded at current location (1:1 scale)');
      }
      if (typeof window.showSnackBar === 'function') {
        window.showSnackBar('3D model quick-loaded successfully at current location', 'success');
      }
    }

  } catch (error) {
    console.error('Error quick loading model:', error);
    
    let errorMessage = 'Unknown error occurred';
    if (error.message.includes('CORS')) {
      errorMessage = 'CORS policy blocked the model loading';
    } else if (error.message.includes('404')) {
      errorMessage = 'Model file not found (404)';
    } else if (error.message.includes('timeout')) {
      errorMessage = 'Model loading timed out';
    } else {
      errorMessage = error.message;
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
  quickLoadAtCurrentLocation,
  removeModels
};

