/**
 * Rock label editor — canvas-based polygon editor with a draggable
 * 400x400 tile window. Drives both Workflow A ("correct AI predictions"
 * launched from the AI Analysis Report) and Workflow B ("label rocks on
 * Cesium" via /label/rocks/capture/), since both endpoints land here.
 *
 * Bootstrapped from `window.ROCK_LABEL_CTX` rendered by
 * `templates/web/rock_label_edit.html`.
 *
 * Coordinate spaces:
 *   - "image"  : pixels of the original query_image (W × H)
 *   - "canvas" : same as image, since canvas.width/height = W/H
 *   - "css"    : DOM pixels = image * scale (zoom factor)
 *   - "client" : viewport coords from MouseEvent.clientX/Y; converted
 *                via canvas.getBoundingClientRect() then / scale.
 */
(function () {
    'use strict';

    const ctx0 = window.ROCK_LABEL_CTX;
    if (!ctx0) {
        console.error('ROCK_LABEL_CTX missing');
        return;
    }

    // ---------------- Constants ---------------- //
    const TILE = ctx0.tileSize || 400;
    const VERTEX_RADIUS = 5;     // image-pixel hit radius for vertex grab
    const POLY_HIT_RADIUS = 4;   // for whole-polygon click (centroid select)
    const MODEL_TYPE = ctx0.modelType || 'unknown';
    const DEFAULT_CATEGORY = ctx0.defaultCategory || '';
    // SAM is class-agnostic — refuse to save polygons that haven't had
    // a category assigned yet. Other modes default to whatever the
    // model was trained for and let the user override.
    const STRICT_CATEGORIES = (MODEL_TYPE === 'sam');

    // Pre-baked palette from the server. Free-text categories the user
    // types in will get a stable hash colour computed in JS.
    const CATEGORY_PALETTE = ctx0.categoryPalette || {};
    const CATEGORY_CHIPS = ctx0.categoryChips || [
        'rock', 'building', 'vegetation', 'water', 'road', 'other'
    ];

    function rgbForCategory(name) {
        if (!name) return [239, 68, 68]; // unknown → red
        const direct = CATEGORY_PALETTE[name];
        if (direct) return direct;
        // Stable hash → HSV → RGB.
        let h = 0;
        for (let i = 0; i < name.length; i++) {
            h = (h * 31 + name.charCodeAt(i)) | 0;
        }
        const hue = ((h >>> 0) % 360) / 360;
        return hsv2rgb(hue, 0.65, 0.92);
    }
    function hsv2rgb(h, s, v) {
        const i = Math.floor(h * 6), f = h * 6 - i;
        const p = v * (1 - s);
        const q = v * (1 - f * s);
        const t = v * (1 - (1 - f) * s);
        let r, g, b;
        switch (i % 6) {
            case 0: r = v; g = t; b = p; break;
            case 1: r = q; g = v; b = p; break;
            case 2: r = p; g = v; b = t; break;
            case 3: r = p; g = q; b = v; break;
            case 4: r = t; g = p; b = v; break;
            case 5: r = v; g = p; b = q; break;
        }
        return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
    }
    function rgbStr(rgb, a) {
        const [r, g, b] = rgb;
        return a == null ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${a})`;
    }

    // ---------------- DOM ---------------- //
    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d');
    const wrap = document.getElementById('canvasWrap');
    const toolButtons = document.querySelectorAll('.tool-btn[data-tool]');
    const datasetSelect = document.getElementById('datasetSelect');
    const datasetName = document.getElementById('datasetName');
    const datasetThreshold = document.getElementById('datasetThreshold');
    const statTilePos = document.getElementById('statTilePos');
    const statPolysIn = document.getElementById('statPolysIn');
    const statSavedSession = document.getElementById('statSavedSession');
    const statSavedDataset = document.getElementById('statSavedDataset');
    const statThreshold = document.getElementById('statThreshold');
    const statPred = document.getElementById('statPred');
    const statAdded = document.getElementById('statAdded');
    const statApproved = document.getElementById('statApproved');
    const statDeleted = document.getElementById('statDeleted');
    const progressBar = document.getElementById('progressBar');
    const retrainStatus = document.getElementById('retrainStatus');
    const toast = document.getElementById('toast');
    // Category panel
    const categoryInput = document.getElementById('categoryInput');
    const categoryChipsEl = document.getElementById('categoryChips');
    const categoryHelpEl = document.getElementById('categoryHelp');
    const categorySelectedLabel = document.getElementById('categorySelectedLabel');
    const categoryBreakdownEl = document.getElementById('categoryBreakdown');
    const defaultCategoryInput = document.getElementById('defaultCategoryInput');

    canvas.width = ctx0.imageWidth;
    canvas.height = ctx0.imageHeight;

    // ---------------- State ---------------- //
    // _nextId must be initialised BEFORE the .map() below, otherwise the
    // hoisted nextId() reference hits its TDZ and the whole module dies
    // silently — leaving the editor with a black canvas. (Yes, exactly
    // the way it died on first load.)
    let _nextId = 0;
    function nextId() { return ++_nextId; }
    // initialPolygons is now [{points, category}, ...] from the server.
    // Tolerate the legacy [[[x,y],...], ...] shape just in case.
    /** @type {Array<{id:number, points: Array<[number,number]>, category:string, source: 'pred'|'user', approved: boolean, deleted: boolean}>} */
    const polygons = (ctx0.initialPolygons || []).map((entry) => {
        const isObj = entry && !Array.isArray(entry) && typeof entry === 'object';
        const pts = isObj ? (entry.points || []) : entry;
        const cat = isObj ? (entry.category || '') : '';
        return {
            id: nextId(),
            points: pts.map(p => [p[0], p[1]]),
            category: cat || DEFAULT_CATEGORY,
            source: 'pred',
            approved: false,
            deleted: false,
        };
    });

    const state = {
        tool: 'select',
        scale: 1.0,
        selectedId: null,
        // For 'add' tool: the in-progress polygon
        adding: null, // {points: [[x,y], ...]}
        // For 'edit' tool: which vertex of which polygon is being dragged
        editing: null, // {polyId, vertexIdx}
        // Tile box position in image coords
        tile: { x: 0, y: 0, w: TILE, h: TILE },
        tileDrag: null, // {dx, dy} when dragging the box
        savedThisSession: 0,
        currentDatasetId: null,
        // Category currently selected as "the next thing I'm drawing" — pre-fill
        // for new polygons, also applied via Shift+click to recolour. Starts
        // from the default category passed by the server.
        currentCategory: DEFAULT_CATEGORY,
    };

    // Place the tile box at the image centre by default.
    state.tile.x = Math.max(0, Math.floor(ctx0.imageWidth / 2 - TILE / 2));
    state.tile.y = Math.max(0, Math.floor(ctx0.imageHeight / 2 - TILE / 2));

    // ---------------- Image load ---------------- //
    const baseImg = new Image();
    baseImg.crossOrigin = 'anonymous';
    baseImg.onload = () => {
        fitToViewport();
        redraw();
    };
    baseImg.onerror = () => {
        showToast('Failed to load image: ' + ctx0.imageUrl, 'error');
    };
    baseImg.src = ctx0.imageUrl;

    // ---------------- Drawing ---------------- //
    function setScale(s, anchor) {
        const newScale = Math.max(0.1, Math.min(8, s));
        if (Math.abs(newScale - state.scale) < 1e-6) return;
        // Preserve scroll anchor (keep the point under cursor stable)
        let anchorRatio = null;
        if (anchor) {
            const before = wrap.getBoundingClientRect();
            const fx = (anchor.clientX - before.left + wrap.scrollLeft) / state.scale;
            const fy = (anchor.clientY - before.top + wrap.scrollTop) / state.scale;
            anchorRatio = { fx, fy, ax: anchor.clientX - before.left, ay: anchor.clientY - before.top };
        }
        state.scale = newScale;
        canvas.style.width = (canvas.width * newScale) + 'px';
        canvas.style.height = (canvas.height * newScale) + 'px';
        if (anchorRatio) {
            wrap.scrollLeft = anchorRatio.fx * newScale - anchorRatio.ax;
            wrap.scrollTop = anchorRatio.fy * newScale - anchorRatio.ay;
        }
    }

    function fitToViewport() {
        const r = wrap.getBoundingClientRect();
        const sx = r.width / canvas.width;
        const sy = r.height / canvas.height;
        setScale(Math.min(sx, sy) * 0.95);
    }

    function clientToImage(evt) {
        const r = canvas.getBoundingClientRect();
        const x = (evt.clientX - r.left) / state.scale;
        const y = (evt.clientY - r.top) / state.scale;
        return [x, y];
    }

    function redraw() {
        ctx.save();
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        if (baseImg.complete && baseImg.naturalWidth) {
            ctx.drawImage(baseImg, 0, 0, canvas.width, canvas.height);
        }

        // Dim everything outside the tile box.
        ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
        ctx.beginPath();
        ctx.rect(0, 0, canvas.width, canvas.height);
        // Counter-clockwise inner = punch-out
        ctx.rect(state.tile.x + state.tile.w, state.tile.y, -state.tile.w, state.tile.h);
        ctx.fill('evenodd');

        // Tile box border + 4-px corner ticks for affordance.
        ctx.lineWidth = 2;
        ctx.strokeStyle = state.tool === 'tile' ? '#10b981' : 'rgba(16, 185, 129, 0.7)';
        ctx.setLineDash([6, 4]);
        ctx.strokeRect(state.tile.x + 1, state.tile.y + 1, state.tile.w - 2, state.tile.h - 2);
        ctx.setLineDash([]);

        // Polygons (skip deleted)
        for (const p of polygons) {
            if (p.deleted) continue;
            drawPolygon(p);
        }

        // In-progress polygon
        if (state.adding) {
            drawAddingPolygon(state.adding);
        }

        ctx.restore();
        updateStats();
    }

    function drawPolygon(p) {
        if (!p.points.length) return;
        const isSelected = p.id === state.selectedId;
        // Colour is driven by category. The dashed outline mode signals
        // "no category set" so the user can spot SAM segments that still
        // need an assignment at a glance.
        const hasCat = !!p.category;
        const rgb = rgbForCategory(p.category);
        const fill = rgbStr(rgb, p.approved ? 0.32 : 0.18);
        const stroke = rgbStr(rgb, 0.95);

        ctx.beginPath();
        ctx.moveTo(p.points[0][0], p.points[0][1]);
        for (let i = 1; i < p.points.length; i++) ctx.lineTo(p.points[i][0], p.points[i][1]);
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.fill();
        if (!hasCat) {
            ctx.setLineDash([6, 4]);
        }
        ctx.lineWidth = isSelected ? 3 : (p.approved ? 2.2 : 1.5);
        ctx.strokeStyle = isSelected ? '#f43f5e' : stroke;
        ctx.stroke();
        ctx.setLineDash([]);

        // Approved tick mark in the centroid for legibility on small polys.
        if (p.approved) {
            const [cx, cy] = polygonCentroid(p.points);
            ctx.fillStyle = rgbStr(rgb, 1);
            ctx.beginPath();
            ctx.arc(cx, cy, 3, 0, Math.PI * 2);
            ctx.fill();
        }

        // Per-polygon category label, rendered in image coords. Skip when
        // we're zoomed way out — the text would just clutter the canvas.
        if (state.scale >= 0.5 && p.points.length >= 3) {
            const [cx, cy] = polygonCentroid(p.points);
            const text = hasCat ? p.category : '⚠ no category';
            // Counter-scale so the label stays roughly screen-sized
            // regardless of zoom.
            const fontPx = Math.max(10, Math.min(20, 12 / state.scale));
            ctx.save();
            ctx.font = `${fontPx}px ui-monospace, SFMono-Regular, Menlo, monospace`;
            const metrics = ctx.measureText(text);
            const padX = 4 / state.scale;
            const padY = 2 / state.scale;
            const w = metrics.width + padX * 2;
            const h = fontPx + padY * 2;
            ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
            ctx.strokeStyle = stroke;
            ctx.lineWidth = 1 / state.scale;
            ctx.beginPath();
            ctx.rect(cx - w / 2, cy - h / 2, w, h);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = hasCat ? '#e2e8f0' : '#fbbf24';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(text, cx, cy);
            ctx.restore();
        }

        // Vertex handles only when in edit mode + selected
        if (state.tool === 'edit' && isSelected) {
            ctx.fillStyle = '#fbbf24';
            ctx.strokeStyle = '#000';
            ctx.lineWidth = 1;
            for (const v of p.points) {
                ctx.beginPath();
                ctx.arc(v[0], v[1], VERTEX_RADIUS, 0, Math.PI * 2);
                ctx.fill();
                ctx.stroke();
            }
        }
    }

    function drawAddingPolygon(adding) {
        if (!adding.points.length) return;
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = '#fbbf24';
        ctx.fillStyle = 'rgba(251, 191, 36, 0.18)';
        ctx.beginPath();
        ctx.moveTo(adding.points[0][0], adding.points[0][1]);
        for (let i = 1; i < adding.points.length; i++) ctx.lineTo(adding.points[i][0], adding.points[i][1]);
        if (adding.points.length >= 3) ctx.closePath();
        ctx.fill();
        ctx.stroke();
        // Vertex dots
        ctx.fillStyle = '#fbbf24';
        for (const v of adding.points) {
            ctx.beginPath();
            ctx.arc(v[0], v[1], 4, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    // ---------------- Geometry helpers ---------------- //
    function pointInPolygon(x, y, points) {
        let inside = false;
        for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
            const [xi, yi] = points[i];
            const [xj, yj] = points[j];
            const intersect = ((yi > y) !== (yj > y)) &&
                (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi);
            if (intersect) inside = !inside;
        }
        return inside;
    }

    function polygonCentroid(points) {
        if (!points.length) return [0, 0];
        let sx = 0, sy = 0;
        for (const p of points) { sx += p[0]; sy += p[1]; }
        return [sx / points.length, sy / points.length];
    }

    function findPolygonAt(x, y) {
        // Iterate in reverse so user-added polygons (drawn last) are picked first.
        for (let i = polygons.length - 1; i >= 0; i--) {
            const p = polygons[i];
            if (p.deleted) continue;
            if (pointInPolygon(x, y, p.points)) return p;
        }
        return null;
    }

    function findVertexAt(x, y, poly) {
        for (let i = 0; i < poly.points.length; i++) {
            const [vx, vy] = poly.points[i];
            const d = Math.hypot(vx - x, vy - y);
            if (d <= VERTEX_RADIUS + 2) return i;
        }
        return -1;
    }

    function pointInTile(x, y) {
        return x >= state.tile.x && x <= state.tile.x + state.tile.w
            && y >= state.tile.y && y <= state.tile.y + state.tile.h;
    }

    // ---------------- Mouse handlers ---------------- //
    canvas.addEventListener('mousedown', (e) => {
        const [x, y] = clientToImage(e);

        if (state.tool === 'tile') {
            if (pointInTile(x, y)) {
                state.tileDrag = { dx: x - state.tile.x, dy: y - state.tile.y };
                wrap.classList.add('dragging');
                e.preventDefault();
            }
            return;
        }

        if (state.tool === 'add') {
            if (!state.adding) state.adding = { points: [] };
            state.adding.points.push([x, y]);
            redraw();
            return;
        }

        if (state.tool === 'edit') {
            const sel = polygons.find(p => p.id === state.selectedId && !p.deleted);
            if (sel) {
                const vi = findVertexAt(x, y, sel);
                if (vi >= 0) {
                    state.editing = { polyId: sel.id, vertexIdx: vi };
                    return;
                }
            }
            // Clicked elsewhere → select polygon under cursor
            const hit = findPolygonAt(x, y);
            state.selectedId = hit ? hit.id : null;
            // Shift+click on the canvas to stamp the staged category onto
            // whatever polygon is under the cursor — handy for SAM where
            // dozens of polygons need the same label.
            if (hit && e.shiftKey && state.currentCategory) {
                hit.category = state.currentCategory;
            }
            syncCategoryPanel();
            redraw();
            return;
        }

        if (state.tool === 'select') {
            const hit = findPolygonAt(x, y);
            state.selectedId = hit ? hit.id : null;
            if (hit && e.shiftKey && state.currentCategory) {
                hit.category = state.currentCategory;
            }
            syncCategoryPanel();
            redraw();
            return;
        }
    });

    canvas.addEventListener('mousemove', (e) => {
        const [x, y] = clientToImage(e);
        if (state.tileDrag) {
            const nx = Math.round(x - state.tileDrag.dx);
            const ny = Math.round(y - state.tileDrag.dy);
            state.tile.x = clamp(nx, 0, ctx0.imageWidth - state.tile.w);
            state.tile.y = clamp(ny, 0, ctx0.imageHeight - state.tile.h);
            redraw();
            return;
        }
        if (state.editing) {
            const p = polygons.find(pp => pp.id === state.editing.polyId);
            if (p) {
                p.points[state.editing.vertexIdx] = [x, y];
                redraw();
            }
        }
    });

    canvas.addEventListener('mouseup', () => {
        state.tileDrag = null;
        wrap.classList.remove('dragging');
        state.editing = null;
    });

    canvas.addEventListener('dblclick', (e) => {
        if (state.tool === 'add' && state.adding && state.adding.points.length >= 3) {
            commitAddingPolygon();
        }
    });

    canvas.addEventListener('wheel', (e) => {
        if (!e.ctrlKey && !e.metaKey) return; // ctrl/cmd + wheel = zoom
        e.preventDefault();
        const factor = e.deltaY > 0 ? 0.9 : 1.1;
        setScale(state.scale * factor, e);
    }, { passive: false });

    function commitAddingPolygon() {
        if (!state.adding || state.adding.points.length < 3) {
            state.adding = null;
            redraw();
            return;
        }
        const p = {
            id: nextId(),
            points: state.adding.points,
            // New polygons inherit whatever the user has staged in the
            // category panel — empty if nothing's been picked yet.
            category: state.currentCategory,
            source: 'user',
            approved: false,
            deleted: false,
        };
        polygons.push(p);
        state.adding = null;
        state.selectedId = p.id;
        syncCategoryPanel();
        redraw();
    }

    // ---------------- Toolbar wiring ---------------- //
    function setTool(tool) {
        // Cancel any in-progress add when switching away from "add"
        if (state.tool === 'add' && tool !== 'add') {
            state.adding = null;
        }
        state.tool = tool;
        toolButtons.forEach(b => {
            b.classList.toggle('active', b.dataset.tool === tool);
        });
        wrap.classList.remove('adding', 'editing');
        if (tool === 'add') wrap.classList.add('adding');
        if (tool === 'edit') wrap.classList.add('editing');
        redraw();
    }

    toolButtons.forEach(b => {
        b.addEventListener('click', () => setTool(b.dataset.tool));
    });

    document.getElementById('btnDelete').addEventListener('click', deleteSelected);
    document.getElementById('btnApprove').addEventListener('click', approveSelected);

    // ---------------- Category panel ---------------- //
    function getSelectedPolygon() {
        return polygons.find(pp => pp.id === state.selectedId && !pp.deleted) || null;
    }

    function applyCategoryToSelected(catName) {
        const p = getSelectedPolygon();
        const name = (catName || '').trim();
        state.currentCategory = name;
        if (p) {
            p.category = name;
        }
        syncCategoryPanel();
        redraw();
    }

    function syncCategoryPanel() {
        const p = getSelectedPolygon();
        if (categorySelectedLabel) {
            categorySelectedLabel.textContent = p
                ? (p.category ? p.category : '⚠ none — pick one')
                : 'no polygon selected';
            categorySelectedLabel.style.color = (p && !p.category) ? '#fbbf24' : '#60a5fa';
        }
        if (categoryInput) {
            categoryInput.value = p ? (p.category || '') : state.currentCategory;
        }
        if (categoryChipsEl) {
            for (const chip of categoryChipsEl.querySelectorAll('.cat-chip')) {
                const cn = chip.dataset.cat;
                chip.classList.toggle('active', !!p && cn === (p.category || ''));
                chip.classList.toggle('staged', !p && cn === state.currentCategory);
            }
        }
        if (categoryBreakdownEl) {
            const counts = {};
            for (const pp of polygons) {
                if (pp.deleted) continue;
                const k = pp.category || '⚠ unset';
                counts[k] = (counts[k] || 0) + 1;
            }
            const rows = Object.entries(counts)
                .sort((a, b) => b[1] - a[1])
                .map(([k, n]) => {
                    const rgb = rgbForCategory(k.startsWith('⚠') ? '' : k);
                    const swatch = `<span class="dot" style="background:${rgbStr(rgb, 1)}"></span>`;
                    return `<div class="stat-row"><span>${swatch}${k}</span><span class="v">${n}</span></div>`;
                })
                .join('');
            categoryBreakdownEl.innerHTML = rows
                || '<div class="keyboard-hint">No polygons yet.</div>';
        }
    }

    function buildCategoryChips() {
        if (!categoryChipsEl) return;
        categoryChipsEl.innerHTML = '';
        for (const cn of CATEGORY_CHIPS) {
            const rgb = rgbForCategory(cn);
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'cat-chip';
            chip.dataset.cat = cn;
            chip.style.borderColor = rgbStr(rgb, 0.95);
            chip.innerHTML = `<span class="dot" style="background:${rgbStr(rgb, 1)}"></span>${cn}`;
            chip.addEventListener('click', () => applyCategoryToSelected(cn));
            categoryChipsEl.appendChild(chip);
        }
    }

    if (categoryInput) {
        categoryInput.addEventListener('change', () => {
            applyCategoryToSelected(categoryInput.value);
        });
        categoryInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                applyCategoryToSelected(categoryInput.value);
                categoryInput.blur();
            }
        });
    }
    if (defaultCategoryInput) {
        defaultCategoryInput.addEventListener('change', () => {
            state.currentCategory = (defaultCategoryInput.value || '').trim();
            syncCategoryPanel();
        });
    }
    buildCategoryChips();
    if (defaultCategoryInput) defaultCategoryInput.value = DEFAULT_CATEGORY;
    if (categoryHelpEl) {
        if (STRICT_CATEGORIES) {
            categoryHelpEl.textContent =
                'SAM is class-agnostic — every polygon needs a category before saving.';
            categoryHelpEl.classList.add('warn');
        } else if (MODEL_TYPE === 'maskrcnn_rocks') {
            categoryHelpEl.textContent =
                'Mask R-CNN predictions arrive labelled "rock". Override per-polygon when the detector confused, e.g., a building or parking lot for a rock.';
        } else {
            categoryHelpEl.textContent =
                'Pick a category for each polygon. Free-text names are allowed.';
        }
    }
    document.getElementById('btnFit').addEventListener('click', () => { fitToViewport(); redraw(); });
    document.getElementById('btnZoomIn').addEventListener('click', () => { setScale(state.scale * 1.25); redraw(); });
    document.getElementById('btnZoomOut').addEventListener('click', () => { setScale(state.scale / 1.25); redraw(); });
    document.getElementById('btnSaveTile').addEventListener('click', saveTile);

    function deleteSelected() {
        const p = polygons.find(pp => pp.id === state.selectedId && !pp.deleted);
        if (!p) return;
        if (p.source === 'pred') {
            p.deleted = true;
        } else {
            // User polygon: actually remove
            const idx = polygons.indexOf(p);
            if (idx >= 0) polygons.splice(idx, 1);
        }
        state.selectedId = null;
        redraw();
    }

    function approveSelected() {
        const p = polygons.find(pp => pp.id === state.selectedId && !pp.deleted);
        if (!p) return;
        p.approved = !p.approved;
        redraw();
    }

    // ---------------- Keyboard shortcuts ---------------- //
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        switch (e.key.toLowerCase()) {
            case 'v': setTool('select'); break;
            case 'a': setTool('add'); break;
            case 'e': setTool('edit'); break;
            case 't': setTool('tile'); break;
            case 'y': approveSelected(); break;
            case 'delete':
            case 'backspace':
                deleteSelected(); break;
            case 'enter':
                if (state.tool === 'add' && state.adding && state.adding.points.length >= 3) {
                    commitAddingPolygon();
                } else {
                    saveTile();
                }
                break;
            case 'escape':
                state.adding = null;
                state.selectedId = null;
                redraw();
                break;
            case 'f': fitToViewport(); redraw(); break;
            case '+': case '=': setScale(state.scale * 1.25); redraw(); break;
            case '-': case '_': setScale(state.scale / 1.25); redraw(); break;
            case 'c':
                // Focus the category text field so the user can type a
                // class name for the selected (or next-drawn) polygon.
                if (categoryInput) {
                    categoryInput.focus();
                    categoryInput.select();
                    e.preventDefault();
                }
                break;
        }
    });

    // ---------------- Stats ---------------- //
    function updateStats() {
        const live = polygons.filter(p => !p.deleted);
        const pred = live.filter(p => p.source === 'pred').length;
        const added = live.filter(p => p.source === 'user').length;
        const approved = live.filter(p => p.approved).length;
        const deleted = polygons.filter(p => p.deleted).length;
        statPred.textContent = pred;
        statAdded.textContent = added;
        statApproved.textContent = approved;
        statDeleted.textContent = deleted;

        statTilePos.textContent = `${state.tile.x},${state.tile.y}`;

        const inTile = live.filter(p => {
            const [cx, cy] = polygonCentroid(p.points);
            return pointInTile(cx, cy);
        }).length;
        statPolysIn.textContent = inTile;
    }

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    // ---------------- Save tile ---------------- //
    async function saveTile() {
        const datasetId = datasetSelect.value || null;
        const name = (datasetName.value || '').trim();
        const minTiles = parseInt(datasetThreshold.value || '50', 10);
        if (!datasetId && !name) {
            showToast('Pick a dataset or enter a new name', 'error');
            return;
        }

        const live = polygons.filter(p => !p.deleted);
        const inTile = live
            .map(p => ({ p, c: polygonCentroid(p.points) }))
            .filter(({ c }) => pointInTile(c[0], c[1]))
            .map(({ p }) => p);

        // Strict-category mode (SAM): any polygon inside the tile that
        // doesn't have a category yet is a hard error — flag and bail
        // before hitting the server.
        if (STRICT_CATEGORIES) {
            const missing = inTile.filter(p => !p.category).length;
            if (missing > 0) {
                showToast(
                    `${missing} polygon(s) in tile have no category. Click them and pick one (C) before saving.`,
                    'error'
                );
                return;
            }
        }

        const polysOut = inTile.map(p => ({
            points: p.points.map(pt => [pt[0], pt[1]]),
            category: p.category || state.currentCategory || '',
        }));

        const corrections = {
            session_id: ctx0.sessionId,
            model_type: MODEL_TYPE,
            initial_pred_count: ctx0.initialPolygons.length,
            kept_pred_count: live.filter(p => p.source === 'pred').length,
            deleted_pred_count: polygons.filter(p => p.deleted && p.source === 'pred').length,
            user_added_count: live.filter(p => p.source === 'user').length,
            approved_count: live.filter(p => p.approved).length,
            recategorized_count: live.filter(
                p => p.source === 'pred' && p.category !== DEFAULT_CATEGORY
            ).length,
            scale_at_save: state.scale,
        };

        const body = {
            tile: { x: state.tile.x, y: state.tile.y, w: state.tile.w, h: state.tile.h },
            polygons: polysOut,
            default_category: state.currentCategory || DEFAULT_CATEGORY,
            strict_categories: STRICT_CATEGORIES,
            dataset_name: name,
            dataset_id: datasetId ? parseInt(datasetId, 10) : null,
            min_tiles: minTiles,
            corrections,
        };

        try {
            const resp = await fetch(ctx0.urls.saveTile, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrf(),
                },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || resp.statusText);

            state.savedThisSession += 1;
            statSavedSession.textContent = state.savedThisSession;
            const ds = data.dataset;
            state.currentDatasetId = ds.id;
            statSavedDataset.textContent = `${ds.num_annotations}`;
            statThreshold.textContent = ds.min_tiles_for_training;
            const pct = Math.min(100, (ds.num_annotations / ds.min_tiles_for_training) * 100);
            progressBar.style.width = pct.toFixed(1) + '%';
            if (data.retrain_sentinel_dropped || ds.status === 'ready') {
                retrainStatus.style.display = 'block';
            }

            // Refresh dataset list so the new dataset shows up if we just created it.
            await refreshDatasets(ds.id);

            const counts = data.category_counts || {};
            const breakdown = Object.entries(counts)
                .map(([k, n]) => `${n} ${k}`).join(', ') || `${data.num_polygons} poly`;
            showToast(
                `Saved tile (${breakdown}) → dataset “${ds.name}” (${ds.num_annotations}/${ds.min_tiles_for_training})`,
                'success'
            );

            // Auto-advance the tile box: shift right by one tile, wrap to next row.
            advanceTile();
            redraw();
        } catch (err) {
            console.error(err);
            showToast('Save failed: ' + err.message, 'error');
        }
    }

    function advanceTile() {
        let nx = state.tile.x + state.tile.w;
        let ny = state.tile.y;
        if (nx + state.tile.w > ctx0.imageWidth) {
            nx = 0;
            ny = state.tile.y + state.tile.h;
            if (ny + state.tile.h > ctx0.imageHeight) {
                ny = 0;
            }
        }
        state.tile.x = nx;
        state.tile.y = ny;
    }

    // ---------------- Datasets dropdown ---------------- //
    async function refreshDatasets(selectId) {
        try {
            const resp = await fetch(ctx0.urls.datasets, { credentials: 'same-origin' });
            if (!resp.ok) return;
            // /label/rocks/datasets/ is @login_required. If the user
            // hasn't logged in yet, Django returns the login page (HTML).
            // Detect & skip without spamming the console.
            const ctype = resp.headers.get('content-type') || '';
            if (!ctype.includes('json')) return;
            const data = await resp.json();
            const current = datasetSelect.value;
            datasetSelect.innerHTML = '<option value="">— Create new below —</option>';
            for (const d of (data.datasets || [])) {
                const opt = document.createElement('option');
                opt.value = d.id;
                opt.textContent = `${d.name} (${d.num_annotations}/${d.min_tiles_for_training}, ${d.status})`;
                datasetSelect.appendChild(opt);
            }
            const want = selectId || current;
            if (want) {
                datasetSelect.value = String(want);
                if (datasetSelect.value === String(want)) {
                    const found = (data.datasets || []).find(d => String(d.id) === String(want));
                    if (found) {
                        statSavedDataset.textContent = found.num_annotations;
                        statThreshold.textContent = found.min_tiles_for_training;
                        const pct = Math.min(100, (found.num_annotations / found.min_tiles_for_training) * 100);
                        progressBar.style.width = pct.toFixed(1) + '%';
                        if (found.status === 'ready') retrainStatus.style.display = 'block';
                    }
                }
            }
        } catch (err) {
            console.warn('refreshDatasets failed', err);
        }
    }

    // ---------------- Misc ---------------- //
    function getCsrf() {
        const m = document.querySelector('input[name=csrfmiddlewaretoken]');
        if (m) return m.value;
        const cookie = document.cookie.split('; ').find(r => r.startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    }

    function showToast(msg, type) {
        toast.textContent = msg;
        toast.className = type || '';
        toast.style.display = 'block';
        clearTimeout(showToast._t);
        showToast._t = setTimeout(() => { toast.style.display = 'none'; }, 4500);
    }

    // ---------------- Init ---------------- //
    setTool('select');
    syncCategoryPanel();
    redraw();
    refreshDatasets();
    statThreshold.textContent = datasetThreshold.value;

    // Re-fit on viewport resize (keeps the canvas usable on small screens)
    window.addEventListener('resize', () => {
        // Don't auto-refit on every resize — it's annoying mid-edit.
        redraw();
    });
})();
