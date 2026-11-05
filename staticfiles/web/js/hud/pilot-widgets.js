// HUD widgets for the AI pilot's camera actions, run through window.DeepGISActions
// (hud/actions.js): "Describe this view" in the AI panel (describe_view, the vision model,
// signed-in users) and "Fly to place" in the View panel (goto and orbit, with the pilot's
// place lookup: mapped sites, OpenStreetMap, then Cesium ion; the IAU gazetteer off Earth).
(function initPilotWidgets() {
    const hud = window.DeepGISActions;
    if (!hud) return;
    const COORDS = /^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$/;

    function sinkInto(el, { done = true } = {}) {
        el.replaceChildren();
        el.hidden = false;
        const sink = hud.logSink(el);
        if (done) return sink;
        return { ...sink, msg: (kind, text, href) => (kind === 'step' && text === 'Done' ? null : sink.msg(kind, text, href)) };
    }

    const onEnter = (input, fn) => input.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        fn();
    });

    const question = document.getElementById('describeQuestion');
    const describeBtn = document.getElementById('describeViewBtn');
    const describeOut = document.getElementById('describeResults');
    if (question && describeBtn && describeOut) {
        const describe = async () => {
            if (describeBtn.disabled) return;
            describeBtn.disabled = true;
            try {
                await hud.run([{ type: 'describe_view', question: question.value.trim() }],
                    sinkInto(describeOut, { done: false }));
            } finally {
                describeBtn.disabled = false;
            }
        };
        describeBtn.addEventListener('click', describe);
        onEnter(question, describe);
    }

    const place = document.getElementById('flyToInput');
    const flyBtn = document.getElementById('flyToBtn');
    const orbitBtn = document.getElementById('orbitPlaceBtn');
    const stopBtn = document.getElementById('flyStopBtn');
    const flyOut = document.getElementById('flyToResults');
    if (place && flyBtn && orbitBtn && stopBtn && flyOut) {
        let latest = 0;
        // A new flight replaces the one under way; only the latest one hides Stop
        const go = async (type) => {
            const text = place.value.trim();
            if (!text) {
                place.focus();
                return;
            }
            const action = { type };
            const m = text.match(COORDS);
            if (m && Math.abs(+m[1]) <= 90 && Math.abs(+m[2]) <= 180) {
                action.lat = +m[1];
                action.lon = +m[2];
            } else {
                action.place = text;
            }
            const mine = ++latest;
            stopBtn.hidden = false;
            try {
                await hud.run([action], sinkInto(flyOut));
            } finally {
                if (mine === latest) stopBtn.hidden = true;
            }
        };
        flyBtn.addEventListener('click', () => go('goto'));
        orbitBtn.addEventListener('click', () => go('orbit'));
        stopBtn.addEventListener('click', () => hud.stop());
        onEnter(place, () => go('goto'));
    }
})();
