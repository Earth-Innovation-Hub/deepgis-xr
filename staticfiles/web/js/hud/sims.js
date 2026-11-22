// Lab simulation desktops on the Earth search page. The list comes from
// /label/api/sims/ (any signed-in account). Each Open link is a path on this site.
(function () {
    const list = document.getElementById('simsList');
    const btn = document.getElementById('hudSimsBtn');
    if (!list || !btn) return;

    const PANEL_PATH = /^\/openuav\/llm\/40\d{3}\/$/;
    const SESSION_SLUG = /^ktwin-[a-z0-9-]{1,34}$/;

    function csrfToken() {
        const el = document.querySelector('input[name=csrfmiddlewaretoken]');
        if (el && el.value) return el.value;
        const hit = document.cookie.split('; ').find(function (c) { return c.indexOf('csrftoken=') === 0; });
        return hit ? decodeURIComponent(hit.split('=').slice(1).join('=')) : '';
    }

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
            const yours = sim.kind === 'session';
            const stopped = yours && sim.status === 'down';
            robots.textContent = names.join(', ') + (yours ? ' · yours' : '') + (stopped ? ' · stopped' : '');
            text.append(title, robots);
            const actions = document.createElement('div');
            actions.className = 'sim-actions';
            if (!stopped) {
                const link = document.createElement('a');
                link.className = 'sim-open';
                link.href = sim.url;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = 'Open';
                actions.append(link);
            }
            if (yours && SESSION_SLUG.test(sim.slug || '')) {
                if (stopped) actions.append(actButton('Start', 'start', sim.slug));
                else actions.append(actButton('Stop', 'stop', sim.slug));
                actions.append(actButton('Purge', 'purge', sim.slug));
            }
            row.append(text, actions);
            list.append(row);
        });
        if (!list.childElementCount) note('No simulations are registered.');
    }

    function actButton(label, action, slug) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'sim-act' + (action === 'purge' ? ' sim-act-purge' : '');
        button.textContent = label;
        button.addEventListener('click', function () { runAction(button, slug, action); });
        return button;
    }

    async function runAction(button, slug, action) {
        if (action === 'purge' && !window.confirm('Remove this digital twin, its container, and its desktop?')) return;
        const label = button.textContent;
        button.disabled = true;
        button.textContent = action === 'purge' ? 'Removing…' : (action === 'stop' ? 'Stopping…' : 'Starting…');
        let resp;
        try {
            resp = await fetch('/label/api/sims/' + encodeURIComponent(slug) + '/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    Accept: 'application/json',
                    'X-CSRFToken': csrfToken(),
                },
                body: JSON.stringify({ action: action }),
            });
        } catch (e) {
            button.disabled = false;
            button.textContent = label;
            return;
        }
        if (!resp.ok) {
            button.disabled = false;
            button.textContent = label;
            let message = 'That did not work.';
            try {
                const body = await resp.json();
                if (body && typeof body.error === 'string' && body.error) message = body.error;
            } catch (e) { /* status is enough */ }
            let flag = list.querySelector('.sim-action-error');
            if (!flag) {
                flag = document.createElement('p');
                flag.className = 'sims-note sim-action-error';
                list.prepend(flag);
            }
            flag.textContent = message;
            return;
        }
        await load();
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
