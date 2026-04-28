/**
 * Tier-2 view for timeseries datasets (Phase 3).
 *
 * Replaces the old "five separate orthophoto checkboxes" UX with two
 * orthogonal axes:
 *
 *   1. A horizontal time scrubber (one tick per Timestep, sorted
 *      chronologically by sort_key).
 *   2. A short list of "product kinds" the dataset publishes
 *      (orthophoto, vector, mesh_3d, ...). Each kind has a single
 *      master toggle and a single opacity slider.
 *
 * The user picks "I want to see the orthophoto" once, then scrubs
 * through time to see how the site evolved -- the panel handles
 * swapping the underlying tile layer at each timestep transition.
 *
 * Per-dataset UI state lives in AppState.catalog.timeseriesState so it
 * survives re-renders triggered by the parent panel.
 */
import { AppState } from '../../state.js';
import {
  toggleOverlayLayer,
  toggleVectorLayer,
} from '../../core/layer-management.js';
import { cssSafe, escapeHtml } from './index.js';

const KIND_BADGES = {
  orthophoto:   { icon: 'fa-image',         color: 'primary',   label: 'orthophoto' },
  vector:       { icon: 'fa-vector-square', color: 'info',      label: 'vector' },
  mesh_3d:      { icon: 'fa-cube',          color: 'warning',   label: '3D mesh' },
  pca:          { icon: 'fa-palette',       color: 'success',   label: 'PCA' },
  rgb_low_zoom: { icon: 'fa-image',         color: 'secondary', label: 'RGB (low z)' },
  kmeans:       { icon: 'fa-th-large',      color: 'success',   label: 'classify' },
  polygons:     { icon: 'fa-draw-polygon',  color: 'info',      label: 'polygons' },
  raw:          { icon: 'fa-database',      color: 'dark',      label: 'raw' },
  other:        { icon: 'fa-layer-group',   color: 'secondary', label: 'other' },
};

/**
 * Internal: catalog of all product kinds present in a dataset, plus a
 * (kind, timestep) -> Product lookup. Computed from the dataset's
 * timesteps; results are deterministic across re-renders.
 */
function indexDataset(dataset) {
  const kinds = new Set();
  // Map<kind, Map<timestepLabel, Product>>
  const byKindAndTs = new Map();
  // Set<kind> that has more than one product within a single timestep
  // (e.g. Dec 2020 has 3 vectors). We pick the canonical one by
  // ordering and surface the others via a "more" disclosure.
  const variantKinds = new Set();

  for (const ts of dataset.timesteps || []) {
    for (const product of ts.products || []) {
      kinds.add(product.kind);
      let kindMap = byKindAndTs.get(product.kind);
      if (!kindMap) {
        kindMap = new Map();
        byKindAndTs.set(product.kind, kindMap);
      }
      const existing = kindMap.get(ts.label);
      if (!existing) {
        kindMap.set(ts.label, product);
      } else {
        variantKinds.add(product.kind);
        // Keep whichever has the lower 'ordering' as canonical.
        if ((product.ordering ?? 0) < (existing.ordering ?? 0)) {
          kindMap.set(ts.label, product);
        }
      }
    }
  }

  const orderedKinds = Array.from(kinds);
  orderedKinds.sort((a, b) => kindRank(a) - kindRank(b));

  return { kinds: orderedKinds, byKindAndTs, variantKinds };
}

function kindRank(kind) {
  // Show orthophoto first, vectors next, exotica last.
  const order = ['orthophoto', 'rgb_low_zoom', 'vector', 'polygons', 'mesh_3d', 'pca', 'kmeans', 'raw', 'other'];
  const idx = order.indexOf(kind);
  return idx === -1 ? 99 : idx;
}

/**
 * Initialize (or reuse) per-dataset UI state. Returns the live state object.
 */
