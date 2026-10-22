// DeepGIS HUD 3D model loader (glTF/GLB URLs or Cesium Ion assets).
// ========== 3D MODEL LOADING ==========
(function init3DModelSystem() {
    console.log('[3D Models] Initializing 3D model system...');

    // Global state for loaded models
    window.loadedModels = [];

    // Setup event listeners for preset buttons
    const presetBtns = document.querySelectorAll('.preset-model-btn');
    presetBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const modelUrl = btn.dataset.url;
            const modelUrlInput = document.getElementById('modelUrl');
            if (modelUrlInput) {
                modelUrlInput.value = modelUrl;
            }
        });
    });

    // Setup model location dropdown
    const modelLocationSelect = document.getElementById('modelLocation');
    const customLocationInputs = document.getElementById('customLocationInputs');
    if (modelLocationSelect && customLocationInputs) {
        modelLocationSelect.addEventListener('change', (e) => {
            customLocationInputs.style.display = e.target.value === 'custom' ? 'block' : 'none';
        });
    }

    // Setup model scale slider
    const modelScaleSlider = document.getElementById('modelScale');
    const scaleValue = document.getElementById('scaleValue');
    if (modelScaleSlider && scaleValue) {
        modelScaleSlider.addEventListener('input', (e) => {
            scaleValue.textContent = `Scale: ${parseFloat(e.target.value).toFixed(1)}x`;
        });
    }

    // Load model at specified location
    async function loadModelAtLocation() {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer) {
            console.error('[3D Models] Viewer not available');
            alert('Viewer not ready yet. Please wait.');
            return;
        }

        const modelUrl = document.getElementById('modelUrl')?.value?.trim();
        if (!modelUrl) {
            alert('Please enter a model URL or Ion Asset ID');
            return;
        }

        const locationOption = document.getElementById('modelLocation')?.value || 'current_view';
        const scale = parseFloat(document.getElementById('modelScale')?.value || '1.0');

        try {
            let modelPosition;
            let modelLon, modelLat, modelAlt = 0;

            const ellipsoid = viewer.scene.globe.ellipsoid;
            const preset = document.getElementById('modelLocation')?.selectedOptions[0]?.dataset;
            switch (preset?.lon !== undefined ? 'preset' : locationOption) {
                case 'preset':
                    modelLon = parseFloat(preset.lon);
                    modelLat = parseFloat(preset.lat);
                    modelAlt = parseFloat(preset.alt || '0');
                    modelPosition = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelAlt, ellipsoid);
                    break;
                case 'custom':
                    modelLon = parseFloat(document.getElementById('customLon')?.value || '0');
                    modelLat = parseFloat(document.getElementById('customLat')?.value || '0');
                    modelAlt = parseFloat(document.getElementById('customAlt')?.value || '0');
                    modelPosition = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelAlt, ellipsoid);
                    break;
                case 'current_view':
                default:
                    const cameraPosition = viewer.camera.positionCartographic;
                    modelLon = Cesium.Math.toDegrees(cameraPosition.longitude);
                    modelLat = Cesium.Math.toDegrees(cameraPosition.latitude);
                    modelAlt = 0; // Ground level
                    modelPosition = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelAlt, ellipsoid);
                    break;
            }

            let loadedEntity = null;

            // Check if it's an Ion Asset ID
            if (/^\d+$/.test(modelUrl)) {
                const ionAssetId = parseInt(modelUrl);
                const tileset = await Cesium.Cesium3DTileset.fromIonAssetId(ionAssetId);

                const transform = Cesium.Transforms.eastNorthUpToFixedFrame(modelPosition, viewer.scene.globe.ellipsoid);
                const scaleMatrix = Cesium.Matrix4.fromUniformScale(scale);
                tileset.modelMatrix = Cesium.Matrix4.multiply(transform, scaleMatrix, new Cesium.Matrix4());

                viewer.scene.primitives.add(tileset);
                viewer.zoomTo(tileset);

                // Store model info
                window.loadedModels.push({
                    type: 'ion',
                    url: modelUrl,
                    ionAssetId: ionAssetId,
                    lon: modelLon,
                    lat: modelLat,
                    alt: modelAlt,
                    scale: scale,
                    primitive: tileset
                });

                console.log(`[3D Models] Ion Asset ${ionAssetId} loaded at (${modelLon}, ${modelLat}, ${modelAlt}) with scale ${scale}`);
            } else {
                // Load as regular GLTF/GLB model
                const entity = viewer.entities.add({
                    name: '3D Model',
                    position: modelPosition,
                    model: {
                        uri: modelUrl,
                        scale: scale,
                        minimumPixelSize: 64,
                        maximumScale: 10000,
                        runAnimations: true,
                        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                        silhouetteColor: Cesium.Color.YELLOW,
                        silhouetteSize: 2.0,
                        show: true
                    }
                });

                await entity.model.readyPromise;
                viewer.zoomTo(entity, new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-30), scale * 100));

                loadedEntity = entity;

                // Store model info
                window.loadedModels.push({
                    type: 'gltf',
                    url: modelUrl,
                    lon: modelLon,
                    lat: modelLat,
                    alt: modelAlt,
                    scale: scale,
                    entity: entity
                });

                console.log(`[3D Models] GLTF model loaded at (${modelLon}, ${modelLat}, ${modelAlt}) with scale ${scale}`);
            }

        } catch (error) {
            console.error('[3D Models] Error loading model:', error);
            alert(`Failed to load model: ${error.message}`);
        }
    }

    // Quick load at current location with 1:1 scale
    async function quickLoadModelAtCurrentLocation() {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer) {
            console.error('[3D Models] Viewer not available');
            alert('Viewer not ready yet. Please wait.');
            return;
        }

        const modelUrl = document.getElementById('modelUrl')?.value?.trim();
        if (!modelUrl) {
            alert('Please enter a model URL or Ion Asset ID');
            return;
        }

        try {
            const cameraPosition = viewer.camera.positionCartographic;
            const modelLon = Cesium.Math.toDegrees(cameraPosition.longitude);
            const modelLat = Cesium.Math.toDegrees(cameraPosition.latitude);
            const modelAlt = 0; // Ground level
            const modelPosition = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelAlt, viewer.scene.globe.ellipsoid);
            const scale = 1.0;

            // Check if it's an Ion Asset ID
            if (/^\d+$/.test(modelUrl)) {
                const ionAssetId = parseInt(modelUrl);
                const tileset = await Cesium.Cesium3DTileset.fromIonAssetId(ionAssetId);

                const transform = Cesium.Transforms.eastNorthUpToFixedFrame(modelPosition, viewer.scene.globe.ellipsoid);
                tileset.modelMatrix = transform;

                viewer.scene.primitives.add(tileset);
                viewer.zoomTo(tileset);

                // Store model info
                window.loadedModels.push({
                    type: 'ion',
                    url: modelUrl,
                    ionAssetId: ionAssetId,
                    lon: modelLon,
                    lat: modelLat,
                    alt: modelAlt,
                    scale: scale,
                    primitive: tileset
                });

                console.log(`[3D Models] Quick loaded Ion Asset ${ionAssetId}`);
            } else {
                const entity = viewer.entities.add({
                    name: '3D Model',
                    position: modelPosition,
                    model: {
                        uri: modelUrl,
                        scale: scale,
                        minimumPixelSize: 64,
                        maximumScale: 10000,
                        runAnimations: true,
                        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                        show: true
                    }
                });

                await entity.model.readyPromise;
                viewer.zoomTo(entity, new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-30), 100));

                // Store model info
                window.loadedModels.push({
                    type: 'gltf',
                    url: modelUrl,
                    lon: modelLon,
                    lat: modelLat,
                    alt: modelAlt,
                    scale: scale,
                    entity: entity
                });

                console.log(`[3D Models] Quick loaded GLTF model`);
            }

            console.log('[3D Models] Model quick-loaded at current location (1:1 scale)');
        } catch (error) {
            console.error('[3D Models] Error quick-loading model:', error);
            alert(`Failed to load model: ${error.message}`);
        }
    }

    // Remove all models
    function removeAllModels() {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer) {
            console.error('[3D Models] Viewer not available');
            return;
        }

        // Remove all loaded models
        window.loadedModels.forEach(modelInfo => {
            if (modelInfo.type === 'ion' && modelInfo.primitive) {
                viewer.scene.primitives.remove(modelInfo.primitive);
            } else if (modelInfo.type === 'gltf' && modelInfo.entity) {
                viewer.entities.remove(modelInfo.entity);
            }
        });

        // Clear the array
        window.loadedModels = [];

        console.log('[3D Models] All models removed');
    }

    // Setup button event listeners
    const loadModelBtn = document.getElementById('loadModel');
    if (loadModelBtn) {
        loadModelBtn.addEventListener('click', loadModelAtLocation);
    }

    const quickLoadBtn = document.getElementById('quickLoadModel');
    if (quickLoadBtn) {
        quickLoadBtn.addEventListener('click', quickLoadModelAtCurrentLocation);
    }

    const removeModelBtn = document.getElementById('removeModel');
    if (removeModelBtn) {
        removeModelBtn.addEventListener('click', removeAllModels);
    }

    console.log('[3D Models] 3D model system initialized');
})();
