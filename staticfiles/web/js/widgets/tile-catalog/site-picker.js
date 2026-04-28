/**
 * Tier-1 site picker.
 *
 * Renders a vertical list of site cards, each with:
 *  - the site's name + a layer-count badge
 *  - a "fly to" icon (zooms the camera to the site's bounds)
 *  - an expand/collapse toggle (only the active site is expanded)
 *  - a body container that the panel fills with Tier-2 content
 *
 * "All sites" is rendered as a special card at the top: clicking it
 * sets activeSiteSlug=null (every site expanded simultaneously).
 */
import { AppState } from '../../state.js';
import { cssSafe, escapeHtml } from './index.js';
import { CONFIG } from '../../config.js';
import { CoordinateUtils } from '../../utils/coordinates.js';
import { CameraUtils } from '../../utils/camera.js';

export function renderSitePicker(container, { sites, activeSiteSlug, onSelect }) {
  if (!container) return;

  if (sites.length === 0) {
    container.innerHTML = '<small class="text-muted">No sites in catalog.</small>';
    return;
  }

  container.innerHTML = `
    <div class="tc-tier1-bar">
      <button class="btn btn-sm tc-site-pill ${activeSiteSlug == null ? 'active' : ''}"
              data-site-slug="">
        <i class="fas fa-globe me-1"></i>All sites
      </button>
      ${sites.map(site => `
        <button class="btn btn-sm tc-site-pill ${activeSiteSlug === site.slug ? 'active' : ''}"
                data-site-slug="${escapeHtml(site.slug)}">
          ${escapeHtml(site.name)}
          <span class="badge bg-secondary ms-1">${countProducts(site)}</span>
        </button>
      `).join('')}
    </div>
    <div class="tc-tier2-stack">
      ${sites.map(site => renderSiteCard(site, activeSiteSlug)).join('')}
    </div>
  `;

  container.querySelectorAll('.tc-site-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      const slug = btn.dataset.siteSlug || null;
      onSelect(slug);
    });
  });

  container.querySelectorAll('.tc-flyto').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const slug = btn.dataset.siteSlug;
      const site = sites.find(s => s.slug === slug);
      if (site) flyToSite(site);
    });
  });
}

function renderSiteCard(site, activeSiteSlug) {
  const isExpanded = activeSiteSlug == null || activeSiteSlug === site.slug;
  const cardId = cssSafe(site.slug);
  return `
    <div class="tc-site-card ${isExpanded ? 'expanded' : 'collapsed'}"
         data-site-card="${escapeHtml(site.slug)}">
      <div class="tc-site-header">
        <div class="tc-site-title">
          <i class="fas fa-map-marker-alt me-1"></i>
          ${escapeHtml(site.name)}
          <small class="text-muted ms-2">(${countProducts(site)} layer${countProducts(site) === 1 ? '' : 's'})</small>
        </div>
        <div class="tc-site-actions">
          <button type="button"
                  class="btn btn-sm btn-link p-0 me-2 tc-flyto"
                  data-site-slug="${escapeHtml(site.slug)}"
                  title="Fly to site">
            <i class="fas fa-paper-plane"></i>
          </button>
        </div>
      </div>
      ${site.description ? `<small class="text-muted d-block mb-2" style="font-size:0.78em;">${escapeHtml(site.description)}</small>` : ''}
      <div class="tc-site-body" data-site-body="${escapeHtml(site.slug)}" id="site_body_${cardId}"></div>
    </div>
  `;
}

function countProducts(site) {
  let n = 0;
  for (const ds of site.datasets) {
    if (ds.kind === 'timeseries') {
      for (const ts of ds.timesteps) n += ts.products.length;
    } else {
      n += ds.products.length;
    }
  }
  return n;
}

/**
 * Fly the Cesium camera to a site's bounds + default zoom.
 * Mirrors the flyTo logic used elsewhere in the codebase but keeps it
 * minimal -- we don't switch scene mode here, we just reposition.
 */
async function flyToSite(site) {
  const viewer = AppState.viewer;
  if (!viewer || !viewer.scene) {
    console.warn('[tile-catalog] flyToSite: viewer not ready');
    return;
  }
  if (!site.bounds || site.bounds.length !== 4) {
    console.warn('[tile-catalog] flyToSite: site has no usable bounds', site.slug);
    return;
  }
  const [w, s, e, n] = site.bounds;
  const lon = (w + e) / 2;
  const lat = (s + n) / 2;
  const zoom = site.defaultZoom ?? CONFIG.DEFAULT_ZOOM_LEVEL ?? 15;
  const height = CoordinateUtils.zoomToHeight(zoom);
  const destination = Cesium.Cartesian3.fromDegrees(lon, lat, height);
  console.log(`[tile-catalog] flying to ${site.slug} (${lon.toFixed(4)},${lat.toFixed(4)} z${zoom})`);
  try {
    await CameraUtils.setCameraView(viewer, destination, {
      duration: 1.5,
      maxHeight: CONFIG.MAX_2D_VIEW_HEIGHT,
    });
  } catch (err) {
    console.warn('[tile-catalog] fly-to failed, falling back to flyTo:', err);
    viewer.camera.flyTo({ destination, duration: 1.5 });
  }
}
