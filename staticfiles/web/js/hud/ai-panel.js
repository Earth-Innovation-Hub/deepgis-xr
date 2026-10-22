// DeepGIS HUD AI panel: model registry, analysis-type options and threshold sliders.
(function() {
    const onReady = (fn) => (document.readyState === 'loading'
        ? document.addEventListener('DOMContentLoaded', fn)
        : fn());

    onReady(() => {
        // Configuration for the six MaskRCNN sibling services running
        // alongside rocks (:5002) / house (:5003). Centralising this
        // table keeps the dropdown, the request builder and the
        // SceneGraph orchestrator in agreement on port + placeholder.
        // If you add another sibling service, extend this map plus
        // the matching elif branches in world-sampler-ui.js.
        window.MASKRCNN_SIBLING_CONFIG = window.MASKRCNN_SIBLING_CONFIG || {
            'maskrcnn_hypolith': {
                port: 5004,
                placeholder: 'e.g. epoch_0011 (Gobabeb hypolith)',
                description: 'Hypolith detection — Gobabeb/Namib Mask R-CNN (remote GPU at :5004). Single class "hypolith"; trained on Joshua Tree + Atacama + Namib desert ground-level imagery.'
            },
            'maskrcnn_litter': {
                port: 5005,
                placeholder: 'e.g. epoch_0008 (DeepGIS litter)',
                description: 'Litter / debris detection — DeepGIS dynamics Mask R-CNN (remote GPU at :5005). Note: epoch_0008.param weights are byte-identical to NewLife — predictions may overlap until distinct checkpoints are recovered.'
            },
            'maskrcnn_roadkill': {
                port: 5006,
                placeholder: 'e.g. roadkill_epoch_0004_sarah',
                description: 'Roadkill detection — Sarah preview Mask R-CNN (remote GPU at :5006). Single class "roadkill"; e0004 checkpoint, low training corpus — treat as a triage filter, not ground truth.'
            },
            'maskrcnn_newlife': {
                port: 5007,
                placeholder: 'e.g. epoch_0008 (DeepGIS newlife)',
                description: 'New-life / organism detection — DeepGIS biology Mask R-CNN (remote GPU at :5007). Note: epoch_0008.param weights are byte-identical to Litter — predictions may overlap until distinct checkpoints are recovered.'
            },
            'maskrcnn_brent_moon_craters': {
                port: 5008,
                placeholder: 'e.g. download_openuas_us__epoch_0099 (Brent)',
                description: 'Lunar crater detection — Brent\'s Mask R-CNN on LROC NAC tiles (remote GPU at :5008). Class "crater"; tuned for Moon imagery, not Mars.'
            },
            'maskrcnn_harish_moon_craters': {
                port: 5009,
                placeholder: 'e.g. download_openuas_us__epoch_0099 (Harish)',
                description: 'Lunar crater detection — Harish\'s Mask R-CNN on LROC NAC tiles (remote GPU at :5009). Class "crater"; complementary checkpoint to Brent\'s for cross-checking.'
            }
        };
        window.MASKRCNN_SIBLING_TYPES = window.MASKRCNN_SIBLING_TYPES ||
            new Set(Object.keys(window.MASKRCNN_SIBLING_CONFIG));

        // Analysis type toggle (for AI panel)
        const analysisSelect = document.getElementById('analysisTypeSelect');
        if (analysisSelect) {
            analysisSelect.addEventListener('change', (e) => {
                const type = e.target.value;
                document.getElementById('samOptions').style.display = type === 'sam' ? 'block' : 'none';
                document.getElementById('yolov8Options').style.display = type === 'yolov8' ? 'block' : 'none';
                document.getElementById('groundingDinoOptions').style.display = type === 'grounding_dino' ? 'block' : 'none';
                document.getElementById('groundedSamOptions').style.display = type === 'grounded_sam' ? 'block' : 'none';
                const maskrcnnRocksOpts = document.getElementById('maskrcnnRocksOptions');
                if (maskrcnnRocksOpts) maskrcnnRocksOpts.style.display = type === 'maskrcnn_rocks' ? 'block' : 'none';
                const maskrcnnHouseOpts = document.getElementById('maskrcnnHouseOptions');
                if (maskrcnnHouseOpts) maskrcnnHouseOpts.style.display = type === 'maskrcnn_house' ? 'block' : 'none';
                const maskrcnnSiblingOpts = document.getElementById('maskrcnnSiblingOptions');
                const isSibling = window.MASKRCNN_SIBLING_TYPES.has(type);
                if (maskrcnnSiblingOpts) maskrcnnSiblingOpts.style.display = isSibling ? 'block' : 'none';
                if (isSibling) {
                    const cfg = window.MASKRCNN_SIBLING_CONFIG[type];
                    const modelIdInput = document.getElementById('maskrcnnSiblingModelId');
                    const registryHint = document.getElementById('maskrcnnSiblingRegistryHint');
                    if (modelIdInput) modelIdInput.placeholder = cfg.placeholder;
                    if (registryHint) {
                        registryHint.textContent = `Full registry: GET http://192.168.0.232:${cfg.port}/api/models`;
                    }
                }
                document.getElementById('zeroShotOptions').style.display = type === 'zero_shot' ? 'block' : 'none';
                document.getElementById('mask2formerOptions').style.display = type === 'mask2former' ? 'block' : 'none';

                const desc = document.getElementById('analysisDescription');
                if (desc) {
                    const descriptions = {
                        'sam': 'Segments all visible regions using Segment Anything Model',
                        'yolov8': 'Ultra-fast detection with 80 COCO classes',
                        'grounding_dino': 'Text-based open-vocabulary object detection',
                        'grounded_sam': 'Detection + high-quality segmentation with text prompts',
                        'maskrcnn_rocks': 'Rock instance segmentation using Bishop/Jezero Mask R-CNN checkpoints (remote GPU at :5002)',
                        'maskrcnn_house': 'House / damage detection using the Tornado/Eureka Mask R-CNN ensemble (remote GPU at :5003). Trained on UAV-oblique tornado imagery — on overhead 3D-tile captures it tends to fire as a generic roof detector.',
                        'zero_shot': 'Detects common objects (person, car, etc.)',
                        'mask2former': 'State-of-the-art detection with 80 COCO categories',
                        'prithvi': 'Earth observation foundation model for satellite imagery'
                    };
                    const siblingCfg = window.MASKRCNN_SIBLING_CONFIG[type];
                    desc.textContent = (siblingCfg && siblingCfg.description) || descriptions[type] || '';
                }
            });
        }

        // MaskRCNN Rocks score-threshold slider
        const mrScore = document.getElementById('maskrcnnRocksScore');
        const mrScoreVal = document.getElementById('maskrcnnRocksScoreValue');
        if (mrScore && mrScoreVal) {
            mrScore.addEventListener('input', (e) => {
                mrScoreVal.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
            });
        }

        // MaskRCNN House score-threshold slider
        const mhScore = document.getElementById('maskrcnnHouseScore');
        const mhScoreVal = document.getElementById('maskrcnnHouseScoreValue');
        if (mhScore && mhScoreVal) {
            mhScore.addEventListener('input', (e) => {
                mhScoreVal.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
            });
        }

        // MaskRCNN Sibling services (hypolith / litter / roadkill /
        // newlife / brent + harish moon craters) share a single
        // score-threshold slider since the panel is reused.
        const msScore = document.getElementById('maskrcnnSiblingScore');
        const msScoreVal = document.getElementById('maskrcnnSiblingScoreValue');
        if (msScore && msScoreVal) {
            msScore.addEventListener('input', (e) => {
                msScoreVal.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
            });
        }

        // YOLOv8 confidence slider
        const yoloConf = document.getElementById('yolov8Confidence');
        const yoloConfVal = document.getElementById('yolov8ConfidenceValue');
        if (yoloConf && yoloConfVal) {
            yoloConf.addEventListener('input', (e) => {
                yoloConfVal.textContent = e.target.value + '%';
            });
        }

        // Zero-shot confidence slider
        const zsConf = document.getElementById('zeroShotConfidence');
        const zsConfVal = document.getElementById('zeroShotConfidenceValue');
        if (zsConf && zsConfVal) {
            zsConf.addEventListener('input', (e) => {
                zsConfVal.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
            });
        }

        // Mask2former confidence slider
        const m2fConf = document.getElementById('mask2formerConfidence');
        const m2fConfVal = document.getElementById('mask2formerConfidenceValue');
        if (m2fConf && m2fConfVal) {
            m2fConf.addEventListener('input', (e) => {
                m2fConfVal.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
            });
        }

        // Grounding DINO threshold sliders
        const gdBox = document.getElementById('gdBoxThreshold');
        const gdBoxVal = document.getElementById('gdBoxThresholdValue');
        if (gdBox && gdBoxVal) {
            gdBox.addEventListener('input', (e) => {
                gdBoxVal.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
            });
        }

        const gdText = document.getElementById('gdTextThreshold');
        const gdTextVal = document.getElementById('gdTextThresholdValue');
        if (gdText && gdTextVal) {
            gdText.addEventListener('input', (e) => {
                gdTextVal.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
            });
        }

        // Grounded-SAM-2 threshold sliders
        const gsBox = document.getElementById('gsBoxThreshold');
        const gsBoxVal = document.getElementById('gsBoxThresholdValue');
        if (gsBox && gsBoxVal) {
            gsBox.addEventListener('input', (e) => {
                gsBoxVal.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
            });
        }

        const gsText = document.getElementById('gsTextThreshold');
        const gsTextVal = document.getElementById('gsTextThresholdValue');
        if (gsText && gsTextVal) {
            gsText.addEventListener('input', (e) => {
                gsTextVal.textContent = (parseFloat(e.target.value) / 100).toFixed(2);
            });
        }
    });
})();
