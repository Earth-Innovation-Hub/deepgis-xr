// VR cockpit for hud/xr.js: panels drawn on 2D canvases and shown as WebXR compositor
// layers, so the headset draws them sharp and at its own frame rate whatever the globe's.
// - Instrument console: a curved (cylinder) layer below eye level, fixed in front of the
//   craft and turning only with it; X re-centres it on where you face or hides it.
// - Compass: a faint quad locked to the head, at the top of the view.
// - Layers wing: the data layers as toggles, left of the console (Y shows or hides it).
//   Kinds and groups come from views/pilot.py (layer_catalog, #hudLayerCatalog).
// - Pilot comms: the AI pilot chat (hud/pilot.js, window.DeepGISPilot) right of the console,
//   with quick prompts and a line typed on the headset's system keyboard (hud/xr.js).
// - Robots: the live fleet (hud/actions.js vehicles()) in the wing's place, with the selected
//   robot's camera frame; fly to it, ride its camera or chase it.
// - Comfort vignette: a head-locked layer that darkens the edges of view while the ground
//   streams past (hud/xr.js sets its strength).
// - Wrist menu: on the left controller, shown while you look at it.
// The laser (hud/xr.js) hovers and clicks buttons through pick/hover/click; click returns
// an action for hud/xr.js to run.
(function initCockpit() {
    const C = {
        glass: 'rgba(6, 14, 28, 0.78)', glassEdge: 'rgba(56, 189, 248, 0.55)', line: '#38bdf8',
        dim: '#64748b', text: '#e2e8f0', soft: '#94a3b8', amber: '#fbbf24', red: '#f87171', green: '#34d399',
    };
    const MONO = 'ui-monospace, "Roboto Mono", "DejaVu Sans Mono", monospace';
    const CONSOLE = { radius: 1.2, angle: Cesium.Math.toRadians(64), width: 1600, drop: 0.42 };
    CONSOLE.height = Math.round(CONSOLE.width / 3.6);
    CONSOLE.metres = CONSOLE.radius * CONSOLE.angle / CONSOLE.width * CONSOLE.height;
    const COMPASS = { width: 1024, height: 96, metres: [0.52, 0.0488], y: 0.21, z: -1.0 };
    // Counter-clockwise from the console's centre, so to the left
    const WING = { width: 1100, metres: 0.72, yaw: Cesium.Math.toRadians(57), dist: 1.05, drop: 0.06, line: 36, top: 112 };
    // Mirrors the wing on the right
    const COMMS = { width: 1100, height: 780, metres: 0.72, yaw: Cesium.Math.toRadians(-57), dist: 1.05, drop: 0.06, line: 34 };
    const QUICK_PROMPTS = [
        ['DESCRIBE', 'Describe what I am looking at'],
        ['WHAT IS HERE', 'What is the place in view, and what is it known for?'],
        ['ORBIT THIS', 'Orbit the point in view'],
        ['CLIMB 1 KM', 'Climb 1 km higher where we are'],
    ];
    // Where the wing is, in its place
    const ROBOTS = { ...WING, width: 1100, height: 700, rows: 6, row: 58 };
    // Head-locked, wider than the eyes' fields of view; drawn under the panels
    const VIGNETTE = { width: 256, height: 256, metres: [2.6, 2.2], z: -0.6 };
    // In the left grip space: above the controller towards the wrist, tilted up to the eyes
    const WRIST = { width: 800, height: 360, metres: [0.2, 0.09], at: { x: 0, y: 0.045, z: 0.07 }, tilt: Cesium.Math.toRadians(-50) };
    const REDRAW_MS = 70;
    const CARDINALS = { 0: 'N', 45: 'NE', 90: 'E', 135: 'SE', 180: 'S', 225: 'SW', 270: 'W', 315: 'NW' };

    function canvas(w, h) {
        const c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        return c;
    }

    const deg = (r) => (Cesium.Math.toDegrees(r) % 360 + 360) % 360;

    function fmtDistance(m) {
        if (!Number.isFinite(m)) return '—';
        if (m < 1000) return `${Math.round(m)} m`;
        return m < 100000 ? `${(m / 1000).toFixed(m < 10000 ? 2 : 1)} km` : `${Math.round(m / 1000)} km`;
    }

    function fmtSpeed(mps) {
        if (mps < 1) return '0 m/s';
        return mps < 1000 ? `${Math.round(mps)} m/s` : `${(mps / 1000).toFixed(1)} km/s`;
    }

    function fmtLatLon(lat, lon) {
        const ns = lat >= 0 ? 'N' : 'S', ew = lon >= 0 ? 'E' : 'W';
        return [`${Math.abs(lat).toFixed(4)}° ${ns}`, `${Math.abs(lon).toFixed(4)}° ${ew}`];
    }

    function bracketBox(ctx, x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.lineTo(x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.lineTo(x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.lineTo(x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.closePath();
    }

    function glassPanel(ctx, W, H, r) {
        ctx.clearRect(0, 0, W, H);
        bracketBox(ctx, 8, 8, W - 16, H - 16, r);
        ctx.fillStyle = C.glass;
        ctx.fill();
        ctx.lineWidth = 3;
        ctx.strokeStyle = C.glassEdge;
        ctx.stroke();
    }

    function headingTape(ctx, x, y, w, h, heading, opts = {}) {
        const span = opts.span || 90;
        const pxPerDeg = w / span;
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, y, w, h);
        ctx.clip();
        ctx.strokeStyle = opts.color || C.line;
        ctx.fillStyle = opts.color || C.line;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.font = `600 ${Math.round(h * 0.42)}px ${MONO}`;
        const first = Math.floor((heading - span / 2) / 5) * 5;
        for (let d = first; d <= heading + span / 2 + 5; d += 5) {
            const px = x + w / 2 + (d - heading) * pxPerDeg;
            const norm = ((d % 360) + 360) % 360;
            const major = norm % 15 === 0;
            ctx.globalAlpha = major ? 0.95 : 0.45;
            ctx.lineWidth = major ? 3 : 2;
            ctx.beginPath();
            ctx.moveTo(px, y + h);
            ctx.lineTo(px, y + h - h * (major ? 0.38 : 0.2));
            ctx.stroke();
            const fits = Math.abs(px - (x + w / 2)) < w / 2 - h * 0.45;
            if (fits && (norm % 45 === 0 || (major && opts.numbers))) {
                ctx.globalAlpha = norm % 45 === 0 ? 1 : 0.7;
                ctx.fillText(CARDINALS[norm] || String(norm).padStart(3, '0'), px, y + h * 0.04);
            }
        }
        ctx.restore();
        ctx.fillStyle = C.amber;
        ctx.beginPath();
        ctx.moveTo(x + w / 2, y + h * 0.5);
        ctx.lineTo(x + w / 2 - h * 0.16, y + h * 0.22);
        ctx.lineTo(x + w / 2 + h * 0.16, y + h * 0.22);
        ctx.closePath();
        ctx.fill();
    }

    // Great-circle metres between two lat/lon points in degrees (Earth radius)
    function distanceM(lat1, lon1, lat2, lon2) {
        const r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLon = (lon2 - lon1) * r;
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2;
        return 2 * 6371000 * Math.asin(Math.min(1, Math.sqrt(a)));
    }

    function fmtAge(sec) {
        if (!Number.isFinite(sec)) return '';
        if (sec < 3) return 'LIVE';
        return sec < 120 ? `${Math.round(sec)} s ago` : `${Math.round(sec / 60)} min ago`;
    }

    function button(ctx, b, hot, font = 30) {
        const on = b.on !== false;
        bracketBox(ctx, b.x, b.y, b.w, b.h, Math.min(14, b.h / 4));
        ctx.fillStyle = b.color;
        ctx.globalAlpha = hot ? 0.4 : on ? 0.14 : 0.05;
        ctx.fill();
        ctx.globalAlpha = on || hot ? 1 : 0.6;
        ctx.lineWidth = hot ? 4 : 2;
        ctx.strokeStyle = b.color;
        ctx.stroke();
        ctx.fillStyle = hot ? C.text : b.color;
        ctx.font = `700 ${font}px ${MONO}`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(b.label, b.x + b.w / 2, b.y + b.h / 2 + 1);
        ctx.globalAlpha = 1;
    }

    // Column-major 4x4 matrices for rigid transforms, as WebXR gives them
    function rigid(p, q) {
        const { x, y, z, w } = q;
        return new Float32Array([
            1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
            2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
            2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0,
            p.x, p.y, p.z, 1,
        ]);
    }

    function mul(a, b) {
        const o = new Float32Array(16);
        for (let c = 0; c < 4; c++) {
            for (let r = 0; r < 4; r++) {
                let s = 0;
                for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
                o[c * 4 + r] = s;
            }
        }
        return o;
    }

    const yawQuat = (yaw) => ({ x: 0, y: Math.sin(yaw / 2), z: 0, w: Math.cos(yaw / 2) });
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const unit = (v) => { const n = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / n, v[1] / n, v[2] / n]; };

    // Ray against a quad of size w x h metres with pose M, seen from its front (+z) side
    function pickQuad(M, w, h, W, H, o, d) {
        const ax = [M[0], M[1], M[2]], ay = [M[4], M[5], M[6]], az = [M[8], M[9], M[10]];
        const v = [o[0] - M[12], o[1] - M[13], o[2] - M[14]];
        const lo = [dot(v, ax), dot(v, ay), dot(v, az)], ld = [dot(d, ax), dot(d, ay), dot(d, az)];
        if (lo[2] <= 0 || ld[2] >= -1e-6) return null;
        const t = -lo[2] / ld[2];
        const px = lo[0] + t * ld[0], py = lo[1] + t * ld[1];
        if (Math.abs(px) > w / 2 || Math.abs(py) > h / 2) return null;
        return { dist: t, x: (px / w + 0.5) * W, y: (0.5 - py / h) * H };
    }

    // [[group title, [{kind, title, locked}]]] for this body
    function layerGroups() {
        const el = document.getElementById('hudLayerCatalog');
        const hud = window.DeepGISActions;
        if (!el || !hud) return [];
        const cat = JSON.parse(el.textContent);
        const titles = new Map(hud.layers().map(l => [l.kind, l.title]));
        const signedIn = document.getElementById('dataLayersMount')?.dataset.signedIn === '1';
        const locked = new Set(signedIn ? [] : cat.signin_kinds);
        return (cat.groups || [])
            .map(([title, kinds]) => [title, kinds.filter(k => titles.has(k))
                .map(k => ({ kind: k, title: titles.get(k), locked: locked.has(k) }))])
            .filter(([, rows]) => rows.length);
    }

    // Words into lines no wider than w in the context's current font
    function wrap(ctx, text, w) {
        const lines = [];
        let line = '';
        String(text).split(/\s+/).filter(Boolean).forEach((word) => {
            const next = line ? `${line} ${word}` : word;
            if (ctx.measureText(next).width <= w || !line) line = next;
            else {
                lines.push(line);
                line = word;
            }
        });
        if (line) lines.push(line);
        return lines;
    }

    // Groups into two columns of about the same height
    function wingColumns(groups) {
        const lines = (g) => 1 + g[1].length;
        const total = groups.reduce((n, g) => n + lines(g), 0);
        const cols = [[], []];
        let n = 0;
        groups.forEach((g) => {
            cols[n > 0 && n + lines(g) / 2 > total / 2 ? 1 : 0].push(g);
            n += lines(g);
        });
        return cols;
    }

    function create({ binding, gl, session, space, viewerSpace, present }) {
        const hud = window.DeepGISActions;
        const groups = layerGroups();
        const columns = wingColumns(groups);
        const wingLines = Math.max(...columns.map(c => c.reduce((n, g) => n + 1 + g[1].length, 0)), 1);
        WING.height = WING.top + wingLines * WING.line + 30;
        const wingMetres = [WING.metres, WING.metres * WING.height / WING.width];
        const commsMetres = [COMMS.metres, COMMS.metres * COMMS.height / COMMS.width];
        const pilot = window.DeepGISPilot;
        const wristOffset = rigid(WRIST.at, { x: Math.sin(WRIST.tilt / 2), y: 0, z: 0, w: Math.cos(WRIST.tilt / 2) });

        const panels = {};
        const addPanel = (id, layer, w, h, draw) => {
            panels[id] = { id, layer, canvas: canvas(w, h), draw, dirty: true, drawnAt: 0, buttons: [] };
            return panels[id];
        };
        addPanel('console', binding.createCylinderLayer({
            space, viewPixelWidth: CONSOLE.width, viewPixelHeight: CONSOLE.height, layout: 'mono',
            radius: CONSOLE.radius, centralAngle: CONSOLE.angle, aspectRatio: CONSOLE.width / CONSOLE.height,
        }), CONSOLE.width, CONSOLE.height, drawConsole);
        addPanel('compass', binding.createQuadLayer({
            space: viewerSpace, viewPixelWidth: COMPASS.width, viewPixelHeight: COMPASS.height, layout: 'mono',
            width: COMPASS.metres[0], height: COMPASS.metres[1],
            transform: new XRRigidTransform({ x: 0, y: COMPASS.y, z: COMPASS.z }),
        }), COMPASS.width, COMPASS.height, drawCompass);
        if (groups.length) {
            addPanel('wing', binding.createQuadLayer({
                space, viewPixelWidth: WING.width, viewPixelHeight: WING.height, layout: 'mono',
                width: wingMetres[0], height: wingMetres[1],
            }), WING.width, WING.height, drawWing);
        }
        const robotsMetres = [ROBOTS.metres, ROBOTS.metres * ROBOTS.height / ROBOTS.width];
        if (hud?.isEarth && hud.vehicles) {
            addPanel('robots', binding.createQuadLayer({
                space, viewPixelWidth: ROBOTS.width, viewPixelHeight: ROBOTS.height, layout: 'mono',
                width: robotsMetres[0], height: robotsMetres[1],
            }), ROBOTS.width, ROBOTS.height, drawRobots);
        }
        addPanel('vignette', binding.createQuadLayer({
            space: viewerSpace, viewPixelWidth: VIGNETTE.width, viewPixelHeight: VIGNETTE.height, layout: 'mono',
            width: VIGNETTE.metres[0], height: VIGNETTE.metres[1],
            transform: new XRRigidTransform({ x: 0, y: 0, z: VIGNETTE.z }),
        }), VIGNETTE.width, VIGNETTE.height, drawVignette);
        if (pilot) {
            addPanel('comms', binding.createQuadLayer({
                space, viewPixelWidth: COMMS.width, viewPixelHeight: COMMS.height, layout: 'mono',
                width: commsMetres[0], height: commsMetres[1],
            }), COMMS.width, COMMS.height, drawComms);
        }
        // Created once the left controller's grip space is known (wristFor)
        addPanel('wrist', null, WRIST.width, WRIST.height, drawWrist);

        const state = {
            console: false, wing: false, comms: false, wrist: false, yaw: 0, head: { x: 0, y: 0, z: 0 },
            consoleMatrix: null, wingMatrix: null, commsMatrix: null, wristMatrix: null, wristSpace: null,
            log: pilot ? pilot.recent() : [], typed: '', keyboard: false, asking: false,
            robots: false, robotsMatrix: null, robot: null, robotsKey: '', frame: null, sound: true,
            vignette: 0, vignetteDrawn: -1,
            hover: null, hit: null, cursor: null,
            status: 'Cockpit online', statusKind: 'step', statusAt: performance.now(),
            data: null, compassHeading: null, busy: new Set(), shownKey: '', presented: '',
        };
        const dirty = (...ids) => ids.forEach((id) => { if (panels[id]) panels[id].dirty = true; });

        function presentNow() {
            const layers = [];
            if (state.vignette > 0.02) layers.push(panels.vignette.layer);
            if (state.console) layers.push(panels.console.layer, panels.compass.layer);
            if (state.wing && panels.wing) layers.push(panels.wing.layer);
            if (state.robots && panels.robots) layers.push(panels.robots.layer);
            if (state.comms && panels.comms) layers.push(panels.comms.layer);
            if (state.wrist && panels.wrist.layer) layers.push(panels.wrist.layer);
            const key = layers.map(l => Object.keys(panels).find(id => panels[id].layer === l)).join();
            if (key === state.presented) return;
            state.presented = key;
            present(layers);
        }

        // Console and wing below eye level, ahead of the head's yaw (counter-clockwise from -z)
        function place(m) {
            state.yaw = Math.atan2(m[8], m[10]);
            state.head = { x: m[12], y: m[13], z: m[14] };
            const centre = { x: m[12], y: m[13] - CONSOLE.drop, z: m[14] };
            panels.console.layer.transform = new XRRigidTransform(centre, yawQuat(state.yaw));
            state.consoleMatrix = rigid(centre, yawQuat(state.yaw));
            const side = (id, spec) => {
                if (!panels[id]) return null;
                const yaw = state.yaw + spec.yaw;
                const at = { x: m[12] - Math.sin(yaw) * spec.dist, y: m[13] - spec.drop, z: m[14] - Math.cos(yaw) * spec.dist };
                panels[id].layer.transform = new XRRigidTransform(at, yawQuat(yaw));
                return rigid(at, yawQuat(yaw));
            };
            state.wingMatrix = side('wing', WING);
            state.robotsMatrix = side('robots', ROBOTS);
            state.commsMatrix = side('comms', COMMS);
            dirty('console', 'wing', 'robots', 'comms');
        }

        function setConsole(on, head) {
            if (on && head) place(head);
            state.console = on;
            if (!on && state.hit?.panel === 'console') state.hover = state.hit = null;
            dirty('console', 'compass', 'wrist');
            presentNow();
        }

        // The layers wing and the robots panel share the left side: showing one hides the
        // other. false when this page has no such panel.
        function setSide(id, on, head) {
            if (!panels[id]) return false;
            const other = id === 'wing' ? 'robots' : 'wing';
            if (on && head && !state.console && !state.comms && !state[other]) place(head);
            state[id] = on;
            if (on) state[other] = false;
            if (['wing', 'robots'].includes(state.hit?.panel) && !state[state.hit.panel]) state.hover = state.hit = null;
            dirty(id, other, 'console', 'wrist');
            presentNow();
            return true;
        }
        const setWing = (on, head) => setSide('wing', on, head);

        // false without the AI pilot on this page
        function setComms(on, head) {
            if (!panels.comms) return false;
            if (on && head && !state.console && !state.wing && !state.robots) place(head);
            state.comms = on;
            if (!on && state.hit?.panel === 'comms') state.hover = state.hit = null;
            dirty('comms', 'console', 'wrist');
            presentNow();
            return true;
        }

        function pilotEvent(e) {
            if (e.type === 'add') state.log.push(e);
            else state.log = state.log.filter(r => r.id !== e.id);
            state.log.splice(0, Math.max(0, state.log.length - 40));
            dirty('comms');
        }

        function wristFor(src) {
            if (state.wristSpace === src.gripSpace) return;
            panels.wrist.layer?.destroy?.();
            panels.wrist.layer = binding.createQuadLayer({
                space: src.gripSpace, viewPixelWidth: WRIST.width, viewPixelHeight: WRIST.height, layout: 'mono',
                width: WRIST.metres[0], height: WRIST.metres[1],
                transform: new XRRigidTransform(WRIST.at, { x: Math.sin(WRIST.tilt / 2), y: 0, z: 0, w: Math.cos(WRIST.tilt / 2) }),
            });
            state.wristSpace = src.gripSpace;
            state.presented = '';
            dirty('wrist');
            if (state.wrist) presentNow();
        }

        // Per XR frame, before picking: the wrist menu shows while you look at your left hand
        function track(frame, head) {
            const src = [...session.inputSources].find(s => s.handedness === 'left' && s.gripSpace);
            let shown = false;
            state.wristMatrix = null;
            if (src) {
                wristFor(src);
                const pose = frame.getPose(src.gripSpace, space);
                if (pose) {
                    const M = state.wristMatrix = mul(pose.transform.matrix, wristOffset);
                    const eye = [head[12], head[13], head[14]], at = [M[12], M[13], M[14]];
                    const toEye = unit([eye[0] - at[0], eye[1] - at[1], eye[2] - at[2]]);
                    const facing = dot([M[8], M[9], M[10]], toEye);
                    const looking = -dot([-head[8], -head[9], -head[10]], toEye);
                    shown = state.wrist ? facing > 0.35 && looking > 0.75 : facing > 0.5 && looking > 0.82;
                }
            }
            if (shown !== state.wrist) {
                state.wrist = shown;
                if (!shown && state.hit?.panel === 'wrist') state.hover = state.hit = null;
                dirty('wrist');
                presentNow();
            }
        }

        function pickConsole(o, d) {
            const s = Math.sin(state.yaw), c = Math.cos(state.yaw);
            const centre = { x: state.consoleMatrix[12], y: state.consoleMatrix[13], z: state.consoleMatrix[14] };
            const lx = o[0] - centre.x, ly = o[1] - centre.y, lz = o[2] - centre.z;
            const ox = lx * c - lz * s, oz = lx * s + lz * c;
            const dx = d[0] * c - d[2] * s, dz = d[0] * s + d[2] * c;
            const a = dx * dx + dz * dz;
            if (a < 1e-9) return null;
            const b = 2 * (ox * dx + oz * dz), k = ox * ox + oz * oz - CONSOLE.radius * CONSOLE.radius;
            const disc = b * b - 4 * a * k;
            if (disc < 0) return null;
            const t = (-b + Math.sqrt(disc)) / (2 * a);
            if (t <= 0) return null;
            const px = ox + t * dx, py = ly + t * d[1], pz = oz + t * dz;
            const theta = Math.atan2(px, -pz);
            if (Math.abs(theta) > CONSOLE.angle / 2 || Math.abs(py) > CONSOLE.metres / 2) return null;
            return { dist: t, x: (theta / CONSOLE.angle + 0.5) * CONSOLE.width, y: (0.5 - py / CONSOLE.metres) * CONSOLE.height };
        }

        // Ray (XR space) against the panels: the nearest {panel, dist, x, y} in canvas pixels, or null.
        // The wrist menu is on the left hand, so only the right hand's ray can point at it.
        function pick(o, d, hand) {
            const hits = [];
            if (state.console) hits.push({ panel: 'console', ...pickConsole(o, d) });
            if (state.wing && state.wingMatrix) {
                hits.push({ panel: 'wing', ...pickQuad(state.wingMatrix, wingMetres[0], wingMetres[1], WING.width, WING.height, o, d) });
            }
            if (state.robots && state.robotsMatrix) {
                hits.push({ panel: 'robots', ...pickQuad(state.robotsMatrix, robotsMetres[0], robotsMetres[1], ROBOTS.width, ROBOTS.height, o, d) });
            }
            if (state.comms && state.commsMatrix) {
                hits.push({ panel: 'comms', ...pickQuad(state.commsMatrix, commsMetres[0], commsMetres[1], COMMS.width, COMMS.height, o, d) });
            }
            if (state.wrist && state.wristMatrix && hand !== 'left') {
                hits.push({ panel: 'wrist', ...pickQuad(state.wristMatrix, WRIST.metres[0], WRIST.metres[1], WRIST.width, WRIST.height, o, d) });
            }
            return hits.filter(h => h.dist != null).sort((a, b) => a.dist - b.dist)[0] || null;
        }

        const buttonAt = (hit) => hit && panels[hit.panel]?.buttons.find(b => hit.x >= b.x && hit.x <= b.x + b.w && hit.y >= b.y && hit.y <= b.y + b.h);

        // true when the laser has just moved onto a button
        function hover(hit) {
            const b = buttonAt(hit);
            const id = b ? `${hit.panel}:${b.id}` : null;
            const cursor = hit ? `${hit.panel}:${Math.round(hit.x / 4)},${Math.round(hit.y / 4)}` : null;
            const entered = !!id && id !== state.hover;
            if (id !== state.hover || cursor !== state.cursor) dirty(state.hit?.panel, hit?.panel);
            state.hover = id;
            state.cursor = cursor;
            state.hit = hit;
            return entered;
        }

        const click = (hit) => buttonAt(hit)?.action || null;

        function status(text, kind = 'step') {
            if (!text) return;
            state.status = String(text).replace(/\s+/g, ' ');
            state.statusKind = kind;
            state.statusAt = performance.now();
            dirty('console');
        }

        function setBusy(kind, on) {
            if (on) state.busy.add(kind); else state.busy.delete(kind);
            dirty('wing');
        }

        function cursorDot(ctx, id) {
            if (state.hit?.panel !== id) return;
            ctx.beginPath();
            ctx.arc(state.hit.x, state.hit.y, 10, 0, 2 * Math.PI);
            ctx.fillStyle = C.line;
            ctx.globalAlpha = 0.9;
            ctx.fill();
            ctx.globalAlpha = 1;
            ctx.lineWidth = 2;
            ctx.strokeStyle = C.text;
            ctx.stroke();
        }

        const isHot = (id, b) => state.hover === `${id}:${b.id}`;

        function drawConsole(p) {
            const ctx = p.canvas.getContext('2d');
            const W = CONSOLE.width, H = CONSOLE.height, d = state.data || {};
            glassPanel(ctx, W, H, 36);
            // Corner ticks
            ctx.strokeStyle = C.line;
            ctx.lineWidth = 5;
            [[8, 60, 8, 8 + 36, 44, 8], [W - 8, 60, W - 8, 44, W - 44, 8]].forEach(([x1, y1, x2, y2, x3, y3]) => {
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.lineTo(x3, y3);
                ctx.stroke();
            });

            headingTape(ctx, W * 0.3, 22, W * 0.4, 64, deg(d.heading || 0), { numbers: true });
            ctx.fillStyle = C.text;
            ctx.font = `700 34px ${MONO}`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(`${String(Math.round(deg(d.heading || 0)) % 360).padStart(3, '0')}°`, W / 2, 92);

            const block = (x, label, value, color = C.text, align = 'left') => {
                ctx.textAlign = align;
                ctx.fillStyle = C.soft;
                ctx.font = `600 24px ${MONO}`;
                ctx.fillText(label, x, 0);
                ctx.fillStyle = color;
                ctx.font = `700 52px ${MONO}`;
                ctx.fillText(value, x, 30);
            };
            ctx.save();
            ctx.translate(0, 40);
            block(70, 'ALT AGL', fmtDistance(d.agl));
            ctx.translate(0, 110);
            block(70, 'SPEED', fmtSpeed(d.speed || 0));
            ctx.restore();

            const [lat, lon] = d.lat == null ? ['—', '—'] : fmtLatLon(d.lat, d.lon);
            ctx.save();
            ctx.translate(0, 40);
            block(W - 70, (d.body || 'earth').toUpperCase(), lat, C.text, 'right');
            ctx.translate(0, 110);
            block(W - 70, 'POSITION', lon, C.text, 'right');
            ctx.restore();

            // Mode lights
            const lights = [
                ['AUTO', d.auto, C.amber],
                [`LAYERS ${d.layers || 0}`, d.layers > 0, C.green],
                [`TGT ${d.target == null ? '—' : fmtDistance(d.target)}`, d.target != null, C.line],
            ];
            const lw = 200, gap = 18, lx0 = W / 2 - (lights.length * lw + (lights.length - 1) * gap) / 2;
            lights.forEach(([label, on, color], i) => {
                const x = lx0 + i * (lw + gap), y = 148;
                bracketBox(ctx, x, y, lw, 50, 10);
                ctx.fillStyle = on ? color : 'rgba(100, 116, 139, 0.18)';
                ctx.globalAlpha = on ? 0.22 : 1;
                ctx.fill();
                ctx.globalAlpha = 1;
                ctx.lineWidth = 2;
                ctx.strokeStyle = on ? color : C.dim;
                ctx.stroke();
                ctx.fillStyle = on ? color : C.dim;
                ctx.font = `700 24px ${MONO}`;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(label, x + lw / 2, y + 26);
            });

            // Status line
            const age = performance.now() - state.statusAt;
            ctx.globalAlpha = age > 12000 ? 0.45 : 1;
            ctx.fillStyle = state.statusKind === 'error' ? C.red : state.statusKind === 'ai' ? C.text : C.soft;
            ctx.font = `500 28px ${MONO}`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            let text = `> ${state.status}`;
            while (ctx.measureText(text).width > W * 0.56 && text.length > 4) text = text.slice(0, -2);
            if (text !== `> ${state.status}`) text = `${text.slice(0, -1)}…`;
            ctx.fillText(text, W / 2, 238);
            ctx.globalAlpha = 1;

            const defs = [
                { id: 'stop', label: 'STOP', color: C.red, action: 'stop' },
                { id: 'hide', label: 'HIDE', color: C.line, action: 'hide' },
            ];
            if (panels.wing) defs.push({ id: 'layers', label: 'LAYERS', color: C.green, action: 'layers', on: state.wing });
            if (panels.robots) defs.push({ id: 'robots', label: 'ROBOTS', color: C.amber, action: 'robots', on: state.robots });
            if (panels.comms) defs.push({ id: 'pilot', label: 'PILOT', color: C.amber, action: 'pilot', on: state.comms });
            // Between the two hint blocks (each about 360 px from its edge)
            const bgap = 16, bw = Math.min(220, (W - 2 * 450 - (defs.length - 1) * bgap) / defs.length), bh = 66;
            const total = defs.length * bw + (defs.length - 1) * bgap;
            p.buttons = defs.map((b, i) => ({ ...b, x: W / 2 - total / 2 + i * (bw + bgap), y: H - bh - 30, w: bw, h: bh }));
            p.buttons.forEach(b => button(ctx, b, isHot('console', b), Math.min(30, Math.floor(bw / 5))));
            ctx.fillStyle = C.dim;
            ctx.font = `500 20px ${MONO}`;
            ctx.textBaseline = 'middle';
            ctx.textAlign = 'left';
            ctx.fillText(`X cockpit${panels.wing ? ' · Y layers' : ''}`, 70, H - 78);
            ctx.fillText(`B stop${panels.comms ? ' · A pilot' : ''}`, 70, H - 50);
            ctx.textAlign = 'right';
            ctx.fillText('trigger: fly there', W - 70, H - 78);
            ctx.fillText('grip+trigger: orbit', W - 70, H - 50);
            cursorDot(ctx, 'console');
        }

        function drawCompass(p) {
            const ctx = p.canvas.getContext('2d');
            const W = COMPASS.width, H = COMPASS.height;
            ctx.clearRect(0, 0, W, H);
            const g = ctx.createLinearGradient(0, 0, W, 0);
            g.addColorStop(0, 'rgba(6, 14, 28, 0)');
            g.addColorStop(0.2, 'rgba(6, 14, 28, 0.35)');
            g.addColorStop(0.8, 'rgba(6, 14, 28, 0.35)');
            g.addColorStop(1, 'rgba(6, 14, 28, 0)');
            ctx.fillStyle = g;
            ctx.fillRect(0, 0, W, H);
            ctx.globalAlpha = 0.75;
            headingTape(ctx, 0, 4, W, H - 8, state.compassHeading || 0, { span: 120 });
            ctx.globalAlpha = 1;
        }

        function drawWing(p) {
            const ctx = p.canvas.getContext('2d');
            const W = WING.width, H = WING.height;
            glassPanel(ctx, W, H, 28);
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = C.line;
            ctx.font = `700 32px ${MONO}`;
            ctx.fillText('DATA LAYERS', 40, 48);
            ctx.fillStyle = C.soft;
            ctx.font = `500 20px ${MONO}`;
            ctx.fillText('around the view · trigger toggles', 40, 82);
            const close = { id: 'close', label: 'CLOSE', color: C.line, action: 'layers', x: W - 196, y: 26, w: 156, h: 52 };
            const buttons = [close];
            if (panels.robots) buttons.push({ id: 'tab', label: 'ROBOTS', color: C.amber, action: 'robots', x: W - 372, y: 26, w: 156, h: 52 });
            const shown = new Set(hud?.shown() || []);
            const colW = (W - 80 - 30) / 2;
            columns.forEach((col, ci) => {
                const x = 40 + ci * (colW + 30);
                let y = WING.top;
                col.forEach(([title, rows]) => {
                    ctx.fillStyle = C.dim;
                    ctx.font = `600 20px ${MONO}`;
                    ctx.textAlign = 'left';
                    const label = title.toUpperCase(), tw = ctx.measureText(label).width;
                    ctx.fillText(label, x, y + WING.line / 2 + 4);
                    ctx.fillRect(x + tw + 12, y + WING.line / 2 + 4, colW - tw - 12, 1);
                    y += WING.line;
                    rows.forEach((r) => {
                        const b = { id: r.kind, x, y: y + 2, w: colW, h: WING.line - 4,
                            action: r.locked ? { locked: r.kind, title: r.title } : { layer: r.kind, title: r.title } };
                        buttons.push(b);
                        const on = shown.has(r.kind), busy = state.busy.has(r.kind), hot = isHot('wing', b);
                        if (hot) {
                            ctx.fillStyle = 'rgba(56, 189, 248, 0.18)';
                            ctx.fillRect(b.x - 6, b.y, b.w + 12, b.h);
                        }
                        const box = 18, bx = x + 4, by = y + (WING.line - box) / 2;
                        ctx.lineWidth = 2;
                        ctx.strokeStyle = r.locked ? C.dim : on ? C.green : C.line;
                        ctx.strokeRect(bx, by, box, box);
                        if (on) {
                            ctx.fillStyle = C.green;
                            ctx.fillRect(bx + 4, by + 4, box - 8, box - 8);
                        }
                        ctx.fillStyle = r.locked ? C.dim : hot || on ? C.text : C.soft;
                        ctx.font = `500 24px ${MONO}`;
                        ctx.textAlign = 'left';
                        ctx.fillText(r.title, x + 36, y + WING.line / 2 + 1);
                        const tag = busy ? ['LOADING', C.amber] : r.locked ? ['SIGN IN', C.dim] : on ? ['ON', C.green] : null;
                        if (tag) {
                            ctx.fillStyle = tag[1];
                            ctx.font = `700 18px ${MONO}`;
                            ctx.textAlign = 'right';
                            ctx.fillText(tag[0], x + colW, y + WING.line / 2 + 1);
                        }
                        y += WING.line;
                    });
                });
            });
            buttons.filter(b => b.id === 'close' || b.id === 'tab').forEach(b => button(ctx, b, isHot('wing', b), 24));
            p.buttons = buttons;
            cursorDot(ctx, 'wing');
        }

        // Drawn when the selected robot's camera frame has loaded
        function loadFrame(v) {
            const seq = v?.frame?.seq;
            if (!v || seq == null) {
                state.frame = null;
                return;
            }
            if (state.frame?.id === v.id && state.frame.seq === seq) return;
            const img = new Image();
            const f = { id: v.id, seq, img, ready: false };
            img.onload = () => {
                if (state.frame !== f) return;
                f.ready = true;
                dirty('robots');
            };
            img.src = `/label/api/vehicles/${encodeURIComponent(v.id)}/frame.jpg?seq=${seq}`;
            if (!state.frame || state.frame.id !== v.id || state.frame.ready) state.frame = f;
        }

        function drawRobots(p) {
            const ctx = p.canvas.getContext('2d');
            const W = ROBOTS.width, H = ROBOTS.height;
            glassPanel(ctx, W, H, 28);
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = C.amber;
            ctx.font = `700 32px ${MONO}`;
            ctx.fillText('ROBOTS', 40, 48);
            ctx.fillStyle = C.soft;
            ctx.font = `500 20px ${MONO}`;
            ctx.fillText('live fleet · trigger a robot, then fly, ride or chase', 40, 82);
            const buttons = [
                { id: 'close', label: 'CLOSE', color: C.line, action: 'robots', x: W - 196, y: 26, w: 156, h: 52 },
            ];
            if (panels.wing) buttons.push({ id: 'tab', label: 'LAYERS', color: C.green, action: 'layers', x: W - 372, y: 26, w: 156, h: 52 });

            const { list, error } = hud.vehicles();
            const following = hud.following();
            const d = state.data || {};
            const listW = 560, top = 112;
            if (!list.length) {
                ctx.fillStyle = error ? C.red : C.dim;
                ctx.font = `500 24px ${MONO}`;
                wrap(ctx, error || 'No robot is reporting its position right now.', listW).forEach((line, i) => ctx.fillText(line, 40, top + 20 + i * 34));
            }
            const sel = list.find(v => v.id === state.robot) || list.find(v => v.id === following?.id) || list[0];
            if (sel) state.robot = sel.id;
            list.slice(0, ROBOTS.rows).forEach((v, i) => {
                const y = top + i * ROBOTS.row;
                const b = { id: `r:${v.id}`, x: 30, y, w: listW + 10, h: ROBOTS.row - 6, action: { robot: v.id } };
                buttons.push(b);
                const isSel = sel?.id === v.id, hot = isHot('robots', b), live = v.age_sec < 3;
                if (isSel || hot) {
                    ctx.fillStyle = isSel ? 'rgba(251, 191, 36, 0.14)' : 'rgba(56, 189, 248, 0.14)';
                    ctx.fillRect(b.x, b.y, b.w, b.h);
                }
                if (isSel) {
                    ctx.fillStyle = C.amber;
                    ctx.fillRect(b.x, b.y, 4, b.h);
                }
                ctx.textAlign = 'left';
                ctx.fillStyle = live ? C.text : C.dim;
                ctx.font = `700 26px ${MONO}`;
                ctx.fillText(v.name || v.id, 46, y + 18);
                ctx.fillStyle = C.soft;
                ctx.font = `500 18px ${MONO}`;
                const state2 = [v.platform, v.armed ? 'armed' : v.landed ? 'landed' : null,
                    Number.isFinite(v.speed_mps) ? fmtSpeed(v.speed_mps) : null].filter(Boolean).join(' · ');
                ctx.fillText(state2, 46, y + 42);
                ctx.textAlign = 'right';
                ctx.fillStyle = following?.id === v.id ? C.line : live ? C.green : C.dim;
                ctx.font = `700 18px ${MONO}`;
                ctx.fillText(following?.id === v.id ? (following.view === 'chase' ? 'CHASING' : 'RIDING') : fmtAge(v.age_sec), listW + 30, y + 18);
                if (d.lat != null) {
                    ctx.fillStyle = C.soft;
                    ctx.font = `500 18px ${MONO}`;
                    ctx.fillText(fmtDistance(distanceM(d.lat, d.lon, v.lat, v.lon)), listW + 30, y + 42);
                }
            });

            // The selected robot's camera
            const fx = 630, fw = W - fx - 40, fh = Math.round(fw * 9 / 16);
            bracketBox(ctx, fx, top, fw, fh, 14);
            ctx.fillStyle = 'rgba(2, 6, 23, 0.9)';
            ctx.fill();
            ctx.lineWidth = 2;
            ctx.strokeStyle = C.dim;
            ctx.stroke();
            loadFrame(sel);
            if (state.frame?.ready && state.frame.id === sel?.id) {
                const img = state.frame.img, k = Math.min(fw / img.width, fh / img.height);
                const iw = img.width * k, ih = img.height * k;
                ctx.drawImage(img, fx + (fw - iw) / 2, top + (fh - ih) / 2, iw, ih);
            } else {
                ctx.fillStyle = C.dim;
                ctx.font = `500 20px ${MONO}`;
                ctx.textAlign = 'center';
                ctx.fillText(sel?.frame ? 'loading camera…' : 'no camera feed', fx + fw / 2, top + fh / 2);
            }
            if (sel) {
                ctx.textAlign = 'left';
                ctx.fillStyle = C.soft;
                ctx.font = `500 18px ${MONO}`;
                const [la, lo] = fmtLatLon(sel.lat, sel.lon);
                ctx.fillText(`${(sel.name || sel.id).toUpperCase()} · ${la} ${lo}`, fx, top + fh + 24);
                if (Number.isFinite(sel.up_m)) ctx.fillText(`${fmtDistance(sel.up_m)} above take-off · heading ${Math.round(((sel.heading_deg || 0) + 360) % 360)}°`, fx, top + fh + 50);
            }

            // Commands for the selected robot
            const cmds = [
                { id: 'fly', label: 'FLY TO', color: C.line },
                { id: 'ride', label: 'RIDE', color: C.amber },
                { id: 'chase', label: 'CHASE', color: C.amber },
                { id: 'release', label: 'RELEASE', color: C.red, on: !!following },
            ];
            const g = 18, bw = (W - 60 - (cmds.length - 1) * g) / cmds.length;
            cmds.forEach((c, i) => {
                const b = { ...c, x: 30 + i * (bw + g), y: H - 96, w: bw, h: 64, on: c.on ?? !!sel,
                    action: sel || c.id === 'release' ? { robotCmd: c.id, id: sel?.id, name: sel?.name || sel?.id } : null };
                buttons.push(b);
                button(ctx, b, isHot('robots', b), 28);
            });
            buttons.filter(b => b.id === 'close' || b.id === 'tab').forEach(b => button(ctx, b, isHot('robots', b), 24));
            p.buttons = buttons.filter(b => b.action);
            cursorDot(ctx, 'robots');
        }

        function drawVignette(p) {
            const ctx = p.canvas.getContext('2d');
            const W = VIGNETTE.width, H = VIGNETTE.height, a = state.vignette;
            ctx.clearRect(0, 0, W, H);
            // Clear within about 25 degrees of the gaze, darkest past the lens edges
            const g = ctx.createRadialGradient(W / 2, H / 2, W * 0.12, W / 2, H / 2, W * 0.42);
            g.addColorStop(0, 'rgba(0, 0, 0, 0)');
            g.addColorStop(0.55, `rgba(0, 0, 0, ${(a * 0.6).toFixed(3)})`);
            g.addColorStop(1, `rgba(0, 0, 0, ${a.toFixed(3)})`);
            ctx.fillStyle = g;
            ctx.fillRect(0, 0, W, H);
            state.vignetteDrawn = a;
        }

        function drawWrist(p) {
            const ctx = p.canvas.getContext('2d');
            const W = WRIST.width, H = WRIST.height;
            glassPanel(ctx, W, H, 24);
            const defs = [
                { id: 'cockpit', label: 'COCKPIT', color: C.line, action: 'cockpit', on: state.console },
                { id: 'layers', label: 'LAYERS', color: C.green, action: 'layers', on: state.wing, needs: 'wing' },
                { id: 'robots', label: 'ROBOTS', color: C.amber, action: 'robots', on: state.robots, needs: 'robots' },
                { id: 'pilot', label: 'PILOT', color: C.amber, action: 'pilot', on: state.comms, needs: 'comms' },
                { id: 'type', label: 'TYPE', color: C.amber, action: 'type', on: state.keyboard, needs: 'comms' },
                { id: 'centre', label: 'CENTRE', color: C.line, action: 'centre', on: false },
                { id: 'sound', label: state.sound ? 'SOUND' : 'MUTED', color: C.line, action: 'sound', on: state.sound },
                { id: 'stop', label: 'STOP', color: C.red, action: 'stop' },
            ].filter(b => !b.needs || panels[b.needs]);
            const cols = defs.length > 6 ? 4 : defs.length > 4 ? 3 : 2, rows = Math.ceil(defs.length / cols);
            const m = 30, gap = 20, bw = (W - 2 * m - (cols - 1) * gap) / cols, bh = (H - 2 * m - (rows - 1) * gap) / rows;
            p.buttons = defs.map((b, i) => ({ ...b, x: m + (i % cols) * (bw + gap), y: m + Math.floor(i / cols) * (bh + gap), w: bw, h: bh }));
            p.buttons.forEach(b => button(ctx, b, isHot('wrist', b), Math.min(40, Math.floor(bw / 5.2))));
            cursorDot(ctx, 'wrist');
        }

        const LOG_COLORS = { user: C.amber, ai: C.text, step: C.soft, error: C.red, robot: C.amber };

        function drawComms(p) {
            const ctx = p.canvas.getContext('2d');
            const W = COMMS.width, H = COMMS.height;
            glassPanel(ctx, W, H, 28);
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = C.amber;
            ctx.font = `700 32px ${MONO}`;
            ctx.fillText('AI PILOT', 40, 48);
            ctx.fillStyle = C.soft;
            ctx.font = `500 20px ${MONO}`;
            ctx.fillText(state.asking ? 'thinking…' : 'TYPE opens the keyboard; its mic dictates', 40, 82);
            const close = { id: 'close', label: 'CLOSE', color: C.line, action: 'pilot', x: W - 196, y: 26, w: 156, h: 52 };

            // Log, newest at the bottom
            const top = 108, bottom = H - 262, x = 40, w = W - 80;
            ctx.strokeStyle = 'rgba(56, 189, 248, 0.25)';
            ctx.lineWidth = 1;
            ctx.strokeRect(x - 10, top - 8, w + 20, bottom - top + 16);
            ctx.font = `500 24px ${MONO}`;
            const lines = [];
            for (let i = state.log.length - 1; i >= 0 && lines.length * COMMS.line < bottom - top; i--) {
                const r = state.log[i];
                const prefix = r.kind === 'user' ? '> ' : r.kind === 'ai' ? '◆ ' : r.kind === 'error' ? '! ' : '  ';
                const wrapped = wrap(ctx, `${prefix}${r.text}`, w);
                for (let j = wrapped.length - 1; j >= 0; j--) lines.unshift([wrapped[j], LOG_COLORS[r.kind] || C.soft]);
            }
            const fit = Math.floor((bottom - top) / COMMS.line);
            const shown = lines.slice(-fit);
            if (!shown.length) {
                ctx.fillStyle = C.dim;
                ctx.fillText('Ask the pilot to fly, explain what you see, or show layers.', x, top + COMMS.line / 2);
            }
            shown.forEach(([text, color], i) => {
                ctx.fillStyle = color;
                ctx.fillText(text, x, top + i * COMMS.line + COMMS.line / 2);
            });

            // Typed line
            const iy = H - 240, ih = 60;
            bracketBox(ctx, x - 10, iy, w + 20, ih, 10);
            ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';
            ctx.fill();
            ctx.lineWidth = state.keyboard ? 3 : 2;
            ctx.strokeStyle = state.keyboard ? C.amber : C.dim;
            ctx.stroke();
            ctx.font = `500 26px ${MONO}`;
            let typed = state.typed;
            while (typed && ctx.measureText(`> ${typed}_`).width > w - 20) typed = typed.slice(1);
            ctx.fillStyle = state.typed ? C.text : C.dim;
            ctx.fillText(state.typed ? `> ${typed}${state.keyboard ? '_' : ''}` : '> press TYPE, then type or tap the mic', x + 6, iy + ih / 2);

            // Keyboard buttons, then quick prompts
            const row = (defs, y, h, font) => {
                const g = 18, bw = (w + 20 - (defs.length - 1) * g) / defs.length;
                return defs.map((b, i) => {
                    const btn = { ...b, x: x - 10 + i * (bw + g), y, w: bw, h };
                    button(ctx, btn, isHot('comms', btn), font);
                    return btn;
                });
            };
            const keys = row([
                { id: 'type', label: 'TYPE', color: C.amber, action: 'type', on: state.keyboard },
                { id: 'send', label: 'SEND', color: C.green, action: 'send', on: !!state.typed.trim() && !state.asking },
                { id: 'clear', label: 'CLEAR', color: C.line, action: 'clear', on: !!state.typed },
            ], H - 166, 60, 28);
            const quick = row(QUICK_PROMPTS.map(([label, text], i) => ({
                id: `q${i}`, label, color: C.line, action: { prompt: text }, on: !state.asking,
            })), H - 90, 56, 22);
            button(ctx, close, isHot('comms', close), 24);
            p.buttons = [close, ...keys, ...quick];
            cursorDot(ctx, 'comms');
        }

        function upload(layer, cnv, frame) {
            const sub = binding.getSubImage(layer, frame);
            gl.bindTexture(gl.TEXTURE_2D, sub.colorTexture);
            gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
            gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
            gl.texSubImage2D(gl.TEXTURE_2D, 0, sub.viewport.x, sub.viewport.y, cnv.width, cnv.height, gl.RGBA, gl.UNSIGNED_BYTE, cnv);
            gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            gl.bindTexture(gl.TEXTURE_2D, null);
        }

        const visible = (id) => (id === 'console' || id === 'compass' ? state.console : state[id]);

        // Per XR frame: new readings, then redraw what changed (each panel at most every
        // REDRAW_MS, or at once when the compositor lost its picture)
        function update(frame, head, data) {
            const prev = state.data;
            state.data = data;
            if (!prev || Math.round(prev.agl) !== Math.round(data.agl) || Math.round(deg(prev.heading)) !== Math.round(deg(data.heading)) ||
                prev.auto !== data.auto || prev.layers !== data.layers || Math.round(prev.speed) !== Math.round(data.speed) ||
                (prev.target == null) !== (data.target == null) || Math.round(prev.target / 10) !== Math.round(data.target / 10)) {
                dirty('console');
            }
            const heading = Math.round(deg(data.heading) * 2) / 2;
            if (heading !== state.compassHeading) {
                state.compassHeading = heading;
                dirty('compass');
            }
            const asking = !!pilot?.busy();
            if (asking !== state.asking) {
                state.asking = asking;
                dirty('comms');
            }
            if (panels.robots && state.robots) {
                const { list, error } = hud.vehicles();
                const f = hud.following();
                const key = JSON.stringify([error, f, list.map(v => [v.id, Math.round(v.age_sec), v.lat?.toFixed(5), v.lon?.toFixed(5),
                    Math.round(v.speed_mps || 0), v.frame?.seq]), Math.round(data.lat * 1e3), Math.round(data.lon * 1e3)]);
                if (key !== state.robotsKey) {
                    state.robotsKey = key;
                    dirty('robots');
                }
            }
            const shownKey = `${(hud?.shown() || []).join()}|${[...state.busy].join()}`;
            if (shownKey !== state.shownKey) {
                state.shownKey = shownKey;
                dirty('wing');
            }
            const now = performance.now();
            Object.values(panels).forEach((p) => {
                if (!p.layer || !visible(p.id)) return;
                const lost = p.layer.needsRedraw;
                if (!lost && (!p.dirty || now - p.drawnAt < REDRAW_MS)) return;
                p.draw(p);
                upload(p.layer, p.canvas, frame);
                p.dirty = false;
                p.drawnAt = now;
            });
        }

        // 0 (off) to 1 (darkest), redrawn in steps of 0.05
        function setVignette(level) {
            const a = Math.round(Math.max(0, Math.min(1, level)) * 20) / 20;
            if (a === state.vignette) return;
            const was = state.vignette > 0.02;
            state.vignette = a;
            dirty('vignette');
            if (was !== a > 0.02) presentNow();
        }

        function destroy() {
            state.console = state.wing = state.robots = state.comms = state.wrist = false;
            Object.values(panels).forEach(p => p.layer?.destroy?.());
        }

        const cockpit = {
            pick, hover, click, status, setBusy, track, update, destroy,
            busy: (kind) => state.busy.has(kind),
            toggle: (head) => setConsole(!state.console, head),
            hide: () => setConsole(false),
            toggleWing: (head) => setWing(!state.wing, head),
            toggleRobots: (head) => setSide('robots', !state.robots, head),
            selectRobot: (id) => { state.robot = id; dirty('robots'); },
            vignette: setVignette,
            sound: (on) => { state.sound = on; dirty('wrist'); },
            toggleComms: (head) => setComms(!state.comms, head),
            showComms: (head) => state.comms || setComms(true, head),
            pilotEvent,
            typed: (text) => { state.typed = text; dirty('comms'); },
            keyboard: (on) => { state.keyboard = on; dirty('comms', 'wrist'); },
            centre: (head) => { place(head); setConsole(true); },
            visible: (id = 'console') => visible(id),
            canvases: Object.fromEntries(Object.entries(panels).map(([id, p]) => [id, p.canvas])),
        };
        setConsole(true, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
        return cockpit;
    }

    window.DeepGISCockpit = { create };
})();
