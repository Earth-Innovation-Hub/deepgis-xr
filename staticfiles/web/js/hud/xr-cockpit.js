// VR cockpit for hud/xr.js: panels drawn on 2D canvases and shown as WebXR compositor
// layers, so the headset draws them sharp and at its own frame rate whatever the globe's.
// - Instrument console: a curved (cylinder) layer below eye level, fixed in front of the
//   craft and turning only with it; X re-centres it on where you face or hides it.
// - Compass: a faint quad locked to the head, at the top of the view.
// The laser (hud/xr.js) hovers and clicks the console's buttons through pick/hover/click.
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

    function create({ binding, gl, space, viewerSpace, present }) {
        const consoleCanvas = canvas(CONSOLE.width, CONSOLE.height);
        const compassCanvas = canvas(COMPASS.width, COMPASS.height);
        const consoleLayer = binding.createCylinderLayer({
            space, viewPixelWidth: CONSOLE.width, viewPixelHeight: CONSOLE.height, layout: 'mono',
            radius: CONSOLE.radius, centralAngle: CONSOLE.angle, aspectRatio: CONSOLE.width / CONSOLE.height,
        });
        const compassLayer = binding.createQuadLayer({
            space: viewerSpace, viewPixelWidth: COMPASS.width, viewPixelHeight: COMPASS.height, layout: 'mono',
            width: COMPASS.metres[0], height: COMPASS.metres[1],
            transform: new XRRigidTransform({ x: 0, y: COMPASS.y, z: COMPASS.z }),
        });
        const state = {
            visible: false, placed: false, yaw: 0, centre: { x: 0, y: 0, z: 0 },
            hover: null, cursor: null, status: 'Cockpit online', statusKind: 'step', statusAt: performance.now(),
            data: null, dirty: true, compassDirty: true, drawnAt: 0, compassHeading: null, buttons: [],
        };

        // Below eye level, straight ahead of the head's yaw (counter-clockwise from -z)
        function place(m) {
            state.yaw = Math.atan2(m[8], m[10]);
            state.centre = { x: m[12], y: m[13] - CONSOLE.drop, z: m[14] };
            const half = state.yaw / 2;
            consoleLayer.transform = new XRRigidTransform(state.centre, { x: 0, y: Math.sin(half), z: 0, w: Math.cos(half) });
            state.placed = true;
            state.dirty = true;
        }

        function show(m) {
            if (m) place(m);
            state.visible = true;
            state.dirty = state.compassDirty = true;
            present([consoleLayer, compassLayer]);
        }

        function hide() {
            state.visible = false;
            state.hover = state.cursor = null;
            present([]);
        }

        // Ray (XR space) against the console's arc: canvas pixel and distance, or null
        function pick(o, d) {
            if (!state.visible) return null;
            const s = Math.sin(state.yaw), c = Math.cos(state.yaw);
            const lx = o[0] - state.centre.x, ly = o[1] - state.centre.y, lz = o[2] - state.centre.z;
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
            return {
                dist: t,
                x: (theta / CONSOLE.angle + 0.5) * CONSOLE.width,
                y: (0.5 - py / CONSOLE.metres) * CONSOLE.height,
            };
        }

        const buttonAt = (hit) => hit && state.buttons.find(b => hit.x >= b.x && hit.x <= b.x + b.w && hit.y >= b.y && hit.y <= b.y + b.h);

        function hover(hit) {
            const id = buttonAt(hit)?.id || null;
            const cursor = hit ? [Math.round(hit.x / 4), Math.round(hit.y / 4)].join() : null;
            if (id !== state.hover || cursor !== state.cursor) state.dirty = true;
            state.hover = id;
            state.cursor = cursor;
            state.hit = hit;
        }

        const click = (hit) => buttonAt(hit)?.id || null;

        function status(text, kind = 'step') {
            if (!text) return;
            state.status = String(text).replace(/\s+/g, ' ');
            state.statusKind = kind;
            state.statusAt = performance.now();
            state.dirty = true;
        }

        function drawConsole() {
            const ctx = consoleCanvas.getContext('2d');
            const W = CONSOLE.width, H = CONSOLE.height, d = state.data || {};
            ctx.clearRect(0, 0, W, H);
            bracketBox(ctx, 8, 8, W - 16, H - 16, 36);
            ctx.fillStyle = C.glass;
            ctx.fill();
            ctx.lineWidth = 3;
            ctx.strokeStyle = C.glassEdge;
            ctx.stroke();
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

            // Buttons
            state.buttons = [
                { id: 'stop', label: 'STOP', color: C.red },
                { id: 'hide', label: 'HIDE', color: C.line },
            ].map((b, i, all) => {
                const bw = 220, bh = 66, total = all.length * bw + (all.length - 1) * 24;
                return { ...b, x: W / 2 - total / 2 + i * (bw + 24), y: H - bh - 30, w: bw, h: bh };
            });
            state.buttons.forEach((b) => {
                const hot = state.hover === b.id;
                bracketBox(ctx, b.x, b.y, b.w, b.h, 14);
                ctx.fillStyle = b.color;
                ctx.globalAlpha = hot ? 0.4 : 0.14;
                ctx.fill();
                ctx.globalAlpha = 1;
                ctx.lineWidth = hot ? 4 : 2;
                ctx.strokeStyle = b.color;
                ctx.stroke();
                ctx.fillStyle = hot ? C.text : b.color;
                ctx.font = `700 30px ${MONO}`;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(b.label, b.x + b.w / 2, b.y + b.h / 2 + 1);
            });
            ctx.fillStyle = C.dim;
            ctx.font = `500 20px ${MONO}`;
            ctx.textAlign = 'left';
            ctx.fillText('X cockpit · B stop', 70, H - 78);
            ctx.fillText('trigger fly · grip+trigger orbit', 70, H - 50);

            if (state.hit) {
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
        }

        function drawCompass(heading) {
            const ctx = compassCanvas.getContext('2d');
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
            headingTape(ctx, 0, 4, W, H - 8, heading, { span: 120 });
            ctx.globalAlpha = 1;
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

        // Per XR frame: new readings, then redraw what changed (at most every REDRAW_MS)
        function update(frame, head, data) {
            if (!state.visible) return;
            const prev = state.data;
            state.data = data;
            const now = performance.now();
            if (!prev || Math.round(prev.agl) !== Math.round(data.agl) || Math.round(deg(prev.heading)) !== Math.round(deg(data.heading)) ||
                prev.auto !== data.auto || prev.layers !== data.layers || Math.round(prev.speed) !== Math.round(data.speed) ||
                (prev.target == null) !== (data.target == null) || Math.round(prev.target / 10) !== Math.round(data.target / 10)) {
                state.dirty = true;
            }
            const heading = Math.round(deg(data.heading) * 2) / 2;
            if (heading !== state.compassHeading) state.compassDirty = true;
            if (now - state.drawnAt < REDRAW_MS && !consoleLayer.needsRedraw && !compassLayer.needsRedraw) return;
            if (state.dirty || consoleLayer.needsRedraw) {
                drawConsole();
                upload(consoleLayer, consoleCanvas, frame);
                state.dirty = false;
                state.drawnAt = now;
            }
            if (state.compassDirty || compassLayer.needsRedraw) {
                drawCompass(heading);
                upload(compassLayer, compassCanvas, frame);
                state.compassHeading = heading;
                state.compassDirty = false;
                state.drawnAt = now;
            }
        }

        function toggle(head) {
            if (state.visible) hide();
            else show(head);
        }

        function destroy() {
            state.visible = false;
            consoleLayer.destroy?.();
            compassLayer.destroy?.();
        }

        const cockpit = { pick, hover, click, status, update, toggle, hide, destroy, visible: () => state.visible,
            canvases: { console: consoleCanvas, compass: compassCanvas } };
        show([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
        return cockpit;
    }

    window.DeepGISCockpit = { create };
})();
