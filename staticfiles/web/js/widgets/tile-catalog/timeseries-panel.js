/**
 * Tier-2 view for timeseries datasets.
 *
 * Phase 2: render each Timestep as a small subheading with a flat
 *          product list under it. Already removes the
 *          "all alphabetical" clutter from the old UI.
 *
 * Phase 3 (next): replace the subheadings with a horizontal scrubber
 *                 and an active-product axis below it; toggling the
 *                 scrubber rotates the active layer for each enabled
 *                 product kind.
 */
import { renderProductRow, wireProductRows } from './product-list.js';
import { escapeHtml } from './index.js';

export function renderTimeseriesPanel(container, { site, dataset }) {
  if (!container) return;
  const timesteps = dataset.timesteps || [];

  if (timesteps.length === 0) {
    container.innerHTML = '<small class="text-muted">No timesteps in this dataset.</small>';
    return;
  }

  container.innerHTML = `
    <div class="tc-dataset-header">
      <strong>${escapeHtml(dataset.name)}</strong>
      <span class="badge bg-warning text-dark ms-2" style="font-size:0.7em;">timeseries: ${timesteps.length}</span>
      ${dataset.description ? `<div><small class="text-muted">${escapeHtml(dataset.description)}</small></div>` : ''}
    </div>
    <div class="tc-timeseries-stack">
      ${timesteps.map(ts => `
        <div class="tc-timestep" data-timestep="${escapeHtml(ts.label)}">
          <div class="tc-timestep-header">
            <i class="fas fa-clock me-1"></i>
            <strong>${escapeHtml(ts.label)}</strong>
            ${ts.description ? `<small class="text-muted ms-2">${escapeHtml(ts.description)}</small>` : ''}
          </div>
          <div class="tc-product-list">
            ${ts.products.map(p => renderProductRow(p, site, dataset, { rowKeyPrefix: `tc_t_${escapeHtml(ts.label)}_` })).join('')}
          </div>
        </div>
      `).join('')}
    </div>
  `;

  wireProductRows(container);
}
