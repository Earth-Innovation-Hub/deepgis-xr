/**
 * Tile Catalog Loader
 *
 * Fetches the hierarchical Site->Dataset->Timestep->Product catalog
 * from /api/v1/tile-catalog/ and joins it with the flat layer
 * descriptors discovered from tileserver-gl's /data.json (held in
 * AppState.availableLayers).
 *
 * After loadCatalog() resolves, AppState.catalog has:
 *
 *   sites:        array of Site nodes ready for the UI tree.
 *                 Inactive sites and Products whose layer_id isn't in
 *                 availableLayers are filtered out.
 *
 *   productIndex: { layer_id -> { site, dataset, timestep, product } }
 *                 lookup table the panel uses to find a Product's
 *                 metadata when given just a layer id.
 *
 *   orphanLayers: layer ids served by tileserver-gl that the catalog
 *                 doesn't know about. The UI puts these in an
 *                 "Uncategorized" section so they're still reachable
 *                 while admins curate them through the Django admin.
 *
 *   error:        non-null if the fetch failed (404, network error,
 *                 etc.). Caller should fall back to a flat list of
 *                 every availableLayer.
 */
import { AppState } from '../state.js';

const CATALOG_ENDPOINT = '/api/v1/tile-catalog/';
const FETCH_TIMEOUT_MS = 8000;

/**
 * Fetch the catalog and merge it with AppState.availableLayers.
 * Idempotent: safe to call multiple times.
 */
export async function loadCatalog() {
  AppState.catalog.error = null;

  let payload;
  try {
    payload = await fetchWithTimeout(CATALOG_ENDPOINT, FETCH_TIMEOUT_MS);
  } catch (err) {
    console.warn('[catalog] could not load tile catalog:', err.message);
    AppState.catalog.error = err.message;
    AppState.catalog.sites = [];
    AppState.catalog.productIndex = {};
    AppState.catalog.orphanLayers = Object.keys(AppState.availableLayers || {});
    return AppState.catalog;
  }

  const knownLayerIds = new Set(Object.keys(AppState.availableLayers || {}));
  const productIndex = {};
  const sites = [];

  for (const siteRaw of payload.sites || []) {
    const site = projectSite(siteRaw, knownLayerIds, productIndex);
    if (site && hasAnyProduct(site)) {
      sites.push(site);
    }
  }

  // Orphans: layers tileserver serves but catalog doesn't reference.
  const claimed = new Set(Object.keys(productIndex));
  const orphanLayers = [];
  for (const layerId of knownLayerIds) {
    if (!claimed.has(layerId)) {
      orphanLayers.push(layerId);
    }
  }
  orphanLayers.sort();

  AppState.catalog.version = payload.version ?? null;
  AppState.catalog.sites = sites;
  AppState.catalog.productIndex = productIndex;
  AppState.catalog.orphanLayers = orphanLayers;

  if (AppState.catalog.activeSiteSlug == null && sites.length > 0) {
    // Don't auto-pick a site -- "all sites visible" is the requested default.
    // We leave activeSiteSlug null and let the panel render every site.
  }

  console.log(
    `[catalog] loaded v${payload.version}: ${sites.length} site(s), ` +
    `${Object.keys(productIndex).length} product(s) live, ` +
    `${orphanLayers.length} orphan(s).`
  );

  return AppState.catalog;
}

/**
 * Return everything the UI needs to render a single Product checkbox row,
 * given just its layer id. Includes default_opacity, label, kind, plus
 * the underlying availableLayers descriptor for tile serving.
 */
export function lookupProduct(layerId) {
  const indexed = AppState.catalog.productIndex[layerId];
  const layerInfo = AppState.availableLayers[layerId] || null;
  return { ...indexed, layerInfo };
}

/**
 * Iterate every product currently visible in the catalog (skips inactive
 * and orphan layers). Useful for callers that want a flat list with
 * catalog metadata applied.
 */
