/**
 * Tile Catalog Panel
 *
 * Top-level Cesium UI panel that replaces the two flat raster/vector
 * checkbox lists with a hierarchical Site -> Dataset -> (Timestep |
 * Product) tree, driven by AppState.catalog.
 *
 * Responsibilities:
 *  - Render Tier-1 site picker (one pill per Site, plus an "All sites" pill)
 *  - For the active selection, mount the right Tier-2 view:
 *      * single / multiband datasets    -> ProductList (Phase 2)
 *      * timeseries datasets            -> TimeseriesPanel (Phase 3)
 *  - Render an "Uncategorized" group for any orphan layers so they
 *    stay reachable while admins curate them through the Django admin.
 *  - Render a top-level UI control bar (comparison mode, viewport filter
 *    toggle) that Phase 4/5 will populate.
 *
 * The actual checkbox + opacity wiring delegates to
 * core/layer-management.js (toggleOverlayLayer, toggleVectorLayer)
 * so the underlying tile-loading machinery is untouched.
 */
import { AppState } from '../../state.js';
import { renderSitePicker } from './site-picker.js';
import { renderProductList } from './product-list.js';
import { renderTimeseriesPanel } from './timeseries-panel.js';
import { renderControlBar } from './control-bar.js';
import {
  enableMoveEndWatcher,
  disableMoveEndWatcher,
  getViewportBboxDeg,
  visibleSiteSlugs,
} from './viewport-filter.js';

const ROOT_ID = 'tileCatalogPanel';

/**
 * Mount-or-update the catalog panel inside the given container element.
 * Safe to call repeatedly; later calls re-render.
 */
export function renderCatalogPanel(container) {
  if (!container) {
    console.warn('[tile-catalog] renderCatalogPanel: no container provided');
    return;
  }

  // Initial scaffold: shell, control bar mount, sites mount, orphan mount.
  if (!container.querySelector(`#${ROOT_ID}`)) {
    container.innerHTML = `
      <div id="${ROOT_ID}" class="tile-catalog-panel">
        <div class="tc-control-bar" id="tcControlBar"></div>
        <div class="tc-sites" id="tcSitesContainer"></div>
        <div class="tc-orphans" id="tcOrphansContainer" style="display:none;"></div>
        <div class="tc-status" id="tcStatus"></div>
      </div>
    `;
  }

  const sitesContainer   = container.querySelector('#tcSitesContainer');
  const orphansContainer = container.querySelector('#tcOrphansContainer');
  const controlBar       = container.querySelector('#tcControlBar');
  const status           = container.querySelector('#tcStatus');

  if (AppState.catalog.error) {
    status.innerHTML = `<small class="text-warning">Catalog unavailable: ${escapeHtml(AppState.catalog.error)}. Showing flat layer list.</small>`;
  } else if (AppState.catalog.sites.length === 0) {
    status.innerHTML = '<small class="text-muted">No catalog sites configured. Add one in /label/admin/tile_catalog/.</small>';
  } else {
    status.innerHTML = '';
  }

  renderControlBar(controlBar, { onChange: () => renderCatalogPanel(container) });

  // Apply viewport filter (Phase 5). When enabled and a viewport is
  // computable, hide sites whose bounds don't intersect.
  let visibleSites = AppState.catalog.sites;
  if (AppState.viewportFilterEnabled) {
    const bbox = getViewportBboxDeg(AppState.viewer);
    const visibleSet = visibleSiteSlugs(AppState.catalog.sites, bbox);
    visibleSites = AppState.catalog.sites.filter(s => visibleSet.has(s.slug));
    enableMoveEndWatcher(AppState.viewer, () => renderCatalogPanel(container));
    if (visibleSites.length === 0) {
      status.innerHTML = '<small class="text-muted">No sites in current viewport. Pan/zoom or untoggle the viewport filter.</small>';
    }
  } else {
    disableMoveEndWatcher();
  }

  renderSitePicker(sitesContainer, {
    sites: visibleSites,
    activeSiteSlug: AppState.catalog.activeSiteSlug,
    onSelect: (slug) => {
      AppState.catalog.activeSiteSlug = slug;
      renderCatalogPanel(container);
    },
  });

  // Tier-2 mount points appear inside each site card as the user expands them.
  // We render every (viewport-filtered) site's body lazily based on activeSiteSlug.
  const expandedSites = AppState.catalog.activeSiteSlug
    ? visibleSites.filter(s => s.slug === AppState.catalog.activeSiteSlug)
    : visibleSites;

  for (const site of expandedSites) {
    const siteBody = sitesContainer.querySelector(`[data-site-body="${site.slug}"]`);
    if (!siteBody) continue;
    siteBody.innerHTML = '';
    for (const dataset of site.datasets) {
      const dsCard = document.createElement('div');
      dsCard.className = 'tc-dataset';
      dsCard.dataset.dataset = dataset.slug;
      siteBody.appendChild(dsCard);
      if (dataset.kind === 'timeseries') {
        renderTimeseriesPanel(dsCard, { site, dataset });
      } else {
        renderProductList(dsCard, { site, dataset });
      }
    }
  }

  // Orphans (layers tileserver serves but the catalog doesn't reference).
  const orphans = AppState.catalog.orphanLayers || [];
  if (orphans.length === 0) {
    orphansContainer.style.display = 'none';
    orphansContainer.innerHTML = '';
  } else {
    orphansContainer.style.display = '';
    orphansContainer.innerHTML = renderOrphans(orphans);
    wireOrphanCheckboxes(orphansContainer);
  }
}

