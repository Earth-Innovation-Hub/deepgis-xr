// DeepGIS HUD AI panel: model options, sliders and per-user panel preferences.
(function() {
    const onReady = (fn) => (document.readyState === 'loading'
        ? document.addEventListener('DOMContentLoaded', fn)
        : fn());

    const PREF_KEY = 'ai_panel';
    const PREF_URL = '/webclient/sampler/world/preferences';
    const SG_MODEL_IDS = ['sgKernelSam3', 'sgKernelYolo', 'sgKernelGroundingDino', 'sgKernelSam', 'sgKernelMrRocks'];

    onReady(() => {
        const panel = document.getElementById('aiPanel');
        if (!panel) return;
        const byId = (id) => document.getElementById(id);

        const optionPanels = {
            'sam3': 'sam3Options',
            'sam': 'samOptions',
            'yolov8': 'yolov8Options',
            'grounding_dino': 'groundingDinoOptions',
            'maskrcnn_rocks': 'maskrcnnRocksOptions'
        };
        const descriptions = {
            'sam3': 'Masks every object you name. Slowest (about 30 s) but the best outlines.',
            'sam': 'Outlines every region, without labels.',
            'yolov8': 'YOLO26 finds 80 everyday classes such as cars and people; YOLOE-26 finds the classes you list.',
            'grounding_dino': 'Boxes for the objects you describe, separated with dots.',
            'maskrcnn_rocks': 'Rock instances from the Bishop/Jezero Mask R-CNN models.'
        };

        const analysisSelect = byId('analysisTypeSelect');
        const showOptions = () => {
            const type = analysisSelect.value;
            Object.entries(optionPanels).forEach(([key, id]) => {
                const el = byId(id);
                if (el) el.style.display = type === key ? 'block' : 'none';
            });
            const desc = byId('analysisDescription');
            if (desc) desc.textContent = descriptions[type] || '';
        };
        if (analysisSelect) {
            analysisSelect.addEventListener('change', showOptions);
            showOptions();
        }

        const bindSlider = (sliderId, valueId, format) => {
            const slider = byId(sliderId);
            const value = byId(valueId);
            if (slider && value) {
                slider.addEventListener('input', (e) => {
                    value.textContent = format(e.target.value);
                });
            }
        };
        const asFraction = (v) => (parseFloat(v) / 100).toFixed(2);
        const asPercent = (v) => v + '%';

        bindSlider('maskrcnnRocksScore', 'maskrcnnRocksScoreValue', asFraction);
        bindSlider('sam3Confidence', 'sam3ConfidenceValue', asPercent);
        bindSlider('yolov8Confidence', 'yolov8ConfidenceValue', asPercent);
        bindSlider('gdBoxThreshold', 'gdBoxThresholdValue', asFraction);
        bindSlider('gdTextThreshold', 'gdTextThresholdValue', asFraction);

        if (panel.dataset.signedIn !== '1') return;

        // Remember the model choice, object lists and scene-graph models per user.
        const readPrefs = () => {
            const prefs = {};
            if (analysisSelect) prefs.analysis_type = analysisSelect.value;
            if (byId('sam3Prompts')) prefs.sam3_prompts = byId('sam3Prompts').value;
            if (byId('sgPrompts')) {
                prefs.sg_prompts = byId('sgPrompts').value;
                prefs.sg_models = SG_MODEL_IDS.filter((id) => byId(id)?.checked);
            }
            if (byId('wmAt')) prefs.wm_at = byId('wmAt').value;
            return prefs;
        };
        const applyPrefs = (prefs) => {
            if (!prefs || typeof prefs !== 'object') return;
            if (analysisSelect && prefs.analysis_type
                && analysisSelect.querySelector(`option[value="${CSS.escape(prefs.analysis_type)}"]`)) {
                analysisSelect.value = prefs.analysis_type;
                showOptions();
            }
            if (typeof prefs.sam3_prompts === 'string' && prefs.sam3_prompts && byId('sam3Prompts')) {
                byId('sam3Prompts').value = prefs.sam3_prompts;
            }
            if (byId('sgPrompts')) {
                if (typeof prefs.sg_prompts === 'string' && prefs.sg_prompts) byId('sgPrompts').value = prefs.sg_prompts;
                if (Array.isArray(prefs.sg_models) && prefs.sg_models.length) {
                    SG_MODEL_IDS.forEach((id) => { if (byId(id)) byId(id).checked = prefs.sg_models.includes(id); });
                }
            }
            if (typeof prefs.wm_at === 'string' && byId('wmAt')
                && byId('wmAt').querySelector(`option[value="${CSS.escape(prefs.wm_at)}"]`)) {
                byId('wmAt').value = prefs.wm_at;
            }
        };

        let saveTimer = null;
        const saveSoon = () => {
            clearTimeout(saveTimer);
            saveTimer = setTimeout(() => {
                fetch(PREF_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ [PREF_KEY]: readPrefs() }),
                }).catch(() => {});
            }, 800);
        };

        fetch(PREF_URL)
            .then((r) => (r.ok ? r.json() : null))
            .then((payload) => applyPrefs(payload?.preferences?.[PREF_KEY]))
            .catch(() => {})
            .finally(() => {
                ['analysisTypeSelect', 'sam3Prompts', 'sgPrompts', 'wmAt', ...SG_MODEL_IDS].forEach((id) => {
                    byId(id)?.addEventListener('change', saveSoon);
                });
            });
    });
})();