function getOrInitState(dataset) {
  let state = AppState.catalog.timeseriesState[dataset.slug];
  if (!state) {
    const firstTs = (dataset.timesteps || [])[0];
    state = {
      activeTimestepLabel: firstTs ? firstTs.label : null,
      enabledKinds: new Set(),
      // Per-kind opacity, defaults derived lazily from each product.
      opacityByKind: {},
      // Last activated layer per kind, so we can toggle it off when the
      // scrubber moves to a different timestep.
      activeLayerByKind: {},
    };
    AppState.catalog.timeseriesState[dataset.slug] = state;
  }
  return state;
}

/**
 * Returns a numeric WSG84 score so we know which timestep maps to
 * which scrubber tick position. Sort_key is an ISO date string by
 * convention; falls back to label string compare if not parseable.
 */
function timestepScore(ts) {
  const t = Date.parse(ts.sortKey || ts.label);
  return isNaN(t) ? 0 : t;
}

// --------------------------------------------------------------------- //
// Public API                                                             //
// --------------------------------------------------------------------- //

export function renderTimeseriesPanel(container, { site, dataset }) {
  if (!container) return;

  const timesteps = (dataset.timesteps || []).slice().sort((a, b) => timestepScore(a) - timestepScore(b));
  if (timesteps.length === 0) {
    container.innerHTML = '<small class="text-muted">No timesteps in this dataset.</small>';
    return;
  }

  const idx = indexDataset({ ...dataset, timesteps });
  const state = getOrInitState(dataset);

  // Backfill default opacity per kind from the first product encountered.
  for (const kind of idx.kinds) {
    if (state.opacityByKind[kind] == null) {
      const kindMap = idx.byKindAndTs.get(kind);
      const firstProduct = kindMap ? Array.from(kindMap.values())[0] : null;
      state.opacityByKind[kind] = firstProduct ? (firstProduct.defaultOpacity ?? 0.7) : 0.7;
    }
  }

  const dsKey   = cssSafe(dataset.slug);
  const dsHasMultiple = idx.variantKinds.size > 0;

  container.innerHTML = `
    <div class="tc-dataset-header">
      <strong>${escapeHtml(dataset.name)}</strong>
      <span class="badge bg-warning text-dark ms-2" style="font-size:0.7em;">timeseries: ${timesteps.length}</span>
      ${dataset.description ? `<div><small class="text-muted">${escapeHtml(dataset.description)}</small></div>` : ''}
    </div>

    <div class="tc-scrubber" id="tc_scrub_${dsKey}">
      <div class="tc-scrubber-controls">
        <button type="button" class="btn btn-link btn-sm tc-scrubber-prev p-0"
                title="Previous timestep"><i class="fas fa-caret-left"></i></button>
        <div class="tc-scrubber-track">
          ${timesteps.map((ts, i) => renderTick(ts, i, timesteps.length, idx, state)).join('')}
        </div>
        <button type="button" class="btn btn-link btn-sm tc-scrubber-next p-0"
                title="Next timestep"><i class="fas fa-caret-right"></i></button>
      </div>
      <div class="tc-scrubber-readout">
        <i class="fas fa-clock me-1"></i>
        <strong class="tc-active-ts-label">${escapeHtml(state.activeTimestepLabel || '?')}</strong>
        <small class="text-muted ms-2 tc-active-ts-desc"></small>
      </div>
    </div>

    <div class="tc-kind-list">
      ${idx.kinds.map(kind => renderKindRow(kind, idx, state, dsKey)).join('')}
    </div>

    ${dsHasMultiple ? `
      <details class="tc-variants-disclosure">
        <summary><i class="fas fa-layer-group me-1"></i>Alternate snapshots within a timestep</summary>
        <small class="text-muted d-block">Some timesteps publish more than one product of a kind (e.g. multiple Dec 2020 vector snapshots). The scrubber shows the canonical one; toggle alternates here.</small>
        <div class="tc-variants-list" id="tc_variants_${dsKey}"></div>
      </details>
    ` : ''}
  `;

  // Surface the active timestep's description (rare but useful).
  refreshScrubberReadout(container, dataset, state, timesteps);
  if (dsHasMultiple) {
    renderVariantList(container.querySelector(`#tc_variants_${dsKey}`), dataset, idx, state, timesteps);
  }

  wireScrubber(container, dataset, idx, state, timesteps);
  wireKindRows(container, dataset, idx, state, timesteps);
}

