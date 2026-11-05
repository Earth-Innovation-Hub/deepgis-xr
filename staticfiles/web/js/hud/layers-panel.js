// HUD Layers panel, data layers (web/hud/layers_panel.html): the AI pilot's layers as
// toggles, in the catalog's groups. Each one runs show_layer / hide_layer through window.DeepGISActions
// (hud/actions.js) around the point in view, or around a place typed above the list, and
// lists the layer's readings, legend and sources under its row. The kinds, groups, colour
// maps and radius range come from views/pilot.py (layer_catalog, #hudLayerCatalog); layers the
// pilot shows or hides tick and untick here too.
(function initLayersPanel() {
    const mount = document.getElementById('dataLayersMount');
    const catalogEl = document.getElementById('hudLayerCatalog');
    const hud = window.DeepGISActions;
    if (!mount || !catalogEl || !hud) return;
    const catalog = JSON.parse(catalogEl.textContent);
    const specs = new Map(hud.layers().map(l => [l.kind, l]));
    const kinds = catalog.kinds.filter(k => specs.has(k));
    if (!kinds.length) return;
    const signedIn = mount.dataset.signedIn === '1';
    const signinKinds = new Set(catalog.signin_kinds);
    const colormapKinds = new Set(catalog.colormap_kinds);
    const [minRadius, maxRadius] = catalog.radius_m;

    function el(tag, className, text) {
        const e = document.createElement(tag);
        if (className) e.className = className;
        if (text != null) e.textContent = text;
        return e;
    }

    // The layer's own lines, without the plan's closing "Done"
    function rowSink(results) {
        const sink = hud.logSink(results);
        return { ...sink, msg: (kind, text, href) => (kind === 'step' && text === 'Done' ? null : sink.msg(kind, text, href)) };
    }

    const rows = new Map();

    function setBusy(r, busy) {
        r.busy = busy;
        r.row.classList.toggle('loading', busy);
        r.box.disabled = busy;
        r.refresh.disabled = busy;
    }

    async function show(r) {
        if (r.busy) return;
        const action = { type: 'show_layer', kind: r.kind };
        const km = parseFloat(r.radius.value);
        if (Number.isFinite(km) && km > 0) {
            action.radius_m = Math.min(maxRadius, Math.max(minRadius, km * 1000));
            r.radius.value = String(action.radius_m / 1000);
        }
        if (r.cmap?.value) action.colormap = r.cmap.value;
        const place = where.value.trim();
        if (place) action.place = place;
        else action.frame = false;
        r.box.checked = true;
        r.results.replaceChildren();
        r.results.hidden = false;
        setBusy(r, true);
        try {
            await hud.run([action], rowSink(r.results));
        } finally {
            setBusy(r, false);
            r.loaded = hud.shown().includes(r.kind);
            sync();
        }
    }

    async function hide(r) {
        r.loaded = false;
        r.results.replaceChildren();
        r.results.hidden = true;
        r.refresh.hidden = true;
        await hud.run([{ type: 'hide_layer', kind: r.kind }]);
    }

    // Tick what is on the globe, whoever drew it
    function sync() {
        const shown = new Set(hud.shown());
        rows.forEach(r => {
            if (r.busy) return;
            const on = shown.has(r.kind);
            r.box.checked = on;
            r.refresh.hidden = !on;
            if (on && !r.loaded) {
                r.loaded = true;
                r.results.replaceChildren();
                r.results.hidden = false;
                hud.logSink(r.results).msg('step', 'Shown by the AI pilot; its readings are in the chat.');
            } else if (!on && r.loaded) {
                r.loaded = false;
                r.results.replaceChildren();
                r.results.hidden = true;
            }
        });
    }

    function makeRow(kind) {
        const spec = specs.get(kind);
        const row = el('div', 'dl-row');
        const top = el('div', 'dl-top');
        const box = el('input', 'form-check-input');
        box.type = 'checkbox';
        box.id = `dataLayer-${kind}`;
        const label = el('label', 'dl-title', spec.title);
        label.htmlFor = box.id;
        if (signinKinds.has(kind) && !signedIn) {
            box.disabled = true;
            label.title = 'Fetched through this server; sign in to load it';
            label.append(el('span', 'dl-hint', 'sign in'));
        }
        const radius = el('input', 'dl-input dl-radius');
        radius.type = 'number';
        radius.min = String(minRadius / 1000);
        radius.max = String(maxRadius / 1000);
        radius.step = 'any';
        radius.placeholder = spec.radius ? String(+(spec.radius / 1000).toPrecision(3)) : 'auto';
        radius.title = 'Radius in km; leave empty for the layer\'s own extent';
        radius.setAttribute('aria-label', `${spec.title} radius in km`);
        top.append(box, label, radius, el('span', 'dl-unit', 'km'));
        let cmap = null;
        if (colormapKinds.has(kind)) {
            cmap = el('select', 'dl-input dl-cmap');
            cmap.append(new Option('colours', ''), ...catalog.colormaps.map(c => new Option(c, c)));
            cmap.title = 'Colour map';
            cmap.setAttribute('aria-label', `${spec.title} colour map`);
            top.append(cmap);
        }
        const refresh = el('button', 'dl-refresh');
        refresh.type = 'button';
        refresh.hidden = true;
        refresh.title = 'Reload around the current view or place';
        refresh.setAttribute('aria-label', `Reload ${spec.title}`);
        refresh.append(el('i', 'fas fa-sync-alt'));
        top.append(refresh);
        const results = el('div', 'dl-results');
        results.hidden = true;
        row.append(top, results);

        const r = { kind, row, box, radius, cmap, refresh, results, busy: false, loaded: false };
        box.addEventListener('change', () => (box.checked ? show(r) : hide(r)));
        refresh.addEventListener('click', () => show(r));
        radius.addEventListener('change', () => { if (box.checked) show(r); });
        cmap?.addEventListener('change', () => { if (box.checked) show(r); });
        rows.set(kind, r);
        return row;
    }

    const where = el('input', 'dl-input dl-place');
    where.type = 'text';
    where.placeholder = hud.isEarth ? 'Around the view, or a place: Bishop, CA' : 'Around the view, or a named feature';
    where.setAttribute('aria-label', 'Centre the data layers on a place');
    // Enter reloads the ticked layers around the new place, one after another
    where.addEventListener('keydown', async (e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        for (const r of rows.values()) if (r.box.checked) await show(r);
    });
    mount.append(el('div', 'dl-heading', 'Data layers'), where);

    catalog.groups.map(([title, ks]) => [title, ks.filter(k => kinds.includes(k))])
        .filter(([, ks]) => ks.length).forEach(([title, ks]) => {
            mount.append(el('div', 'dl-group', title), ...ks.map(makeRow));
        });

    hud.on('layers', sync);
    sync();
})();
