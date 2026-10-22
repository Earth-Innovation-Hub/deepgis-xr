// DeepGIS AI pilot chat, shared by the Earth, Moon and planet viewers.
// POST /label/api/pilot/ turns a request into actions (goto, orbit, takeoff,
// land, look, stop, wait, show_layer, hide_layer); they run here, in order,
// on the drone (hud/drone.js). On Earth place names go to OpenStreetMap, then
// Cesium Ion, and data layers are available; elsewhere names come from the IAU
// gazetteer (scripts/build_planet_nomenclature.py) and the page's preset sites.
(function initAiPilot() {
    const panel = document.getElementById('pilotPanel');
    const toggleBtn = document.getElementById('hudPilotBtn');
    const log = document.getElementById('pilotLog');
    const form = document.getElementById('pilotForm');
    const input = document.getElementById('pilotInput');
    const sendBtn = document.getElementById('pilotSendBtn');
    const stopBtn = document.getElementById('pilotStopBtn');
    if (!panel || !toggleBtn || !form) return;

    const history = [];
    const geocodeCache = new Map();
    let runId = 0; // bumped to cancel the running plan

    class Cancelled extends Error {}

    const body = panel.dataset.body || 'earth';
    const isEarth = body === 'earth';
    // Flight envelope: Earth is flown at drone scale, other bodies at orbiter scale
    const SCALE = isEarth
        ? { alt: 20000, radius: 20000, orbitAlt: 3000, speed: 150, climb: 50 }
        : { alt: 200000, radius: 300000, orbitAlt: 100000, speed: 2000, climb: 1000 };

    const getViewer = () => window.AppState?.viewer || window.viewer;
    const ellipsoid = () => getViewer().scene.globe.ellipsoid;
    const drone = () => window.DeepGISDrone || {};
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const fmtM = (m) => m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;

    toggleBtn.addEventListener('click', () => {
        const open = panel.classList.toggle('visible');
        toggleBtn.classList.toggle('active', open);
        if (open) input.focus();
    });
    document.getElementById('pilotCloseBtn').addEventListener('click', () => {
        panel.classList.remove('visible');
        toggleBtn.classList.remove('active');
    });

    function addMsg(kind, text, linkHref) {
        const div = document.createElement('div');
        div.className = `pilot-msg ${kind}`;
        div.textContent = text;
        if (linkHref) {
            const a = document.createElement('a');
            a.href = linkHref;
            a.textContent = ' Sign in';
            div.appendChild(a);
        }
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
        return div;
    }

    function csrfToken() {
        const el = document.querySelector('input[name=csrfmiddlewaretoken]');
        return el ? el.value
            : (document.cookie.split('; ').find(c => c.startsWith('csrftoken='))?.split('=')[1] || '');
    }

    async function groundHeight(lon, lat) {
        const viewer = getViewer();
        const carto = Cesium.Cartographic.fromRadians(lon, lat);
        try {
            const [s] = await Cesium.sampleTerrainMostDetailed(viewer.terrainProvider, [carto]);
            if (Number.isFinite(s.height)) return s.height;
        } catch (e) { /* ellipsoid or unavailable terrain */ }
        return viewer.scene.globe.getHeight(carto) || 0;
    }

    // Ground point at the centre of the screen (what the user is looking at)
    function viewTarget() {
        const viewer = getViewer();
        const canvas = viewer.scene.canvas;
        const centre = new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2);
        const ray = viewer.camera.getPickRay(centre);
        const hit = (ray && viewer.scene.globe.pick(ray, viewer.scene)) ||
            viewer.camera.pickEllipsoid(centre, ellipsoid());
        return hit ? Cesium.Cartographic.fromCartesian(hit, ellipsoid()) : null;
    }

    async function currentView() {
        const viewer = getViewer();
        const cam = viewer.camera.positionCartographic;
        const ground = await groundHeight(cam.longitude, cam.latitude);
        const view = {
            lat: Cesium.Math.toDegrees(cam.latitude),
            lon: Cesium.Math.toDegrees(cam.longitude),
            height_agl: cam.height - ground,
            heading_deg: Cesium.Math.toDegrees(viewer.camera.heading),
        };
        const t = viewTarget();
        if (t) view.target = { lat: Cesium.Math.toDegrees(t.latitude), lon: Cesium.Math.toDegrees(t.longitude) };
        return view;
    }

    // OpenStreetMap knows parks, peaks and landmarks that Ion misses ("Griffith
    // Park, Los Angeles" came back from Ion as Carlton Way Park). Public
    // Nominatim allows ~1 request/s; lookups are cached per page.
    async function nominatim(place) {
        const url = 'https://nominatim.openstreetmap.org/search?' +
            new URLSearchParams({ q: place, format: 'jsonv2', limit: '1', 'accept-language': 'en' });
        try {
            const resp = await fetch(url, { signal: AbortSignal.timeout(8000) });
            if (!resp.ok) return null;
            const [h] = await resp.json();
            if (!h) return null;
            const [south, north, west, east] = h.boundingbox.map(Number);
            const lat = Cesium.Math.toRadians(Number(h.lat));
            const sizeM = Math.max(Cesium.Math.toRadians(east - west) * EARTH_R * Math.cos(lat),
                                   Cesium.Math.toRadians(north - south) * EARTH_R);
            return { lon: Cesium.Math.toRadians(Number(h.lon)), lat, sizeM: sizeM > 50 ? sizeM : null,
                     label: h.display_name.split(', ').slice(0, 3).join(', ') };
        } catch (e) {
            return null;
        }
    }

    // Off Earth, places come from the IAU gazetteer ([name, lat, lon, diameter_km,
    // type] rows, largest first) plus the page's preset sites (#modelLocation)
    let gazetteer = null;
    const normName = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
        .replace(/\b(the|crater|landing site|site)\b/g, '').replace(/[^a-z0-9]+/g, ' ').trim();

    async function loadGazetteer() {
        if (gazetteer) return gazetteer;
        const rows = [];
        document.querySelectorAll('#modelLocation option[data-lat]').forEach(o => {
            rows.push([o.textContent.trim(), +o.dataset.lat, +o.dataset.lon, 0, 'Preset site']);
        });
        const url = panel.dataset.gazetteerUrl;
        if (url) {
            try {
                const r = await fetch(url);
                if (r.ok) rows.push(...(await r.json()).features);
            } catch (e) { console.warn('Gazetteer unavailable:', e); }
        }
        gazetteer = rows.map(f => ({ key: normName(f[0]), f }));
        return gazetteer;
    }

    async function gazetteerPlace(name) {
        const q = normName(name);
        if (!q) return null;
        const rows = await loadGazetteer();
        const m = rows.find(r => r.key === q) ||
            rows.find(r => r.key.startsWith(q + ' ') || q.startsWith(r.key + ' ')) ||
            rows.find(r => r.key.includes(q));
        if (!m) return null;
        const [label, lat, lon, km, type] = m.f;
        return { lon: Cesium.Math.toRadians(lon), lat: Cesium.Math.toRadians(lat),
                 sizeM: km > 0 ? km * 1000 : null, label: type ? `${label} (${type.split(',')[0]})` : label };
    }

    // -> {lon, lat (radians), sizeM (place extent or null), label}
    async function resolvePoint(a) {
        if (Number.isFinite(a.lat) && Number.isFinite(a.lon)) {
            return { lon: Cesium.Math.toRadians(a.lon), lat: Cesium.Math.toRadians(a.lat), sizeM: null,
                     label: `${a.lat.toFixed(4)}, ${a.lon.toFixed(4)}` };
        }
        if (a.place && !isEarth) {
            const hit = await gazetteerPlace(a.place);
            if (!hit) throw new Error(`No IAU-named feature "${a.place}" on ${body}`);
            return hit;
        }
        if (a.place) {
            let hit = geocodeCache.get(a.place) || await geologyPlace(a.place);
            if (!hit && (hit = await nominatim(a.place))) geocodeCache.set(a.place, hit);
            if (!hit) {
                const svc = new Cesium.IonGeocoderService({ scene: getViewer().scene });
                const results = await svc.geocode(a.place);
                if (!results || !results.length) throw new Error(`Could not find "${a.place}"`);
                const dest = results[0].destination;
                if (dest instanceof Cesium.Rectangle) {
                    const c = Cesium.Rectangle.center(dest);
                    const R = Cesium.Ellipsoid.WGS84.maximumRadius;
                    const w = dest.width * R * Math.cos(c.latitude), h = dest.height * R;
                    hit = { lon: c.longitude, lat: c.latitude, sizeM: Math.max(w, h) };
                } else {
                    const c = Cesium.Cartographic.fromCartesian(dest);
                    hit = { lon: c.longitude, lat: c.latitude, sizeM: null };
                }
                hit.label = results[0].displayName || a.place;
                geocodeCache.set(a.place, hit);
            }
            return hit;
        }
        const t = viewTarget() || getViewer().camera.positionCartographic;
        return { lon: t.longitude, lat: t.latitude, sizeM: null, label: 'the point in view' };
    }

    function check(id) { if (id !== runId) throw new Cancelled(); }

    // Data layers (show_layer / hide_layer). The model only picks the kind, place
    // and radius; each kind in LAYERS fetches from a public, citable source, then
    // the runner draws, lists and cites what came back, so nothing is invented.
    const EARTH_R = 6371008.8;
    const deg = (r) => Cesium.Math.toDegrees(r);
    const rad = (d) => Cesium.Math.toRadians(d);
    const shownLayers = new Map(); // kind -> {ds, imagery}
    let layerArea = null; // {lon, lat (radians), radius (m)} of the latest layer shown

    // Curated geology sites: descriptions from the Arizona Geological Survey and
    // others, coordinates from OpenStreetMap
    const GEOLOGY_URL = panel.dataset.geologyUrl;
    let geologyData = null;

    function distanceM(lon1, lat1, lon2, lat2) {
        const s = Math.sin((lat2 - lat1) / 2) ** 2 +
            Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2;
        return 2 * EARTH_R * Math.asin(Math.min(1, Math.sqrt(s)));
    }

    function insideRing(ring, x, y) {
        let inside = false;
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            const [xi, yi] = ring[i], [xj, yj] = ring[j];
            if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
        }
        return inside;
    }

    // Metres from (lon, lat) radians to a feature: 0 inside an outline, else the nearest vertex
    function featureDistance(f, lon, lat) {
        const g = f.geometry || {};
        const x = Cesium.Math.toDegrees(lon), y = Cesium.Math.toDegrees(lat);
        const polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
        if (polys.some(p => insideRing(p[0], x, y))) return 0;
        let best = Infinity;
        const walk = (c) => {
            if (typeof c[0] === 'number') {
                best = Math.min(best, distanceM(lon, lat, Cesium.Math.toRadians(c[0]), Cesium.Math.toRadians(c[1])));
            } else c.forEach(walk);
        };
        walk(g.coordinates || []);
        return best;
    }

    const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    function geologyHtml(p, d) {
        const rows = [['Type', p.category], ['Rock units', p.rock_units], ['Age', p.age], ['Distance', fmtM(d)]]
            .filter(r => r[1]).map(r => `<tr><th>${r[0]}</th><td>${esc(r[1])}</td></tr>`).join('');
        const sources = (p.sources || []).filter(s => /^https?:\/\//.test(s.url || ''))
            .map(s => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join('');
        return (p.description ? `<p>${esc(p.description)}</p>` : '') +
            `<table class="cesium-infoBox-defaultTable"><tbody>${rows}</tbody></table>` +
            (sources ? `<p>Sources:</p><ul>${sources}</ul>` : '') +
            (p.coord_source ? `<p style="font-size:11px">Location: ${esc(p.coord_source)}</p>` : '');
    }

    async function loadGeology() {
        if (!geologyData) {
            const resp = await fetch(GEOLOGY_URL);
            if (!resp.ok) throw new Error('Could not load the geology layer');
            geologyData = await resp.json();
        }
        return geologyData;
    }

    // Ion has no peaks or buttes ("Hayden Butte" comes back as Hayden Rd), so
    // names of mapped geology sites resolve to their OpenStreetMap point first.
    // "Tempe Butte (Hayden Butte)" answers to either name.
    async function geologyPlace(place) {
        const key = place.split(',')[0].trim().toLowerCase().replace(/^the /, '');
        let data;
        try { data = await loadGeology(); } catch (e) { return null; }
        const f = data.features.find(f => f.geometry.type === 'Point' &&
            f.properties.name.toLowerCase().split(/\s*[()]\s*/).filter(Boolean).includes(key));
        if (!f) return null;
        const [lon, lat] = f.geometry.coordinates;
        return { lon: Cesium.Math.toRadians(lon), lat: Cesium.Math.toRadians(lat), sizeM: null,
                 label: f.properties.name };
    }

    // Published geologic maps anywhere (most detailed in the US) via Macrostrat:
    // sample the map at the centre and on two rings, keep the most detailed
    // map at each point, merge repeats. Each unit carries its source map.
    const MACROSTRAT_API = 'https://macrostrat.org/api/v2/geologic_units/map';
    const MACROSTRAT_TILES = 'https://tiles.macrostrat.org/carto/{z}/{x}/{y}.png';
    const MAP_SCALES = ['large', 'medium', 'small', 'tiny'];

    async function mapUnits(lon, lat, radius) {
        const pts = ringPoints(lon, lat, radius, [[0.5, 6], [1, 8]]);
        const hits = await Promise.all(pts.map(async ([x, y]) => {
            try {
                const resp = await fetch(`${MACROSTRAT_API}?` + new URLSearchParams({
                    lat: Cesium.Math.toDegrees(y).toFixed(5), lng: Cesium.Math.toDegrees(x).toFixed(5) }));
                if (!resp.ok) return null;
                const res = (await resp.json()).success || {};
                const data = res.data || [];
                const u = MAP_SCALES.map(s => data.find(d => d.scale === s)).find(Boolean);
                return u ? { u, ref: (res.refs || {})[u.source_id], d: distanceM(lon, lat, x, y) } : null;
            } catch (e) {
                return null;
            }
        }));
        const units = new Map();
        hits.filter(Boolean).forEach(h => {
            const key = `${h.u.source_id}|${h.u.name}`;
            const prev = units.get(key);
            if (prev) { prev.n++; prev.d = Math.min(prev.d, h.d); } else units.set(key, { ...h, n: 1 });
        });
        return { sampled: pts.length, units: [...units.values()].sort((x, y) => y.n - x.n || x.d - y.d) };
    }

    function unitLine({ u, d }) {
        const age = u.b_int_name === u.t_int_name ? u.b_int_name : `${u.b_int_name} to ${u.t_int_name}`;
        const fmtMa = (v) => v >= 1 ? String(Math.round(v * 10) / 10) : String(+v.toPrecision(2));
        const ma = Number.isFinite(u.b_int_age) && Number.isFinite(u.t_int_age)
            ? ` (${fmtMa(u.b_int_age)}-${fmtMa(u.t_int_age)} Ma)` : '';
        let rock = (u.descrip || u.lith || '').replace(/\s+/g, ' ').trim();
        if (rock.length > 110) rock = rock.slice(0, 107) + '...';
        const where = d < 1 ? 'at the centre' : `nearest ${fmtM(d)}`;
        return `${u.name}: ${age}${ma}${rock ? '; ' + rock : ''} [${where}]`;
    }

    function offsetPoint(lon, lat, east, north) {
        return [lon + east / (EARTH_R * Math.cos(lat)), lat + north / EARTH_R];
    }

    // The centre plus rings of sample points: [[lon, lat] radians]; rings = [[fraction of radius, count]]
    function ringPoints(lon, lat, radius, rings) {
        const pts = [[lon, lat]];
        for (const [frac, n] of rings) {
            for (let k = 0; k < n; k++) {
                const t = 2 * Math.PI * k / n;
                pts.push(offsetPoint(lon, lat, radius * frac * Math.cos(t), radius * frac * Math.sin(t)));
            }
        }
        return pts;
    }

    function areaRect(lon, lat, radius) {
        const dLat = radius / EARTH_R, dLon = radius / (EARTH_R * Math.cos(lat));
        return new Cesium.Rectangle(lon - dLon, lat - dLat, lon + dLon, lat + dLat);
    }

    async function fetchJson(url, opts = {}, timeoutMs = 25000) {
        const host = new URL(url).host;
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), timeoutMs);
        opts.signal?.addEventListener('abort', () => ctl.abort());
        try {
            const resp = await fetch(url, { ...opts, signal: ctl.signal });
            if (!resp.ok) throw new Error(`${host} returned HTTP ${resp.status}`);
            const text = await resp.text();
            try { return JSON.parse(text); } catch (e) { throw new Error(`${host} is unavailable right now (not a data response)`); }
        } catch (e) {
            if (e.name === 'AbortError') throw new Error(`${host} did not respond`);
            throw e;
        } finally {
            clearTimeout(timer);
        }
    }

    // ArcGIS feature query: features within radius of the point, as GeoJSON
    async function arcgisNear(layerUrl, p, radius, params) {
        const fc = await fetchJson(`${layerUrl}/query?` + new URLSearchParams({
            where: '1=1', geometryType: 'esriGeometryPoint', inSR: '4326',
            geometry: JSON.stringify({ x: deg(p.lon), y: deg(p.lat), spatialReference: { wkid: 4326 } }),
            distance: String(Math.round(radius)), units: 'esriSRUnit_Meter',
            spatialRel: 'esriSpatialRelIntersects', outSR: '4326', geometryPrecision: '5',
            returnGeometry: 'true', f: 'geojson', ...params,
        }));
        if (fc.error) throw new Error(fc.error.message || `${new URL(layerUrl).host} query failed`);
        return fc;
    }

    function tableHtml(rows, links = []) {
        const body = rows.filter(r => r[1] !== undefined && r[1] !== null && r[1] !== '')
            .map(r => `<tr><th>${esc(r[0])}</th><td>${esc(r[1])}</td></tr>`).join('');
        const anchors = links.filter(l => /^https?:\/\//.test(l[1] || ''))
            .map(l => `<p><a href="${esc(l[1])}" target="_blank" rel="noopener">${esc(l[0])}</a></p>`).join('');
        return `<table class="cesium-infoBox-defaultTable"><tbody>${body}</tbody></table>${anchors}`;
    }

    function pinLabel(e, text) {
        e.label = new Cesium.LabelGraphics({
            text, font: '13px sans-serif',
            fillColor: Cesium.Color.WHITE, outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cesium.Cartesian2(0, -40),
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
        });
    }

    // Dots instead of pins for layers with many points
    function dot(e, color) {
        e.billboard = undefined;
        e.point = new Cesium.PointGraphics({
            pixelSize: 9, color, outlineColor: Cesium.Color.BLACK, outlineWidth: 1,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
        });
    }

    const nearestText = (d) => d < 1 ? 'at the centre' : `nearest ${fmtM(d)}`;
    const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;

    function lineLength(coords) {
        let m = 0;
        for (let i = 1; i < coords.length; i++) {
            m += distanceM(rad(coords[i - 1][0]), rad(coords[i - 1][1]), rad(coords[i][0]), rad(coords[i][1]));
        }
        return m;
    }

    // Centre and radius covering every coordinate of a FeatureCollection
    function boundsArea(fc) {
        let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
        const walk = (c) => {
            if (typeof c[0] === 'number') {
                w = Math.min(w, c[0]); e = Math.max(e, c[0]); s = Math.min(s, c[1]); n = Math.max(n, c[1]);
            } else c.forEach(walk);
        };
        fc.features.forEach(f => f.geometry && walk(f.geometry.coordinates));
        if (!Number.isFinite(w)) return null;
        const lon = rad((w + e) / 2), lat = rad((s + n) / 2);
        return { lon, lat, radius: Math.max(500, distanceM(lon, lat, rad(e), rad(n))) };
    }

    // ---- Layer sources ----
    const QFAULTS_URL = 'https://earthquake.usgs.gov/arcgis/rest/services/haz/Qfaults/MapServer/21';
    const FEMA_ZONES_URL = 'https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28';
    const NIFC_URL = 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/' +
        'InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0';
    const NLDI_URL = 'https://api.water.usgs.gov/nldi/linked-data';
    const NWIS_IV_URL = 'https://waterservices.usgs.gov/nwis/iv/';
    const NLCD_WMS = 'https://www.mrlc.gov/geoserver/mrlc_display/NLCD_2021_Land_Cover_L48/wms';
    const NLCD_LAYER = 'NLCD_2021_Land_Cover_L48';
    const SDA_URL = 'https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest';
    const SDM_WMS = 'https://sdmdataaccess.sc.egov.usda.gov/Spatial/SDM.wms';
    const INAT_URL = 'https://api.inaturalist.org/v1';
    // The public Overpass instance is often at capacity; try mirrors in turn
    const OVERPASS_URLS = ['https://overpass-api.de/api/interpreter',
        'https://maps.mail.ru/osm/tools/overpass/api/interpreter', 'https://overpass.private.coffee/api/interpreter'];

    function faultColor(age = '') {
        const a = String(age).toLowerCase();
        if (a.includes('historic')) return Cesium.Color.RED;
        if (a.includes('latest')) return Cesium.Color.ORANGERED;
        if (a.startsWith('late')) return Cesium.Color.ORANGE;
        if (a.includes('middle')) return Cesium.Color.YELLOW;
        return Cesium.Color.LIGHTGRAY;
    }

    const FLOOD_ZONES = {
        A: '1% annual chance (100-year) flood, no base flood elevation',
        AE: '1% annual chance (100-year) flood, base flood elevation set',
        AH: '1% annual chance shallow ponding, 1-3 ft deep',
        AO: '1% annual chance sheet flow, 1-3 ft deep',
        AR: '1% annual chance flood, levee being restored',
        A99: '1% annual chance flood, levee under construction',
        V: 'coastal high hazard (1% annual chance)',
        VE: 'coastal high hazard (1% annual chance) with wave action',
        D: 'possible but undetermined flood hazard',
    };

    function floodLabel(q) {
        const sub = String(q.ZONE_SUBTY || '').trim();
        if (q.FLD_ZONE === 'X') {
            if (sub.includes('0.2')) return 'Zone X (shaded): 0.2% annual chance (500-year) flood';
            return sub ? `Zone X: ${sub.toLowerCase()}` : 'Zone X: minimal flood hazard';
        }
        const base = `Zone ${q.FLD_ZONE}: ${FLOOD_ZONES[q.FLD_ZONE] || 'special flood hazard area'}`;
        return sub.includes('FLOODWAY') ? `${base}, regulatory floodway` : base;
    }

    const NLCD_CLASSES = {
        11: 'Open water', 12: 'Perennial ice/snow',
        21: 'Developed, open space', 22: 'Developed, low intensity',
        23: 'Developed, medium intensity', 24: 'Developed, high intensity',
        31: 'Barren land (rock, sand, clay)',
        41: 'Deciduous forest', 42: 'Evergreen forest', 43: 'Mixed forest',
        51: 'Dwarf scrub', 52: 'Shrub/scrub', 71: 'Grassland/herbaceous',
        72: 'Sedge/herbaceous', 73: 'Lichens', 74: 'Moss',
        81: 'Pasture/hay', 82: 'Cultivated crops',
        90: 'Woody wetlands', 95: 'Emergent herbaceous wetlands',
    };

    async function nlcdAt(lonDeg, latDeg) {
        const d = 0.0002;
        const j = await fetchJson(`${NLCD_WMS}?` + new URLSearchParams({
            service: 'WMS', version: '1.1.1', request: 'GetFeatureInfo',
            layers: NLCD_LAYER, query_layers: NLCD_LAYER, srs: 'EPSG:4326',
            bbox: [lonDeg - d, latDeg - d, lonDeg + d, latDeg + d].join(','),
            width: '3', height: '3', x: '1', y: '1', info_format: 'application/json',
        }));
        return j.features?.[0]?.properties?.PALETTE_INDEX;
    }

    // USDA Soil Data Access: SQL in, rows as objects out (form POST avoids a CORS preflight)
    async function sda(query) {
        const j = await fetchJson(SDA_URL, { method: 'POST', body: new URLSearchParams({ query, format: 'JSON+COLUMNNAME' }) });
        const [head, ...rows] = j.Table || [];
        return head ? rows.map(r => Object.fromEntries(head.map((h, i) => [h, r[i]]))) : [];
    }

    // Instances can each take 15-40 s when loaded, so ask all and keep the first answer
    // and retry once after quick refusals (rate limits)
    async function overpass(query) {
        for (let attempt = 0; attempt < 2; attempt++) {
            const ctl = new AbortController();
            const t0 = Date.now();
            try {
                return await Promise.any(OVERPASS_URLS.map(url => fetchJson(url,
                    { method: 'POST', body: new URLSearchParams({ data: query }), signal: ctl.signal }, 60000)));
            } catch (e) {
                if (Date.now() - t0 > 20000) break;
                await new Promise(r => setTimeout(r, 5000));
            } finally {
                ctl.abort();
            }
        }
        throw new Error('The OpenStreetMap feature service (Overpass) is busy; try again in a minute');
    }

    function osmGeoJson(elements) {
        return {
            type: 'FeatureCollection',
            features: elements.map(el => {
                let geometry = null;
                if (el.type === 'node') geometry = { type: 'Point', coordinates: [el.lon, el.lat] };
                else if (el.geometry) geometry = { type: 'LineString', coordinates: el.geometry.map(g => [g.lon, g.lat]) };
                else if (el.center) geometry = { type: 'Point', coordinates: [el.center.lon, el.center.lat] };
                return geometry && { type: 'Feature', geometry, properties: { ...el.tags, osm_id: `${el.type}/${el.id}` } };
            }).filter(Boolean),
        };
    }

    const around = (p, radius) => `(around:${Math.round(radius)},${deg(p.lat).toFixed(5)},${deg(p.lon).toFixed(5)})`;
    const OSM_SOURCE = 'OpenStreetMap contributors (ODbL), via the Overpass API';

    function osmHtml(q, rows) {
        return tableHtml([['Name', q.name], ...rows], [['View on OpenStreetMap', `https://www.openstreetmap.org/${q.osm_id}`]]);
    }

    function circlePositions(lon, lat, radius) {
        const pts = [];
        for (let k = 0; k <= 128; k++) {
            const t = 2 * Math.PI * k / 128;
            const la = lat + radius * Math.sin(t) / EARTH_R;
            pts.push(Cesium.Cartesian3.fromRadians(lon + radius * Math.cos(t) / (EARTH_R * Math.cos(lat)), la));
        }
        return pts;
    }

    // Each kind: load(p, radius, action) -> {fc?, style?, decorate?(entity, props),
    // imagery?, imageryAlpha?, area?, lines: [[msgKind, text]], sources: [text], empty}
    const LAYERS = {
        geology: {
            title: 'Geology', radius: 5000,
            async load(p, radius) {
                const unitsPending = mapUnits(p.lon, p.lat, radius);
                const data = await loadGeology();
                const found = data.features
                    .map(f => ({ f, d: featureDistance(f, p.lon, p.lat) }))
                    .filter(x => x.d <= radius)
                    .sort((x, y) => x.d - y.d);
                const byName = new Map(found.map(x => [x.f.properties.name, x]));
                const lines = [];
                const sites = found.filter(x => x.f.geometry.type === 'Point');
                if (sites.length) {
                    lines.push(['step', `Geologic sites within ${fmtM(radius)} of ${p.label} ` +
                        '(click a marker for rock units and sources):']);
                    sites.forEach(({ f, d }) => lines.push(['geo',
                        `${f.properties.name}, ${fmtM(d)}: ${f.properties.category}; ${f.properties.age}`]));
                }
                const { sampled, units } = await unitsPending;
                const top = units.slice(0, 8);
                if (top.length) {
                    lines.push(['step', `Geologic map units within ${fmtM(radius)} of ${p.label} ` +
                        `(Macrostrat, ${sampled} sample points; map overlay shown):`]);
                    top.forEach(x => lines.push(['geo', unitLine(x)]));
                }
                return {
                    fc: { type: 'FeatureCollection', features: found.map(x => x.f) },
                    style: { fill: Cesium.Color.ORANGE.withAlpha(0.15), markerColor: Cesium.Color.ORANGERED, markerSymbol: 'mountain' },
                    decorate(e) {
                        const hit = byName.get(e.name);
                        if (hit) e.description = geologyHtml(hit.f.properties, hit.d);
                        if (e.billboard) pinLabel(e, e.name);
                    },
                    imagery: new Cesium.UrlTemplateImageryProvider({
                        url: MACROSTRAT_TILES, tileWidth: 512, tileHeight: 512, maximumLevel: 13,
                        rectangle: areaRect(p.lon, p.lat, radius),
                        credit: new Cesium.Credit('Geologic map: Macrostrat (CC BY 4.0)'),
                    }),
                    imageryAlpha: 0.55,
                    lines,
                    sources: [...new Set(top.map(x => x.ref).filter(Boolean))],
                    empty: `No geologic data found within ${fmtM(radius)} of ${p.label}`,
                };
            },
        },

        faults: {
            title: 'Faults', radius: 15000,
            async load(p, radius) {
                const fc = await arcgisNear(QFAULTS_URL, p, radius, {
                    outFields: 'fault_name,section_name,age,slip_rate,slip_sense,dip_direction,class,mapped_scale,fault_url',
                    maxAllowableOffset: '0.0001', resultRecordCount: '2000',
                });
                const groups = new Map();
                fc.features.forEach(f => {
                    const q = f.properties, d = featureDistance(f, p.lon, p.lat);
                    const key = `${q.fault_name}|${q.section_name || ''}`;
                    const g = groups.get(key);
                    if (g) g.d = Math.min(g.d, d); else groups.set(key, { q, d });
                });
                const list = [...groups.values()].sort((x, y) => x.d - y.d);
                const lines = list.length ? [['step', `Quaternary faults within ${fmtM(radius)} of ${p.label} ` +
                    `(USGS; ${list.length === 1 ? '1 fault' : `${list.length} faults and fault sections`}, nearest first; click a line for its report):`]] : [];
                list.slice(0, 12).forEach(({ q, d }) => {
                    const motion = [q.slip_sense, q.slip_rate].filter(v => v && v !== 'Unspecified').join(', ');
                    const section = q.section_name ? `, ${q.section_name.replace(/\s+section$/i, '')} section` : '';
                    lines.push(['geo', `${q.fault_name}${section}: ` +
                        `last moved ${q.age || 'at an unknown time'}${motion ? `; ${motion}` : ''} [${nearestText(d)}]`]);
                });
                return {
                    fc, style: { stroke: Cesium.Color.ORANGERED, strokeWidth: 3 },
                    decorate(e, q) {
                        if (e.polyline) {
                            e.polyline.material = faultColor(q.age);
                            e.polyline.width = 3;
                        }
                        e.name = q.fault_name;
                        e.description = tableHtml([['Fault', q.fault_name], ['Section', q.section_name],
                            ['Most recent movement', q.age], ['Slip sense', q.slip_sense], ['Slip rate', q.slip_rate],
                            ['Dip direction', q.dip_direction], ['Class', q.class], ['Mapped at', q.mapped_scale]],
                            [['USGS fault report', q.fault_url]]);
                    },
                    lines,
                    sources: ['U.S. Geological Survey and state geological surveys, Quaternary Fault and Fold Database of the United States'],
                    empty: `No mapped Quaternary faults within ${fmtM(radius)} of ${p.label} (the USGS database covers the US)`,
                };
            },
        },

        flood: {
            title: 'Flood zones', radius: 3000,
            async load(p, radius) {
                const [fc, centre] = await Promise.all([
                    arcgisNear(FEMA_ZONES_URL, p, radius, {
                        where: "SFHA_TF = 'T' OR ZONE_SUBTY LIKE '%0.2%'",
                        outFields: 'FLD_ZONE,ZONE_SUBTY,SFHA_TF', maxAllowableOffset: '0.0001', resultRecordCount: '500',
                    }),
                    arcgisNear(FEMA_ZONES_URL, p, 1, { outFields: 'FLD_ZONE,ZONE_SUBTY,SFHA_TF', returnGeometry: 'false' })
                        .catch(() => null),
                ]);
                const tally = new Map();
                fc.features.forEach(f => {
                    const k = floodLabel(f.properties);
                    tally.set(k, (tally.get(k) || 0) + 1);
                });
                const here = centre?.features?.[0] ? floodLabel(centre.features[0].properties) : null;
                const lines = [];
                if (here || tally.size) {
                    lines.push(['step', `FEMA flood zones within ${fmtM(radius)} of ${p.label} ` +
                        '(blue: 1% annual chance, orange: 0.2%; click an area for its zone):']);
                    if (here) lines.push(['geo', `At the centre: ${here}`]);
                    [...tally.entries()].sort((x, y) => y[1] - x[1])
                        .forEach(([k, n]) => lines.push(['geo', `${k}: ${plural(n, 'mapped area')}`]));
                    if (!tally.size) lines.push(['geo', 'No 1% or 0.2% annual chance flood areas mapped in the circle']);
                }
                return {
                    fc, style: { fill: Cesium.Color.DODGERBLUE.withAlpha(0.35) },
                    decorate(e, q) {
                        const floodway = String(q.ZONE_SUBTY || '').includes('FLOODWAY');
                        if (e.polygon) {
                            e.polygon.material = q.SFHA_TF === 'T'
                                ? (floodway ? Cesium.Color.NAVY : Cesium.Color.DODGERBLUE).withAlpha(0.4)
                                : Cesium.Color.ORANGE.withAlpha(0.3);
                        }
                        e.name = `Flood zone ${q.FLD_ZONE}`;
                        e.description = tableHtml([['Zone', floodLabel(q)], ['Subtype', q.ZONE_SUBTY],
                            ['Special flood hazard area', q.SFHA_TF === 'T' ? 'Yes' : 'No']],
                            [['FEMA Flood Map Service Center (official maps)', 'https://msc.fema.gov/portal/home']]);
                    },
                    lines,
                    sources: ['FEMA National Flood Hazard Layer (NFHL); use the FEMA Flood Map Service Center for official determinations'],
                    empty: `No FEMA flood map data within ${fmtM(radius)} of ${p.label}; the map may not cover this area (US only)`,
                };
            },
        },

        fires: {
            title: 'Fire perimeters', radius: 20000,
            async load(p, radius) {
                const fc = await arcgisNear(NIFC_URL, p, radius, {
                    outFields: 'INCIDENT,FIRE_YEAR_INT,GIS_ACRES,AGENCY,SOURCE',
                    orderByFields: 'GIS_ACRES DESC', resultRecordCount: '200', maxAllowableOffset: '0.0005',
                });
                const fires = new Map();
                fc.features.forEach(f => {
                    const q = f.properties, d = featureDistance(f, p.lon, p.lat);
                    // Agencies often each map the same fire, with differently cased names
                    const key = `${String(q.INCIDENT || '').trim().toLowerCase()}|${q.FIRE_YEAR_INT}`;
                    const g = fires.get(key);
                    if (g) { g.acres = Math.max(g.acres, q.GIS_ACRES || 0); g.d = Math.min(g.d, d); }
                    else fires.set(key, { q, acres: q.GIS_ACRES || 0, d });
                });
                const list = [...fires.values()].sort((x, y) => y.acres - x.acres);
                const years = list.map(x => x.q.FIRE_YEAR_INT).filter(Number.isFinite);
                const span = years.length ? `, ${Math.min(...years)}-${Math.max(...years)}` : '';
                const lines = list.length ? [['step', `Past fire perimeters within ${fmtM(radius)} of ${p.label} ` +
                    `(NIFC, ${plural(list.length, 'fire')}${span}${fc.features.length >= 200 ? ', largest 200 shown' : ''}; largest first):`]] : [];
                list.slice(0, 12).forEach(({ q, acres, d }) => lines.push(['geo',
                    `${q.INCIDENT || 'Unnamed fire'} (${q.FIRE_YEAR_INT || 'year unknown'}): ` +
                    `${Math.round(acres).toLocaleString()} acres${q.AGENCY ? `, ${q.AGENCY}` : ''} [${nearestText(d)}]`]));
                return {
                    fc, style: { fill: Cesium.Color.RED.withAlpha(0.25) },
                    decorate(e, q) {
                        if (e.polygon) e.polygon.material = Cesium.Color.RED.withAlpha(0.25);
                        e.name = `${q.INCIDENT || 'Fire'} (${q.FIRE_YEAR_INT || '?'})`;
                        e.description = tableHtml([['Fire', q.INCIDENT], ['Year', q.FIRE_YEAR_INT],
                            ['Acres', q.GIS_ACRES && Math.round(q.GIS_ACRES).toLocaleString()],
                            ['Agency', q.AGENCY], ['Perimeter source', q.SOURCE]]);
                    },
                    lines,
                    sources: ['National Interagency Fire Center, InterAgency Fire Perimeter History (all years)'],
                    empty: `No recorded fire perimeters within ${fmtM(radius)} of ${p.label} (NIFC history, US only)`,
                };
            },
        },

        river: {
            title: 'River trace', radius: null,
            async load(p, radius, a) {
                const km = a.distance_km || 50;
                const wkt = `POINT(${deg(p.lon).toFixed(5)} ${deg(p.lat).toFixed(5)})`;
                const pos = await fetchJson(`${NLDI_URL}/comid/position?coords=${encodeURIComponent(wkt)}`);
                const comid = pos.features?.[0]?.properties?.comid;
                if (!comid) throw new Error(`No mapped stream or river at ${p.label}`);
                const nav = `${NLDI_URL}/comid/${comid}/navigation/DM`;
                const [flow, sites] = await Promise.all([
                    fetchJson(`${nav}/flowlines?distance=${km}`),
                    fetchJson(`${nav}/nwissite?distance=${km}`).catch(() => ({ features: [] })),
                ]);
                const ids = sites.features.map(f => String(f.properties.identifier || '').replace(/^USGS-/, ''));
                const live = new Map();
                if (ids.length) {
                    const iv = await fetchJson(`${NWIS_IV_URL}?` + new URLSearchParams({
                        // Without a period NWIS returns each gauge's last value ever, which can be decades old
                        format: 'json', parameterCd: '00060', period: 'PT12H', sites: ids.slice(0, 100).join(','),
                    })).catch(() => null);
                    (iv?.value?.timeSeries || []).forEach(ts => {
                        const v = ts.values?.[0]?.value?.slice(-1)[0];
                        const q = v ? Number(v.value) : NaN;
                        if (Number.isFinite(q) && q > -999999) {
                            live.set(ts.sourceInfo.siteCode[0].value, { q, t: v.dateTime });
                        }
                    });
                }
                const gauges = sites.features.map((f, i) => {
                    const [x, y] = f.geometry.coordinates;
                    return { f, id: ids[i], name: f.properties.name, live: live.get(ids[i]),
                             d: distanceM(p.lon, p.lat, rad(x), rad(y)) };
                }).sort((x, y) => x.d - y.d);
                const when = (t) => new Date(t).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
                const flowText = (g) => g.live ? `${g.live.q.toLocaleString()} ft³/s at ${when(g.live.t)}` : 'no live discharge reading';
                const fc = {
                    type: 'FeatureCollection',
                    features: [
                        ...flow.features.map(f => ({ ...f, properties: { kind: 'flowline' } })),
                        ...gauges.map(g => ({ type: 'Feature', geometry: g.f.geometry, properties: {
                            kind: 'gauge', name: g.name, site: g.id, flow: flowText(g), live: !!g.live } })),
                    ],
                };
                const withFlow = gauges.filter(g => g.live);
                const lines = [['step', `Downstream from ${p.label}: ${km} km traced on the NHDPlus river network, ` +
                    `${plural(gauges.length, 'USGS monitoring site')} (${withFlow.length} with live discharge):`]];
                withFlow.forEach(g => lines.push(['geo', `${g.name} (USGS ${g.id}): ${flowText(g)} [${fmtM(g.d)} from the start]`]));
                if (gauges.length && !withFlow.length) lines.push(['geo', 'None of the downstream sites is reporting live discharge']);
                if (gauges.length > withFlow.length && withFlow.length) {
                    lines.push(['geo', `${plural(gauges.length - withFlow.length, 'other site')} without a live discharge reading`]);
                }
                return {
                    fc, style: { stroke: Cesium.Color.DODGERBLUE, strokeWidth: 4, markerColor: Cesium.Color.DODGERBLUE, markerSymbol: 'water' },
                    decorate(e, q) {
                        if (q.kind === 'flowline' && e.polyline) {
                            e.polyline.material = Cesium.Color.DODGERBLUE;
                            e.polyline.width = 4;
                            e.name = 'Downstream flow path';
                        } else if (q.kind === 'gauge') {
                            if (q.live) pinLabel(e, q.flow.split(' at ')[0]); else dot(e, Cesium.Color.LIGHTSKYBLUE);
                            e.name = q.name;
                            e.description = tableHtml([['Site', q.name], ['USGS site number', q.site], ['Discharge', q.flow]],
                                [['USGS monitoring location page', `https://waterdata.usgs.gov/monitoring-location/${q.site}/`]]);
                        }
                    },
                    area: boundsArea(flow),
                    lines,
                    sources: ['USGS Network-Linked Data Index (NHDPlus V2 flowlines)',
                        'USGS Water Services instantaneous values (provisional data, subject to revision)'],
                    empty: '',
                };
            },
        },

        landcover: {
            title: 'Land cover', radius: 5000,
            async load(p, radius) {
                const pts = ringPoints(p.lon, p.lat, radius, [[0.5, 8], [1, 16]]);
                const vals = await Promise.all(pts.map(([x, y]) => nlcdAt(deg(x), deg(y)).catch(() => null)));
                const counts = new Map();
                let n = 0;
                vals.forEach(v => {
                    if (!NLCD_CLASSES[v]) return;
                    counts.set(v, (counts.get(v) || 0) + 1);
                    n++;
                });
                const lines = [];
                if (n) {
                    lines.push(['step', `Land cover within ${fmtM(radius)} of ${p.label} ` +
                        `(NLCD 2021, ${n} sample points; map overlay shown):`]);
                    if (NLCD_CLASSES[vals[0]]) lines.push(['geo', `At the centre: ${NLCD_CLASSES[vals[0]]}`]);
                    [...counts.entries()].sort((x, y) => y[1] - x[1])
                        .forEach(([c, k]) => lines.push(['geo', `${Math.round(100 * k / n)}% ${NLCD_CLASSES[c]}`]));
                }
                return {
                    imagery: new Cesium.WebMapServiceImageryProvider({
                        url: NLCD_WMS, layers: NLCD_LAYER, rectangle: areaRect(p.lon, p.lat, radius),
                        parameters: { transparent: true, format: 'image/png' },
                        credit: new Cesium.Credit('Land cover: NLCD 2021 (MRLC)'),
                    }),
                    imageryAlpha: 0.6,
                    lines,
                    sources: n ? ['Multi-Resolution Land Characteristics Consortium, National Land Cover Database 2021 (30 m, contiguous US)'] : [],
                    empty: `No NLCD land cover within ${fmtM(radius)} of ${p.label}; it covers the contiguous US only`,
                };
            },
        },

        soils: {
            title: 'Soils', radius: 300,
            async load(p, radius) {
                const ring = ringPoints(p.lon, p.lat, radius, [[1, 24]]).slice(1);
                const xy = ([x, y]) => `${deg(x).toFixed(6)} ${deg(y).toFixed(6)}`;
                const polygon = `polygon((${[...ring, ring[0]].map(xy).join(', ')}))`;
                const units = (geom) => `SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('${geom}')`;
                const [rows, centre] = await Promise.all([
                    sda('SELECT mu.mukey, mu.muname, l.areaname, c.compname, c.comppct_r, c.drainagecl, c.hydgrp ' +
                        'FROM mapunit mu JOIN legend l ON l.lkey = mu.lkey ' +
                        "LEFT JOIN component c ON c.mukey = mu.mukey AND c.majcompflag = 'Yes' " +
                        `WHERE mu.mukey IN (${units(polygon)}) ORDER BY mu.mukey, c.comppct_r DESC`),
                    sda(units(`point(${xy([p.lon, p.lat])})`)).catch(() => []),
                ]);
                const centreKey = centre[0] && String(Object.values(centre[0])[0]);
                const byUnit = new Map();
                rows.forEach(r => {
                    const u = byUnit.get(r.mukey) || { ...r, comps: [] };
                    if (r.compname) u.comps.push(`${r.compname} ${r.comppct_r || '?'}%`);
                    byUnit.set(r.mukey, u);
                });
                const list = [...byUnit.values()].sort((x, y) => (String(y.mukey) === centreKey) - (String(x.mukey) === centreKey));
                const lines = list.length ? [['step', `Soil map units within ${fmtM(radius)} of ${p.label} ` +
                    '(USDA SSURGO; the overlay shows unit boundaries):']] : [];
                list.slice(0, 8).forEach(u => {
                    const sameName = u.comps.length === 1 && u.compname &&
                        String(u.muname).toLowerCase().startsWith(String(u.compname).toLowerCase());
                    const props = [!sameName && u.comps.join(', '), u.drainagecl,
                        u.hydgrp && `hydrologic group ${u.hydgrp}`].filter(Boolean);
                    lines.push(['geo', `${u.muname}${String(u.mukey) === centreKey ? ' (at the centre)' : ''}` +
                        `${props.length ? ': ' + props.join('; ') : ''}`]);
                });
                const areas = [...new Set(list.map(u => u.areaname).filter(Boolean))];
                return {
                    imagery: new Cesium.WebMapServiceImageryProvider({
                        url: SDM_WMS, layers: 'mapunitpoly', rectangle: areaRect(p.lon, p.lat, Math.max(radius * 1.5, 300)),
                        parameters: { transparent: true, format: 'image/png' },
                        credit: new Cesium.Credit('Soils: USDA NRCS SSURGO'),
                    }),
                    imageryAlpha: 0.9,
                    lines,
                    sources: list.length ? ['USDA NRCS Soil Survey Geographic Database (SSURGO), via Soil Data Access',
                        ...areas.map(a => `Soil survey area: ${a}`)] : [],
                    empty: `No SSURGO soil survey data within ${fmtM(radius)} of ${p.label} (US only)`,
                };
            },
        },

        wildlife: {
            title: 'Wildlife', radius: 2000,
            async load(p, radius) {
                const q = { lat: deg(p.lat).toFixed(5), lng: deg(p.lon).toFixed(5),
                            radius: (radius / 1000).toFixed(2), quality_grade: 'research' };
                const [counts, obs] = await Promise.all([
                    fetchJson(`${INAT_URL}/observations/species_counts?` + new URLSearchParams({ ...q, per_page: '10' })),
                    fetchJson(`${INAT_URL}/observations?` + new URLSearchParams({ ...q, per_page: '200', order_by: 'observed_on' })),
                ]);
                const features = obs.results.filter(o => o.geojson && o.taxon).map(o => ({
                    type: 'Feature', geometry: o.geojson, properties: {
                        common: o.taxon.preferred_common_name || o.taxon.name, sci: o.taxon.name,
                        group: o.taxon.iconic_taxon_name, date: o.observed_on, user: o.user?.login,
                        license: o.license_code, uri: o.uri, photo: o.photos?.[0]?.url?.replace('square', 'small'),
                    },
                }));
                const lines = [];
                if (counts.results.length) {
                    lines.push(['step', `Wildlife within ${fmtM(radius)} of ${p.label} (iNaturalist research grade: ` +
                        `${plural(obs.total_results, 'observation')} of ${counts.total_results.toLocaleString()} species; most observed first):`]);
                    counts.results.forEach(r => lines.push(['geo',
                        `${r.taxon.preferred_common_name || r.taxon.name} (${r.taxon.name}), ` +
                        `${r.taxon.iconic_taxon_name || 'other'}: ${plural(r.count, 'observation')}`]));
                    lines.push(['step', `The map shows the ${features.length} most recent; click a dot for its photo and observer`]);
                }
                const GROUP_COLORS = { Aves: 'DEEPSKYBLUE', Mammalia: 'SIENNA', Reptilia: 'LIMEGREEN', Amphibia: 'TEAL',
                    Insecta: 'GOLD', Arachnida: 'ORANGE', Plantae: 'GREENYELLOW', Fungi: 'ORCHID', Mollusca: 'PINK' };
                return {
                    fc: { type: 'FeatureCollection', features },
                    decorate(e, o) {
                        dot(e, Cesium.Color[GROUP_COLORS[o.group]] || Cesium.Color.WHITE);
                        e.name = o.common;
                        e.description = (o.photo && /^https:\/\//.test(o.photo) ? `<img src="${esc(o.photo)}" style="max-width:100%">` : '') +
                            tableHtml([['Species', `${o.common} (${o.sci})`], ['Group', o.group], ['Observed', o.date],
                                ['Observer', o.user], ['License', o.license || 'all rights reserved']],
                                [['Observation on iNaturalist', o.uri]]);
                    },
                    lines,
                    sources: ['iNaturalist research-grade observations (inaturalist.org); each observation is licensed by its observer'],
                    empty: `No research-grade iNaturalist observations within ${fmtM(radius)} of ${p.label}`,
                };
            },
        },

        trails: {
            title: 'Trails', slow: true, radius: 3000,
            async load(p, radius) {
                const a = around(p, radius);
                const res = await overpass(`[out:json][timeout:25];(way["highway"~"^(path|bridleway)$"]${a};` +
                    `way["highway"~"^(footway|track|cycleway)$"]["name"]${a};);out geom 1500;`);
                const fc = osmGeoJson(res.elements || []);
                const byName = new Map();
                let total = 0, unnamed = 0;
                fc.features.forEach(f => {
                    const m = lineLength(f.geometry.coordinates || []), d = featureDistance(f, p.lon, p.lat);
                    total += m;
                    if (!f.properties.name) { unnamed += m; return; }
                    const g = byName.get(f.properties.name) || { m: 0, d: Infinity };
                    g.m += m; g.d = Math.min(g.d, d);
                    byName.set(f.properties.name, g);
                });
                const lines = fc.features.length ? [['step', `Trails within ${fmtM(radius)} of ${p.label} ` +
                    `(OpenStreetMap: ${fmtM(total)} of paths${byName.size ? `, ${byName.size} named` : ''}; longest first):`]] : [];
                [...byName.entries()].sort((x, y) => y[1].m - x[1].m).slice(0, 12)
                    .forEach(([name, g]) => lines.push(['geo', `${name}: ${fmtM(g.m)} [${nearestText(g.d)}]`]));
                if (unnamed) lines.push(['geo', `Unnamed paths: ${fmtM(unnamed)}`]);
                return {
                    fc, style: { stroke: Cesium.Color.SANDYBROWN, strokeWidth: 3 },
                    decorate(e, q) {
                        if (e.polyline) { e.polyline.material = Cesium.Color.SANDYBROWN; e.polyline.width = 3; }
                        e.name = q.name || 'Unnamed path';
                        e.description = osmHtml(q, [['Type', q.highway], ['Surface', q.surface],
                            ['Difficulty (SAC scale)', q.sac_scale], ['Access', q.access]]);
                    },
                    lines, sources: [OSM_SOURCE],
                    empty: `No trails mapped in OpenStreetMap within ${fmtM(radius)} of ${p.label}`,
                };
            },
        },

        springs: {
            title: 'Springs', slow: true, radius: 5000,
            async load(p, radius) {
                const res = await overpass(`[out:json][timeout:25];` +
                    `node["natural"~"^(spring|hot_spring|geyser)$"]${around(p, radius)};out 500;`);
                const fc = osmGeoJson(res.elements || []);
                const list = fc.features.map(f => ({ q: f.properties, d: featureDistance(f, p.lon, p.lat) }))
                    .sort((x, y) => x.d - y.d);
                const kindOf = (q) => String(q.natural).replace('_', ' ');
                const lines = list.length ? [['step', `Springs within ${fmtM(radius)} of ${p.label} ` +
                    `(OpenStreetMap, ${list.length}; nearest first):`]] : [];
                list.slice(0, 12).forEach(({ q, d }) => lines.push(['geo',
                    `${q.name || `Unnamed ${kindOf(q)}`}${q.name ? ` (${kindOf(q)})` : ''} [${nearestText(d)}]`]));
                return {
                    fc,
                    decorate(e, q) {
                        dot(e, q.natural === 'hot_spring' ? Cesium.Color.TOMATO : Cesium.Color.AQUA);
                        e.name = q.name || `Unnamed ${kindOf(q)}`;
                        e.description = osmHtml(q, [['Type', kindOf(q)], ['Drinking water', q.drinking_water],
                            ['Elevation (m)', q.ele], ['Seasonal', q.seasonal]]);
                    },
                    lines, sources: [OSM_SOURCE],
                    empty: `No springs mapped in OpenStreetMap within ${fmtM(radius)} of ${p.label}`,
                };
            },
        },

        mines: {
            title: 'Mines', slow: true, radius: 5000,
            async load(p, radius) {
                const a = around(p, radius);
                const res = await overpass(`[out:json][timeout:25];(nwr["historic"="mine"]${a};` +
                    `nwr["man_made"~"^(mineshaft|adit)$"]${a};nwr["landuse"="quarry"]${a};nwr["industrial"="mine"]${a};);out center 500;`);
                const fc = osmGeoJson(res.elements || []);
                const typeOf = (q) => q.historic === 'mine' ? 'historic mine' : q.man_made === 'mineshaft' ? 'mine shaft'
                    : q.man_made === 'adit' ? 'adit' : q.landuse === 'quarry' ? 'quarry' : 'mine';
                const list = fc.features.map(f => ({ q: f.properties, d: featureDistance(f, p.lon, p.lat) }))
                    .sort((x, y) => x.d - y.d);
                const lines = list.length ? [['step', `Mines and quarries within ${fmtM(radius)} of ${p.label} ` +
                    `(OpenStreetMap, ${list.length}; nearest first):`]] : [];
                list.slice(0, 12).forEach(({ q, d }) => {
                    const what = [typeOf(q), q.resource && `resource: ${q.resource}`].filter(Boolean).join(', ');
                    lines.push(['geo', `${q.name || 'Unnamed'} (${what}) [${nearestText(d)}]`]);
                });
                return {
                    fc,
                    decorate(e, q) {
                        dot(e, Cesium.Color.DARKORANGE);
                        e.name = q.name || typeOf(q);
                        e.description = osmHtml(q, [['Type', typeOf(q)], ['Resource', q.resource],
                            ['Operator', q.operator], ['Start date', q.start_date]]);
                    },
                    lines, sources: [OSM_SOURCE],
                    empty: `No mines or quarries mapped in OpenStreetMap within ${fmtM(radius)} of ${p.label}`,
                };
            },
        },
    };

    function flight(opts, id) {
        const viewer = getViewer();
        return new Promise((resolve, reject) => {
            const done = { complete: resolve, cancel: () => reject(new Cancelled()) };
            if (opts.sphere) viewer.camera.flyToBoundingSphere(opts.sphere, { ...opts.options, ...done });
            else viewer.camera.flyTo({ ...opts, ...done });
        }).then(() => check(id));
    }

    async function until(cond, id) {
        while (!cond()) {
            check(id);
            await new Promise(r => setTimeout(r, 200));
        }
        check(id);
    }

    function setInput(elId, value) {
        const el = document.getElementById(elId);
        if (!el) return;
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function haltMotion() {
        drone().stopOrbit?.();
        drone().stopVertical?.();
        getViewer()?.camera.cancelFlight();
    }

    // Cancels the running plan as well as the motion
    function stopAll() {
        runId++;
        haltMotion();
    }

    async function verticalTo(height, speed, id) {
        const viewer = getViewer();
        const dz = height - viewer.camera.positionCartographic.height;
        if (Math.abs(dz) < 1) return;
        setInput('droneVerticalSpeed', Math.round(speed || clamp(Math.abs(dz) / 15, 5, SCALE.climb)));
        if (dz > 0) drone().climbTo(height); else drone().descendTo(height);
        await until(() => !drone().isVerticalActive(), id);
    }

    const runners = {
        async goto(a, id) {
            // No destination: change height where we are, then point the camera
            if (!a.place && !(Number.isFinite(a.lat) && Number.isFinite(a.lon))) {
                if (a.alt_m) await runners.takeoff(a, id);
                if (Number.isFinite(a.pitch_deg) || Number.isFinite(a.heading_deg)) await runners.look(a);
                return;
            }
            const p = await resolvePoint(a);
            check(id);
            const viewer = getViewer();
            const ground = await groundHeight(p.lon, p.lat);
            const pitchDeg = Number.isFinite(a.pitch_deg) ? a.pitch_deg : -45;
            // Frame from at least 20 deg down so the camera stays near the place;
            // a shallower requested tilt is applied after arriving.
            const framePitch = Cesium.Math.toRadians(Math.min(pitchDeg, -20));
            const heading = Number.isFinite(a.heading_deg) ? Cesium.Math.toRadians(a.heading_deg) : viewer.camera.heading;
            // alt_m is the camera height above ground
            const alt = a.alt_m || clamp((p.sizeM || 600) * 0.8, 100, SCALE.alt);
            const range = alt / Math.sin(-framePitch);
            addMsg('step', `Flying to ${p.label} (${fmtM(alt)} above ground)`);
            await flight({
                sphere: new Cesium.BoundingSphere(Cesium.Cartesian3.fromRadians(p.lon, p.lat, ground, ellipsoid()), 0),
                options: { offset: new Cesium.HeadingPitchRange(heading, framePitch, range) },
            }, id);
            if (pitchDeg > -20) await runners.look({ pitch_deg: pitchDeg });
        },

        async orbit(a, id) {
            const p = await resolvePoint(a);
            check(id);
            const viewer = getViewer();
            const ground = await groundHeight(p.lon, p.lat);
            // Orbiting the centre of a data layer: size the circle to keep the area in view
            const geo = layerArea && distanceM(p.lon, p.lat, layerArea.lon, layerArea.lat) < 1000
                ? layerArea : null;
            const radius = a.radius_m || (geo ? clamp(geo.radius * 0.5, 100, SCALE.radius)
                : clamp((p.sizeM || 1000) * 0.6, 100, SCALE.radius));
            const alt = a.alt_m || (geo ? clamp(geo.radius * 0.35, 80, 7000) : clamp(radius * 0.5, 80, SCALE.orbitAlt));
            const revs = a.revolutions || 1;
            const speed = a.speed_mps || clamp(2 * Math.PI * radius / 75, 5, SCALE.speed);
            const pitchDeg = Number.isFinite(a.pitch_deg) ? a.pitch_deg
                : -Cesium.Math.toDegrees(Math.atan2(alt, radius));

            // Start on the circle at the bearing of the current camera (shortest hop)
            const R = ellipsoid().maximumRadius;
            const cam = viewer.camera.positionCartographic;
            const east = (cam.longitude - p.lon) * Math.cos(p.lat), north = cam.latitude - p.lat;
            const theta = (Math.abs(east) + Math.abs(north) > 1e-9) ? Math.atan2(north, east) : -Math.PI / 2;
            const startLat = p.lat + radius * Math.sin(theta) / R;
            const startLon = p.lon + radius * Math.cos(theta) / (R * Math.cos(p.lat));
            const centre = Cesium.Cartesian3.fromRadians(p.lon, p.lat, 0, ellipsoid());
            const toCentre = new Cesium.EllipsoidGeodesic(
                new Cesium.Cartographic(startLon, startLat), new Cesium.Cartographic(p.lon, p.lat), ellipsoid()).startHeading;

            setInput('droneOrbitRadius', Math.round(radius));
            setInput('droneOrbitRevolutions', revs);
            setInput('droneHorizontalSpeed', Math.round(speed));
            drone().stopOrbit?.();
            setInput('droneOrbitPitch', Math.round(pitchDeg));
            setInput('droneOrbitYaw', 0);

            addMsg('step', `Orbiting ${p.label}: radius ${fmtM(radius)}, ${fmtM(alt)} above ground, ` +
                `${revs} lap${revs === 1 ? '' : 's'} ${a.clockwise ? 'clockwise' : 'counter-clockwise'} at ${Math.round(speed)} m/s`);
            await flight({
                destination: Cesium.Cartesian3.fromRadians(startLon, startLat, ground + alt, ellipsoid()),
                orientation: { heading: toCentre, pitch: Cesium.Math.toRadians(pitchDeg), roll: 0 },
            }, id);
            drone().orbitAround(centre, { clockwise: !!a.clockwise });
            await until(() => !drone().isOrbiting(), id);
        },

        async takeoff(a, id) {
            const viewer = getViewer();
            const cam = viewer.camera.positionCartographic;
            const ground = await groundHeight(cam.longitude, cam.latitude);
            const agl = a.alt_m || (cam.height - ground + (isEarth ? 100 : 5000));
            addMsg('step', `${ground + agl >= cam.height ? 'Climbing' : 'Descending'} to ${fmtM(agl)} above ground`);
            await verticalTo(ground + agl, a.speed_mps, id);
        },

        async land(a, id) {
            const viewer = getViewer();
            const cam = viewer.camera.positionCartographic;
            const ground = await groundHeight(cam.longitude, cam.latitude);
            addMsg('step', 'Descending to the ground');
            await verticalTo(ground + 2, a.speed_mps, id);
        },

        async look(a) {
            const camera = getViewer().camera;
            if (Number.isFinite(a.pitch_deg)) setInput('droneOrbitPitch', Math.round(a.pitch_deg));
            camera.setView({
                destination: camera.position,
                orientation: {
                    heading: Number.isFinite(a.heading_deg) ? Cesium.Math.toRadians(a.heading_deg) : camera.heading,
                    pitch: Number.isFinite(a.pitch_deg) ? Cesium.Math.toRadians(a.pitch_deg) : camera.pitch,
                    roll: 0,
                },
            });
            addMsg('step', 'Camera pointed');
        },

        async stop() {
            haltMotion();
            addMsg('step', 'Stopped');
        },

        async wait(a, id) {
            const end = Date.now() + (a.seconds || 0) * 1000;
            addMsg('step', `Hovering ${Math.round(a.seconds || 0)} s`);
            await until(() => Date.now() >= end, id);
        },

        async show_layer(a, id) {
            const spec = isEarth && LAYERS[a.kind];
            if (!spec) throw new Error(`No "${a.kind}" layer on ${body}`);
            const p = await resolvePoint(a);
            check(id);
            const viewer = getViewer();
            const radius = a.radius_m || spec.radius;
            const loading = addMsg('step', `Loading ${spec.title.toLowerCase()} for ${p.label}...` +
                (spec.slow ? ' (OpenStreetMap can take up to a minute)' : ''));
            let res;
            try {
                res = await spec.load(p, radius, a);
            } catch (e) {
                if (e instanceof Cancelled) throw e;
                // One unavailable source should not cancel the rest of the plan
                addMsg('error', `${spec.title}: ${e.message || e}`);
                return;
            } finally {
                loading.remove();
            }
            check(id);

            const ds = res.fc
                ? await Cesium.GeoJsonDataSource.load(res.fc, { clampToGround: true, ...(res.style || {}) })
                : new Cesium.CustomDataSource();
            check(id);
            ds.name = `ai-pilot-${a.kind}`;
            const now = Cesium.JulianDate.now();
            ds.entities.values.forEach(e => {
                if (e.billboard) {
                    e.billboard.heightReference = Cesium.HeightReference.CLAMP_TO_GROUND;
                    e.billboard.disableDepthTestDistance = Number.POSITIVE_INFINITY;
                }
                if (res.decorate) res.decorate(e, e.properties ? e.properties.getValue(now) : {});
            });
            if (!res.area && radius) {
                ds.entities.add({
                    name: `${spec.title}: search radius ${fmtM(radius)}`,
                    polyline: {
                        positions: circlePositions(p.lon, p.lat, radius), clampToGround: true,
                        width: 2, material: Cesium.Color.YELLOW.withAlpha(0.8),
                    },
                });
            }
            runners.hide_layer({ kind: a.kind }, id, true);
            await viewer.dataSources.add(ds);
            let imagery = null;
            if (res.imagery) {
                imagery = viewer.imageryLayers.addImageryProvider(res.imagery);
                imagery.alpha = res.imageryAlpha ?? 0.6;
            }
            shownLayers.set(a.kind, { ds, imagery });
            layerArea = res.area || { lon: p.lon, lat: p.lat, radius: radius || 5000 };

            if (res.lines.length) {
                res.lines.forEach(([kind, text]) => addMsg(kind, text));
                (res.sources || []).forEach(s => addMsg('step', `Source: ${String(s).trim()}`));
            } else if (res.empty) addMsg('step', res.empty);
            if (a.frame) {
                const r = layerArea.radius;
                const ground = await groundHeight(layerArea.lon, layerArea.lat);
                await flight({
                    sphere: new Cesium.BoundingSphere(Cesium.Cartesian3.fromRadians(layerArea.lon, layerArea.lat, ground), r),
                    options: { offset: new Cesium.HeadingPitchRange(viewer.camera.heading, Cesium.Math.toRadians(-50), r * 2.6) },
                }, id);
            }
        },

        // No kind: remove every layer
        async hide_layer(a, id, quiet) {
            const viewer = getViewer();
            const kinds = a.kind ? [a.kind] : [...shownLayers.keys()];
            const removed = kinds.filter(k => shownLayers.has(k));
            removed.forEach(k => {
                const { ds, imagery } = shownLayers.get(k);
                viewer.dataSources.remove(ds, true);
                if (imagery) viewer.imageryLayers.remove(imagery, true);
                shownLayers.delete(k);
            });
            if (!shownLayers.size) layerArea = null;
            if (quiet) return;
            if (removed.length) addMsg('step', `Removed: ${removed.map(k => LAYERS[k].title.toLowerCase()).join(', ')}`);
            else addMsg('step', a.kind ? `No ${LAYERS[a.kind]?.title.toLowerCase() || a.kind} layer is shown` : 'No layers are shown');
        },
    };

    // Heading and tilt only exist in 3D; the page opens in 2D
    async function ensure3D(id) {
        const scene = getViewer().scene;
        if (scene.mode === Cesium.SceneMode.SCENE3D) return;
        addMsg('step', 'Switching to 3D view');
        const morphed = new Promise(r => {
            const off = scene.morphComplete.addEventListener(() => { off(); r(); });
            setTimeout(r, 4000);
        });
        const btn3D = document.getElementById('view3D');
        if (btn3D) btn3D.click(); else scene.morphTo3D(1.0);
        await morphed;
        check(id);
    }

    const samePlace = (x, y) => (x.place && x.place === y.place) ||
        (Number.isFinite(x.lat) && x.lat === y.lat && x.lon === y.lon);

    async function runPlan(actions) {
        // An orbit flies to its own start point; a goto to the same place first is a detour
        actions = actions.filter((a, i) => {
            if (a.type !== 'goto') return true;
            const next = actions.slice(i + 1).find(b => b.type !== 'show_layer');
            return !(next && next.type === 'orbit' && samePlace(a, next));
        });
        // A new plan replaces whatever is flying now
        stopAll();
        const id = runId;
        try {
            if (actions.some(a => a.type !== 'stop')) await ensure3D(id);
            for (const [i, a] of actions.entries()) {
                check(id);
                // Frame the area unless a later step moves the camera anyway
                if (a.type === 'show_layer') {
                    a.frame = !actions.slice(i + 1).some(b => b.type === 'goto' || b.type === 'orbit');
                }
                await runners[a.type](a, id);
            }
            if (actions.some(a => a.type !== 'stop')) addMsg('step', 'Done');
        } catch (e) {
            if (e instanceof Cancelled) return;
            addMsg('error', e.message || String(e));
        }
    }

    stopBtn.addEventListener('click', () => { stopAll(); addMsg('step', 'Stopped'); });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const message = input.value.trim();
        if (!message || !getViewer()) return;
        input.value = '';
        addMsg('user', message);
        const thinking = addMsg('step', 'Thinking...');
        sendBtn.disabled = true;
        try {
            const resp = await fetch('/label/api/pilot/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                body: JSON.stringify({ message, history, body, view: await currentView() }),
            });
            const data = await resp.json().catch(() => ({}));
            thinking.remove();
            if (resp.status === 401) {
                addMsg('error', 'The AI pilot is for signed-in users.', `/label/admin/login/?next=${encodeURIComponent(location.pathname)}`);
                return;
            }
            if (!resp.ok) {
                addMsg('error', data.error || `Request failed (${resp.status})`);
                return;
            }
            addMsg('ai', data.reply || '(no reply)');
            history.push({ role: 'user', content: message },
                         { role: 'assistant', content: JSON.stringify({ reply: data.reply, actions: data.actions }) });
            history.splice(0, Math.max(0, history.length - 8));
            if (data.actions && data.actions.length) runPlan(data.actions);
        } catch (err) {
            thinking.remove();
            addMsg('error', `Request failed: ${err.message || err}`);
        } finally {
            sendBtn.disabled = false;
        }
    });

    console.log('[AI Pilot] Initialized');
})();
