// DeepGIS AI pilot chat, shared by the Earth, Moon and planet viewers.
// POST /label/api/pilot/ turns a request into actions (goto, orbit, takeoff, land,
// look, stop, wait, show_layer, hide_layer, describe_view, follow_vehicle); they run
// in order through window.DeepGISActions (hud/actions.js), which reports into this chat.
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
        // Follow-up questions ("what is the dark patch on the left?") can refer to it
        described(data) {
            history.push({ role: 'assistant',
                           content: `What I saw in the view: ${[data.summary, ...(data.observations || [])].join(' ')}`.slice(0, 2000) });
            history.splice(0, Math.max(0, history.length - 8));
        },
    };
    const addMsg = out.msg;

    const ROBOT_COMMAND_URL = '/label/api/pilot/robot-command/';
    const ROBOT_COMMAND_NAMES = { instruct: 'instruction', return_home: 'return home and land', land: 'land now' };

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

    stopBtn.addEventListener('click', () => { hud.stop(); addMsg('step', 'Stopped'); });

    let asking = false;

    // false when there is nothing to send or a request is already out
    async function ask(text) {
        const message = String(text || '').trim();
        if (!message || asking || !getViewer()) return false;
        asking = true;
        addMsg('user', message);
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
            const camera = actions.filter(a => a.type !== 'robot_command');
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
