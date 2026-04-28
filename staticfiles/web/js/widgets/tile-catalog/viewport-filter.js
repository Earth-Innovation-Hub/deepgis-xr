/**
 * Viewport filter (Phase 5).
 *
 * When AppState.viewportFilterEnabled is true, only Sites whose
 * bounds intersect the current camera viewport are shown in Tier-1.
 * The filter listens to Cesium's camera moveEnd and asks the parent
 * panel to re-render whenever the camera comes to rest.
 *
 * Activation lives on the catalog control bar; the actual filtering
 * happens in index.js when it walks AppState.catalog.sites.
 */
import { AppState } from '../../state.js';

let _moveEndOff = null;
let _onCameraSettled = null;

/**
 * Compute the camera viewport in WGS84 degrees as [w, s, e, n].
 * Returns null if the camera is in a state where no rectangle can
 * be computed (e.g. looking off-globe in 3D).
 */
export function getViewportBboxDeg(viewer) {
  if (!viewer || !viewer.camera) return null;
  let rect;
  try {
    rect = viewer.camera.computeViewRectangle();
  } catch (e) {
    return null;
  }
  if (!rect) return null;
  return [
    Cesium.Math.toDegrees(rect.west),
    Cesium.Math.toDegrees(rect.south),
    Cesium.Math.toDegrees(rect.east),
    Cesium.Math.toDegrees(rect.north),
  ];
}

/**
 * Walk catalog sites and return the slugs that intersect the
 * viewport. Sites without bounds are always visible (defensive
 * default -- we don't want to "hide" a misconfigured site).
 */
export function visibleSiteSlugs(sites, viewportBbox) {
  if (!viewportBbox) return new Set(sites.map(s => s.slug));
  const [vw, vs, ve, vn] = viewportBbox;
  const visible = new Set();
  for (const site of sites) {
    if (!site.bounds || site.bounds.length !== 4) {
      visible.add(site.slug);
      continue;
    }
    const [w, s, e, n] = site.bounds;
    if (!(w > ve || e < vw || s > vn || n < vs)) {
      visible.add(site.slug);
    }
  }
  return visible;
}

/**
 * Subscribe / unsubscribe to camera moveEnd, calling onSettled() when
 * the camera comes to rest. Idempotent: calling enable() twice
 * replaces the prior subscription.
 */
export function enableMoveEndWatcher(viewer, onSettled) {
  disableMoveEndWatcher();
  if (!viewer || !viewer.camera || !viewer.camera.moveEnd) return;
  _onCameraSettled = onSettled;
  _moveEndOff = viewer.camera.moveEnd.addEventListener(() => {
    if (_onCameraSettled) {
      try { _onCameraSettled(); } catch (e) { console.warn('[viewport-filter]', e); }
    }
  });
}

export function disableMoveEndWatcher() {
  if (_moveEndOff) {
    try { _moveEndOff(); } catch (_) { /* fn() removes the listener */ }
    _moveEndOff = null;
  }
  _onCameraSettled = null;
}
