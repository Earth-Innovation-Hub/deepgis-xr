// DeepGIS URL-based experience sharing.
// ========== URL-BASED EXPERIENCE SHARING ==========
(function initExperienceSharing() {
    console.log('[Experience] Initializing URL-based experience sharing...');

    const shareBtn = document.getElementById('quickShare');
    if (!shareBtn) {
        console.warn('[Experience] Share button not found');
        return;
    }

    // Get current camera and drone state
    function captureExperienceState() {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer) {
            console.warn('[Experience] Viewer not available');
            return null;
        }

        const camera = viewer.camera;
        const position = camera.positionCartographic;

        // Get camera state
        const state = {
            // Camera position
            lon: Cesium.Math.toDegrees(position.longitude).toFixed(6),
            lat: Cesium.Math.toDegrees(position.latitude).toFixed(6),
            alt: position.height.toFixed(2),
            heading: Cesium.Math.toDegrees(camera.heading).toFixed(2),
            pitch: Cesium.Math.toDegrees(camera.pitch).toFixed(2),
            roll: Cesium.Math.toDegrees(camera.roll).toFixed(2),
        };

        // Get view mode (2D or 3D)
        const sceneMode = viewer.scene.mode;
        if (sceneMode === Cesium.SceneMode.SCENE2D) {
            state.viewMode = '2d';
        } else if (sceneMode === Cesium.SceneMode.COLUMBUS_VIEW) {
            state.viewMode = 'columbus';
        } else {
            state.viewMode = '3d'; // Default to 3D
        }

        // Get drone fly settings
        const flyDistanceEl = document.getElementById('droneFlyDistance');
        const horizontalSpeedEl = document.getElementById('droneHorizontalSpeed');
        const verticalSpeedEl = document.getElementById('droneVerticalSpeed');

        if (flyDistanceEl) state.flyDist = flyDistanceEl.value;
        if (horizontalSpeedEl) state.hSpeed = horizontalSpeedEl.value;
        if (verticalSpeedEl) state.vSpeed = verticalSpeedEl.value;

        // Get orbit settings
        const orbitRadiusEl = document.getElementById('droneOrbitRadius');
        const orbitPitchEl = document.getElementById('droneOrbitPitch');
        const orbitYawEl = document.getElementById('droneOrbitYaw');

        if (orbitRadiusEl) state.orbRadius = orbitRadiusEl.value;
        if (orbitPitchEl) state.orbPitch = orbitPitchEl.value;
        if (orbitYawEl) state.orbYaw = orbitYawEl.value;

        // Check if orbit is active
        const orbitBtn = document.getElementById('droneOrbitBtn');
        if (orbitBtn && orbitBtn.classList.contains('active')) {
            state.orbiting = '1';
        }

        // Check if takeoff/land/fly is active
        const takeoffBtn = document.getElementById('droneTakeoffBtn');
        const landBtn = document.getElementById('droneLandBtn');
        const flyBtn = document.getElementById('droneFlyBtn');

        if (takeoffBtn && takeoffBtn.classList.contains('active')) {
            state.takeoff = '1';
        }
        if (landBtn && landBtn.classList.contains('active')) {
            state.landing = '1';
        }
        if (flyBtn && flyBtn.classList.contains('active')) {
            state.flying = '1';
        }

        // Get 3D model info (if any models are loaded)
        if (window.loadedModels && window.loadedModels.length > 0) {
            // For now, only save the first loaded model (can be extended for multiple models)
            const model = window.loadedModels[0];
            state.modelUrl = model.url;
            state.modelLon = model.lon.toFixed(6);
            state.modelLat = model.lat.toFixed(6);
            state.modelAlt = model.alt.toFixed(2);
            state.modelScale = model.scale.toFixed(2);
            console.log('[Experience] Including 3D model in state:', {
                url: state.modelUrl,
                position: `(${state.modelLon}, ${state.modelLat}, ${state.modelAlt})`,
                scale: state.modelScale
            });
        }

        console.log('[Experience] Captured state:', state);
        return state;
    }

    // Generate shareable URL
    function generateExperienceURL(state) {
        if (!state) return null;

        const url = new URL(window.location.href);
        // Clear existing params
        url.search = '';

        // Add experience parameters
        Object.keys(state).forEach(key => {
            url.searchParams.set(key, state[key]);
        });

        return url.toString();
    }

    // Copy URL to clipboard
    async function copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (err) {
            console.error('[Experience] Clipboard copy failed:', err);
            return false;
        }
    }

    // Share button click handler
    shareBtn.addEventListener('click', async () => {
        const state = captureExperienceState();
        if (!state) {
            alert('Unable to capture current view state');
            return;
        }

        const url = generateExperienceURL(state);
        console.log('[Experience] Generated URL:', url);

        const copied = await copyToClipboard(url);

        if (copied) {
            // Visual feedback
            const originalHTML = shareBtn.innerHTML;
            shareBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
            shareBtn.classList.add('active');

            setTimeout(() => {
                shareBtn.innerHTML = originalHTML;
                shareBtn.classList.remove('active');
            }, 2000);

            console.log('[Experience] URL copied to clipboard');
        } else {
            // Fallback: show URL in prompt
            prompt('Copy this URL to share:', url);
        }
    });

    // Load experience from URL on page load
    function loadExperienceFromURL() {
        const urlParams = new URLSearchParams(window.location.search);

        // Check if experience parameters exist
        if (!urlParams.has('lon') || !urlParams.has('lat')) {
            console.log('[Experience] No experience parameters in URL');
            return;
        }

        console.log('[Experience] Loading experience from URL...');

        // Wait for viewer to be ready and not morphing
        let checkCount = 0;
        const maxChecks = 100; // 10 seconds max wait

        const checkViewer = setInterval(() => {
            checkCount++;

            const viewer = window.AppState?.viewer || window.viewer;
            if (!viewer) {
                if (checkCount >= maxChecks) {
                    console.error('[Experience] Timeout waiting for viewer');
                    clearInterval(checkViewer);
                }
                return;
            }

            // Check if scene is morphing
            try {
                if (viewer.scene && viewer.scene.morphTime && viewer.scene.morphTime !== 1.0) {
                    console.log('[Experience] Scene is still morphing, waiting...', viewer.scene.morphTime);
                    if (checkCount >= maxChecks) {
                        console.warn('[Experience] Timeout waiting for morph to complete, proceeding anyway');
                        clearInterval(checkViewer);
                    } else {
                        return;
                    }
                }
            } catch (error) {
                console.warn('[Experience] Error checking morphTime:', error);
                // Proceed anyway if we can't check morphTime
            }

            clearInterval(checkViewer);

            // Parse parameters
            const lon = parseFloat(urlParams.get('lon'));
            const lat = parseFloat(urlParams.get('lat'));
            const alt = parseFloat(urlParams.get('alt')) || 1000;
            const heading = parseFloat(urlParams.get('heading')) || 0;
            const pitch = parseFloat(urlParams.get('pitch')) || -45;
            const roll = parseFloat(urlParams.get('roll')) || 0;
            const viewMode = urlParams.get('viewMode') || '3d';

            console.log('[Experience] Requested viewMode:', viewMode);
            console.log('[Experience] Current scene mode:', viewer.scene.mode);
            console.log('[Experience] Cesium.SceneMode.SCENE3D:', Cesium.SceneMode.SCENE3D);

            // Restore view mode first (check current mode to avoid unnecessary morphs)
            const currentMode = viewer.scene.mode;
            let needsMorph = false;

            if (viewMode === '2d' && currentMode !== Cesium.SceneMode.SCENE2D) {
                console.log('[Experience] Morphing to 2D view...');
                viewer.scene.morphTo2D(2.0);
                needsMorph = true;
            } else if (viewMode === 'columbus' && currentMode !== Cesium.SceneMode.COLUMBUS_VIEW) {
                console.log('[Experience] Morphing to Columbus view...');
                viewer.scene.morphToColumbusView(2.0);
                needsMorph = true;
            } else if (viewMode === '3d' && currentMode !== Cesium.SceneMode.SCENE3D) {
                console.log('[Experience] Morphing to 3D view from mode', currentMode, 'to', Cesium.SceneMode.SCENE3D);
                viewer.scene.morphTo3D(2.0);
                needsMorph = true;
            } else {
                console.log('[Experience] Scene already in requested mode:', viewMode, 'currentMode:', currentMode);
            }

            // Set camera position (wait longer if morph is needed)
            const cameraDelay = needsMorph ? 2500 : 800;
            setTimeout(() => {
                viewer.camera.setView({
                    destination: Cesium.Cartesian3.fromDegrees(lon, lat, alt),
                    orientation: {
                        heading: Cesium.Math.toRadians(heading),
                        pitch: Cesium.Math.toRadians(pitch),
                        roll: Cesium.Math.toRadians(roll)
                    }
                });
                console.log('[Experience] Camera position restored');
            }, cameraDelay);

            // Restore drone fly settings
            if (urlParams.has('flyDist')) {
                const el = document.getElementById('droneFlyDistance');
                if (el) el.value = urlParams.get('flyDist');
            }
            if (urlParams.has('hSpeed')) {
                const el = document.getElementById('droneHorizontalSpeed');
                if (el) el.value = urlParams.get('hSpeed');
            }
            if (urlParams.has('vSpeed')) {
                const el = document.getElementById('droneVerticalSpeed');
                if (el) el.value = urlParams.get('vSpeed');
            }

            // Restore orbit settings
            if (urlParams.has('orbRadius')) {
                const el = document.getElementById('droneOrbitRadius');
                if (el) el.value = urlParams.get('orbRadius');
            }
            if (urlParams.has('orbPitch')) {
                const el = document.getElementById('droneOrbitPitch');
                const val = urlParams.get('orbPitch');
                if (el) {
                    el.value = val;
                    const display = document.getElementById('orbitPitchValue');
                    if (display) display.textContent = `${val}°`;
                }
            }
            if (urlParams.has('orbYaw')) {
                const el = document.getElementById('droneOrbitYaw');
                const val = urlParams.get('orbYaw');
                if (el) {
                    el.value = val;
                    const display = document.getElementById('orbitYawValue');
                    if (display) display.textContent = `${val}°`;
                }
            }

            // Restore 3D model if present in URL
            if (urlParams.has('modelUrl')) {
                const modelUrl = urlParams.get('modelUrl');
                const modelLon = parseFloat(urlParams.get('modelLon'));
                const modelLat = parseFloat(urlParams.get('modelLat'));
                const modelAlt = parseFloat(urlParams.get('modelAlt')) || 0;
                const modelScale = parseFloat(urlParams.get('modelScale')) || 1.0;

                console.log('[Experience] Loading 3D model from URL:', {
                    url: modelUrl,
                    position: `(${modelLon}, ${modelLat}, ${modelAlt})`,
                    scale: modelScale
                });

                // Wait for viewer to be fully ready before loading model
                setTimeout(async () => {
                    try {
                        const modelPosition = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelAlt);

                        // Check if it's an Ion Asset ID
                        if (/^\d+$/.test(modelUrl)) {
                            const ionAssetId = parseInt(modelUrl);
                            const tileset = await Cesium.Cesium3DTileset.fromIonAssetId(ionAssetId);

                            const transform = Cesium.Transforms.eastNorthUpToFixedFrame(modelPosition);
                            const scaleMatrix = Cesium.Matrix4.fromUniformScale(modelScale);
                            tileset.modelMatrix = Cesium.Matrix4.multiply(transform, scaleMatrix, new Cesium.Matrix4());

                            viewer.scene.primitives.add(tileset);

                            // Store model info
                            window.loadedModels.push({
                                type: 'ion',
                                url: modelUrl,
                                ionAssetId: ionAssetId,
                                lon: modelLon,
                                lat: modelLat,
                                alt: modelAlt,
                                scale: modelScale,
                                primitive: tileset
                            });

                            console.log('[Experience] Ion Asset model restored from URL');
                        } else {
                            // Load as regular GLTF/GLB model
                            const entity = viewer.entities.add({
                                name: '3D Model',
                                position: modelPosition,
                                model: {
                                    uri: modelUrl,
                                    scale: modelScale,
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

                            // Store model info
                            window.loadedModels.push({
                                type: 'gltf',
                                url: modelUrl,
                                lon: modelLon,
                                lat: modelLat,
                                alt: modelAlt,
                                scale: modelScale,
                                entity: entity
                            });

                            console.log('[Experience] GLTF model restored from URL');
                        }

                        // Update model URL input field to show the loaded model
                        const modelUrlInput = document.getElementById('modelUrl');
                        if (modelUrlInput) {
                            modelUrlInput.value = modelUrl;
                        }

                        // Update model scale slider
                        const modelScaleSlider = document.getElementById('modelScale');
                        const scaleValue = document.getElementById('scaleValue');
                        if (modelScaleSlider) {
                            modelScaleSlider.value = modelScale;
                            if (scaleValue) {
                                scaleValue.textContent = `Scale: ${modelScale.toFixed(1)}x`;
                            }
                        }
                    } catch (error) {
                        console.error('[Experience] Error loading model from URL:', error);
                    }
                }, 3000); // Wait 3s to ensure viewer and camera are fully ready
            }

            // Start orbit if it was active
            if (urlParams.get('orbiting') === '1') {
                setTimeout(() => {
                    const orbitBtn = document.getElementById('droneOrbitBtn');
                    if (orbitBtn) {
                        console.log('[Experience] Starting orbit from URL');
                        orbitBtn.click();
                    }
                }, 1500);
            }

            // Restore takeoff/land/fly state (with delay to ensure widgets are ready)
            setTimeout(() => {
                if (urlParams.get('takeoff') === '1') {
                    const takeoffBtn = document.getElementById('droneTakeoffBtn');
                    if (takeoffBtn && !takeoffBtn.classList.contains('active')) {
                        console.log('[Experience] Starting takeoff from URL');
                        takeoffBtn.click();
                    }
                }
                if (urlParams.get('landing') === '1') {
                    const landBtn = document.getElementById('droneLandBtn');
                    if (landBtn && !landBtn.classList.contains('active')) {
                        console.log('[Experience] Starting landing from URL');
                        landBtn.click();
                    }
                }
                if (urlParams.get('flying') === '1') {
                    const flyBtn = document.getElementById('droneFlyBtn');
                    if (flyBtn && !flyBtn.classList.contains('active')) {
                        console.log('[Experience] Starting fly mode from URL');
                        flyBtn.click();
                    }
                }
            }, 2000); // Delay to ensure camera position is restored first

            // Force 3D mode at the end if requested (workaround for viewport not switching on its own)
            if (viewMode === '3d') {
                setTimeout(() => {
                    const viewer = window.AppState?.viewer || window.viewer;
                    if (viewer && viewer.scene.mode !== Cesium.SceneMode.SCENE3D) {
                        console.log('[Experience] Force switching to 3D mode (workaround)');
                        // Trigger the 3D button click (same as V key behavior)
                        const btn3D = document.getElementById('view3D');
                        if (btn3D) {
                            btn3D.click();
                        } else {
                            // Fallback: direct morph
                            viewer.scene.morphTo3D(1.0);
                        }
                    }
                }, 3000); // After all other restoration completes
            }

            console.log('[Experience] Experience loaded from URL');
        }, 100);
    }

    // Load experience on page load
    loadExperienceFromURL();

    // Keyboard shortcut: S key for share
    document.addEventListener('keydown', (e) => {
        if (e.key === 's' || e.key === 'S') {
            // Don't trigger if typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            e.preventDefault();
            shareBtn.click();
        }
    });

    console.log('[Experience] URL-based experience sharing initialized (Press S to share)');
})();
