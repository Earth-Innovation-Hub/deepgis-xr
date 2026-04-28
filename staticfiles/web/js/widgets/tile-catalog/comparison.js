/**
 * Comparison-mode helpers (Phase 4).
 *
 * Wraps Cesium's imagery split primitives for the timeseries panel:
 *
 *   - Swipe mode: two layers active at the same time, one drawn left of
 *     a vertical split line, the other right. Position is controlled
 *     by viewer.scene.splitPosition (0..1).
 *
 *   - Overlay mode: both layers drawn full-screen but at half opacity,
 *     so spatial differences read as a visual blend ("ghost" diff).
 *     Cesium doesn't ship a true MULTIPLY/SUBTRACT mode for imagery,
 *     so this is the pragmatic best we can offer without a custom
 *     shader.
 *
 *   - Single mode: clears any split / blend state set by the others.
 *
 * The actual "which layer goes left vs right" decision is owned by the
 * caller (timeseries-panel.js) -- this module just exposes setters.
 */

const SD = (typeof Cesium !== 'undefined' && Cesium.SplitDirection) ? Cesium.SplitDirection : null;

/**
 * Find the Cesium ImageryLayer for the given tileserver layer_id.
 * Returns null if the layer isn't currently active.
 */
export function findImageryLayer(viewer, layerId, currentLayers) {
  if (!viewer) return null;
  const overlay = currentLayers?.overlays?.[layerId];
  return overlay || null;
}

/**
 * Set a layer's split direction. mode must be 'left', 'right', or 'none'.
 * Falls back gracefully if Cesium.SplitDirection isn't available.
 */
export function setLayerSplitDirection(layer, mode) {
  if (!layer || !SD) return;
  switch (mode) {
    case 'left':  layer.splitDirection = SD.LEFT;  break;
    case 'right': layer.splitDirection = SD.RIGHT; break;
    case 'none':
    default:      layer.splitDirection = SD.NONE;  break;
  }
}

/**
 * Set the global split position (0..1). 0.5 = vertical split at screen
 * midpoint. Cesium routes this through viewer.scene.splitPosition or
 * scene.imagerySplitPosition depending on version.
 */
export function setSplitPosition(viewer, ratio) {
  if (!viewer || !viewer.scene) return;
  const v = Math.max(0, Math.min(1, ratio));
  if ('splitPosition' in viewer.scene) {
    viewer.scene.splitPosition = v;
  } else if ('imagerySplitPosition' in viewer.scene) {
    viewer.scene.imagerySplitPosition = v;
  }
  viewer.scene.requestRender?.();
}

/**
 * Reset all comparison-related state on a list of imagery layers:
 * clear split direction and restore opacity from the supplied map.
 */
export function clearComparison(layers, opacityByLayerId) {
  for (const { layer, layerId } of layers) {
    if (!layer) continue;
    setLayerSplitDirection(layer, 'none');
    if (opacityByLayerId && layerId in opacityByLayerId) {
      layer.alpha = opacityByLayerId[layerId];
    }
  }
}

/**
 * Apply swipe mode: layerA gets LEFT, layerB gets RIGHT. Both keep
 * their current opacity. Caller is responsible for calling
 * setSplitPosition() initially (default 0.5).
 */
export function applySwipe(layerA, layerB) {
  setLayerSplitDirection(layerA, 'left');
  setLayerSplitDirection(layerB, 'right');
}

/**
 * Apply overlay mode: both layers full-screen, each at half opacity.
 * Returns the previous opacity values so callers can restore on exit.
 */
export function applyOverlay(layerA, layerB) {
  const prev = {
    a: layerA?.alpha ?? null,
    b: layerB?.alpha ?? null,
  };
  setLayerSplitDirection(layerA, 'none');
  setLayerSplitDirection(layerB, 'none');
  if (layerA) layerA.alpha = 0.5;
  if (layerB) layerB.alpha = 0.5;
  return prev;
}
