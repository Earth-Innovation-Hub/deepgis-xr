/**
 * Feature-layer registry (Tier-D layer manager).
 *
 * Tileserver-backed raster/vector layers are managed by
 * `core/layer-management.js` (they have their own discovery flow via
 * `/data.json`). This module handles the other category of "feature"
 * layers — things like OSM 3D Buildings and Cesium World Terrain that
 * are toggled on/off as single units and that, pre-refactor, each owned
 * its own bespoke setup path duplicated across page templates.
 *
 * Design goals
 *   - One descriptor per feature layer; pages pick layers by id.
 *   - Idempotent enable() / disable() (safe to call with the same state).
 *   - isEnabled() reflects the actual layer, not a checkbox shadow state,
 *     so UI can be rehydrated from current state on page load.
 *   - Lazy-loaded implementations: heavier layers (ADS-B, weather) can
 *     dynamic-import their utils module the first time they're enabled
 *     without pulling that code into the critical-path bundle.
 *
 * See `notes/2026-04-22-deepgis-xr-refactoring.md` (Tier D) for the plan
 * that motivates this module and the duplications it replaces.
 */

import { AppState } from '../state.js';
import { toggleOSMBuildings } from './cesium-init.js';
import { toggleTerrain } from './base-map.js';

/**
 * @typedef {Object} FeatureLayerDescriptor
 * @property {string}   id          Stable id used as a registry key and DOM id suffix.
 * @property {string}   label       Human-readable label for the toggle row.
 * @property {string}   category    Loose grouping, e.g. 'buildings', 'terrain',
 *                                  'weather', 'aircraft'. UIs may use this to
 *                                  split toggles into sections.
 * @property {string}  [description]Tooltip / helper text.
 * @property {string}  [icon]       Font Awesome class (e.g. 'fas fa-building').
 * @property {string}  [shortcut]   Optional keyboard shortcut character.
 * @property {(viewer: any) => (void|Promise<void>)} enable
 * @property {(viewer: any) => (void|Promise<void>)} disable
 * @property {() => boolean} isEnabled
 */

/** @type {Map<string, FeatureLayerDescriptor>} */
const registry = new Map();

/**
 * Register a feature layer descriptor. Returns the descriptor so callers
 * can keep a handle to it for custom UI.
 * @param {FeatureLayerDescriptor} descriptor
 */
export function registerFeatureLayer(descriptor) {
  if (!descriptor || !descriptor.id) {
    throw new Error('registerFeatureLayer: descriptor.id is required');
  }
  if (typeof descriptor.enable !== 'function' || typeof descriptor.disable !== 'function') {
    throw new Error(`registerFeatureLayer(${descriptor.id}): enable/disable must be functions`);
  }
  if (typeof descriptor.isEnabled !== 'function') {
    throw new Error(`registerFeatureLayer(${descriptor.id}): isEnabled must be a function`);
  }
  if (registry.has(descriptor.id)) {
    console.warn(`[feature-layers] overwriting existing registration for ${descriptor.id}`);
  }
  registry.set(descriptor.id, descriptor);
  return descriptor;
}

/** @param {string} id */
export function getFeatureLayer(id) {
  return registry.get(id);
}

/**
 * List all registered descriptors, optionally filtered by category.
 * @param {{ category?: string }} [filter]
 * @returns {FeatureLayerDescriptor[]}
 */
export function listFeatureLayers(filter = {}) {
  const items = [...registry.values()];
  return filter.category ? items.filter(d => d.category === filter.category) : items;
}

/**
 * Drive a feature layer through its enable/disable entry point. Resolves
 * after the layer state settles; rejects if the descriptor is unknown or
 * if the underlying enable/disable throws.
 * @param {string} id
 * @param {any} viewer
 * @param {boolean} enabled
 */
export async function setFeatureLayerEnabled(id, viewer, enabled) {
  const d = registry.get(id);
  if (!d) throw new Error(`Unknown feature layer: ${id}`);
  if (!viewer) throw new Error(`setFeatureLayerEnabled(${id}): viewer is required`);
  if (enabled) {
    await d.enable(viewer);
  } else {
    await d.disable(viewer);
  }
  return d.isEnabled();
}

/**
 * Render a column of Bootstrap form-check toggle rows for the given
 * layer ids into `container`. The rendered markup matches the existing
 * HUD styling used on label_search.html so pages can drop this in
 * without a separate stylesheet.
 *
 * Intended for use by page templates that want the registry-backed
 * toggles without hand-rolling the DOM + event-wiring each time (see
 * label_topology.html for the first consumer).
 *
 * @param {HTMLElement} container
 * @param {string[]} layerIds
 * @param {{ getViewer?: () => any }} [options]
 */
