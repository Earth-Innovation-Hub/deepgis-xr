/**
 * Screen-space-error policy per Cesium SceneMode.
 * Kept out of config.js so modules importing it never depend on a new export
 * from a config.js that browsers may still have cached.
 */
import { CONFIG } from '../config.js';

/**
 * Cesium measures SSE in CSS pixels, so on HiDPI displays each allowed error
 * pixel spans several device pixels and 2D imagery looks soft. In 2D the value
 * is divided by devicePixelRatio (capped at 1.5 to bound tile count).
 */
export function screenSpaceErrorForMode(mode) {
  const modes = CONFIG.MEMORY.MODE_SPECIFIC;
  if (mode === Cesium.SceneMode.SCENE2D) {
    const dpr = Math.min(Math.max(window.devicePixelRatio || 1, 1), 1.5);
    return modes.SCENE2D.MAX_SCREEN_SPACE_ERROR / dpr;
  }
  if (mode === Cesium.SceneMode.COLUMBUS_VIEW) {
    return modes.COLUMBUS_VIEW.MAX_SCREEN_SPACE_ERROR;
  }
  return modes.SCENE3D.MAX_SCREEN_SPACE_ERROR;
}
