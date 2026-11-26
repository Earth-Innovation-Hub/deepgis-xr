// The world model's sampling loop, run from the page.
//
// Each pull asks the server which view to capture next (a 100 m cell and a ground sample
// distance, chosen by a policy), captures it with the page's own scene-graph build, and tells
// the server which capture answered, so what the model expected sits beside what came back.
//
//   samplerLoop.run({ n: 30, policies: ['thompson', 'uniform'], run: 'a label', bbox: [w, s, e, n] })
//   samplerLoop.stop()        finish the capture in hand, then stop
//   samplerLoop.state         progress, the last pull and any errors
//   samplerLoop.results(run)  the stored pulls with the per-policy comparison
//
// The map has to be in 2D: scene graphs are built from a top-down view.
(function () {
    'use strict';

    const API = '/webclient/sampler/world/';
    const MAX_ERRORS_IN_A_ROW = 2;
    const state = { running: false, stopping: false, run: '', done: 0, total: 0, last: null, errors: [], pulls: [] };

    async function call(path, body) {
        const resp = await fetch(API + path, body === undefined ? undefined : {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        let data = null;
        try { data = await resp.json(); } catch (err) { /* not JSON: report the status */ }
        if (!resp.ok || !data || data.status !== 'success') {
            throw new Error((data && data.message) || `${path} returned ${resp.status}`);
        }
        return data;
    }

    // One pull: propose, capture, report. Resolves to {pull_id, policy, predicted, realised, error}.
    async function step(opts = {}) {
        const ui = window.worldSamplerUI;
        const viewer = ui && ui.viewer;
        if (!viewer) throw new Error('the map is not ready');
        const scene = viewer.scene;
        if (scene.mode !== Cesium.SceneMode.SCENE2D) throw new Error('switch the map to 2D first');
        const canvas = scene.canvas;
        const view = await call('next_view', {
            taxonomy: opts.taxonomy || 'urban_v1',
            policy: opts.policy || 'thompson',
            run: opts.run || '',
            bbox: opts.bbox || null,
            image_size: [canvas.width, canvas.height],
        });
        // In 2D the view is as wide as the camera is high, in projected metres; on the ground
        // that is cos(latitude) times as much.
        const height = view.gsd_m * canvas.width / Math.cos(Cesium.Math.toRadians(view.lat));
        viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(view.lon, view.lat, height) });

        let built = null;
        let error = null;
        try {
            built = await ui.buildSceneGraph({ kernels: ['sam3'], height });
            if (built.degraded && built.degraded.length) error = `${built.degraded.join(', ')} unavailable`;
            else if (!built.worldUpdated || !built.sessionId) error = 'the world model was not updated';
        } catch (err) {
            error = String((err && err.message) || err);
        }
        let pull = null;
        if (!error) {
            try {
                pull = (await call('pulls', { pull_id: view.pull_id, session_id: built.sessionId })).pull;
            } catch (err) {
                error = String((err && err.message) || err);
            }
        }
        if (error) pull = (await call('pulls', { pull_id: view.pull_id, error })).pull;
        return {
            pull_id: view.pull_id, policy: view.policy, band: view.band, gsd_m: view.gsd_m,
            predicted: view.predicted, realised: pull && pull.realised, error,
        };
    }

    // n pulls per policy, the policies taking turns so each sees the store at the same stage.
    async function run(opts = {}) {
        if (state.running) throw new Error('a run is already going');
        const policies = opts.policies && opts.policies.length ? opts.policies : ['thompson'];
        const n = Math.max(1, Math.min(parseInt(opts.n, 10) || 1, 100));
        Object.assign(state, {
            running: true, stopping: false, run: opts.run || `loop-${new Date().toISOString().slice(0, 16)}`,
            done: 0, total: n * policies.length, last: null, errors: [], pulls: [],
        });
        let failures = 0;
        try {
            for (let i = 0; i < state.total && !state.stopping; i++) {
                let out;
                try {
                    out = await step({ ...opts, policy: policies[i % policies.length], run: state.run });
                } catch (err) {
                    out = { policy: policies[i % policies.length], error: String((err && err.message) || err) };
                }
                state.last = out;
                state.pulls.push(out);
                state.done = i + 1;
                if (out.error) {
                    state.errors.push({ i, pull_id: out.pull_id, error: out.error });
                    failures += 1;
                    if (failures >= MAX_ERRORS_IN_A_ROW) break;
                } else {
                    failures = 0;
                }
            }
        } finally {
            state.running = false;
        }
        return results(state.run);
    }

    function results(runLabel, taxonomy) {
        const q = new URLSearchParams({ taxonomy: taxonomy || 'urban_v1', run: runLabel || state.run, limit: '500' });
        return call(`pulls?${q}`);
    }

    window.samplerLoop = { run, step, results, state, stop() { state.stopping = true; } };
})();