export function eachLiveProduct() {
  return Object.entries(AppState.catalog.productIndex).map(([layerId, ctx]) => ({
    layerId,
    ...ctx,
    layerInfo: AppState.availableLayers[layerId],
  }));
}

// --------------------------------------------------------------------- //
// Internal helpers                                                      //
// --------------------------------------------------------------------- //

async function fetchWithTimeout(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, {
      signal: controller.signal,
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) {
      throw new Error(`${resp.status} ${resp.statusText} from ${url}`);
    }
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}

function projectSite(siteRaw, knownLayerIds, productIndex) {
  const site = {
    slug: siteRaw.slug,
    name: siteRaw.name,
    description: siteRaw.description || '',
    bounds: Array.isArray(siteRaw.bounds) ? siteRaw.bounds.slice(0, 4) : null,
    defaultZoom: siteRaw.default_zoom ?? null,
    defaultCameraPitch: siteRaw.default_camera_pitch ?? null,
    ordering: siteRaw.ordering ?? 0,
    datasets: [],
  };

  for (const dsRaw of siteRaw.datasets || []) {
    const ds = projectDataset(dsRaw, site, knownLayerIds, productIndex);
    if (ds && hasAnyProductInDataset(ds)) {
      site.datasets.push(ds);
    }
  }
  return site;
}

function projectDataset(dsRaw, site, knownLayerIds, productIndex) {
  const ds = {
    slug: dsRaw.slug,
    name: dsRaw.name,
    description: dsRaw.description || '',
    kind: dsRaw.kind, // 'timeseries' | 'single' | 'multiband'
    ordering: dsRaw.ordering ?? 0,
    timesteps: [],
    products: [],
  };

  if (ds.kind === 'timeseries') {
    for (const tsRaw of dsRaw.timesteps || []) {
      const ts = {
        label: tsRaw.label,
        sortKey: tsRaw.sort_key,
        description: tsRaw.description || '',
        products: [],
      };
      for (const prodRaw of tsRaw.products || []) {
        const product = projectProduct(prodRaw, knownLayerIds);
        if (product) {
          ts.products.push(product);
          productIndex[product.layerId] = {
            site, dataset: ds, timestep: ts, product,
          };
        }
      }
      // Drop empty timesteps (every product unreachable on tileserver).
      if (ts.products.length > 0) {
        ds.timesteps.push(ts);
      }
    }
  } else {
    for (const prodRaw of dsRaw.products || []) {
      const product = projectProduct(prodRaw, knownLayerIds);
      if (product) {
        ds.products.push(product);
        productIndex[product.layerId] = {
          site, dataset: ds, timestep: null, product,
        };
      }
    }
  }
  return ds;
}

function projectProduct(prodRaw, knownLayerIds) {
  if (!knownLayerIds.has(prodRaw.layer_id)) return null;
  return {
    layerId: prodRaw.layer_id,
    kind: prodRaw.kind,
    label: prodRaw.label || prodRaw.layer_id,
    description: prodRaw.description || '',
    defaultOpacity: typeof prodRaw.default_opacity === 'number'
      ? prodRaw.default_opacity
      : 0.7,
    ordering: prodRaw.ordering ?? 0,
  };
}

function hasAnyProduct(site) {
  return site.datasets.some(ds => hasAnyProductInDataset(ds));
}

function hasAnyProductInDataset(ds) {
  if (ds.kind === 'timeseries') {
    return ds.timesteps.some(ts => ts.products.length > 0);
  }
  return ds.products.length > 0;
}

/**
 * Bounding-box intersection test (WGS84 degrees). Returns true if the
 * site's bounds overlap with the camera-viewport bbox. Used by the
 * Phase-5 viewport filter.
 */
export function siteIntersectsViewport(site, viewportBbox) {
  if (!site || !site.bounds || !viewportBbox) return true; // be permissive
  const [w1, s1, e1, n1] = site.bounds;
  const [w2, s2, e2, n2] = viewportBbox;
  return !(w1 > e2 || e1 < w2 || s1 > n2 || n1 < s2);
}
