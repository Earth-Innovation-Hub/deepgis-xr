// Lab simulation desktops on the Earth search page. The list comes from
// /label/api/sims/ (any signed-in account). Each Open link is a path on this site.
(function () {
    const list = document.getElementById('simsList');
    const btn = document.getElementById('hudSimsBtn');
    if (!list || !btn) return;

    const PANEL_PATH = /^\/openuav\/llm\/40\d{3}\/$/;

    function note(text, href, label) {
        list.replaceChildren();
        const p = document.createElement('p');
        p.className = 'sims-note';
        p.textContent = text;
        list.append(p);
        if (href && label) {
            const a = document.createElement('a');
            a.className = 'sim-open';
            a.href = href;
            a.textContent = label;
            list.append(a);
        }
    }

    function render(sims) {
        list.replaceChildren();
        if (!sims.length) {
            note('No simulations are registered.');
            return;
        }
        sims.forEach(function (sim) {
            if (!sim || typeof sim.url !== 'string' || !PANEL_PATH.test(sim.url)) return;
            const row = document.createElement('div');
            row.className = 'sim-row';
            const text = document.createElement('div');
            text.className = 'sim-row-text';
            const title = document.createElement('div');
            title.className = 'sim-row-name';
            title.textContent = sim.world || sim.name || sim.slug || 'Simulation';
            const robots = document.createElement('div');
            robots.className = 'sim-row-robots';
            const names = Array.isArray(sim.robots) ? sim.robots.filter(function (r) { return typeof r === 'string'; }) : [];
            robots.textContent = names.join(', ') + (sim.kind === 'session' ? ' · yours' : '');
            text.append(title, robots);
            const link = document.createElement('a');
            link.className = 'sim-open';
            link.href = sim.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = 'Open';
            row.append(text, link);
            list.append(row);
        });
        if (!list.childElementCount) note('No simulations are registered.');
    }

    async function load() {
        note('Loading simulations…');
        let resp;
        try {
            resp = await fetch('/label/api/sims/', {
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
        } catch (e) {
            note('Could not reach the simulation list.');
            return;
        }
        if (resp.status === 401) {
            let login = '/label/admin/login/?next=/label/3d/search/';
            try {
                const body = await resp.json();
                if (body && typeof body.login_url === 'string' && body.login_url.charAt(0) === '/') login = body.login_url;
            } catch (e) { /* the status is enough */ }
            note('Sign in to open a simulation desktop.', login, 'Sign in');
            return;
        }
        if (resp.status === 403) {
            note('This account cannot open simulation desktops.');
            return;
        }
        if (!resp.ok) {
            note('The simulation list is unavailable.');
            return;
        }
        let data;
        try {
            data = await resp.json();
        } catch (e) {
            note('The simulation list is unavailable.');
            return;
        }
        render(Array.isArray(data.sims) ? data.sims : []);
    }

    btn.addEventListener('click', load);
})();