export function renderFeatureLayerToggles(container, layerIds, options = {}) {
  if (!container) return;
  const getViewer = options.getViewer || (() => window.viewer || AppState.viewer);

  for (const id of layerIds) {
    const d = registry.get(id);
    if (!d) {
      console.warn(`[feature-layers] renderFeatureLayerToggles: no descriptor for ${id}`);
      continue;
    }

    const row = document.createElement('div');
    row.className = 'form-check mb-2';
    row.dataset.featureLayerId = id;

    const checkbox = document.createElement('input');
    checkbox.className = 'form-check-input';
    checkbox.type = 'checkbox';
    checkbox.id = `feature-layer-${id}`;
    checkbox.checked = !!d.isEnabled();

    const label = document.createElement('label');
    label.className = 'form-check-label';
    label.setAttribute('for', checkbox.id);
    label.style.cssText = 'color: #cbd5e1; font-size: 0.85rem;';
    label.innerHTML = `${d.icon ? `<i class="${d.icon} me-2"></i>` : ''}${d.label}`;
    if (d.description) label.title = d.description;

    row.append(checkbox, label);
    container.appendChild(row);

    checkbox.addEventListener('change', async (e) => {
      const target = /** @type {HTMLInputElement} */ (e.target);
      const desiredState = target.checked;
      const viewer = getViewer();
      if (!viewer) {
        console.warn(`[feature-layers] ${id}: viewer not ready yet`);
        target.checked = !desiredState;
        return;
      }
      try {
        await setFeatureLayerEnabled(id, viewer, desiredState);
      } catch (err) {
        console.error(`[feature-layers] failed to ${desiredState ? 'enable' : 'disable'} ${id}:`, err);
        target.checked = !desiredState;
      }
    });

    if (d.shortcut) bindShortcut(d.shortcut, checkbox);
  }
}

/**
 * Wire a single-character keyboard shortcut to flip a checkbox and
 * dispatch a change event. Mirrors the hand-rolled bindings in
 * label_search.html (e.g. `B` for buildings, `T` for terrain) so pages
 * adopting the registry get the same UX for free.
 */
function bindShortcut(key, checkbox) {
  const wanted = key.toLowerCase();
  document.addEventListener('keydown', (e) => {
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if ((e.key || '').toLowerCase() !== wanted) return;
    e.preventDefault();
    checkbox.checked = !checkbox.checked;
    checkbox.dispatchEvent(new Event('change'));
  });
}

// --------------------------------------------------------------------------
// Built-in registrations
// --------------------------------------------------------------------------

// OSM 3D Buildings — global building footprints from OpenStreetMap (ODbL).
// `toggleOSMBuildings` is the canonical helper from core/cesium-init.js;
// it already handles lazy tileset creation and caches the primitive on
// AppState.currentLayers.osmBuildings.
registerFeatureLayer({
  id: 'osm-buildings',
  label: '3D Buildings (OSM)',
  category: 'buildings',
  description: 'OpenStreetMap 3D building footprints. Free & open (ODbL).',
  icon: 'fas fa-building',
  shortcut: 'b',
  enable: (viewer) => toggleOSMBuildings(viewer, true),
  disable: (viewer) => toggleOSMBuildings(viewer, false),
  isEnabled: () => !!AppState.currentLayers.osmBuildings?.show
});

// Cesium World Terrain — high-resolution global terrain from Cesium Ion.
// `toggleTerrain` swaps out `viewer.terrainProvider` directly rather than
// caching on AppState, so we read the live state from the viewer: anything
// other than the default EllipsoidTerrainProvider means 3D terrain is on.
registerFeatureLayer({
  id: 'cesium-world-terrain',
  label: 'World Terrain',
  category: 'terrain',
  description: 'High-resolution global terrain (Cesium Ion).',
  icon: 'fas fa-mountain',
  shortcut: 't',
  enable: (viewer) => toggleTerrain(viewer, true),
  disable: (viewer) => toggleTerrain(viewer, false),
  isEnabled: () => {
    const v = (typeof window !== 'undefined' && window.viewer) || AppState.viewer;
    if (!v || !v.terrainProvider) return false;
    // Cesium may not be loaded in tests; fall back to a duck-type check.
    const Ellipsoid = (typeof Cesium !== 'undefined' && Cesium.EllipsoidTerrainProvider) || null;
    if (Ellipsoid) return !(v.terrainProvider instanceof Ellipsoid);
    return !/ellipsoid/i.test(v.terrainProvider.constructor?.name || '');
  }
});

// --------------------------------------------------------------------------
// TODO (Tier D follow-up): register NWS weather stations, OpenSky ADS-B,
// canopy-height, and the oceanographic / Sentinel-2 overlays once their
// widgets expose a stable enable/disable surface. Each of those is
// currently driven by its own HUD panel, so the registry interface needs
// to coexist with panel-specific UX before we flip the switch. See
// notes/2026-04-22-deepgis-xr-refactoring.md (Tier D, sections on
// per-layer lifecycle normalisation).
// --------------------------------------------------------------------------

export default {
  registerFeatureLayer,
  getFeatureLayer,
  listFeatureLayers,
  setFeatureLayerEnabled,
  renderFeatureLayerToggles
};
