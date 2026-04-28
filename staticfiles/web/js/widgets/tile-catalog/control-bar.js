/**
 * Tile catalog control bar (Phase 5: viewport filter).
 *
 * Currently exposes one global control: "filter to viewport" toggle.
 * When on, only Sites whose bounds intersect the camera viewport
 * appear in Tier-1; the panel re-renders whenever the camera settles.
 *
 * Phase 4's comparison-mode is per-dataset (lives in the timeseries
 * panel), so it intentionally doesn't appear here.
 */
import { AppState } from '../../state.js';

export function renderControlBar(container, opts) {
  if (!container) return;

  const filterOn = !!AppState.viewportFilterEnabled;

  container.innerHTML = `
    <div class="tc-controls-row">
      <label class="form-check form-switch tc-viewport-filter-switch m-0">
        <input class="form-check-input" type="checkbox" id="tcViewportFilter"
               ${filterOn ? 'checked' : ''}>
        <span class="form-check-label" style="font-size:0.78em;">
          <i class="fas fa-crop-alt me-1"></i>Filter to viewport
        </span>
      </label>
    </div>
  `;

  const cb = container.querySelector('#tcViewportFilter');
  if (cb) {
    cb.addEventListener('change', (e) => {
      AppState.viewportFilterEnabled = e.target.checked;
      if (typeof opts?.onChange === 'function') opts.onChange();
    });
  }
}