function renderTick(ts, i, total, idx, state) {
  const isActive = ts.label === state.activeTimestepLabel;
  const tickKey = cssSafe(`${ts.label}_${i}`);
  // What kinds are available at this timestep? Render small dots so
  // the user sees ahead-of-time which timesteps lack a particular kind.
  const availableKinds = Array.from(idx.byKindAndTs.entries())
    .filter(([_, kindMap]) => kindMap.has(ts.label))
    .map(([kind, _]) => kind);

  const dots = availableKinds.map(k => {
    const meta = KIND_BADGES[k] || KIND_BADGES.other;
    return `<span class="tc-tick-dot bg-${meta.color}" title="${escapeHtml(meta.label)} available"></span>`;
  }).join('');

  return `
    <button type="button"
            class="tc-tick ${isActive ? 'active' : ''}"
            data-timestep-label="${escapeHtml(ts.label)}"
            data-tick-key="${tickKey}"
            title="${escapeHtml(ts.label)}${ts.description ? ' — ' + escapeHtml(ts.description) : ''}">
      <span class="tc-tick-rail"></span>
      <span class="tc-tick-knob"></span>
      <span class="tc-tick-label">${escapeHtml(ts.label)}</span>
      <span class="tc-tick-dots">${dots}</span>
    </button>
  `;
}

function renderKindRow(kind, idx, state, dsKey) {
  const meta = KIND_BADGES[kind] || KIND_BADGES.other;
  const enabled = state.enabledKinds.has(kind);
  const opacityPct = Math.round((state.opacityByKind[kind] ?? 0.7) * 100);
  const kindKey = cssSafe(`${dsKey}_${kind}`);

  // How many timesteps include this kind? Used as a hint badge.
  const kindMap = idx.byKindAndTs.get(kind);
  const coverage = kindMap ? kindMap.size : 0;
  const totalTs = (state && Object.keys(state).length) || 0;

  // Is this kind available at the active timestep? Affects label intensity.
  const availableNow = kindMap?.has(state.activeTimestepLabel);

  return `
    <div class="tc-kind-row ${availableNow ? '' : 'tc-kind-unavailable'}"
         data-kind="${escapeHtml(kind)}"
         data-kind-key="${kindKey}">
      <div class="form-check d-flex align-items-center">
        <input class="form-check-input tc-kind-toggle" type="checkbox"
               id="kind_${kindKey}"
               data-kind="${escapeHtml(kind)}"
               ${enabled ? 'checked' : ''}
               ${availableNow ? '' : 'disabled'}>
        <label class="form-check-label tc-kind-label flex-grow-1"
               for="kind_${kindKey}"
               style="font-size: 0.88em;">
          <i class="fas ${meta.icon} me-1"></i>
          ${meta.label}
          <span class="badge bg-${meta.color} ms-1"
                title="${coverage} timestep${coverage === 1 ? '' : 's'} include this kind"
                style="font-size:0.65em; vertical-align: middle;">${coverage}</span>
          ${availableNow ? '' : '<small class="text-muted ms-1">(not at this timestep)</small>'}
        </label>
      </div>
      <div class="tc-opacity-slider" id="op_${kindKey}" style="${enabled ? '' : 'display:none;'}">
        <input type="range" class="form-range tc-kind-opacity"
               id="opv_${kindKey}"
               data-kind="${escapeHtml(kind)}"
               data-kind-key="${kindKey}"
               min="0" max="100" value="${opacityPct}"
               style="height: 4px;">
        <small class="text-muted">Opacity:
          <span class="tc-opacity-value" data-kind-key="${kindKey}">${opacityPct}%</span>
        </small>
      </div>
    </div>
  `;
}