// --------------------------------------------------------------------- //
// Orphan layers: simple flat list                                        //
// --------------------------------------------------------------------- //

function renderOrphans(orphans) {
  const rows = orphans
    .map(layerId => {
      const info = AppState.availableLayers[layerId] || {};
      const isVector = info.format === 'pbf' || info.type === 'vector';
      const icon = isVector ? 'fa-vector-square' : 'fa-map';
      return `
        <div class="form-check tc-orphan-row" data-layer-id="${layerId}" data-vector="${isVector ? '1' : '0'}">
          <input class="form-check-input tc-orphan-toggle" type="checkbox"
                 id="orphan_${cssSafe(layerId)}" data-layer-id="${layerId}">
          <label class="form-check-label" for="orphan_${cssSafe(layerId)}"
                 style="font-size: 0.85em;">
            <i class="fas ${icon} me-1"></i>${escapeHtml(info.name || layerId)}
          </label>
        </div>
      `;
    })
    .join('');
  return `
    <details class="tc-orphan-group">
      <summary class="layer-group-title" style="cursor:pointer; font-size: 0.9em;">
        <i class="fas fa-folder-open me-1"></i>
        Uncategorized layers (${orphans.length})
      </summary>
      <small class="text-muted d-block mb-2" style="font-size: 0.75em;">
        Served by tileserver but not in the catalog. Add them in
        <code>/label/admin/tile_catalog/</code> to give them a proper home.
      </small>
      ${rows}
    </details>
  `;
}

function wireOrphanCheckboxes(root) {
  // We hand off to the same toggleOverlayLayer / toggleVectorLayer used
  // for catalog products. Lazy-import to avoid a hard dependency cycle
  // with the larger layer-management module.
  import('../../core/layer-management.js').then(({ toggleOverlayLayer, toggleVectorLayer }) => {
    root.querySelectorAll('.tc-orphan-toggle').forEach(cb => {
      cb.addEventListener('change', (e) => {
        const layerId = e.target.dataset.layerId;
        const isVector = e.target.closest('.tc-orphan-row').dataset.vector === '1';
        const fn = isVector ? toggleVectorLayer : toggleOverlayLayer;
        fn(AppState.viewer, layerId, e.target.checked).catch(err => {
          console.error('[tile-catalog] orphan toggle failed:', err);
        });
      });
    });
  });
}

// --------------------------------------------------------------------- //
// Utilities                                                              //
// --------------------------------------------------------------------- //

export function cssSafe(s) {
  return String(s).replace(/[^A-Za-z0-9_-]/g, '_');
}

export function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export { ROOT_ID };
