// DeepGIS HUD AI panel: analysis-type options and threshold sliders.
(function() {
    const onReady = (fn) => (document.readyState === 'loading'
        ? document.addEventListener('DOMContentLoaded', fn)
        : fn());

    onReady(() => {
        const optionPanels = {
            'sam': 'samOptions',
            'yolov8': 'yolov8Options',
            'grounding_dino': 'groundingDinoOptions',
            'maskrcnn_rocks': 'maskrcnnRocksOptions'
        };
        const descriptions = {
            'sam': 'Segments all visible regions using Segment Anything Model',
            'yolov8': 'Ultra-fast detection with 80 COCO classes',
            'grounding_dino': 'Text-based open-vocabulary object detection',
            'maskrcnn_rocks': 'Rock instance segmentation using Bishop/Jezero Mask R-CNN checkpoints'
        };

        // Analysis type toggle (for AI panel)
        const analysisSelect = document.getElementById('analysisTypeSelect');
        if (analysisSelect) {
            analysisSelect.addEventListener('change', (e) => {
                const type = e.target.value;
                Object.entries(optionPanels).forEach(([key, id]) => {
                    const el = document.getElementById(id);
                    if (el) el.style.display = type === key ? 'block' : 'none';
                });
                const desc = document.getElementById('analysisDescription');
                if (desc) desc.textContent = descriptions[type] || '';
            });
        }

        const bindSlider = (sliderId, valueId, format) => {
            const slider = document.getElementById(sliderId);
            const value = document.getElementById(valueId);
            if (slider && value) {
                slider.addEventListener('input', (e) => {
                    value.textContent = format(e.target.value);
                });
            }
        };
        const asFraction = (v) => (parseFloat(v) / 100).toFixed(2);

        bindSlider('maskrcnnRocksScore', 'maskrcnnRocksScoreValue', asFraction);
        bindSlider('yolov8Confidence', 'yolov8ConfidenceValue', (v) => v + '%');
        bindSlider('gdBoxThreshold', 'gdBoxThresholdValue', asFraction);
        bindSlider('gdTextThreshold', 'gdTextThresholdValue', asFraction);
    });
})();
