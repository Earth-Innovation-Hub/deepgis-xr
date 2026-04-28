/**
 * Tier-2 view for single / multiband datasets.
 *
 * Renders one row per Product with:
 *  - a checkbox that toggles the layer on/off via the existing
 *    toggleOverlayLayer / toggleVectorLayer functions
 *  - an opacity slider that defaults to product.defaultOpacity, hidden
 *    until the layer is enabled
 *  - a kind badge (orthophoto / vector / pca / etc.) so users can scan
 *    quickly across heterogeneous products
 */
import { AppState } from '../../state.js';
import { toggleOverlayLayer, toggleVectorLayer } from '../../core/layer-management.js';
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

export function renderProductList(container, { site, dataset }) {
  if (!container) return;

  const products = dataset.products || [];
  if (products.length === 0) {
    container.innerHTML = '<small class="text-muted">No products in this dataset.</small>';
    return;
  }

  container.innerHTML = `
    <div class="tc-dataset-header">
      <strong>${escapeHtml(dataset.name)}</strong>
      ${dataset.description ? `<div><small class="text-muted">${escapeHtml(dataset.description)}</small></div>` : ''}
    </div>
    <div class="tc-product-list">
      ${products.map(p => renderProductRow(p, site, dataset)).join('')}
    </div>
  `;

  wireProductRows(container);
}

export function renderProductRow(product, site, dataset, { rowKeyPrefix = 'tc_p_' } = {}) {
  const layerInfo = AppState.availableLayers[product.layerId] || {};
  const isVector = layerInfo.format === 'pbf' || product.kind === 'vector' || product.kind === 'polygons';
  const kindMeta = KIND_BADGES[product.kind] || KIND_BADGES.other;
  const rowKey   = cssSafe(rowKeyPrefix + product.layerId);
  const opacityPct = Math.round((product.defaultOpacity ?? 0.7) * 100);

  return `
    <div class="tc-product-row"
         data-layer-id="${escapeHtml(product.layerId)}"
         data-vector="${isVector ? '1' : '0'}"
         data-row-key="${rowKey}">
      <div class="form-check d-flex align-items-center">
        <input class="form-check-input tc-product-toggle"
               type="checkbox"
               id="cb_${rowKey}"
               data-layer-id="${escapeHtml(product.layerId)}">
        <label class="form-check-label tc-product-label flex-grow-1"
               for="cb_${rowKey}"
               style="font-size: 0.88em;">
          <i class="fas ${kindMeta.icon} me-1"></i>${escapeHtml(product.label)}
          <span class="badge bg-${kindMeta.color} ms-1" style="font-size:0.65em; vertical-align: middle;">${kindMeta.label}</span>
        </label>
      </div>
      <div class="tc-opacity-slider" id="op_${rowKey}" style="display:none;">
        <input type="range"
               class="form-range tc-product-opacity"
               id="opv_${rowKey}"
               data-layer-id="${escapeHtml(product.layerId)}"
               data-row-key="${rowKey}"
               min="0" max="100" value="${opacityPct}"
               style="height: 4px;">
        <small class="text-muted">Opacity:
          <span class="tc-opacity-value" data-row-key="${rowKey}">${opacityPct}%</span>
        </small>
      </div>
    </div>
  `;
}

export function wireProductRows(scope) {
  scope.querySelectorAll('.tc-product-toggle').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const layerId = e.target.dataset.layerId;
      const row = e.target.closest('.tc-product-row');
      const rowKey = row?.dataset.rowKey;
      const opacityBox = scope.querySelector(`#op_${rowKey}`);
      if (opacityBox) opacityBox.style.display = e.target.checked ? '' : 'none';

      const isVector = row?.dataset.vector === '1';
      const fn = isVector ? toggleVectorLayer : toggleOverlayLayer;
      fn(AppState.viewer, layerId, e.target.checked).catch(err => {
        console.error('[tile-catalog] product toggle failed:', err);
      });

      // If the user just enabled a layer, push the catalog default-opacity
      // through immediately (opacity slider already has the right value;
      // the slider's input handler will fire next time the user moves it).
      if (e.target.checked) {
        const slider = scope.querySelector(`#opv_${rowKey}`);
        if (slider) applyOpacity(layerId, isVector, parseInt(slider.value, 10));
      }
    });
  });

  scope.querySelectorAll('.tc-product-opacity').forEach(slider => {
    slider.addEventListener('input', (e) => {
      const layerId = e.target.dataset.layerId;
      const rowKey  = e.target.dataset.rowKey;
      const value   = parseInt(e.target.value, 10);
      const valueEl = scope.querySelector(`.tc-opacity-value[data-row-key="${rowKey}"]`);
      if (valueEl) valueEl.textContent = `${value}%`;
      const isVector = e.target.closest('.tc-product-row')?.dataset.vector === '1';
      applyOpacity(layerId, isVector, value);
    });
  });
}

function applyOpacity(layerId, isVector, percent) {
  const ratio = Math.max(0, Math.min(1, percent / 100));
  if (isVector) {
    if (AppState.vectorRenderer) {
      AppState.vectorRenderer.setLayerOpacity(layerId, ratio);
    }
  } else {
    const overlay = AppState.currentLayers.overlays[layerId];
    if (overlay) overlay.alpha = ratio;
  }
}
