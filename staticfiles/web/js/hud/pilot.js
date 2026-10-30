// DeepGIS AI pilot chat, shared by the Earth, Moon and planet viewers.
// POST /label/api/pilot/ turns a request into actions (goto, orbit, takeoff,
// land, look, stop, wait, show_layer, hide_layer, describe_view, follow_vehicle);
// they run here, in order, on the drone (hud/drone.js). describe_view posts one frame of the
// globe to /label/api/pilot/describe/ and lists what the lab's model sees. follow_vehicle
// rides the camera on a live vehicle's pose from /label/api/vehicles/live/ until stop,
// with the vehicle's own camera frames in a corner when it posts them.
// On Earth place names go to OpenStreetMap, then
// Cesium Ion; elsewhere names come from the IAU gazetteer
// (scripts/build_planet_nomenclature.py) and the page's preset sites, and the
// data layers (PLANET_LAYERS) are drawn from the body's terrain or elevation maps.
(function initAiPilot() {
    const panel = document.getElementById('pilotPanel');
    const toggleBtn = document.getElementById('hudPilotBtn');
    const log = document.getElementById('pilotLog');
    const form = document.getElementById('pilotForm');
    const input = document.getElementById('pilotInput');
    const modelSelect = document.getElementById('pilotModel');
    const sendBtn = document.getElementById('pilotSendBtn');
    const stopBtn = document.getElementById('pilotStopBtn');
    if (!panel || !toggleBtn || !form) return;

    const history = [];
    const geocodeCache = new Map();
    let runId = 0; // bumped to cancel the running plan
    let lastMessage = ''; // the request a describe_view answers

    class Cancelled extends Error {}

    const body = panel.dataset.body || 'earth';
    const isEarth = body === 'earth';

    async function loadModels() {
        if (!modelSelect) return;
        try {
            const resp = await fetch('/label/api/pilot/models/', { credentials: 'same-origin' });
            if (!resp.ok) return;
            const data = await resp.json();
            const models = [...new Set(data.models || [])];
            if (!models.length) return;
            modelSelect.replaceChildren(...models.map(name => {
                const option = document.createElement('option');
                option.value = name;
                option.textContent = `${name.toLowerCase().includes('gemma') ? 'Gemma' : 'Qwen'} · ${name}`;
                return option;
            }));
            if (data.default_model) modelSelect.value = data.default_model;
        } catch (_) {
            // Keep the server-default Gemma option when discovery is unavailable.
        }
    }
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
            pitch_deg: Cesium.Math.toDegrees(viewer.camera.pitch),
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
    const bodyR = () => isEarth ? EARTH_R : ellipsoid().maximumRadius;
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
        return 2 * bodyR() * Math.asin(Math.min(1, Math.sqrt(s)));
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
    // USGS Landsat Collection 2 Level-2 from Microsoft Planetary Computer: STAC search,
    // then its tiler colours, stretches and samples the surface temperature band
    const PC_STAC_URL = 'https://planetarycomputer.microsoft.com/api/stac/v1/search';
    const PC_DATA_URL = 'https://planetarycomputer.microsoft.com/api/data/v1';
    // lwir11 (ST_B10) digital numbers: kelvin = DN * scale + offset
    const LST_SCALE = 0.00341802, LST_OFFSET = 149.0;
    const dnToC = (dn) => dn * LST_SCALE + LST_OFFSET - 273.15;
    const fmtC = (c) => `${c.toFixed(1)} °C (${(c * 9 / 5 + 32).toFixed(0)} °F)`;
    // Names as the tiler knows them (matplotlib); stops only draw the chat legend.
    // Keep the names in step with COLORMAPS in views/pilot.py.
    const COLORMAPS = {
        jet: ['#00007f', '#0000ff', '#007fff', '#00ffff', '#7fff7f', '#ffff00', '#ff7f00', '#ff0000', '#7f0000'],
        turbo: ['#30123b', '#4662d7', '#36aaf9', '#1ae4b6', '#72fe5e', '#c8ef34', '#faba39', '#f66b19', '#ca2a04', '#7a0403'],
        viridis: ['#440154', '#482878', '#3e4989', '#31688e', '#26828e', '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725'],
        inferno: ['#000004', '#1b0c41', '#4a0c6b', '#781c6d', '#a52c60', '#cf4446', '#ed6925', '#fb9b06', '#f7d13d', '#fcffa4'],
        plasma: ['#0d0887', '#46039f', '#7201a8', '#9c179e', '#bd3786', '#d8576b', '#ed7953', '#fb9f3a', '#fdca26', '#f0f921'],
        coolwarm: ['#3b4cc0', '#6788ee', '#9abbff', '#c9d7f0', '#edd1c2', '#f7a889', '#e26952', '#b40426'],
        rdylgn: ['#a50026', '#d73027', '#f46d43', '#fdae61', '#fee08b', '#ffffbf', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837'],
    };
    const cmapOf = (a, fallback) => COLORMAPS[a.colormap] ? a.colormap : fallback;
    // NOAA ERDDAP grids, relayed by views/pilot.py (pilot_ocean)
    const PILOT_OCEAN_URL = '/label/api/pilot/ocean/';
    // OpenTopography lidar stored on this server (pilot_topo), and OpenTopography's catalog
    const PILOT_TOPO_URL = '/label/api/pilot/topo/';
    const OT_CATALOG_URL = 'https://portal.opentopography.org/API/otCatalog';
    const OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast';

    // Newest Landsat 8/9 scene over the area; a nearly clear one wins over a newer cloudier one
    async function landsatScene(bbox) {
        const j = await fetchJson(PC_STAC_URL, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                collections: ['landsat-c2-l2'], bbox, limit: 10,
                query: { 'eo:cloud_cover': { lt: 20 }, platform: { in: ['landsat-8', 'landsat-9'] } },
                sortby: [{ field: 'datetime', direction: 'desc' }],
            }),
        });
        const items = (j.features || []).filter(f => f.assets?.lwir11);
        return items.find(f => f.properties['eo:cloud_cover'] <= 5) || items[0] || null;
    }

    // Newest nearly clear Sentinel-2 scene over the point (scenes are 110 km tiles)
    async function sentinelScene(p) {
        const j = await fetchJson(PC_STAC_URL, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                collections: ['sentinel-2-l2a'], limit: 10,
                intersects: { type: 'Point', coordinates: [deg(p.lon), deg(p.lat)] },
                query: { 'eo:cloud_cover': { lt: 10 } },
                sortby: [{ field: 'datetime', direction: 'desc' }],
            }),
        });
        const items = (j.features || []).filter(f => f.assets?.B04 && f.assets?.B08);
        return items.find(f => f.properties['eo:cloud_cover'] <= 2) || items[0] || null;
    }

    // Every scene of the same satellite pass over the box: an area can span several tiles
    async function passScenes(scene, bbox) {
        const day = scene.properties.datetime.slice(0, 10);
        const j = await fetchJson(PC_STAC_URL, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ collections: ['sentinel-2-l2a'], bbox, limit: 20,
                                   datetime: `${day}T00:00:00Z/${day}T23:59:59Z` }),
        });
        const same = (j.features || []).filter(f => f.properties.datetime === scene.properties.datetime &&
            f.properties.platform === scene.properties.platform && f.assets?.B04 && f.assets?.B08);
        return same.some(f => f.id === scene.id) ? same : [scene, ...same];
    }

    // Mosaic of the given items, for tiles across scene edges
    async function pcMosaic(ids) {
        const j = await fetchJson(`${PC_DATA_URL}/mosaic/register`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ collections: ['sentinel-2-l2a'], 'filter-lang': 'cql2-json',
                                   filter: { op: 'in', args: [{ property: 'id' }, ids] } }),
        });
        const id = j.searchid || j.id;
        if (!id) throw new Error('planetarycomputer.microsoft.com did not register the image mosaic');
        return id;
    }

    const ageText = (when) => {
        const days = Math.round((Date.now() - when) / 86400000);
        return days < 1 ? 'today' : `${days} day${days === 1 ? '' : 's'} ago`;
    };

    function hexRgb(h) {
        const n = parseInt(h.slice(1), 16);
        return [n >> 16, (n >> 8) & 255, n & 255];
    }

    // Colour of t in [0, 1] along a COLORMAPS ramp
    function rampColor(stops, t) {
        const x = clamp(t, 0, 1) * (stops.length - 1);
        const i = Math.min(Math.floor(x), stops.length - 2), f = x - i;
        const a = hexRgb(stops[i]), b = hexRgb(stops[i + 1]);
        return a.map((v, k) => Math.round(v + (b[k] - v) * f));
    }

    // {lat, lon, values} grid (cell centres, rows south to north, null = no data) as one
    // image over the cells; `scale` maps a value before colouring (e.g. Math.log10)
    function gridImagery(grid, res, cmap, lo, hi, credit, scale = (v) => v) {
        const rows = grid.lat.length, cols = grid.lon.length;
        const c = document.createElement('canvas');
        c.width = cols;
        c.height = rows;
        const g = c.getContext('2d');
        const img = g.createImageData(cols, rows);
        for (let r = 0; r < rows; r++) {
            for (let k = 0; k < cols; k++) {
                const v = grid.values[rows - 1 - r][k]; // canvas row 0 is the north edge
                if (v === null || !Number.isFinite(v)) continue;
                img.data.set([...rampColor(COLORMAPS[cmap], (scale(v) - lo) / (hi - lo)), 255], (r * cols + k) * 4);
            }
        }
        g.putImageData(img, 0, 0);
        return new Cesium.SingleTileImageryProvider({
            url: c.toDataURL(), tileWidth: cols, tileHeight: rows,
            rectangle: Cesium.Rectangle.fromDegrees(grid.lon[0] - res / 2, grid.lat[0] - res / 2,
                grid.lon[cols - 1] + res / 2, grid.lat[rows - 1] + res / 2),
            credit: new Cesium.Credit(credit),
        });
    }

    // Sorted values of the grid cells within radius of p, and the cell nearest p
    function gridStats(grid, p, radius) {
        const vals = [];
        let centre = null, best = Infinity;
        grid.lat.forEach((la, i) => grid.lon.forEach((lo, j) => {
            const v = grid.values[i][j];
            if (v === null || !Number.isFinite(v)) return;
            const d = distanceM(p.lon, p.lat, rad(lo), rad(la));
            if (d <= radius) vals.push(v);
            if (d < best) { best = d; centre = { v, d }; }
        }));
        if (!vals.length) return null;
        vals.sort((x, y) => x - y);
        const q = (f) => vals[Math.min(vals.length - 1, Math.floor(f * vals.length))];
        return { vals, centre, min: vals[0], max: vals[vals.length - 1], p2: q(0.02), p98: q(0.98),
                 median: q(0.5), mean: vals.reduce((s, v) => s + v, 0) / vals.length };
    }

    // GET from one of this server's data endpoints, which answer errors as {error}
    async function serverJson(url, params, relay, upstream) {
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), 60000);
        try {
            const resp = await fetch(`${url}?${new URLSearchParams(params)}`, { credentials: 'same-origin', signal: ctl.signal });
            const j = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(j.error || `the ${relay} relay returned HTTP ${resp.status}`);
            return j;
        } catch (e) {
            if (e.name === 'AbortError') throw new Error(`${upstream} did not respond`);
            throw e;
        } finally {
            clearTimeout(timer);
        }
    }

    const oceanGrid = (kind, rect) => serverJson(PILOT_OCEAN_URL, {
        kind, south: deg(rect.south).toFixed(2), north: deg(rect.north).toFixed(2),
        west: deg(rect.west).toFixed(2), east: deg(rect.east).toFixed(2),
    }, 'NOAA data', 'NOAA ERDDAP');

    // The pilot_topo PNG packs height (red), hillshade (green), slope (blue) and coverage
    // (alpha); colour the height with the colour map and darken it by the hillshade
    async function reliefImagery(t, cmap) {
        const img = new Image();
        img.src = t.png;
        await img.decode();
        const c = document.createElement('canvas');
        c.width = img.width;
        c.height = img.height;
        const g = c.getContext('2d', { willReadFrequently: true });
        g.drawImage(img, 0, 0);
        const d = g.getImageData(0, 0, c.width, c.height);
        const px = d.data;
        const lut = Array.from({ length: 256 }, (_, i) => rampColor(COLORMAPS[cmap], i / 255));
        for (let i = 0; i < px.length; i += 4) {
            if (!px[i + 3]) continue;
            const col = lut[px[i]], s = 0.2 + 0.8 * px[i + 1] / 255;
            px[i] = col[0] * s;
            px[i + 1] = col[1] * s;
            px[i + 2] = col[2] * s;
            px[i + 3] = 255;
        }
        g.putImageData(d, 0, 0);
        return new Cesium.SingleTileImageryProvider({
            url: c.toDataURL(), tileWidth: c.width, tileHeight: c.height,
            rectangle: Cesium.Rectangle.fromDegrees(...t.bounds),
            credit: new Cesium.Credit('Lidar terrain: OpenTopography'),
        });
    }

    // [west, south, east, north] of any GeoJSON object's coordinates
    function geoBox(geo) {
        const box = [Infinity, Infinity, -Infinity, -Infinity];
        const walk = (c) => {
            if (typeof c[0] === 'number') {
                box[0] = Math.min(box[0], c[0]); box[1] = Math.min(box[1], c[1]);
                box[2] = Math.max(box[2], c[0]); box[3] = Math.max(box[3], c[1]);
            } else c.forEach(walk);
        };
        (geo?.features || [geo]).forEach(f => f?.geometry?.coordinates && walk(f.geometry.coordinates));
        return Number.isFinite(box[0]) ? box : null;
    }

    const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    const compass = (d) => COMPASS[Math.round(((d % 360) + 360) % 360 / 45) % 8];

    // Current conditions on an n x n grid over the area plus the centre (last), from Open-Meteo
    async function weatherGrid(p, radius, n = 7) {
        const rect = areaRect(p.lon, p.lat, radius);
        const dLat = (rect.north - rect.south) / n, dLon = (rect.east - rect.west) / n;
        const lat = [], lon = [];
        for (let i = 0; i < n; i++) lat.push(deg(rect.south + (i + 0.5) * dLat));
        for (let j = 0; j < n; j++) lon.push(deg(rect.west + (j + 0.5) * dLon));
        const pts = lat.flatMap(la => lon.map(lo => [la, lo])).concat([[deg(p.lat), deg(p.lon)]]);
        const j = await fetchJson(`${OPEN_METEO_URL}?` + new URLSearchParams({
            latitude: pts.map(x => x[0].toFixed(4)).join(','),
            longitude: pts.map(x => x[1].toFixed(4)).join(','),
            current: 'temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,precipitation',
            timezone: 'auto',
        }));
        const list = Array.isArray(j) ? j : [j];
        if (list.length !== pts.length || !list.every(x => x.current)) throw new Error('api.open-meteo.com returned no current conditions');
        const field = (key) => lat.map((_, i) => lon.map((_, k) => list[i * n + k].current[key] ?? null));
        return { lat, lon, res: Math.min(deg(dLat), deg(dLon)), field, centre: list[list.length - 1] };
    }

    // Shared loader for the humidity and air temperature layers
    async function weatherLayer(p, radius, a, key, title, fmt, minSpan) {
        const cmap = cmapOf(a, 'turbo');
        const w = await weatherGrid(p, radius);
        const grid = { lat: w.lat, lon: w.lon, values: w.field(key) };
        const st = gridStats(grid, p, Infinity);
        if (!st) return { lines: [], empty: `No current ${title.toLowerCase()} for ${p.label}` };
        const lo = st.min, hi = Math.max(st.max, lo + minSpan);
        const c = w.centre.current;
        const local = String(c.time || '').replace('T', ' ');
        const lines = [['step', `${title} around ${p.label} (${fmtM(radius)} radius), current conditions at ${local} local time:`],
            ['geo', `At the centre: air ${fmtC(c.temperature_2m)}, humidity ${Math.round(c.relative_humidity_2m)}%, ` +
                `dew point ${fmtC(c.dew_point_2m)}`],
            ['geo', `Across the area: ${fmt(st.min)} to ${fmt(st.max)}`],
            ['geo', `Wind ${Math.round(c.wind_speed_10m)} km/h from the ${compass(c.wind_direction_10m)}` +
                (c.precipitation > 0 ? `; ${c.precipitation} mm of rain in the last 15 minutes` : '; no rain right now')],
            ['step', 'These are weather-model values on a grid of a few kilometres, blended between points, not station readings.']];
        return {
            imagery: gridImagery(grid, w.res, cmap, lo, hi, 'Weather: Open-Meteo.com'),
            imageryAlpha: 0.6, lines,
            legend: { title: `${title} (${cmap})`, colors: COLORMAPS[cmap], lo: fmt(lo), hi: fmt(hi) },
            sources: ['Open-Meteo forecast API (open-meteo.com, CC BY 4.0), current conditions from national weather ' +
                      'models such as NOAA HRRR and GFS'],
            empty: '',
        };
    }

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
        const R = bodyR();
        const pts = [];
        for (let k = 0; k <= 128; k++) {
            const t = 2 * Math.PI * k / 128;
            const la = lat + radius * Math.sin(t) / R;
            pts.push(Cesium.Cartesian3.fromRadians(lon + radius * Math.cos(t) / (R * Math.cos(lat)), la, 0, ellipsoid()));
        }
        return pts;
    }

    // Off-Earth layers colour the globe from the terrain heights (a globe material),
    // or switch on a colour elevation map from planet-bodies.js on bodies without
    // terrain. Same contract as LAYERS, plus globe: {ramp?: {type, min, max},
    // contour?: {spacing}} and legend: {title, colors, lo, hi}.
    const HEAT = ['#30123b', '#4662d7', '#36aaf9', '#1ae4b6', '#72fe5e', '#c8ef34',
                  '#faba39', '#f66b19', '#ca2a04', '#7a0403']; // turbo
    const globeLayers = new Map(); // kind -> globe spec
    const bodyInfo = () => window.PlanetBodies?.get(body) || {};
    const hasTerrain = () => !(getViewer().terrainProvider instanceof Cesium.EllipsoidTerrainProvider);
    const fmtH = (m) => Math.abs(m) >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
    const terrainSource = () => {
        if (isEarth) return 'Cesium World Terrain (Cesium ion), built from SRTM, USGS 3DEP and other national elevation models';
        const t = bodyInfo().terrain || {};
        return `${t.name || 'Terrain model'}${t.link ? ` (${t.link})` : ''}`;
    };
    const heightDatum = () => isEarth
        ? 'above the WGS84 ellipsoid, which can sit tens of metres off sea level'
        : `relative to the ${fmtM(bodyR())} reference sphere`;
    // A named feature with a size: 1.5 diameters; otherwise about the area in view
    const planetRadius = (p) => clamp(p.sizeM ? p.sizeM * 1.5
        : getViewer().camera.positionCartographic.height * 1.2, 5000, 1500000);

    // `fill` < 1 puts the whole ramp in the first part and holds the last colour
    function rampCanvas(colors, fill = 1) {
        const c = document.createElement('canvas');
        c.width = 256;
        c.height = 1;
        const g = c.getContext('2d');
        const grad = g.createLinearGradient(0, 0, 256 * fill, 0);
        colors.forEach((col, i) => grad.addColorStop(i / (colors.length - 1), col));
        g.fillStyle = grad;
        g.fillRect(0, 0, 256, 1);
        return c;
    }

    function applyGlobeMaterial() {
        const globe = getViewer().scene.globe;
        let ramp = null, contour = null;
        globeLayers.forEach(g => { ramp = g.ramp || ramp; contour = g.contour || contour; });
        // SlopeRamp maps 0-90 degrees across the image; the colours span 0-45
        const rampFabric = ramp && (ramp.type === 'slope'
            ? { type: 'SlopeRamp', uniforms: { image: rampCanvas(ramp.colors || HEAT, 0.5) } }
            : { type: 'ElevationRamp',
                uniforms: { image: rampCanvas(ramp.colors || HEAT), minimumHeight: ramp.min, maximumHeight: ramp.max } });
        const contourFabric = contour && { type: 'ElevationContour',
            uniforms: { width: 2, spacing: contour.spacing, color: Cesium.Color.WHITE.withAlpha(0.9) } };
        if (rampFabric && contourFabric) {
            globe.material = new Cesium.Material({ translucent: false, fabric: {
                type: 'DeepGISRampContour',
                materials: { rampMaterial: rampFabric, contourMaterial: contourFabric },
                components: {
                    diffuse: 'contourMaterial.alpha == 0.0 ? rampMaterial.diffuse : contourMaterial.diffuse',
                    alpha: 'max(contourMaterial.alpha, rampMaterial.alpha)',
                },
            } });
        } else if (rampFabric || contourFabric) {
            globe.material = new Cesium.Material({ translucent: false, fabric: rampFabric || contourFabric });
        } else {
            globe.material = undefined;
        }
    }

    // Sorted terrain heights on a grid over the area, read at a level whose tiles are
    // about a quarter of the radius across: a handful of tiles, not hundreds
    async function areaHeights(p, radius) {
        const tp = getViewer().terrainProvider;
        const R = bodyR();
        const radiusDeg = Cesium.Math.toDegrees(radius / R);
        const level = clamp(Math.round(Math.log2(180 / Math.max(radiusDeg / 2, 1e-6))), 0, 15);
        const pts = [];
        const n = 24;
        for (let i = 0; i <= n; i++) {
            for (let j = 0; j <= n; j++) {
                const e = (2 * i / n - 1) * radius, no = (2 * j / n - 1) * radius;
                if (e * e + no * no <= radius * radius) {
                    pts.push(new Cesium.Cartographic(p.lon + e / (R * Math.cos(p.lat)), p.lat + no / R));
                }
            }
        }
        let samples;
        try {
            samples = await Cesium.sampleTerrain(tp, level, pts);
        } catch (e) {
            samples = await Cesium.sampleTerrainMostDetailed(tp, pts);
        }
        const h = samples.map(s => s.height).filter(Number.isFinite).sort((a, b) => a - b);
        if (h.length < 3) throw new Error('No terrain heights here yet; try again once the surface has loaded');
        return h;
    }

    function niceStep(x) {
        const p = 10 ** Math.floor(Math.log10(x));
        return [1, 2, 5, 10].map(m => m * p).find(s => s >= x);
    }

    function elevationImagery(p, radius) {
        const info = bodyInfo();
        const src = (info.elevationImagery || []).map(id => (info.imagery || []).find(s => s.id === id)).find(Boolean);
        if (!src) throw new Error(`No elevation data for ${info.name || body}`);
        return {
            imagery: window.PlanetBodies.imageryProvider(src, ellipsoid(), Cesium),
            imageryAlpha: 1,
            area: { lon: p.lon, lat: p.lat, radius },
            lines: [['step', `Showing ${src.name}: elevation as colour (an image map; there is no height model here to measure)`]],
            sources: [`${src.credit}${src.link ? ` (${src.link})` : ''}`],
        };
    }

    const needTerrain = (title) => {
        if (!hasTerrain()) throw new Error(`${title} needs a terrain model, and ${bodyInfo().name || body} has none here`);
    };

    const PLANET_LAYERS = {
        elevation: {
            title: 'Elevation', radius: planetRadius,
            async load(p, radius, a = {}) {
                if (!hasTerrain()) return elevationImagery(p, radius);
                const h = await areaHeights(p, radius);
                const lo = h[0], hi = h[h.length - 1];
                const cmap = cmapOf(a, null);
                const colors = cmap ? COLORMAPS[cmap] : HEAT;
                return {
                    globe: { ramp: { type: 'elevation', min: lo, max: Math.max(hi, lo + 1), colors } },
                    legend: { title: cmap ? `Elevation (${cmap})` : 'Elevation', colors, lo: fmtH(lo), hi: fmtH(hi) },
                    lines: [['step', `Elevation within ${fmtM(radius)} of ${p.label}: ${fmtH(lo)} to ${fmtH(hi)}, ` +
                        `median ${fmtH(h[Math.floor(h.length / 2)])}, ${heightDatum()}. Colours stretch over this range` +
                        (isEarth ? ' and replace the satellite imagery while the layer is shown.' : '.')]],
                    sources: [terrainSource()],
                };
            },
        },
        slope: {
            title: 'Slope', radius: planetRadius,
            async load(p, radius) {
                needTerrain('Slope');
                return {
                    globe: { ramp: { type: 'slope' } },
                    legend: { title: 'Slope', colors: HEAT, lo: '0°', hi: '45°+' },
                    lines: [['step', 'Slope of the terrain surface, from flat (dark blue) to 45° or steeper (dark red).']],
                    sources: [terrainSource()],
                };
            },
        },
        contours: {
            title: 'Contours', radius: planetRadius,
            async load(p, radius) {
                needTerrain('Contours');
                const h = await areaHeights(p, radius);
                const spacing = niceStep(Math.max(h[h.length - 1] - h[0], 10) / 12);
                return {
                    globe: { contour: { spacing } },
                    lines: [['step', `Contour lines every ${fmtH(spacing)} (${fmtH(h[0])} to ${fmtH(h[h.length - 1])} within ${fmtM(radius)} of ${p.label}).`]],
                    sources: [terrainSource()],
                };
            },
        },
    };
    const layerSpecs = () => isEarth ? LAYERS : PLANET_LAYERS;
    const terrainRadius = (p) => p.sizeM ? clamp(p.sizeM / 2, 500, 50000) : 5000;

    function addLegend({ title, colors, lo, hi }) {
        const div = addMsg('step', title);
        const bar = document.createElement('div');
        bar.style.cssText = `min-width:220px;height:10px;border-radius:3px;margin:4px 0 2px;background:linear-gradient(to right, ${colors.join(', ')})`;
        const ends = document.createElement('div');
        ends.style.cssText = 'min-width:220px;display:flex;justify-content:space-between;gap:12px;font-size:11px';
        [lo, hi].forEach(v => {
            const s = document.createElement('span');
            s.textContent = v;
            ends.appendChild(s);
        });
        div.append(bar, ends);
    }

    // Each kind: load(p, radius, action) -> {fc?, style?, decorate?(entity, props),
    // imagery?, imageryAlpha?, area?, ring?, lines: [[msgKind, text]], sources: [text], empty}
    // (ring: where to draw the radius circle when it is not around the asked-for point)
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

        surface_temp: {
            title: 'Surface temperature',
            radius: (p) => p.sizeM ? clamp(p.sizeM / 2, 1000, 20000) : 5000,
            async load(p, radius, a) {
                const cmap = COLORMAPS[a.colormap] ? a.colormap : 'turbo';
                const rect = areaRect(p.lon, p.lat, radius);
                const scene = await landsatScene([deg(rect.west), deg(rect.south), deg(rect.east), deg(rect.north)]);
                if (!scene) return { lines: [], empty: `No Landsat thermal image with under 20% cloud covers ${p.label}` };
                const q = new URLSearchParams({ collection: 'landsat-c2-l2', item: scene.id, assets: 'lwir11' });
                const ring = circlePositions(p.lon, p.lat, radius).map(c => {
                    const g = Cesium.Cartographic.fromCartesian(c);
                    return [deg(g.longitude), deg(g.latitude)];
                });
                const [stats, centre] = await Promise.all([
                    fetchJson(`${PC_DATA_URL}/item/statistics?${q}&nodata=0&max_size=1024`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } }),
                    }, 40000),
                    fetchJson(`${PC_DATA_URL}/item/point/${deg(p.lon).toFixed(5)},${deg(p.lat).toFixed(5)}?${q}`).catch(() => null),
                ]);
                const s = Object.values(stats?.properties?.statistics || {})[0];
                if (!s || !(s.valid_percent > 0) || !Number.isFinite(s.percentile_2)) {
                    return { lines: [], empty: `The latest clear Landsat image (${scene.id}) has no thermal data over ${p.label}` };
                }
                // A uniform area still gets at least a 1 °C spread
                const lo = s.percentile_2, hi = Math.max(s.percentile_98, lo + 1 / LST_SCALE);
                const when = new Date(scene.properties.datetime);
                const days = Math.round((Date.now() - when) / 86400000);
                const platform = String(scene.properties.platform || 'landsat').replace('landsat-', 'Landsat ');
                const lines = [['step', `Surface temperature within ${fmtM(radius)} of ${p.label}, from the ${platform} image of ` +
                    `${when.toISOString().slice(0, 16).replace('T', ' ')} UTC (${days} day${days === 1 ? '' : 's'} ago, ` +
                    `${Math.round(scene.properties['eo:cloud_cover'])}% cloud over the whole scene):`]];
                const c0 = centre?.values?.[0];
                if (Number.isFinite(c0) && c0 > 0) lines.push(['geo', `At the centre: ${fmtC(dnToC(c0))}`]);
                lines.push(['geo', `Average: ${fmtC(dnToC(s.mean))}`]);
                lines.push(['geo', `Coolest ${fmtC(dnToC(s.min))}, hottest ${fmtC(dnToC(s.max))}`]);
                // valid_percent counts the circle's bounding square, which the circle fills π/4 of
                const covered = Math.min(100, s.valid_percent / (Math.PI / 4));
                if (covered < 95) lines.push(['geo', `The image covers about ${Math.round(covered)}% of the area`]);
                lines.push(['step', 'This is the temperature of the ground and roofs at the time of the image, not the air temperature.']);
                const tiles = new URLSearchParams(q);
                tiles.set('nodata', '0');
                tiles.set('rescale', `${Math.round(lo)},${Math.round(hi)}`);
                tiles.set('colormap_name', cmap);
                tiles.set('format', 'png');
                return {
                    imagery: new Cesium.UrlTemplateImageryProvider({
                        url: `${PC_DATA_URL}/item/tiles/WebMercatorQuad/{z}/{x}/{y}@1x?${tiles}`,
                        rectangle: rect, maximumLevel: 14,
                        credit: new Cesium.Credit('Surface temperature: USGS Landsat Collection 2 via Microsoft Planetary Computer'),
                    }),
                    imageryAlpha: 0.75,
                    lines,
                    legend: { title: `Surface temperature (${cmap}), middle 96% of the area`, colors: COLORMAPS[cmap],
                              lo: `${dnToC(lo).toFixed(1)} °C`, hi: `${dnToC(hi).toFixed(1)} °C` },
                    sources: ['U.S. Geological Survey, Landsat 8-9 Collection 2 Level-2 Surface Temperature (band ST_B10, 30 m), ' +
                              'via Microsoft Planetary Computer', `Scene ${scene.id}`],
                    empty: '',
                };
            },
        },

        ndvi: {
            title: 'Vegetation (NDVI)',
            radius: (p) => p.sizeM ? clamp(p.sizeM / 2, 500, 20000) : 3000,
            async load(p, radius, a) {
                const cmap = cmapOf(a, 'rdylgn');
                const scene = await sentinelScene(p);
                if (!scene) return { lines: [], empty: `No Sentinel-2 image with under 10% cloud covers ${p.label}` };
                // From processing baseline 04.00 (2022) each band's numbers carry a +1000 offset,
                // which cancels in the difference but not in the sum
                const sum = parseFloat(scene.properties['s2:processing_baseline']) >= 4 ? 'B08_b1+B04_b1-2000' : 'B08_b1+B04_b1';
                const q = new URLSearchParams({ collection: 'sentinel-2-l2a', nodata: '0',
                                                expression: `(B08_b1-B04_b1)/(${sum})`, asset_as_band: 'false' });
                const rect = areaRect(p.lon, p.lat, radius);
                const scenes = await passScenes(scene, [deg(rect.west), deg(rect.south), deg(rect.east), deg(rect.north)]);
                const ring = circlePositions(p.lon, p.lat, radius).map(c => {
                    const g = Cesium.Cartographic.fromCartesian(c);
                    return [deg(g.longitude), deg(g.latitude)];
                });
                const feature = JSON.stringify({ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } });
                // NDVI histogram in 0.01 bins from -1 to 1 per scene; pixels outside a scene are nodata
                const [mosaic, centre, ...perScene] = await Promise.all([
                    pcMosaic(scenes.map(f => f.id)),
                    fetchJson(`${PC_DATA_URL}/item/point/${deg(p.lon).toFixed(5)},${deg(p.lat).toFixed(5)}?${q}&item=${scene.id}`).catch(() => null),
                    ...scenes.map(f => fetchJson(`${PC_DATA_URL}/item/statistics?${q}&item=${f.id}&max_size=1024&histogram_bins=200&histogram_range=-1,1`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: feature,
                    }, 40000).then(st => Object.values(st?.properties?.statistics || {})[0]).catch(() => null)),
                ]);
                const counts = new Array(200).fill(0);
                perScene.forEach(s => (s?.histogram?.[0] || []).forEach((n, i) => { counts[i] += n; }));
                const total = counts.reduce((t, n) => t + n, 0);
                if (!total) return { lines: [], empty: `The latest clear Sentinel-2 image (${scene.id}) has no data over ${p.label}` };
                // Bin i covers -1 + i/100 to -1 + (i+1)/100; near-black pixels (deep water, shadow)
                // divide by almost zero and fall outside -1 to 1, so they are left out
                const share = (from, to) => Math.round(100 * counts.slice(from, to).reduce((t, n) => t + n, 0) / total);
                const pct = (f) => {
                    let acc = 0;
                    const i = counts.findIndex(n => (acc += n) >= f * total);
                    return -1 + (i + 0.5) / 100;
                };
                const when = new Date(scene.properties.datetime);
                const sat = scene.properties.platform || 'Sentinel-2';
                const cloud = Math.max(...scenes.map(f => f.properties['eo:cloud_cover'] || 0));
                const lines = [['step', `Vegetation greenness (NDVI) within ${fmtM(radius)} of ${p.label}, from the ${sat} pass of ` +
                    `${when.toISOString().slice(0, 10)} (${ageText(when)}; ${plural(scenes.length, 'image tile')}, ` +
                    `up to ${Math.round(cloud)}% cloud each):`]];
                const c0 = centre?.values?.[0];
                if (Number.isFinite(c0) && Math.abs(c0) <= 1) lines.push(['geo', `At the centre: NDVI ${c0.toFixed(2)}`]);
                lines.push(['geo', `Median NDVI ${pct(0.5).toFixed(2)}; most of the area (2nd to 98th percentile) ` +
                    `${pct(0.02).toFixed(2)} to ${pct(0.98).toFixed(2)}`]);
                lines.push(['geo', `Green vegetation (NDVI 0.4 or more): about ${share(140, 200)}% of the area`]);
                lines.push(['geo', `Bare ground, buildings, roads or water (below 0.1): about ${share(0, 110)}%`]);
                lines.push(['step', 'NDVI runs from -1 to 1: water is below 0, bare soil and pavement near 0.1, ' +
                    'sparse plants 0.2-0.4 and dense healthy vegetation above 0.6. Clouds in the image read as low values.']);
                const tiles = new URLSearchParams(q);
                tiles.set('rescale', '-0.1,0.8');
                tiles.set('colormap_name', cmap);
                tiles.set('format', 'png');
                return {
                    imagery: new Cesium.UrlTemplateImageryProvider({
                        url: `${PC_DATA_URL}/mosaic/${mosaic}/tiles/WebMercatorQuad/{z}/{x}/{y}@1x?${tiles}`,
                        rectangle: rect, maximumLevel: 15,
                        credit: new Cesium.Credit('NDVI: ESA Copernicus Sentinel-2 via Microsoft Planetary Computer'),
                    }),
                    imageryAlpha: 0.75,
                    lines,
                    legend: { title: `NDVI (${cmap})`, colors: COLORMAPS[cmap], lo: '-0.1 bare or water', hi: '0.8 dense green' },
                    sources: ['ESA Copernicus Sentinel-2 Level-2A surface reflectance (red band B04 and near-infrared band B08, 10 m), ' +
                              'via Microsoft Planetary Computer', `${scenes.length === 1 ? 'Scene' : 'Scenes'} ${scenes.map(f => f.id).join(', ')}`],
                    empty: '',
                };
            },
        },

        humidity: {
            title: 'Humidity',
            radius: (p) => p.sizeM ? clamp(p.sizeM / 2, 5000, 100000) : 20000,
            load: (p, radius, a) => weatherLayer(p, radius, a, 'relative_humidity_2m', 'Relative humidity',
                (v) => `${Math.round(v)}%`, 5),
        },

        air_temp: {
            title: 'Air temperature',
            radius: (p) => p.sizeM ? clamp(p.sizeM / 2, 5000, 100000) : 20000,
            load: (p, radius, a) => weatherLayer(p, radius, a, 'temperature_2m', 'Air temperature (2 m above ground)',
                (v) => `${v.toFixed(1)} °C`, 1),
        },

        sea_temp: {
            title: 'Sea surface temperature',
            radius: (p) => p.sizeM ? clamp(p.sizeM / 2, 5000, 150000) : 30000,
            async load(p, radius, a) {
                const cmap = cmapOf(a, 'turbo');
                const g = await oceanGrid('sea_temp', areaRect(p.lon, p.lat, radius));
                const st = gridStats(g, p, radius);
                if (!st) return { lines: [], empty: `No sea surface temperature within ${fmtM(radius)} of ${p.label} (no open water there)` };
                const lo = st.p2, hi = Math.max(st.p98, lo + 0.5);
                const lines = [['step', `Sea surface temperature within ${fmtM(radius)} of ${p.label}, from the daily MUR analysis for ` +
                    `${String(g.time).slice(0, 10)} (a 1 km blend of several satellites and buoys):`]];
                if (st.centre.d < 2000) lines.push(['geo', `At the centre: ${fmtC(st.centre.v)}`]);
                else lines.push(['geo', `Nearest water to the centre (${fmtM(st.centre.d)} away): ${fmtC(st.centre.v)}`]);
                lines.push(['geo', `Average: ${fmtC(st.mean)}`]);
                lines.push(['geo', `Coolest ${fmtC(st.min)}, warmest ${fmtC(st.max)}`]);
                return {
                    imagery: gridImagery(g, g.res, cmap, lo, hi, 'Sea surface temperature: NASA JPL MUR via NOAA CoastWatch'),
                    imageryAlpha: 0.8, lines,
                    legend: { title: `Sea surface temperature (${cmap}), middle 96% of the area`, colors: COLORMAPS[cmap],
                              lo: `${lo.toFixed(1)} °C`, hi: `${hi.toFixed(1)} °C` },
                    sources: ['NASA JPL Multi-scale Ultra-high Resolution (MUR) SST analysis v4.1, GHRSST Level 4 (0.01°), ' +
                              `via NOAA CoastWatch ERDDAP, dataset ${g.dataset}`],
                    empty: '',
                };
            },
        },

        chlorophyll: {
            title: 'Chlorophyll',
            radius: (p) => p.sizeM ? clamp(p.sizeM / 2, 5000, 150000) : 30000,
            async load(p, radius, a) {
                const cmap = cmapOf(a, 'viridis');
                const g = await oceanGrid('chlorophyll', areaRect(p.lon, p.lat, radius));
                const st = gridStats(g, p, radius);
                if (!st) return { lines: [], empty: `No chlorophyll data within ${fmtM(radius)} of ${p.label} (no open water there)` };
                // Chlorophyll spans orders of magnitude; colour it on a log scale
                const lo = Math.log10(Math.max(st.p2, 0.01)), hi = Math.max(Math.log10(Math.max(st.p98, 0.01)), lo + 0.3);
                const mg = (v) => `${v < 1 ? v.toFixed(2) : v.toFixed(1)} mg/m³`;
                const lines = [['step', `Chlorophyll-a in the surface water within ${fmtM(radius)} of ${p.label}, for ` +
                    `${String(g.time).slice(0, 10)} (daily satellite ocean colour, cloud gaps filled statistically):`]];
                if (st.centre.d < 3000) lines.push(['geo', `At the centre: ${mg(st.centre.v)}`]);
                else lines.push(['geo', `Nearest water to the centre (${fmtM(st.centre.d)} away): ${mg(st.centre.v)}`]);
                lines.push(['geo', `Median ${mg(st.median)}; lowest ${mg(st.min)}, highest ${mg(st.max)}`]);
                lines.push(['step', 'Higher chlorophyll means more phytoplankton. Open ocean is usually below 0.3 mg/m³; ' +
                    'productive coastal upwelling water often reaches 1-10 mg/m³ and blooms more.']);
                return {
                    imagery: gridImagery(g, g.res, cmap, lo, hi, 'Chlorophyll: NOAA CoastWatch', (v) => Math.log10(Math.max(v, 0.01))),
                    imageryAlpha: 0.8, lines,
                    legend: { title: `Chlorophyll-a (${cmap}, log scale), middle 96% of the area`, colors: COLORMAPS[cmap],
                              lo: mg(10 ** lo), hi: mg(10 ** hi) },
                    sources: ['NOAA CoastWatch gap-filled (DINEOF) chlorophyll-a from NOAA S-NPP and NOAA-20 VIIRS and ' +
                              `Copernicus Sentinel-3A OLCI, science quality, 2 km, via NOAA CoastWatch ERDDAP, dataset ${g.dataset}`],
                    empty: '',
                };
            },
        },

        // Cesium World Terrain, coloured on the globe as off Earth
        elevation: { ...PLANET_LAYERS.elevation, radius: terrainRadius },
        slope: { ...PLANET_LAYERS.slope, radius: terrainRadius },
        contours: { ...PLANET_LAYERS.contours, radius: terrainRadius },

        lidar_dem: {
            title: 'Lidar terrain',
            radius: (p) => p.sizeM ? clamp(p.sizeM / 2, 300, 10000) : 2000,
            async load(p, radius, a) {
                const cmap = cmapOf(a, 'turbo');
                const t = await serverJson(PILOT_TOPO_URL, { lat: deg(p.lat).toFixed(5), lon: deg(p.lon).toFixed(5),
                                                             radius_m: String(Math.round(radius)) }, 'lidar', 'The lidar server');
                const d = t.dataset, st = t.stats;
                const fmtZ = (m) => `${Math.round(m).toLocaleString('en-US')} m`;
                const share = (f) => `${Math.round(f * 100)}%`;
                const where = t.moved_m ? `the nearest stored survey ground, ${fmtM(t.moved_m)} from ${p.label}` : p.label;
                const lines = [['step', `${d.name}: ${d.product}, collected ${d.collected} (${d.source_res}), ` +
                    `shown at ${t.res_m} m per pixel within ${fmtM(t.radius_m)} of ${where}:`]];
                if (st.centre !== null) {
                    lines.push(['geo', `At the centre: ${fmtZ(st.centre)}` +
                        (st.centre_slope !== null ? `, slope ${Math.round(st.centre_slope)}°` : '')]);
                }
                lines.push(['geo', `Heights ${fmtZ(st.min)} to ${fmtZ(st.max)}, median ${fmtZ(st.median)}; ` +
                    `local relief ${fmtZ(st.p98 - st.p2)} (2nd to 98th percentile)`]);
                if (st.slope_median !== null) {
                    lines.push(['geo', `Slope: median ${st.slope_median.toFixed(1)}°; ${share(st.steep_share)} of the ground ` +
                        'is steeper than 30° (scarps, cliffs, channel walls)']);
                }
                if (st.coverage < 0.95) lines.push(['step', `The survey covers ${share(st.coverage)} of this circle; the rest shows the base map.`]);
                if (t.others.length) lines.push(['step', `Also stored for this area: ${t.others.join('; ')}`]);
                lines.push(['step', 'Shaded relief lit from several directions and coloured by height, in metres in the survey\'s vertical datum.']);
                const area = { lon: rad(t.lon), lat: rad(t.lat), radius: t.radius_m };
                return {
                    imagery: await reliefImagery(t, cmap), imageryAlpha: 1,
                    area, ring: area, lines,
                    legend: { title: `Lidar height (${cmap}), middle 98% of the area`, colors: COLORMAPS[cmap],
                              lo: fmtZ(t.elev[0]), hi: fmtZ(t.elev[1]) },
                    sources: [`${d.name}. Distributed by OpenTopography, https://doi.org/${d.doi}`],
                    empty: '',
                };
            },
        },

        topo_datasets: {
            title: 'OpenTopography datasets',
            // Surveys cover sites, not towns: look well beyond a small place's extent
            radius: (p) => clamp((p.sizeM || 0) / 2, 15000, 50000),
            async load(p, radius) {
                const r = areaRect(p.lon, p.lat, radius);
                const query = (productFormat) => `${OT_CATALOG_URL}?` + new URLSearchParams({
                    productFormat, minx: deg(r.west).toFixed(4), miny: deg(r.south).toFixed(4),
                    maxx: deg(r.east).toFixed(4), maxy: deg(r.north).toFixed(4),
                    detail: 'true', outputFormat: 'json', include_federated: 'true',
                });
                const [pc, rs, stored] = await Promise.all([
                    fetchJson(query('PointCloud'), {}, 45000), fetchJson(query('Raster'), {}, 45000),
                    serverJson(PILOT_TOPO_URL, { list: 1 }, 'lidar', 'The lidar server').then(j => j.datasets, () => []),
                ]);
                const found = new Map();
                for (const e of [...(pc.Datasets || []), ...(rs.Datasets || [])].map(x => x.Dataset).filter(Boolean)) {
                    const geo = e.spatialCoverage?.geo?.geojson;
                    const box = geoBox(geo);
                    // The global elevation models (SRTM, Copernicus and the like) cover everywhere
                    if (!box || box[2] - box[0] > 20) continue;
                    const id = e.alternateName || e.identifier?.value || e.name;
                    if (!found.has(id)) found.set(id, { e, id, geo, formats: new Set() });
                    found.get(id).formats.add(/point/i.test(e.fileFormat || '') ? 'point cloud' : 'raster');
                }
                const list = [...found.values()].map(x => {
                    const e = x.e;
                    const dates = String(e.temporalCoverage || '').replace(' / ', ' to ');
                    const here = stored.find(s => s.id.startsWith(`${x.id}_`));
                    const link = e.url || (e.alternateName ? 'https://portal.opentopography.org/datasets'
                        : `https://portal.opentopography.org/usgsDataset?dsid=${encodeURIComponent(x.id)}`);
                    return { ...x, dates, here, link, start: dates.slice(0, 10),
                             host: e.alternateName ? 'OpenTopography' : 'USGS 3DEP (indexed by OpenTopography)' };
                }).sort((a, b) => b.start.localeCompare(a.start));
                const props = new Map(list.map(x => [x.id, x]));
                const features = list.flatMap(x => (x.geo.features || [x.geo]).filter(f => f?.geometry)
                    .map(f => ({ type: 'Feature', geometry: f.geometry, properties: { dsid: x.id } })));
                const lines = list.length ? [['step', `OpenTopography datasets within ${fmtM(radius)} of ${p.label}, newest first ` +
                    '(footprints outlined; click one for its citation link):']] : [];
                list.slice(0, 15).forEach(x => lines.push(['geo', `${x.e.name} (${x.dates || 'date unknown'}; ${[...x.formats].join(' and ')}; ` +
                    `${x.host})` + (x.here ? '. Stored on DeepGIS: ask for lidar terrain here.' : '')]));
                if (list.length > 15) lines.push(['step', `...and ${list.length - 15} more`]);
                return {
                    fc: { type: 'FeatureCollection', features },
                    style: { fill: Cesium.Color.CYAN.withAlpha(0.12), stroke: Cesium.Color.CYAN },
                    decorate(ent, q) {
                        const x = props.get(q.dsid);
                        if (!x) return;
                        ent.name = x.e.name;
                        ent.description = tableHtml([['Dataset', x.e.name], ['Collected', x.dates], ['Products', [...x.formats].join(', ')],
                            ['Host', x.host], ['On DeepGIS', x.here ? `yes, ${x.here.product}` : ''], ['Citation', x.e.citation]],
                            [['Dataset page', x.link]]);
                    },
                    lines,
                    sources: ['OpenTopography catalog API (portal.opentopography.org), including the USGS 3DEP lidar it indexes'],
                    empty: `No OpenTopography lidar or local elevation datasets within ${fmtM(radius)} of ${p.label}`,
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

    const PILOT_DESCRIBE_URL = '/label/api/pilot/describe/';
    const CAPTURE_MAX_PX = 1280;

    // One frame of the globe as a JPEG data URL. It is read in postRender, while the
    // WebGL drawing buffer still holds the frame (the viewer does not preserve it).
    function captureView() {
        const scene = getViewer().scene;
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => { off(); reject(new Error('the view did not render')); }, 5000);
            const off = scene.postRender.addEventListener(() => {
                off();
                clearTimeout(timer);
                try {
                    const src = scene.canvas;
                    const k = Math.min(1, CAPTURE_MAX_PX / Math.max(src.width, src.height));
                    const c = document.createElement('canvas');
                    c.width = Math.round(src.width * k);
                    c.height = Math.round(src.height * k);
                    c.getContext('2d').drawImage(src, 0, 0, c.width, c.height);
                    resolve(c.toDataURL('image/jpeg', 0.85));
                } catch (e) {
                    reject(new Error(`could not read the view (${e.message || e})`));
                }
            });
            scene.requestRender();
        });
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

    // follow_vehicle: the camera rides on a vehicle that posts its pose to DeepGIS (the
    // OpenUAV PX4 twin today). Poses are polled and the camera eases toward the latest
    // one every frame. Heights are metres above the vehicle's local origin (its take-off
    // point) added to the terrain height there, so no geoid model is needed.
    const VEHICLES_URL = '/label/api/vehicles/live/';
    const FOLLOW_POLL_MS = 250;
    const FOLLOW_STALE_SEC = 3;
    const CHASE_RANGE_M = 40;
    let follow = null;
    const originGround = new Map();

    async function liveVehicles() {
        const resp = await fetch(VEHICLES_URL, { credentials: 'same-origin' });
        if (resp.status === 401) throw new Error('Following a vehicle is for signed-in users.');
        if (!resp.ok) throw new Error(`Vehicle list failed (HTTP ${resp.status})`);
        return (await resp.json()).vehicles || [];
    }

    async function vehicleHeight(v) {
        if (v.ref && Number.isFinite(v.up_m)) {
            const key = `${v.ref.lat.toFixed(7)},${v.ref.lon.toFixed(7)}`;
            if (!originGround.has(key)) originGround.set(key, await groundHeight(rad(v.ref.lon), rad(v.ref.lat)));
            return originGround.get(key) + v.up_m;
        }
        return (await groundHeight(rad(v.lon), rad(v.lat))) + (Number.isFinite(v.up_m) ? v.up_m : 2);
    }

    const vehicleName = (v) => v.name || v.id;

    // Picture-in-picture of the followed vehicle's latest camera frame, for vehicles
    // that post frames (/label/api/vehicles/frame/); the pose list carries the frame's seq
    const FRAME_STALE_SEC = 10;

    function showFrame(f, p) {
        if (f.pipClosed || !p.frame) return;
        if (!f.pip) {
            const box = document.createElement('div');
            box.style.cssText = 'position:fixed;left:16px;bottom:70px;z-index:1000;width:min(40vw,440px);' +
                'background:rgba(0,0,0,.8);border:1px solid rgba(255,255,255,.3);border-radius:6px;' +
                'overflow:hidden;color:#fff;font:12px sans-serif;box-shadow:0 2px 12px rgba(0,0,0,.5)';
            const img = document.createElement('img');
            img.alt = `${vehicleName(p)} camera`;
            img.style.cssText = 'display:block;width:100%;height:auto;background:#111';
            const bar = document.createElement('div');
            bar.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:8px;padding:3px 4px 3px 8px';
            const label = document.createElement('span');
            const close = document.createElement('button');
            close.type = 'button';
            close.textContent = '\u00d7';
            close.title = 'Hide the camera';
            close.style.cssText = 'background:none;border:0;color:#fff;font-size:16px;line-height:1;cursor:pointer;padding:0 4px';
            close.addEventListener('click', () => { hideFrame(f); f.pipClosed = true; });
            bar.append(label, close);
            box.append(img, bar);
            document.body.appendChild(box);
            f.pip = { box, img, label, seq: null };
        }
        const { img, label } = f.pip;
        if (p.frame.seq !== f.pip.seq) {
            f.pip.seq = p.frame.seq;
            img.src = `/label/api/vehicles/${encodeURIComponent(p.id)}/frame.jpg?seq=${p.frame.seq}`;
        }
        const age = p.frame.age_sec;
        const stale = age > FRAME_STALE_SEC;
        img.style.opacity = stale ? '0.45' : '1';
        label.textContent = `${vehicleName(p)} camera · ${stale ? `last frame ${Math.round(age)} s ago` : `${age.toFixed(1)} s old`}`;
    }

    function hideFrame(f) {
        if (f.pip) f.pip.box.remove();
        f.pip = null;
    }

    function stopFollow() {
        if (!follow) return;
        const f = follow;
        follow = null;
        clearTimeout(f.timer);
        f.off();
        hideFrame(f);
        const viewer = getViewer();
        if (f.marker) viewer.entities.remove(f.marker);
        viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
        viewer.camera.frustum.fov = f.fov;
        viewer.scene.requestRender();
    }

    function startFollow(v, view) {
        const viewer = getViewer();
        const f = { id: v.id, view, fov: viewer.camera.frustum.fov, pose: null, shown: null, lost: false };
        follow = f;
        const poll = async () => {
            try {
                const p = (await liveVehicles()).find(x => x.id === f.id);
                if (follow !== f) return;
                if (p && p.age_sec < FOLLOW_STALE_SEC) {
                    f.pose = {
                        pos: Cesium.Cartesian3.fromDegrees(p.lon, p.lat, await vehicleHeight(p), ellipsoid()),
                        heading: rad(p.heading_deg || 0),
                        pitch: rad(clamp(Number.isFinite(p.gimbal_pitch_deg) ? p.gimbal_pitch_deg : -90, -89.9, 45)),
                    };
                    if (view === 'camera' && Number.isFinite(p.hfov_deg)) viewer.camera.frustum.fov = rad(p.hfov_deg);
                    showFrame(f, p);
                    if (f.lost) addMsg('step', `${vehicleName(p)} is reporting again`);
                    f.lost = false;
                    viewer.scene.requestRender();
                } else if (!f.lost && follow === f) {
                    f.lost = true;
                    addMsg('step', `No pose from ${vehicleName(v)} for ${FOLLOW_STALE_SEC} s; holding the last view`);
                }
            } catch (e) { /* the next poll retries */ }
            if (follow === f) f.timer = setTimeout(poll, FOLLOW_POLL_MS);
        };
        let last = performance.now();
        f.off = viewer.scene.preRender.addEventListener(() => {
            if (!f.pose) return;
            const now = performance.now();
            const k = 1 - Math.exp(-Math.min(1, (now - last) / 1000) * 6);
            last = now;
            if (!f.shown) {
                f.shown = { pos: Cesium.Cartesian3.clone(f.pose.pos), heading: f.pose.heading, pitch: f.pose.pitch };
            } else {
                Cesium.Cartesian3.lerp(f.shown.pos, f.pose.pos, k, f.shown.pos);
                f.shown.heading += k * Cesium.Math.negativePiToPi(f.pose.heading - f.shown.heading);
                f.shown.pitch += k * (f.pose.pitch - f.shown.pitch);
            }
            const camera = viewer.camera;
            if (view === 'chase') {
                camera.lookAt(f.shown.pos, new Cesium.HeadingPitchRange(f.shown.heading, rad(-25), CHASE_RANGE_M));
            } else {
                camera.setView({ destination: f.shown.pos,
                                 orientation: { heading: f.shown.heading, pitch: f.shown.pitch, roll: 0 } });
            }
            if (Cesium.Cartesian3.distance(f.shown.pos, f.pose.pos) > 0.05) viewer.scene.requestRender();
        });
        if (view === 'chase') {
            f.marker = viewer.entities.add({
                position: new Cesium.CallbackProperty(() => f.shown?.pos, false),
                point: { pixelSize: 12, color: Cesium.Color.ORANGE, outlineColor: Cesium.Color.WHITE,
                         outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
                label: { text: vehicleName(v), font: '13px sans-serif', pixelOffset: new Cesium.Cartesian2(0, -18),
                         fillColor: Cesium.Color.WHITE, showBackground: true,
                         disableDepthTestDistance: Number.POSITIVE_INFINITY },
            });
        }
        poll();
    }

    // Cancels the running plan as well as the motion; a plan that only describes the
    // view keeps following, so "what do you see?" looks through the vehicle's camera
    function stopAll(keepFollow = false) {
        runId++;
        haltMotion();
        if (!keepFollow) stopFollow();
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
            const alt = a.alt_m || (geo ? clamp(geo.radius * 0.35, 80, isEarth ? 7000 : SCALE.orbitAlt) : clamp(radius * 0.5, 80, SCALE.orbitAlt));
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
            stopFollow();
            addMsg('step', 'Stopped');
        },

        async follow_vehicle(a, id) {
            if (!isEarth) throw new Error(`No vehicles report positions on ${body}`);
            const list = await liveVehicles();
            check(id);
            const live = list.filter(v => v.age_sec < FOLLOW_STALE_SEC);
            if (!live.length) {
                addMsg('step', list.length
                    ? `No vehicle is reporting right now (${list.map(v => `${vehicleName(v)}: last pose ${Math.round(v.age_sec)} s ago`).join('; ')})`
                    : 'No vehicle is reporting its position to DeepGIS right now');
                return;
            }
            const wanted = (a.vehicle || '').toLowerCase();
            const named = wanted && live.find(v => v.id === wanted || vehicleName(v).toLowerCase().includes(wanted));
            if (wanted && !named) {
                addMsg('step', `No live vehicle called "${a.vehicle}". Live now: ${live.map(vehicleName).join(', ')}`);
                return;
            }
            const v = named || live[0];
            if (!named && live.length > 1) {
                addMsg('step', `Also live: ${live.slice(1).map(vehicleName).join(', ')} (name one to follow it)`);
            }
            const view = a.view === 'chase' ? 'chase' : 'camera';
            startFollow(v, view);
            const settle = Date.now() + 5000;
            await until(() => follow?.shown || Date.now() > settle, id);
            const where = Number.isFinite(v.up_m) ? `, ${fmtM(v.up_m)} above its take-off point` : '';
            addMsg('step', `Following ${vehicleName(v)} ${view === 'chase' ? 'from behind' : 'through its camera'}` +
                   `${where}, heading ${Math.round(((v.heading_deg || 0) + 360) % 360)}°.` +
                   `${v.frame ? ' Its camera is at the bottom left.' : ''} Say "stop" to let go.`);
        },

        async wait(a, id) {
            const end = Date.now() + (a.seconds || 0) * 1000;
            addMsg('step', `Hovering ${Math.round(a.seconds || 0)} s`);
            await until(() => Date.now() >= end, id);
        },

        async show_layer(a, id) {
            const spec = layerSpecs()[a.kind];
            if (!spec) throw new Error(`No "${a.kind}" layer on ${body}`);
            const p = await resolvePoint(a);
            check(id);
            const viewer = getViewer();
            const radius = a.radius_m || (typeof spec.radius === 'function' ? spec.radius(p) : spec.radius);
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
            const ring = res.ring || (!res.area && radius ? { lon: p.lon, lat: p.lat, radius } : null);
            if (ring) {
                ds.entities.add({
                    name: `${spec.title}: search radius ${fmtM(ring.radius)}`,
                    polyline: {
                        positions: circlePositions(ring.lon, ring.lat, ring.radius), clampToGround: true,
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
            if (res.globe) {
                // Elevation and slope both colour the whole surface; the newer one wins
                if (res.globe.ramp) {
                    [...globeLayers].filter(([k, g]) => g.ramp && k !== a.kind)
                        .forEach(([k]) => runners.hide_layer({ kind: k }, id, true));
                }
                globeLayers.set(a.kind, res.globe);
                applyGlobeMaterial();
            }
            shownLayers.set(a.kind, { ds, imagery });
            layerArea = res.area || { lon: p.lon, lat: p.lat, radius: radius || 5000 };

            if (res.lines.length) {
                res.lines.forEach(([kind, text]) => addMsg(kind, text));
                if (res.legend) addLegend(res.legend);
                (res.sources || []).forEach(s => addMsg('step', `Source: ${String(s).trim()}`));
            } else if (res.empty) addMsg('step', res.empty);
            if (a.frame) {
                const r = layerArea.radius;
                const ground = await groundHeight(layerArea.lon, layerArea.lat);
                await flight({
                    sphere: new Cesium.BoundingSphere(Cesium.Cartesian3.fromRadians(layerArea.lon, layerArea.lat, ground, ellipsoid()), r),
                    options: { offset: new Cesium.HeadingPitchRange(viewer.camera.heading, Cesium.Math.toRadians(-50), r * 2.6) },
                }, id);
            }
        },

        // No kind: remove every layer
        async hide_layer(a, id, quiet) {
            const viewer = getViewer();
            const kinds = a.kind ? [a.kind] : [...shownLayers.keys()];
            const removed = kinds.filter(k => shownLayers.has(k));
            const recolour = removed.some(k => globeLayers.has(k));
            removed.forEach(k => {
                const { ds, imagery } = shownLayers.get(k);
                viewer.dataSources.remove(ds, true);
                if (imagery) viewer.imageryLayers.remove(imagery, true);
                shownLayers.delete(k);
                globeLayers.delete(k);
            });
            if (recolour) applyGlobeMaterial();
            if (!shownLayers.size) layerArea = null;
            if (quiet) return;
            const specs = layerSpecs();
            if (removed.length) addMsg('step', `Removed: ${removed.map(k => specs[k].title.toLowerCase()).join(', ')}`);
            else addMsg('step', a.kind ? `No ${specs[a.kind]?.title.toLowerCase() || a.kind} layer is shown` : 'No layers are shown');
        },

        async describe_view(a, id) {
            const scene = getViewer().scene;
            const settle = Date.now() + 8000;
            await until(() => scene.globe.tilesLoaded || Date.now() > settle, id);
            const working = addMsg('step', 'Looking at the view...');
            let data;
            try {
                const image = await captureView();
                const resp = await fetch(PILOT_DESCRIBE_URL, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                    body: JSON.stringify({ image, body, view: await currentView(), question: lastMessage }),
                });
                data = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(data.error || `View analysis failed (HTTP ${resp.status})`);
            } finally {
                working.remove();
            }
            check(id);
            const observations = data.observations || [];
            if (data.summary) addMsg('ai', data.summary);
            observations.forEach(o => addMsg('step', `• ${o}`));
            if (!data.summary && !observations.length) addMsg('step', 'Nothing to report in this view');
            // Follow-up questions ("what is the dark patch on the left?") can refer to it
            history.push({ role: 'assistant',
                           content: `What I saw in the view: ${[data.summary, ...observations].join(' ')}`.slice(0, 2000) });
            history.splice(0, Math.max(0, history.length - 8));
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
        stopAll(actions.every(a => a.type === 'describe_view'));
        const id = runId;
        try {
            // Describing the view as it is needs no 3D switch
            if (actions.some(a => a.type !== 'stop' && a.type !== 'describe_view')) await ensure3D(id);
            for (const [i, a] of actions.entries()) {
                check(id);
                // Frame the area unless a later step moves the camera anyway; off Earth
                // a layer for the area in view (sized from the camera) stays put
                if (a.type === 'show_layer') {
                    a.frame = !actions.slice(i + 1).some(b => b.type === 'goto' || b.type === 'orbit') &&
                        (isEarth || !!a.place || Number.isFinite(a.lat));
                }
                await runners[a.type](a, id);
            }
            if (actions.some(a => a.type !== 'stop') && !follow) addMsg('step', 'Done');
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
        lastMessage = message;
        addMsg('user', message);
        const thinking = addMsg('step', 'Thinking...');
        sendBtn.disabled = true;
        try {
            const resp = await fetch('/label/api/pilot/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                body: JSON.stringify({
                    message, history, body, view: await currentView(),
                    model: modelSelect?.value || '',
                }),
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

    loadModels();
    console.log('[AI Pilot] Initialized');
})();
