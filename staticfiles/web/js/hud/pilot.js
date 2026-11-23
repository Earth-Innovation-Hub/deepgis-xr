// DeepGIS AI pilot chat, shared by the Earth, Moon and planet viewers.
// POST /label/api/pilot/ turns a request into actions (goto, orbit, adjust, takeoff, land,
// look, stop, wait, show_layer, hide_layer, describe_view, check_view, follow_vehicle, find_objects, show_scene_graphs); they
// run in order through window.DeepGISActions (hud/actions.js), which reports into this chat.
// A plan that ends in check_view is a task with a goal for the view: when the vision model
// says it is not met yet, the chat asks the planner again with what it saw ("Goal check"),
// up to GOAL_ROUNDS times, until it is met, the user says something else or presses Stop.
// For superusers the server may also return robot_command, a command for one of the lab's
// robots: it does not run with the plan but becomes a card in the chat, and is posted to
// /label/api/pilot/robot-command/ only when the user presses Send (Preview plans it only).
// window.DeepGISPilot lets other panels (the VR comms panel, hud/xr-cockpit.js) ask through
// the same path and mirror the chat: on(fn) gets {type: 'add', id, kind, text} for each line
// and {type: 'remove', id} when a passing line ("Thinking...") goes. Robot commands are
// mirrored as a notice only; they are sent from the card in this chat.
(function initAiPilot() {
    const panel = document.getElementById('pilotPanel');
    const toggleBtn = document.getElementById('hudPilotBtn');
    const log = document.getElementById('pilotLog');
    const form = document.getElementById('pilotForm');
    const input = document.getElementById('pilotInput');
    const modelSelect = document.getElementById('pilotModel');
    const sendBtn = document.getElementById('pilotSendBtn');
    const stopBtn = document.getElementById('pilotStopBtn');
    const hud = window.DeepGISActions;
    if (!panel || !toggleBtn || !form || !hud) return;

    const history = [];
    const body = hud.body;
    const csrfToken = hud.csrfToken;
    const getViewer = () => window.AppState?.viewer || window.viewer;

    function modelLabel(name) {
        const id = name.toLowerCase();
        if (id.includes('gemma-4')) return 'Gemma 4';
        if (id.includes('gemma')) return 'Gemma';
        if (id.includes('robot')) return 'Qwen robot';
        const size = id.match(/(\d+(?:\.\d+)?)b/);
        return size ? `Qwen ${size[1].replace(/\.0$/, '')}B` : 'Qwen';
    }

    async function loadModels() {
        if (!modelSelect) return;
        try {
            const resp = await fetch('/label/api/pilot/models/', { credentials: 'same-origin' });
            if (!resp.ok) return;
            const data = await resp.json();
            const models = [...new Set(data.models || [])];
            if (!models.length) return;
            const labels = models.map(modelLabel);
            modelSelect.replaceChildren(...models.map((name, i) => {
                const option = document.createElement('option');
                option.value = name;
                option.title = name;
                option.textContent = labels.filter(label => label === labels[i]).length > 1
                    ? `${labels[i]} · ${name.split('/').pop()}` : labels[i];
                return option;
            }));
            if (data.default_model) modelSelect.value = data.default_model;
            const selected = modelSelect.selectedOptions[0];
            modelSelect.title = selected ? selected.title || selected.textContent : 'AI model';
        } catch (_) {
            // Keep the server-default Gemma option when discovery is unavailable.
        }
    }

    toggleBtn.addEventListener('click', () => {
        const open = panel.classList.toggle('visible');
        toggleBtn.classList.toggle('active', open);
        if (open) input.focus();
    });
    document.getElementById('pilotCloseBtn').addEventListener('click', () => {
        panel.classList.remove('visible');
        toggleBtn.classList.remove('active');
    });

    const listeners = new Set();
    const recent = [];
    let seq = 0;
    function emit(e) {
        if (e.type === 'add') {
            recent.push(e);
            recent.splice(0, Math.max(0, recent.length - 40));
        } else {
            const i = recent.findIndex(r => r.id === e.id);
            if (i >= 0) recent.splice(i, 1);
        }
        listeners.forEach((fn) => {
            try { fn(e); } catch (err) { console.error('[AI Pilot] listener failed', err); }
        });
    }
    const announce = (kind, text) => {
        const id = ++seq;
        emit({ type: 'add', id, kind, text: String(text ?? '') });
        return id;
    };

    const base = hud.logSink(log);
    const out = {
        ...base,
        msg(kind, text, href) {
            const el = base.msg(kind, text, href);
            const id = announce(kind, text);
            const remove = el.remove.bind(el);
            el.remove = () => { remove(); emit({ type: 'remove', id }); };
            return el;
        },
        // The chart stays on the page; listeners (the VR comms panel) get its text
        histogram(hist, label, text) {
            const el = base.histogram(hist, label);
            announce('step', text);
            return el;
        },
        // Follow-up questions ("what is the dark patch on the left?") can refer to it
        described(data) {
            history.push({ role: 'assistant',
                           content: `What I saw in the view: ${[data.summary, ...(data.observations || [])].join(' ')}`.slice(0, 2000) });
            history.splice(0, Math.max(0, history.length - 8));
        },
        // Measured results ("what is the median house size?" can refer to them)
        noted(text) {
            history.push({ role: 'assistant', content: String(text).slice(0, 2000) });
            history.splice(0, Math.max(0, history.length - 8));
        },
        goal: onGoalChecked,
    };

    // The task the planner is working on: { goal, rounds } while check_view keeps failing
    const GOAL_ROUNDS = 3;
    let task = null;

    function onGoalChecked(r) {
        if (r.met) { task = null; return; }
        if (!task || task.goal !== r.goal) task = { goal: r.goal, rounds: 0 };
        if (task.rounds >= GOAL_ROUNDS) {
            addMsg('step', `Stopped trying after ${GOAL_ROUNDS} corrections; tell me how to change the view`);
            task = null;
            return;
        }
        task.rounds += 1;
        const clip = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
        const message = `Goal check ${task.rounds} of ${GOAL_ROUNDS}: "${clip(r.goal, 120)}" is not met yet. ` +
            `The camera shows: ${clip(r.seen || 'nothing relevant', 220)}` +
            `${r.suggestion ? ` Suggested change: ${clip(r.suggestion, 120)}` : ''}`;
        ask(message, { auto: `Correcting the view (${task.rounds} of ${GOAL_ROUNDS})` });
    }
    const addMsg = out.msg;

    const ROBOT_COMMAND_URL = '/label/api/pilot/robot-command/';
    const ROBOT_COMMAND_NAMES = { instruct: 'instruction', return_home: 'return home and land', land: 'land now' };

    const CREATE_TWIN_URL = '/label/api/pilot/create-twin/';
    const CREATE_TWIN_FIELDS = { vehicle_class: 'kestrel', count: 1, width_m: 150, length_m: 150 };

    function patchMetres(value, fallback) {
        const n = Number(value);
        const side = Number.isFinite(n) ? n : fallback;
        return Math.min(400, Math.max(20, side));
    }

    const MOON_DEM_GRID = 65;

    function terrainPoint(view) {
        const t = view && view.target;
        if (!t || !Number.isFinite(t.lat) || !Number.isFinite(t.lon)) {
            throw new Error('No terrain under the crosshair; tilt the camera toward the ground.');
        }
        return t;
    }

    function lookAtAndBbox(widthM, lengthM) {
        const width = patchMetres(widthM, CREATE_TWIN_FIELDS.width_m);
        const length = patchMetres(lengthM, CREATE_TWIN_FIELDS.length_m);
        return hud.currentView().then(async (view) => {
            const t = terrainPoint(view);
            const look = {
                lat: t.lat, lon: t.lon, elev_m: Number.isFinite(t.elev_m) ? t.elev_m : 0,
            };
            if (body !== 'moon') {
                const dem = await sampleDem(look, width, length);
                const dlat = (length / 2) / 111320;
                const cos = Math.max(0.05, Math.abs(Math.cos(t.lat * Math.PI / 180)));
                const dlon = (width / 2) / (111320 * cos);
                return {
                    body: 'earth',
                    dem,
                    look_at: look,
                    bbox: { west: t.lon - dlon, south: t.lat - dlat, east: t.lon + dlon, north: t.lat + dlat },
                    width_m: width,
                    length_m: length,
                };
            }
            const dem = await sampleDem(look, width, length);
            const metres = 1737400 * Math.PI / 180;
            const dlat = (length / 2) / metres;
            const cos = Math.max(0.001, Math.abs(Math.cos(t.lat * Math.PI / 180)));
            const dlon = (width / 2) / (metres * cos);
            return {
                body: 'moon',
                dem,
                look_at: look,
                bbox: { west: t.lon - dlon, south: t.lat - dlat, east: t.lon + dlon, north: t.lat + dlat },
                width_m: width,
                length_m: length,
            };
        });
    }

    // East-north grid on the viewer's ellipsoid. Row 0 is the north edge.
    // Heights are metres relative to the look-at. On Earth this is Cesium World
    // Terrain, which includes USGS 3DEP where that survey covers the patch.
    // On the Moon it is the LOLA terrain already drawn on the globe.
    async function sampleDem(look, width, length) {
        const viewer = getViewer();
        const provider = viewer && viewer.terrainProvider;
        const place = body === 'moon' ? 'Lunar terrain' : 'Terrain';
        if (!provider || provider instanceof Cesium.EllipsoidTerrainProvider) {
            throw new Error(`${place} has not loaded. Wait for the ground to draw, then confirm again.`);
        }
        const ellipsoid = viewer.scene.globe.ellipsoid;
        const origin = Cesium.Cartesian3.fromDegrees(look.lon, look.lat, look.elev_m || 0, ellipsoid);
        const enu = Cesium.Transforms.eastNorthUpToFixedFrame(origin, ellipsoid);
        const mid = (MOON_DEM_GRID - 1) / 2;
        const stepE = width / (MOON_DEM_GRID - 1);
        const stepN = length / (MOON_DEM_GRID - 1);
        const carts = [];
        for (let row = 0; row < MOON_DEM_GRID; row++) {
            const north = (mid - row) * stepN;
            for (let col = 0; col < MOON_DEM_GRID; col++) {
                const east = (col - mid) * stepE;
                const offset = Cesium.Matrix4.multiplyByPoint(
                    enu, new Cesium.Cartesian3(east, north, 0), new Cesium.Cartesian3());
                carts.push(Cesium.Cartographic.fromCartesian(offset, ellipsoid));
            }
        }
        const sampled = await Cesium.sampleTerrainMostDetailed(provider, carts);
        let missing = 0;
        const heights = sampled.map((cart) => {
            if (!Number.isFinite(cart.height)) {
                missing += 1;
                return 0;
            }
            return Math.round((cart.height - look.elev_m) * 100) / 100;
        });
        // A missed pick uses the ellipsoid (height 0). The centre cell is the
        // look-at, so it is near 0 only when that height is the terrain height.
        // Missing cells used to be stored as 0, which punches flats into the mesh.
        const center = heights[(MOON_DEM_GRID * MOON_DEM_GRID - 1) / 2];
        if (missing > 0) {
            throw new Error(`${place} has not loaded under the crosshair. Wait for the ground, then confirm again.`);
        }
        if (!Number.isFinite(center) || Math.abs(center) > 30) {
            throw new Error(`${place} under the crosshair does not match the sampled ground. Tilt onto the ground and confirm again.`);
        }
        return { grid: MOON_DEM_GRID, heights };
    }

    function viewportJpeg() {
        if (!hud.captureView) return Promise.resolve('');
        return hud.captureView().catch(() => '');
    }

    function createTwinCard(a) {
        const card = base.msg('robot', '');
        const title = document.createElement('div');
        title.className = 'pilot-robot-title';
        const width = patchMetres(a.width_m, CREATE_TWIN_FIELDS.width_m);
        const length = patchMetres(a.length_m, CREATE_TWIN_FIELDS.length_m);
        const klass = a.vehicle_class || CREATE_TWIN_FIELDS.vehicle_class;
        const where = body === 'moon' ? 'the lunar ground under the crosshair' : 'the center of the view';
        title.textContent = `Create Gazebo twin (${klass}, ${Math.round(width)}×${Math.round(length)} m) of ${where}`;
        announce('robot', `${title.textContent}. Confirm it from the chat on the page.`);
        card.appendChild(title);
        const text = document.createElement('div');
        text.className = 'pilot-robot-text';
        text.textContent = body === 'moon'
            ? 'Samples the LOLA elevation into a heightmap and spawns one x500, 15 m above the center.'
            : 'Samples Cesium World Terrain (3DEP where it covers this place) and uses that grid as the Gazebo ground.';
        card.appendChild(text);
        const row = document.createElement('div');
        row.className = 'pilot-robot-buttons';
        const button = (label, cls) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = cls;
            b.textContent = label;
            row.appendChild(b);
            return b;
        };
        const send = button('Create twin', 'send');
        const cancel = button('Cancel', 'cancel');
        card.appendChild(row);
        const busy = on => [send, cancel].forEach(b => { b.disabled = on; });
        cancel.addEventListener('click', () => { row.remove(); addMsg('step', 'Twin not created'); });
        send.addEventListener('click', async () => {
            busy(true);
            const working = addMsg('step', body === 'moon'
                ? 'Sampling lunar elevation and starting the twin...'
                : 'Sampling terrain elevation and starting the twin...');
            try {
                const geo = await lookAtAndBbox(width, length);
                const nadir = await viewportJpeg();
                const resp = await fetch(CREATE_TWIN_URL, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                    body: JSON.stringify({
                        vehicle_class: klass,
                        count: 1,
                        width_m: geo.width_m,
                        length_m: geo.length_m,
                        body: geo.body || body,
                        look_at: geo.look_at,
                        bbox: geo.bbox,
                        dem: geo.dem,
                        nadir,
                    }),
                });
                const data = await resp.json().catch(() => ({}));
                working.remove();
                if (!resp.ok) {
                    addMsg('error', data.error || `Twin job failed (HTTP ${resp.status})`);
                    busy(false);
                    return;
                }
                row.remove();
                addMsg('ai', `Twin job ${data.callsign || data.id}: ${data.message || data.status}`);
                await pollCreateTwin(data.id, out);
            } catch (err) {
                working.remove();
                addMsg('error', `Twin job failed: ${err.message || err}`);
                busy(false);
            }
        });
        log.scrollTop = log.scrollHeight;
    }

    async function pollCreateTwin(jobId, sink) {
        if (!jobId) return;
        const statusEl = addMsg('step', 'Building twin...');
        const started = Date.now();
        try {
            while (Date.now() - started < 15 * 60 * 1000) {
                await new Promise(r => setTimeout(r, 1500));
                const resp = await fetch(`${CREATE_TWIN_URL}${encodeURIComponent(jobId)}/`, {
                    credentials: 'same-origin',
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    statusEl.remove();
                    addMsg('error', data.error || `Twin status failed (HTTP ${resp.status})`);
                    return;
                }
                statusEl.textContent = data.message || data.status || 'Building twin...';
                if (data.status === 'ready') {
                    statusEl.remove();
                    const vehicle = data.vehicle || data.callsign;
                    const readyMsg = addMsg('ai', `Twin ready: ${vehicle}. Following in chase view.`);
                    if (typeof data.url === 'string' && /^\/openuav\/llm\/40\d{3}\/$/.test(data.url)) {
                        const open = document.createElement('a');
                        open.href = data.url;
                        open.target = '_blank';
                        open.rel = 'noopener noreferrer';
                        open.textContent = ' Open desktop';
                        readyMsg.appendChild(open);
                    }
                    if (vehicle) {
                        hud.run([{ type: 'follow_vehicle', vehicle, view: data.follow_view || 'chase' }], sink);
                    }
                    return;
                }
                if (data.status === 'failed') {
                    statusEl.remove();
                    addMsg('error', data.message || 'Twin build failed');
                    return;
                }
            }
            statusEl.remove();
            addMsg('error', 'Twin build timed out; check the job later.');
        } catch (err) {
            statusEl.remove();
            addMsg('error', `Twin status failed: ${err.message || err}`);
        }
    }


    function robotCommandCard(a) {
        const card = base.msg('robot', '');
        const title = document.createElement('div');
        title.className = 'pilot-robot-title';
        title.textContent = `Command for ${a.vehicle}: ${ROBOT_COMMAND_NAMES[a.command] || a.command}`;
        announce('robot', `${title.textContent}. Review and send it from the chat on the page.`);
        card.appendChild(title);
        if (a.instruction) {
            const text = document.createElement('div');
            text.className = 'pilot-robot-text';
            text.textContent = `“${a.instruction}”`;
            card.appendChild(text);
        }
        const row = document.createElement('div');
        row.className = 'pilot-robot-buttons';
        const button = (label, cls) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = cls;
            b.textContent = label;
            row.appendChild(b);
            return b;
        };
        const preview = a.command === 'instruct' ? button('Preview plan', 'preview') : null;
        const send = button('Send', 'send');
        const cancel = button('Cancel', 'cancel');
        card.appendChild(row);
        const busy = on => [preview, send, cancel].forEach(b => { if (b) b.disabled = on; });
        cancel.addEventListener('click', () => { row.remove(); addMsg('step', `Not sent to ${a.vehicle}`); });
        preview?.addEventListener('click', () => postRobotCommand(a, true, busy));
        send.addEventListener('click', async () => {
            if (await postRobotCommand(a, false, busy)) row.remove();
        });
        log.scrollTop = log.scrollHeight;
    }

    // true once the server has answered a real send (accepted or not), so the card can't send twice
    async function postRobotCommand(a, dryRun, busy) {
        busy(true);
        const working = addMsg('step', dryRun ? `Planning for ${a.vehicle} (nothing is sent)...` : `Sending to ${a.vehicle}...`);
        try {
            const resp = await fetch(ROBOT_COMMAND_URL, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                body: JSON.stringify({ vehicle: a.vehicle, command: a.command,
                                       instruction: a.instruction || '', dry_run: dryRun }),
            });
            const data = await resp.json().catch(() => ({}));
            working.remove();
            if (!resp.ok) {
                addMsg('error', data.error || `Command failed (HTTP ${resp.status})`);
                return false;
            }
            reportRobotResult(data);
            return !dryRun;
        } catch (err) {
            working.remove();
            addMsg('error', `Command failed: ${err.message || err}`);
            return false;
        } finally {
            busy(false);
        }
    }

    function reportRobotResult(d) {
        const plan = d.plan && typeof d.plan === 'object' ? d.plan : null;
        if (d.accepted === false || d.result === 'rejected' || d.result === 'needs_clarification') {
            addMsg('error', `${d.vehicle}: ${d.message || d.result || 'rejected'}`);
            return;
        }
        if (d.dry_run) addMsg('ai', `Plan for ${d.vehicle} (not sent):`);
        else if (d.accepted == null) addMsg('ai', `Sent to ${d.vehicle}; no acknowledgement yet. ${d.message || ''}`.trim());
        else addMsg('ai', `${d.vehicle} accepted it${d.message ? `: ${d.message}` : ''}`);
        if (plan) {
            (Array.isArray(plan.steps) ? plan.steps : []).forEach(s => addMsg('step', `• ${s}`));
            const parts = [];
            if (Number.isFinite(plan.waypoints)) parts.push(`${plan.waypoints} waypoints`);
            if (Number.isFinite(plan.path_m)) parts.push(`${Math.round(plan.path_m)} m`);
            if (plan.end) parts.push(`then ${plan.end}`);
            if (parts.length) addMsg('step', parts.join(', '));
        } else if (d.dry_run && d.message) {
            addMsg('step', d.message);
        }
        if (!d.dry_run && d.result === 'in_progress') addMsg('step', `${d.vehicle} is on its way; chase it to watch`);
    }

    stopBtn.addEventListener('click', () => { task = null; hud.stop(); addMsg('step', 'Stopped'); });

    let asking = false;

    // false when there is nothing to send or a request is already out. opts.auto: the
    // chat line for a turn the page sends itself (a goal check) instead of the message
    async function ask(text, opts = {}) {
        const message = String(text || '').trim();
        if (!message || asking || !getViewer()) return false;
        if (!opts.auto) task = null;
        asking = true;
        addMsg(opts.auto ? 'step' : 'user', opts.auto || message);
        const thinking = addMsg('step', 'Thinking...');
        sendBtn.disabled = true;
        try {
            const resp = await fetch('/label/api/pilot/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                body: JSON.stringify({
                    message, history, body, view: await hud.currentView(),
                    model: modelSelect?.value || '',
                    // Placed 3D models on this page (DeepGISModels.sites); the server turns them into a Models line
                    models: (window.DeepGISModels?.sites || []).map((s) => ({
                        id: s.id, name: s.name, lat: s.lat, lon: s.lon,
                        aliases: s.aliases || [], radius_m: s.radius_m,
                    })),
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
            const actions = data.actions || [];
            actions.filter(a => a.type === 'robot_command').forEach(robotCommandCard);
            actions.filter(a => a.type === 'create_twin').forEach(createTwinCard);
            const camera = actions.filter(a => a.type !== 'robot_command' && a.type !== 'create_twin');
            camera.filter(a => a.type === 'describe_view').forEach(a => { a.question = message; });
            if (camera.length) hud.run(camera, out);
        } catch (err) {
            thinking.remove();
            addMsg('error', `Request failed: ${err.message || err}`);
        } finally {
            asking = false;
            sendBtn.disabled = false;
        }
        return true;
    }

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        if (asking || !input.value.trim()) return;
        const message = input.value;
        input.value = '';
        ask(message);
    });

    window.DeepGISPilot = {
        ask,
        busy: () => asking,
        recent: () => recent.slice(),
        on: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
    };

    modelSelect?.addEventListener('change', () => {
        const selected = modelSelect.selectedOptions[0];
        modelSelect.title = selected ? selected.title || selected.textContent : 'AI model';
    });
    loadModels();
    console.log('[AI Pilot] Initialized');
})();