function refreshScrubberReadout(container, dataset, state, timesteps) {
  const labelEl = container.querySelector('.tc-active-ts-label');
  const descEl  = container.querySelector('.tc-active-ts-desc');
  if (!labelEl) return;
  const active = timesteps.find(t => t.label === state.activeTimestepLabel);
  labelEl.textContent = active ? active.label : '?';
  if (descEl) descEl.textContent = active && active.description ? active.description : '';
}

function renderVariantList(node, dataset, idx, state, timesteps) {
  if (!node) return;
  const rows = [];
  for (const kind of idx.variantKinds) {
    const kindMap = idx.byKindAndTs.get(kind);
    for (const ts of timesteps) {
      // Find every product of this kind at this timestep, then drop
      // the canonical one (kindMap.get(ts.label)).
      const canonical = kindMap.get(ts.label);
      const allAtTs = (ts.products || []).filter(p => p.kind === kind);
      for (const p of allAtTs) {
        if (canonical && canonical.layerId === p.layerId) continue;
        rows.push({ ts, product: p, kind });
      }
    }
  }
  if (rows.length === 0) {
    node.innerHTML = '<small class="text-muted">(no extra snapshots)</small>';
    return;
  }
  node.innerHTML = rows.map(({ ts, product, kind }) => {
    const meta = KIND_BADGES[kind] || KIND_BADGES.other;
    const k = cssSafe(`alt_${product.layerId}`);
    return `
      <div class="form-check tc-variant-row" data-layer-id="${escapeHtml(product.layerId)}">
        <input class="form-check-input tc-variant-toggle" type="checkbox"
               id="alt_${k}" data-layer-id="${escapeHtml(product.layerId)}">
        <label class="form-check-label" for="alt_${k}" style="font-size:0.82em;">
          <i class="fas ${meta.icon} me-1"></i>${escapeHtml(ts.label)} — ${escapeHtml(product.label)}
          <span class="badge bg-${meta.color} ms-1" style="font-size:0.6em;">${meta.label}</span>
        </label>
      </div>
    `;
  }).join('');

  node.querySelectorAll('.tc-variant-toggle').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const layerId = e.target.dataset.layerId;
      const product = AppState.catalog.productIndex[layerId]?.product;
      const isVector = isVectorKind(product?.kind);
      const fn = isVector ? toggleVectorLayer : toggleOverlayLayer;
      fn(AppState.viewer, layerId, e.target.checked).catch(err =>
        console.error('[tile-catalog] variant toggle failed:', err)
      );
    });
  });
}

// --------------------------------------------------------------------- //
// Wiring                                                                 //
// --------------------------------------------------------------------- //

function wireScrubber(container, dataset, idx, state, timesteps) {
  const ticks = container.querySelectorAll('.tc-tick');
  ticks.forEach(tick => {
    tick.addEventListener('click', () => {
      const newLabel = tick.dataset.timestepLabel;
      if (newLabel === state.activeTimestepLabel) return;
      transitionTimestep({ container, dataset, idx, state, timesteps, newLabel });
    });
  });

  const prevBtn = container.querySelector('.tc-scrubber-prev');
  const nextBtn = container.querySelector('.tc-scrubber-next');
  if (prevBtn) {
    prevBtn.addEventListener('click', () => stepScrubber({ container, dataset, idx, state, timesteps, delta: -1 }));
  }
  if (nextBtn) {
    nextBtn.addEventListener('click', () => stepScrubber({ container, dataset, idx, state, timesteps, delta: +1 }));
  }
}

function stepScrubber({ container, dataset, idx, state, timesteps, delta }) {
  const i = timesteps.findIndex(t => t.label === state.activeTimestepLabel);
  const newI = Math.max(0, Math.min(timesteps.length - 1, i + delta));
  if (newI === i) return;
  transitionTimestep({ container, dataset, idx, state, timesteps, newLabel: timesteps[newI].label });
}

