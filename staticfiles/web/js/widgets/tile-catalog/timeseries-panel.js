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
import {
  findImageryLayer,
  setLayerSplitDirection,
  setSplitPosition,
  clearComparison,
  applySwipe,
  applyOverlay,
} from './comparison.js';

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
    const tss = dataset.timesteps || [];
    const firstTs = tss[0];
    const lastTs  = tss[tss.length - 1];
    state = {
      activeTimestepLabel: firstTs ? firstTs.label : null,
      enabledKinds: new Set(),
      // Per-kind opacity, defaults derived lazily from each product.
      opacityByKind: {},
      // Last activated layer per kind, so we can toggle it off when the
      // scrubber moves to a different timestep.
      activeLayerByKind: {},
      // ----- Comparison-mode state (Phase 4) -----
      // 'single' | 'swipe' | 'overlay'
      comparisonMode: 'single',
      // The "B" timestep used in swipe / overlay. Defaults to the last
      // timestep so the user immediately sees a meaningful comparison.
      compareTimestepLabel: tss.length >= 2 && lastTs ? lastTs.label : null,
      // Where the vertical split sits in swipe mode (0..1).
      splitPosition: 0.5,
      // Saved-opacity table so we can restore after leaving overlay mode.
      _preComparisonOpacity: {},
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

  const inComparison = state.comparisonMode !== 'single' && state.compareTimestepLabel;

  container.innerHTML = `
    <div class="tc-dataset-header">
      <strong>${escapeHtml(dataset.name)}</strong>
      <span class="badge bg-warning text-dark ms-2" style="font-size:0.7em;">timeseries: ${timesteps.length}</span>
      ${dataset.description ? `<div><small class="text-muted">${escapeHtml(dataset.description)}</small></div>` : ''}
    </div>

    <div class="tc-mode-selector" data-dataset="${escapeHtml(dataset.slug)}">
      <small class="text-muted me-2">Compare:</small>
      ${['single', 'swipe', 'overlay'].map(m => `
        <button type="button" class="btn btn-sm tc-mode-pill ${state.comparisonMode === m ? 'active' : ''}"
                data-mode="${m}" title="${modeTooltip(m)}">
          ${modeIcon(m)} ${m}
        </button>
      `).join('')}
    </div>

    <div class="tc-scrubber" id="tc_scrub_${dsKey}">
      <div class="tc-scrubber-controls">
        <button type="button" class="btn btn-link btn-sm tc-scrubber-prev p-0"
                title="Previous timestep"><i class="fas fa-caret-left"></i></button>
        <div class="tc-scrubber-track ${inComparison ? 'comparing' : ''}">
          ${timesteps.map((ts, i) => renderTick(ts, i, timesteps.length, idx, state)).join('')}
        </div>
        <button type="button" class="btn btn-link btn-sm tc-scrubber-next p-0"
                title="Next timestep"><i class="fas fa-caret-right"></i></button>
      </div>
      <div class="tc-scrubber-readout">
        <i class="fas fa-clock me-1"></i>
        <strong class="tc-active-ts-label">${escapeHtml(state.activeTimestepLabel || '?')}</strong>
        ${inComparison ? `
          <span class="text-muted mx-1">vs</span>
          <strong class="tc-compare-ts-label">${escapeHtml(state.compareTimestepLabel || '?')}</strong>
        ` : ''}
        <small class="text-muted ms-2 tc-active-ts-desc"></small>
      </div>
      ${state.comparisonMode === 'swipe' ? `
        <div class="tc-split-control">
          <small class="text-muted me-1">Split:</small>
          <input type="range" class="form-range tc-split-slider"
                 min="0" max="100" value="${Math.round(state.splitPosition * 100)}"
                 style="height: 4px;">
        </div>
      ` : ''}
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
  wireModeSelector(container, dataset, idx, state, timesteps);

  // Re-apply comparison mode after every render, in case the user
  // toggled a kind while in swipe/overlay mode.
  applyComparisonState(dataset, idx, state, timesteps);
}

function renderTick(ts, i, total, idx, state) {
  const isActive  = ts.label === state.activeTimestepLabel;
  const isCompare = state.comparisonMode !== 'single' && ts.label === state.compareTimestepLabel;
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

  const cls = ['tc-tick'];
  if (isActive)  cls.push('active');
  if (isCompare) cls.push('compare');

  return `
    <button type="button"
            class="${cls.join(' ')}"
            data-timestep-label="${escapeHtml(ts.label)}"
            data-tick-key="${tickKey}"
            title="${escapeHtml(ts.label)}${ts.description ? ' — ' + escapeHtml(ts.description) : ''}${isCompare ? ' (B / compare pin)' : ''}">
      <span class="tc-tick-rail"></span>
      <span class="tc-tick-knob"></span>
      <span class="tc-tick-label">${escapeHtml(ts.label)}</span>
      <span class="tc-tick-dots">${dots}</span>
    </button>
  `;
}

function modeIcon(mode) {
  switch (mode) {
    case 'single':  return '<i class="fas fa-circle"></i>';
    case 'swipe':   return '<i class="fas fa-columns"></i>';
    case 'overlay': return '<i class="fas fa-clone"></i>';
    default:        return '';
  }
}

function modeTooltip(mode) {
  switch (mode) {
    case 'single':  return 'Show only the active timestep.';
    case 'swipe':   return 'Show A on the left and B on the right of a vertical split. Drag the slider to move the split.';
    case 'overlay': return 'Blend A and B at half opacity to see where they differ.';
    default:        return '';
  }
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
    tick.addEventListener('click', (e) => {
      const newLabel = tick.dataset.timestepLabel;
      // Shift-click (or right-click) sets the B (compare) pin in
      // swipe / overlay mode; otherwise it's a normal A pin move.
      if (state.comparisonMode !== 'single' && (e.shiftKey || e.altKey)) {
        if (newLabel === state.activeTimestepLabel) return;
        state.compareTimestepLabel = newLabel;
        renderTimeseriesPanel(container, { site: null, dataset });
        return;
      }
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

  const splitSlider = container.querySelector('.tc-split-slider');
  if (splitSlider) {
    splitSlider.addEventListener('input', (e) => {
      state.splitPosition = parseInt(e.target.value, 10) / 100;
      setSplitPosition(AppState.viewer, state.splitPosition);
    });
  }
}

function wireModeSelector(container, dataset, idx, state, timesteps) {
  container.querySelectorAll('.tc-mode-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      const newMode = btn.dataset.mode;
      if (newMode === state.comparisonMode) return;

      // Leaving comparison: restore opacity from snapshot, clear split.
      if (newMode === 'single') {
        restoreFromComparison(state);
      } else if (state.compareTimestepLabel == null) {
        // Initialise compare pin to a sensible default if the user
        // entered comparison without one set yet.
        state.compareTimestepLabel = (timesteps[timesteps.length - 1] || {}).label || null;
      }

      state.comparisonMode = newMode;
      renderTimeseriesPanel(container, { site: null, dataset });
    });
  });
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

// --------------------------------------------------------------------- //
// Comparison-mode application                                            //
// --------------------------------------------------------------------- //

/**
 * After a render, reconcile the actual Cesium imagery state with
 * state.comparisonMode. Single mode = clear all split state. Swipe and
 * overlay activate the second timestep's products and apply the
 * appropriate split direction / alpha.
 *
 * Only raster layers participate in split mode (Cesium's split is
 * per-imagery-layer, not per-vector-renderer); vector layers stay on
 * normally in all modes.
 */
function applyComparisonState(dataset, idx, state, timesteps) {
  // Step 1: ensure all "B" layers reflect the current state. We
  // maintain state._compareLayerByKind so we can swap them in/out
  // without leaking activations.
  if (state.comparisonMode === 'single') {
    teardownCompareLayers(state);
    setSplitPosition(AppState.viewer, 0.5);
    return;
  }

  ensureCompareLayers(state, idx);

  // Step 2: apply split / overlay to every (A, B) raster pair.
  const pairs = enumeratePairs(state);
  if (state.comparisonMode === 'swipe') {
    for (const { aLayer, bLayer } of pairs) applySwipe(aLayer, bLayer);
    setSplitPosition(AppState.viewer, state.splitPosition ?? 0.5);
  } else if (state.comparisonMode === 'overlay') {
    state._preComparisonOpacity = state._preComparisonOpacity || {};
    for (const { aLayer, bLayer, aLayerId, bLayerId } of pairs) {
      if (aLayer && state._preComparisonOpacity[aLayerId] == null) {
        state._preComparisonOpacity[aLayerId] = aLayer.alpha;
      }
      if (bLayer && state._preComparisonOpacity[bLayerId] == null) {
        state._preComparisonOpacity[bLayerId] = bLayer.alpha;
      }
      applyOverlay(aLayer, bLayer);
    }
  }
}

function ensureCompareLayers(state, idx) {
  state._compareLayerByKind = state._compareLayerByKind || {};
  const wantedB = {}; // kind -> Product

  for (const kind of state.enabledKinds) {
    if (isVectorKind(kind)) continue; // split applies to imagery only
    const kindMap = idx.byKindAndTs.get(kind);
    if (!kindMap) continue;
    const bProduct = kindMap.get(state.compareTimestepLabel);
    if (bProduct) wantedB[kind] = bProduct;
  }

  // Activate any B products that aren't already on.
  for (const [kind, product] of Object.entries(wantedB)) {
    const existing = state._compareLayerByKind[kind];
    if (existing && existing.layerId === product.layerId) continue;
    if (existing) {
      toggleOverlayLayer(AppState.viewer, existing.layerId, false).catch(() => {});
    }
    toggleOverlayLayer(AppState.viewer, product.layerId, true).catch(err =>
      console.error('[tile-catalog] compare-B activate failed:', err)
    );
    state._compareLayerByKind[kind] = { layerId: product.layerId };
  }

  // Deactivate any B products no longer wanted (kind disabled or B-pin moved).
  for (const kind of Object.keys(state._compareLayerByKind)) {
    if (!wantedB[kind]) {
      const stale = state._compareLayerByKind[kind];
      toggleOverlayLayer(AppState.viewer, stale.layerId, false).catch(() => {});
      delete state._compareLayerByKind[kind];
    }
  }
}

function teardownCompareLayers(state) {
  if (!state._compareLayerByKind) return;
  for (const kind of Object.keys(state._compareLayerByKind)) {
    const stale = state._compareLayerByKind[kind];
    toggleOverlayLayer(AppState.viewer, stale.layerId, false).catch(() => {});
  }
  state._compareLayerByKind = {};
  // Clear any split state on the A layers.
  for (const kind of state.enabledKinds) {
    const a = state.activeLayerByKind[kind];
    if (!a || a.isVector) continue;
    const aLayer = findImageryLayer(AppState.viewer, a.layerId, AppState.currentLayers);
    setLayerSplitDirection(aLayer, 'none');
  }
}

function restoreFromComparison(state) {
  // Restore alpha on A and B layers we touched in overlay mode.
  if (state._preComparisonOpacity) {
    for (const [layerId, alpha] of Object.entries(state._preComparisonOpacity)) {
      const layer = findImageryLayer(AppState.viewer, layerId, AppState.currentLayers);
      if (layer && alpha != null) layer.alpha = alpha;
    }
    state._preComparisonOpacity = {};
  }
  teardownCompareLayers(state);
}

function enumeratePairs(state) {
  const out = [];
  for (const kind of state.enabledKinds) {
    if (isVectorKind(kind)) continue;
    const a = state.activeLayerByKind[kind];
    const b = state._compareLayerByKind?.[kind];
    if (!a || !b) continue;
    const aLayer = findImageryLayer(AppState.viewer, a.layerId, AppState.currentLayers);
    const bLayer = findImageryLayer(AppState.viewer, b.layerId, AppState.currentLayers);
    out.push({ aLayer, bLayer, aLayerId: a.layerId, bLayerId: b.layerId });
  }
  return out;
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
