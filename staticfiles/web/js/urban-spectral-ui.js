/**
 * Urban Spectral Analysis — viewport-driven UI
 *
 * Client side of the `urban_spectral` analyzer. Reads the current Cesium
 * viewport as a WGS84 bbox, POSTs to /webclient/sampler/analyze-viewport
 * with `model_type: 'urban_spectral'`, and renders:
 *
 *   - the Laplacian eigenspectrum as a pure-SVG sparkline,
 *   - a compact diagnostics strip (ΔH, Δ′, β₁, Δβ₁, λ_fiedler, N),
 *   - the Fiedler eigenvector on top of the globe as per-building points
 *     coloured by a diverging red/white/blue colormap.
 *
 * Stands alone so it can be included from any template that already
 * hosts a Cesium viewer and (optionally) the World Sampler UI.
 */

(function () {
    'use strict';

    const ENDPOINT = '/webclient/sampler/analyze-viewport';
    const DEFAULT_PARAMS = {
        k: 8,
        n_max: 1500,
        sigma_frac: 0.05,
        tau: 1.0,
        mu2: 2.0,
        sigma2: 1.0,
    };

    // Diverging red/white/blue ramp, bytes (r,g,b) as tuples.
    // Matches matplotlib 'RdBu_r' at a coarser 11-stop resolution — small
    // enough to inline without pulling in a colormap lib.
    const RD_BU_R = [
        [ 33,  102, 172],
        [ 67,  147, 195],
        [146, 197, 222],
        [209, 229, 240],
        [247, 247, 247],
        [253, 219, 199],
        [244, 165, 130],
        [214,  96,  77],
        [178,  24,  43],
        [103,   0,  31],
    ];

    function lerp(a, b, t) { return a + (b - a) * t; }

    function colormap(value) {
        // `value` assumed in [-1, 1]; map to [0, 1].
        const v = Math.max(0, Math.min(1, 0.5 * (value + 1)));
        const idx = v * (RD_BU_R.length - 1);
        const lo  = Math.floor(idx);
        const hi  = Math.min(lo + 1, RD_BU_R.length - 1);
        const t   = idx - lo;
        const r = Math.round(lerp(RD_BU_R[lo][0], RD_BU_R[hi][0], t));
        const g = Math.round(lerp(RD_BU_R[lo][1], RD_BU_R[hi][1], t));
        const b = Math.round(lerp(RD_BU_R[lo][2], RD_BU_R[hi][2], t));
        return { r, g, b };
    }

    function normalizeSigned(values) {
        // Symmetric max-abs normalisation so the colormap is zero-centred.
        let m = 0;
        for (let i = 0; i < values.length; i++) {
            const a = Math.abs(values[i]);
            if (a > m) m = a;
        }
        if (m < 1e-12) m = 1;
        const out = new Float64Array(values.length);
        for (let i = 0; i < values.length; i++) out[i] = values[i] / m;
        return out;
    }

    // =====================================================================
    // Bbox capture
    // =====================================================================

    function viewportBbox(viewer) {
        if (!viewer || !viewer.camera || !viewer.scene || !viewer.scene.globe) {
            return null;
        }
        const rect = viewer.camera.computeViewRectangle(
            viewer.scene.globe.ellipsoid,
        );
        if (!rect) return null;
        return {
            west:  Cesium.Math.toDegrees(rect.west),
            south: Cesium.Math.toDegrees(rect.south),
            east:  Cesium.Math.toDegrees(rect.east),
            north: Cesium.Math.toDegrees(rect.north),
        };
    }

    // =====================================================================
    // Main controller
    // =====================================================================

    class UrbanSpectralUI {
        constructor(viewer) {
            this.viewer = viewer;
            this.params = { ...DEFAULT_PARAMS };
            this.lastResult = null;
            this.pointCollection = null;   // Cesium.PointPrimitiveCollection
            this._inflight = null;
            this._renderedAny = false;

            this.mountPanel();
        }

        // ------------------------------------------------------------------
        // UI
        // ------------------------------------------------------------------

        mountPanel() {
            if (document.getElementById('urbanSpectralPanel')) return;

            const panel = document.createElement('div');
            panel.id = 'urbanSpectralPanel';
            panel.className = 'layer-group accordion-panel';
            panel.style.cssText = [
                'border: 2px solid #38bdf8',
                'background: rgba(56, 189, 248, 0.06)',
                'margin-top: 8px',
            ].join(';');
            panel.innerHTML = `
                <div class="layer-group-title accordion-header"
                     data-target="urbanSpectralContent"
                     style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;padding:6px 10px;">
                    <span><i class="fas fa-wave-square"></i> Urban Spectral</span>
                    <i class="fas fa-chevron-down accordion-icon"></i>
                </div>
                <div class="accordion-content expanded" id="urbanSpectralContent" style="padding:8px 10px;">
                    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;">
                        <button id="urbanSpectralRunBtn"
                                class="btn btn-sm"
                                style="background:#0ea5e9;color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;">
                            <i class="fas fa-play"></i> Analyze viewport
                        </button>
                        <button id="urbanSpectralOverlayBtn"
                                class="btn btn-sm"
                                style="background:#334155;color:#cbd5e1;border:none;padding:4px 8px;border-radius:4px;cursor:pointer;"
                                title="Toggle Fiedler-vector overlay on the globe"
                                disabled>
                            <i class="fas fa-eye"></i> Overlay
                        </button>
                        <button id="urbanSpectralClearBtn"
                                class="btn btn-sm"
                                style="background:#1e293b;color:#94a3b8;border:none;padding:4px 8px;border-radius:4px;cursor:pointer;"
                                title="Clear overlay">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>

                    <details style="margin-bottom:6px;color:#cbd5e1;font-size:11px;">
                        <summary style="cursor:pointer;">Parameters</summary>
                        <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 8px;margin-top:6px;align-items:center;">
                            <label>k (NN)</label>
                            <input id="urbanSpectralK" type="number" min="2" max="32" value="${DEFAULT_PARAMS.k}"
                                   style="width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;padding:2px 4px;">
                            <label>n_max</label>
                            <input id="urbanSpectralNmax" type="number" min="50" max="5000" step="50" value="${DEFAULT_PARAMS.n_max}"
                                   style="width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;padding:2px 4px;">
                            <label>τ (tau)</label>
                            <input id="urbanSpectralTau" type="number" step="0.1" value="${DEFAULT_PARAMS.tau}"
                                   style="width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;padding:2px 4px;"
                                   title="Diffusion time. Set to 0 for auto (1/λ_max).">
                        </div>
                    </details>

                    <div id="urbanSpectralStatus"
                         style="font-size:11px;color:#94a3b8;min-height:14px;margin-bottom:4px;"></div>

                    <svg id="urbanSpectralChart" width="100%" height="90"
                         viewBox="0 0 300 90" preserveAspectRatio="none"
                         style="background:#0f172a;border:1px solid #1e293b;border-radius:3px;"></svg>

                    <div id="urbanSpectralDiagnostics"
                         style="margin-top:6px;font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#e2e8f0;line-height:1.5;">
                    </div>
                </div>
            `;

            // Find a mount point — prefer the World Sampler container so the
            // two panels live next to each other; otherwise fall back to
            // any sidebar-ish element.
            const host =
                document.getElementById('worldSamplerSection') ||
                document.getElementById('hudSamplerContainer') ||
                document.querySelector('.layer-controls') ||
                document.querySelector('#sidebar-wrapper .sidebar-content') ||
                document.querySelector('.sidebar-content') ||
                document.body;

            // Insert *after* the World Sampler section when possible,
            // otherwise just append.
            if (host.id === 'worldSamplerSection' && host.parentElement) {
                host.parentElement.insertBefore(panel, host.nextSibling);
            } else {
                host.appendChild(panel);
            }

            this.bindEvents();
        }

        bindEvents() {
            const q = (id) => document.getElementById(id);
            q('urbanSpectralRunBtn').addEventListener('click', () => this.run());
            q('urbanSpectralOverlayBtn').addEventListener('click', () => this.toggleOverlay());
            q('urbanSpectralClearBtn').addEventListener('click', () => this.clearOverlay());

            // Simple accordion toggle in case the page doesn't provide one.
            const header = q('urbanSpectralPanel').querySelector('.accordion-header');
            const content = q('urbanSpectralContent');
            header.addEventListener('click', () => {
                content.style.display = content.style.display === 'none' ? '' : 'none';
            });
        }

        setStatus(text, color) {
            const el = document.getElementById('urbanSpectralStatus');
            if (!el) return;
            el.textContent = text || '';
            el.style.color = color || '#94a3b8';
        }

        // ------------------------------------------------------------------
        // Request
        // ------------------------------------------------------------------

        readParams() {
            const q = (id) => document.getElementById(id);
            const k    = parseInt(q('urbanSpectralK').value,    10);
            const nMax = parseInt(q('urbanSpectralNmax').value, 10);
            const tau  = parseFloat(q('urbanSpectralTau').value);
            return {
                k:     Number.isFinite(k)    ? k    : DEFAULT_PARAMS.k,
                n_max: Number.isFinite(nMax) ? nMax : DEFAULT_PARAMS.n_max,
                tau:   Number.isFinite(tau)  ? tau  : DEFAULT_PARAMS.tau,
            };
        }

        async run() {
            if (this._inflight) {
                this.setStatus('Request already in flight…', '#fbbf24');
                return;
            }
            const bbox = viewportBbox(this.viewer);
            if (!bbox) {
                this.setStatus('Viewport not ready.', '#ef4444');
                return;
            }

            const params = this.readParams();
            const body = {
                model_type: 'urban_spectral',
                bbox,
                ...params,
            };

            this.setStatus(
                `Fetching OSM buildings inside ` +
                `S${bbox.south.toFixed(3)} W${bbox.west.toFixed(3)} ` +
                `N${bbox.north.toFixed(3)} E${bbox.east.toFixed(3)}…`,
            );

            const runBtn     = document.getElementById('urbanSpectralRunBtn');
            const overlayBtn = document.getElementById('urbanSpectralOverlayBtn');
            runBtn.disabled  = true;
            const started    = performance.now();

            try {
                this._inflight = fetch(ENDPOINT, {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify(body),
                });
                const resp = await this._inflight;

                if (!resp.ok) {
                    const err = await this.safeParseError(resp);
                    this.setStatus(
                        `${resp.status}: ${err.message}${err.code ? ' [' + err.code + ']' : ''}`,
                        '#ef4444',
                    );
                    return;
                }

                const result = await resp.json();
                if (result.status !== 'ok') {
                    this.setStatus(
                        result.message || 'Analyzer returned non-ok status.',
                        '#ef4444',
                    );
                    return;
                }

                if (result.n_buildings === 0) {
                    this.setStatus('No buildings in viewport — pan or zoom in.', '#fbbf24');
                    this.clearOverlay();
                    this.clearChart();
                    this.renderDiagnostics(null);
                    return;
                }

                this.lastResult = result;
                this.renderChart(result);
                this.renderDiagnostics(result);
                this.renderOverlay(result);
                overlayBtn.disabled = false;

                const ms = Math.round(performance.now() - started);
                const t  = result.timings || {};
                this.setStatus(
                    `✓ ${result.n_buildings} buildings · ` +
                    `graph ${t.graph_build_s}s · spectral ${t.spectral_s}s · total ${(ms/1000).toFixed(2)}s`,
                    '#10b981',
                );
            } catch (err) {
                console.error('[UrbanSpectral] request failed', err);
                this.setStatus(`Network error: ${err.message}`, '#ef4444');
            } finally {
                runBtn.disabled = false;
                this._inflight  = null;
            }
        }

        async safeParseError(resp) {
            try {
                const ct = resp.headers.get('content-type') || '';
                if (ct.includes('application/json')) {
                    const j = await resp.json();
                    return { message: j.message || resp.statusText, code: j.code };
                }
                const text = (await resp.text()) || resp.statusText;
                return { message: text.substring(0, 200) };
            } catch (_) {
                return { message: resp.statusText };
            }
        }

        // ------------------------------------------------------------------
        // Eigenspectrum chart (SVG, no deps)
        // ------------------------------------------------------------------

        renderChart(result) {
            const svg = document.getElementById('urbanSpectralChart');
            if (!svg) return;
            while (svg.firstChild) svg.removeChild(svg.firstChild);

            const eig   = result.eigvals  || [];
            const h0    = result.h0       || [];
            const hStar = result.h_star   || [];
            const N     = eig.length;
            if (!N) return;

            const W = 300, H = 90, padL = 18, padR = 4, padT = 4, padB = 14;
            const plotW = W - padL - padR;
            const plotH = H - padT - padB;

            const lamMax = Math.max(eig[N - 1], 1e-9);
            const yMax   = Math.max(...h0, ...hStar, 1e-9);
            const yMin   = Math.min(...h0, ...hStar, 1e-9);
            const logMin = Math.log(Math.max(yMin, 1e-8));
            const logMax = Math.log(Math.max(yMax, 1e-7));
            const logRng = Math.max(logMax - logMin, 1e-3);

            const xOf = (lam) => padL + (lam / lamMax) * plotW;
            const yOf = (h)   => padT + (1 - (Math.log(Math.max(h, 1e-8)) - logMin) / logRng) * plotH;

            const polyline = (values, stroke, dash) => {
                const ns = 'http://www.w3.org/2000/svg';
                const p  = document.createElementNS(ns, 'polyline');
                const pts = [];
                for (let i = 0; i < N; i++) {
                    pts.push(`${xOf(eig[i]).toFixed(1)},${yOf(values[i]).toFixed(1)}`);
                }
                p.setAttribute('points',        pts.join(' '));
                p.setAttribute('fill',          'none');
                p.setAttribute('stroke',        stroke);
                p.setAttribute('stroke-width',  '1.3');
                if (dash) p.setAttribute('stroke-dasharray', dash);
                svg.appendChild(p);
            };

            // Axis baseline
            const ns = 'http://www.w3.org/2000/svg';
            const axis = document.createElementNS(ns, 'line');
            axis.setAttribute('x1', padL);
            axis.setAttribute('y1', padT + plotH);
            axis.setAttribute('x2', W - padR);
            axis.setAttribute('y2', padT + plotH);
            axis.setAttribute('stroke', '#334155');
            axis.setAttribute('stroke-width', '0.5');
            svg.appendChild(axis);

            // Curves: h0 dashed (vacuum), h* solid (fixed point)
            polyline(h0,    '#64748b', '3,2');
            polyline(hStar, '#38bdf8', null);

            // Labels
            const label = (x, y, text, fill, size) => {
                const t = document.createElementNS(ns, 'text');
                t.setAttribute('x', x);
                t.setAttribute('y', y);
                t.setAttribute('fill', fill);
                t.setAttribute('font-size', String(size || 9));
                t.setAttribute('font-family', 'ui-monospace, Menlo, monospace');
                t.textContent = text;
                svg.appendChild(t);
            };
            label(padL, padT + 8,           'h(λ)',       '#94a3b8');
            label(W - padR - 56, padT + 8,  'h₀ dashed',  '#64748b');
            label(W - padR - 56, padT + 18, 'h* solid',   '#38bdf8');
            label(padL,          H - 2,     `λ 0`,        '#64748b');
            label(W - padR - 40, H - 2,     `λ_max ${lamMax.toExponential(2)}`, '#64748b');
        }

        clearChart() {
            const svg = document.getElementById('urbanSpectralChart');
            if (svg) while (svg.firstChild) svg.removeChild(svg.firstChild);
        }

        // ------------------------------------------------------------------
        // Diagnostics strip
        // ------------------------------------------------------------------

        renderDiagnostics(result) {
            const el = document.getElementById('urbanSpectralDiagnostics');
            if (!el) return;
            if (!result) { el.innerHTML = ''; return; }

            const d  = result.diagnostics || {};
            const fmt = (x, k = 3) =>
                (x === null || x === undefined || !Number.isFinite(x))
                    ? '·'
                    : Number(x).toFixed(k);

            const dH      = d.delta_H;
            const dHColor = (dH < -0.05) ? '#38bdf8'
                          : (dH >  0.05) ? '#f97316'
                                         : '#94a3b8';

            el.innerHTML = `
                <div>N = ${result.n_buildings} / ${result.n_buildings_total || result.n_buildings} buildings</div>
                <div>β₀ = ${d.beta0}, β₁ = ${d.beta1} (null ${d.beta1_null}) → Δβ₁ = <b>${d.delta_beta1 > 0 ? '+' : ''}${d.delta_beta1}</b></div>
                <div>λ_fiedler = ${fmt(d.lam_fiedler, 4)} · edges = ${d.n_edges}</div>
                <div>H[h*]  = ${fmt(d.H_obs)} · H[h₀] = ${fmt(d.H_vac)}</div>
                <div>ΔH = <span style="color:${dHColor};font-weight:700;">${fmt(dH)}</span> · Δ′ = ${fmt(d.delta_prime)} · converged: ${d.converged ? '✓' : '✗'} (${d.n_iter} iter)</div>
            `;
        }

        // ------------------------------------------------------------------
        // Fiedler overlay on globe
        // ------------------------------------------------------------------

        ensurePointCollection() {
            if (this.pointCollection &&
                !this.pointCollection.isDestroyed &&
                this.viewer.scene.primitives.contains(this.pointCollection)) {
                return this.pointCollection;
            }
            this.pointCollection = new Cesium.PointPrimitiveCollection();
            this.viewer.scene.primitives.add(this.pointCollection);
            return this.pointCollection;
        }

        renderOverlay(result) {
            if (!this.viewer || !Cesium) return;
            const coll = this.ensurePointCollection();
            coll.removeAll();

            const centroids = result.centroids_lonlat || [];
            const fv        = result.fiedler_vec || [];
            if (!centroids.length || !fv.length) return;

            const fvNorm = normalizeSigned(fv);
            const N      = Math.min(centroids.length, fvNorm.length);

            for (let i = 0; i < N; i++) {
                const [lon, lat] = centroids[i];
                const { r, g, b } = colormap(fvNorm[i]);
                coll.add({
                    position:      Cesium.Cartesian3.fromDegrees(lon, lat),
                    color:         Cesium.Color.fromBytes(r, g, b, 230),
                    pixelSize:     7,
                    outlineColor:  Cesium.Color.BLACK.withAlpha(0.45),
                    outlineWidth:  1,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY,
                });
            }
            coll.show = true;

            const btn = document.getElementById('urbanSpectralOverlayBtn');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-eye-slash"></i> Overlay';
                btn.style.background = '#0ea5e9';
                btn.style.color = 'white';
            }
            this._renderedAny = true;
        }

        toggleOverlay() {
            if (!this.pointCollection) return;
            this.pointCollection.show = !this.pointCollection.show;
            const btn = document.getElementById('urbanSpectralOverlayBtn');
            if (!btn) return;
            btn.innerHTML = this.pointCollection.show
                ? '<i class="fas fa-eye-slash"></i> Overlay'
                : '<i class="fas fa-eye"></i> Overlay';
            btn.style.background = this.pointCollection.show ? '#0ea5e9' : '#334155';
            btn.style.color      = this.pointCollection.show ? 'white'   : '#cbd5e1';
        }

        clearOverlay() {
            if (this.pointCollection && !this.pointCollection.isDestroyed) {
                this.pointCollection.removeAll();
                this.pointCollection.show = false;
            }
            const btn = document.getElementById('urbanSpectralOverlayBtn');
            if (btn) {
                btn.disabled = !this._renderedAny;
                btn.innerHTML = '<i class="fas fa-eye"></i> Overlay';
                btn.style.background = '#334155';
                btn.style.color      = '#cbd5e1';
            }
        }
    }

    // =====================================================================
    // Auto-initialize — match the world-sampler-ui.js discovery pattern so
    // the panel comes up on label_search, label_moon_viewer, etc.
    // =====================================================================

    function findViewer() {
        if (window.viewer)                                     return window.viewer;
        if (window.cesiumViewer)                               return window.cesiumViewer;
        if (window.DeepGISTopology && window.DeepGISTopology.viewer)
            return window.DeepGISTopology.viewer;
        return null;
    }

    function init() {
        if (window.urbanSpectralUI) return;
        const viewer = findViewer();
        if (viewer && window.Cesium) {
            try {
                window.urbanSpectralUI = new UrbanSpectralUI(viewer);
                console.log('[UrbanSpectral] UI ready');
            } catch (err) {
                console.error('[UrbanSpectral] init failed:', err);
            }
            return;
        }
        // retry until the viewer appears (matches World Sampler cadence)
        setTimeout(init, 1000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => setTimeout(init, 2200));
    } else {
        setTimeout(init, 2200);
    }

    // Expose the class for callers that want to construct manually.
    window.UrbanSpectralUI = UrbanSpectralUI;
})();