function transitionTimestep({ container, dataset, idx, state, timesteps, newLabel }) {
  const oldLabel = state.activeTimestepLabel;
  state.activeTimestepLabel = newLabel;

  // For each enabled kind: toggle off the old layer, on the new one (if any).
  for (const kind of state.enabledKinds) {
    const kindMap = idx.byKindAndTs.get(kind);
    if (!kindMap) continue;
    const oldProduct = kindMap.get(oldLabel);
    const newProduct = kindMap.get(newLabel);
    swapLayer(kind, oldProduct, newProduct, state);
  }

  // Re-render in-place: only the scrubber + kind rows need updating
  // (the dataset header is unchanged). We simply rebuild the content.
  renderTimeseriesPanel(container, { site: null, dataset });
}

function wireKindRows(container, dataset, idx, state, timesteps) {
  container.querySelectorAll('.tc-kind-toggle').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const kind = e.target.dataset.kind;
      const enabled = e.target.checked;
      const kindMap = idx.byKindAndTs.get(kind);
      const product = kindMap ? kindMap.get(state.activeTimestepLabel) : null;

      if (enabled) {
        state.enabledKinds.add(kind);
        if (product) {
          activateLayer(kind, product, state);
        }
      } else {
        state.enabledKinds.delete(kind);
        if (state.activeLayerByKind[kind]) {
          deactivateLayer(kind, state.activeLayerByKind[kind], state);
        }
      }

      const kindKey = e.target.closest('.tc-kind-row').dataset.kindKey;
      const opBox = container.querySelector(`#op_${kindKey}`);
      if (opBox) opBox.style.display = enabled ? '' : 'none';
    });
  });

  container.querySelectorAll('.tc-kind-opacity').forEach(slider => {
    slider.addEventListener('input', (e) => {
      const kind = e.target.dataset.kind;
      const kindKey = e.target.dataset.kindKey;
      const value = parseInt(e.target.value, 10);
      const valueEl = container.querySelector(`.tc-opacity-value[data-kind-key="${kindKey}"]`);
      if (valueEl) valueEl.textContent = `${value}%`;
      state.opacityByKind[kind] = value / 100;
      // Apply to currently-active layer (if any).
      const active = state.activeLayerByKind[kind];
      if (active) applyOpacity(active.layerId, isVectorKind(kind), value / 100);
    });
  });
}

// --------------------------------------------------------------------- //
// Layer activation primitives                                            //
// --------------------------------------------------------------------- //

function activateLayer(kind, product, state) {
  if (!product) return;
  const isVector = isVectorKind(product.kind);
  const fn = isVector ? toggleVectorLayer : toggleOverlayLayer;
  fn(AppState.viewer, product.layerId, true)
    .then(() => {
      applyOpacity(product.layerId, isVector, state.opacityByKind[kind] ?? 0.7);
    })
    .catch(err => console.error('[tile-catalog] activate failed:', err));
  state.activeLayerByKind[kind] = { layerId: product.layerId, isVector };
}

function deactivateLayer(kind, active, state) {
  if (!active) return;
  const fn = active.isVector ? toggleVectorLayer : toggleOverlayLayer;
  fn(AppState.viewer, active.layerId, false).catch(err =>
    console.error('[tile-catalog] deactivate failed:', err)
  );
  delete state.activeLayerByKind[kind];
}

function swapLayer(kind, oldProduct, newProduct, state) {
  if (oldProduct && state.activeLayerByKind[kind]?.layerId === oldProduct.layerId) {
    deactivateLayer(kind, state.activeLayerByKind[kind], state);
  }
  if (newProduct) {
    activateLayer(kind, newProduct, state);
  }
}

function isVectorKind(kind) {
  return kind === 'vector' || kind === 'polygons';
}

function applyOpacity(layerId, isVector, ratio) {
  const v = Math.max(0, Math.min(1, ratio));
  if (isVector) {
    if (AppState.vectorRenderer) {
      AppState.vectorRenderer.setLayerOpacity(layerId, v);
    }
  } else {
    const overlay = AppState.currentLayers.overlays[layerId];
    if (overlay) overlay.alpha = v;
  }
}
