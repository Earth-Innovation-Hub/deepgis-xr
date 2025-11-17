/**
 * Base Map Management
 * Handles base map selection and terrain toggling
 */
import { AppState } from '../state.js';

/**
 * Toggle terrain
 */
export async function toggleTerrain(viewer, enabled) {
  if (enabled) {
    try {
      if (typeof Cesium.createWorldTerrainAsync === 'function') {
        viewer.terrainProvider = await Cesium.createWorldTerrainAsync();
        if (typeof window.updateStatusIndicator === 'function') {
          window.updateStatusIndicator('Ion 3D Terrain enabled');
        }
      } else if (typeof Cesium.createWorldTerrain === 'function') {
        viewer.terrainProvider = Cesium.createWorldTerrain();
        if (typeof window.updateStatusIndicator === 'function') {
          window.updateStatusIndicator('Ion 3D Terrain enabled');
        }
      } else {
        viewer.terrainProvider = new Cesium.CesiumTerrainProvider({
          url: Cesium.IonResource.fromAssetId(1)
        });
        if (typeof window.updateStatusIndicator === 'function') {
          window.updateStatusIndicator('Ion 3D Terrain enabled (legacy)');
        }
      }
    } catch (error) {
      console.warn('Failed to enable Ion terrain:', error);
      viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('3D Terrain disabled (fallback)');
      }
    }
  } else {
    viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator('3D Terrain disabled');
    }
  }
}

/**
 * Change base map
 */
export async function changeBaseMap(viewer, mapType) {
  // Remove only base map layers, preserve tileserver layers
  const layersToRemove = [];
  for (let i = viewer.imageryLayers.length - 1; i >= 0; i--) {
    const layer = viewer.imageryLayers.get(i);
    const credit = layer.imageryProvider?.credit?.html || '';
    const isTileServerLayer = credit.includes('DeepGIS TileServer') || 
                             layer === AppState.currentLayers.baseRaster ||
                             Object.values(AppState.currentLayers.overlays).includes(layer);
    
    if (!isTileServerLayer) {
      layersToRemove.push(layer);
    }
  }
  
  layersToRemove.forEach(layer => {
    viewer.imageryLayers.remove(layer);
    if (layer.imageryProvider?.destroy) {
      try {
        layer.imageryProvider.destroy();
      } catch (e) {
        console.warn('Error disposing base map provider:', e);
      }
    }
  });

  let imageryProvider;
  switch (mapType) {
    case 'ion_satellite':
      try {
        if (typeof Cesium.createWorldImageryAsync === 'function') {
          if (typeof window.updateStatusIndicator === 'function') {
            window.updateStatusIndicator('Loading Ion satellite imagery...');
          }
          imageryProvider = await Cesium.createWorldImageryAsync({
            style: Cesium.IonWorldImageryStyle.AERIAL
          });
        } else if (typeof Cesium.createWorldImagery === 'function') {
          imageryProvider = Cesium.createWorldImagery({
            style: Cesium.IonWorldImageryStyle.AERIAL
          });
        } else {
          imageryProvider = await Cesium.IonImageryProvider.fromAssetId(2);
        }
      } catch (error) {
        console.warn('Ion satellite imagery failed:', error);
        imageryProvider = null;
      }
      break;
    case 'ion_streets':
      try {
        if (typeof Cesium.createWorldImageryAsync === 'function') {
          if (typeof window.updateStatusIndicator === 'function') {
            window.updateStatusIndicator('Loading Ion streets imagery...');
          }
          imageryProvider = await Cesium.createWorldImageryAsync({
            style: Cesium.IonWorldImageryStyle.ROAD
          });
        } else if (typeof Cesium.createWorldImagery === 'function') {
          imageryProvider = Cesium.createWorldImagery({
            style: Cesium.IonWorldImageryStyle.ROAD
          });
        } else {
          imageryProvider = await Cesium.IonImageryProvider.fromAssetId(3);
        }
      } catch (error) {
        console.warn('Ion streets imagery failed:', error);
        imageryProvider = null;
      }
      break;
    case 'none':
      if (typeof window.updateStatusIndicator === 'function') {
        window.updateStatusIndicator('Base map disabled');
      }
      return;
    default:
      // Default to Ion satellite imagery
      try {
        if (typeof Cesium.createWorldImageryAsync === 'function') {
          imageryProvider = await Cesium.createWorldImageryAsync({
            style: Cesium.IonWorldImageryStyle.AERIAL
          });
        } else if (typeof Cesium.createWorldImagery === 'function') {
          imageryProvider = Cesium.createWorldImagery({
            style: Cesium.IonWorldImageryStyle.AERIAL
          });
        } else {
          imageryProvider = await Cesium.IonImageryProvider.fromAssetId(2);
        }
      } catch (error) {
        console.warn('Failed to create default Ion imagery:', error);
        imageryProvider = null;
      }
  }

  if (imageryProvider) {
    viewer.imageryLayers.addImageryProvider(imageryProvider);
    if (typeof window.updateStatusIndicator === 'function') {
      window.updateStatusIndicator(`Base map: ${mapType}`);
    }
  }
}

export default {
  toggleTerrain,
  changeBaseMap
};

