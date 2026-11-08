// DeepGIS HUD keyboard shortcuts (press H for the legend).
(function() {
    const onReady = (fn) => (document.readyState === 'loading'
        ? document.addEventListener('DOMContentLoaded', fn)
        : fn());

    // Each body sets its own globe colour; wireframe mode (W) restores it on exit.
    let texturedBaseColor = null;

    onReady(() => {
        document.addEventListener('keydown', (e) => {
            // Ignore if typing in input fields
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
                return;
            }

            // H key: Toggle keyboard shortcuts legend
            if (e.key === 'h' || e.key === 'H') {
                e.preventDefault();
                const legend = document.getElementById('keyboardShortcutsLegend');
                if (legend) {
                    legend.classList.toggle('visible');
                }
                return;
            }

            // V key: Toggle view mode (2D/3D)
            if (e.key === 'v' || e.key === 'V') {
                e.preventDefault();
                const viewer = window.AppState?.viewer || window.viewer;
                if (viewer) {
                    const currentMode = viewer.scene.mode;
                    if (currentMode === Cesium.SceneMode.SCENE3D) {
                        // Switch to 2D
                        const btn2D = document.getElementById('view2D');
                        if (btn2D) btn2D.click();
                    } else {
                        // Switch to 3D
                        const btn3D = document.getElementById('view3D');
                        if (btn3D) btn3D.click();
                    }
                }
                return;
            }

            // Arrow keys: look north / south / west / east from where the camera is
            const perspective = { ArrowUp: 0, ArrowDown: 180, ArrowLeft: 270, ArrowRight: 90 };
            if (e.key in perspective) {
                e.preventDefault();
                const viewer = window.AppState?.viewer || window.viewer;
                if (viewer?.camera) {
                    viewer.camera.setView({
                        destination: viewer.camera.position,
                        orientation: {
                            heading: Cesium.Math.toRadians(perspective[e.key]),
                            pitch: Cesium.Math.toRadians(-45),
                            roll: 0,
                        },
                    });
                }
                return;
            }

            // F key: Toggle full screen
            if (e.key === 'f' || e.key === 'F') {
                e.preventDefault();
                if (!document.fullscreenElement) {
                    document.documentElement.requestFullscreen().catch(err => {
                        console.warn('Error attempting to enable fullscreen:', err);
                    });
                } else {
                    document.exitFullscreen();
                }
                return;
            }

            // B key: Toggle 3D Buildings
            if (e.key === 'b' || e.key === 'B') {
                e.preventDefault();
                const buildingsToggle = document.getElementById('buildingsToggle');
                if (buildingsToggle) {
                    buildingsToggle.checked = !buildingsToggle.checked;
                    buildingsToggle.dispatchEvent(new Event('change'));
                }
                return;
            }

            // W key: Toggle wireframe/textured mode
            if (e.key === 'w' || e.key === 'W') {
                e.preventDefault();
                const viewer = window.AppState?.viewer || window.viewer;
                if (viewer && viewer.imageryLayers && viewer.scene) {
                    const globe = viewer.scene.globe;
                    const layers = viewer.imageryLayers;

                    // Check if any layer is visible (default to true if no layers)
                    let hasVisibleLayers = true;
                    if (layers.length > 0) {
                        // Check if at least one layer is visible
                        hasVisibleLayers = false;
                        for (let i = 0; i < layers.length; i++) {
                            if (layers.get(i).show) {
                                hasVisibleLayers = true;
                                break;
                            }
                        }
                    }

                    // Toggle all imagery layers
                    for (let i = 0; i < layers.length; i++) {
                        const layer = layers.get(i);
                        layer.show = !hasVisibleLayers;
                    }

                    // Toggle wireframe mesh details
                    if (hasVisibleLayers) {
                        texturedBaseColor = Cesium.Color.clone(globe.baseColor);
                        // Wireframe mode: Enable debug wireframe to show mesh details
                        try {
                            // Access debug wireframe (private API, use with caution)
                            if (globe._surface && globe._surface._tileProvider && globe._surface._tileProvider._debug) {
                                globe._surface._tileProvider._debug.wireframe = true;
                            }

                            // Also set base color for better wireframe visibility
                            globe.baseColor = Cesium.Color.fromCssColorString('#2d3748');

                            // Disable lighting for clearer wireframe view
                            globe.enableLighting = false;

                            // Increase terrain exaggeration slightly to make mesh more visible
                            if (globe.terrainExaggeration !== undefined) {
                                globe.terrainExaggeration = Math.max(1.0, globe.terrainExaggeration || 1.0);
                            }

                            console.log('Wireframe mode: ON - Showing mesh details');
                        } catch (error) {
                            console.warn('Could not enable wireframe debug mode:', error);
                            // Fallback: just hide textures and set base color
                            globe.baseColor = Cesium.Color.fromCssColorString('#4a5568');
                            globe.enableLighting = false;
                        }
                    } else {
                        // Textured mode: Disable wireframe and restore settings
                        try {
                            if (globe._surface && globe._surface._tileProvider && globe._surface._tileProvider._debug) {
                                globe._surface._tileProvider._debug.wireframe = false;
                            }
                        } catch (error) {
                            // Ignore if debug property doesn't exist
                        }

                        // Restore default settings
                        globe.baseColor = texturedBaseColor || Cesium.Color.WHITE;
                        globe.enableLighting = true;

                        console.log('Wireframe mode: OFF - Textured mode restored');
                    }
                }
                return;
            }

            // T key: Hide/show all toolbars
            if (e.key === 't' || e.key === 'T') {
                e.preventDefault();
                // Everything but the QR code overlay, which stays visible
                const elements = [
                    document.getElementById('hudToolbar'),
                    document.querySelector('.hud-quick-views'),
                    document.getElementById('cameraInfo'),
                    document.getElementById('flightPanel'),
                    document.getElementById('navigationWidgetGroup'),
                    document.getElementById('performanceIndicator'),
                    document.getElementById('aircraftCountIndicator'),
                    document.getElementById('leftJoystick'),
                    document.getElementById('rightJoystick'),
                    document.querySelector('.main-heading'),
                    document.querySelector('.cesium-viewer-toolbar'),
                ].filter(el => el);
                const isHidden = elements[0] && elements[0].style.display === 'none';

                elements.forEach(el => {
                    if (el) {
                        el.style.display = isHidden ? '' : 'none';
                    }
                });

                console.log(`[HUD] Toolbars and widgets ${isHidden ? 'shown' : 'hidden'} (QR code remains visible)`);
                return;
            }

            // D key: Drone Fly Forward
            if (e.key === 'd' || e.key === 'D') {
                e.preventDefault();
                const droneFlyBtn = document.getElementById('droneFlyBtn');
                if (droneFlyBtn) {
                    droneFlyBtn.click();
                }
                return;
            }

            // U key: Takeoff (Up)
            if (e.key === 'u' || e.key === 'U') {
                e.preventDefault();
                const takeoffBtn = document.getElementById('droneTakeoffBtn');
                if (takeoffBtn) {
                    takeoffBtn.click();
                }
                return;
            }

            // L key: Land
            if (e.key === 'l' || e.key === 'L') {
                e.preventDefault();
                const landBtn = document.getElementById('droneLandBtn');
                if (landBtn) {
                    landBtn.click();
                }
                return;
            }

            // O key: Start Orbit
            if (e.key === 'o' || e.key === 'O') {
                e.preventDefault();
                const droneOrbitBtn = document.getElementById('droneOrbitBtn');
                if (droneOrbitBtn) {
                    droneOrbitBtn.click();
                }
                return;
            }

            // J key: Toggle Joysticks (Space pauses an orbit: hud/drone.js)
            if (e.key === 'j' || e.key === 'J') {
                e.preventDefault();
                document.getElementById('hudJoystickBtn')?.click();
                return;
            }

            // G key: Flight panel
            if (e.key === 'g' || e.key === 'G') {
                e.preventDefault();
                if (document.getElementById('flightPanel')) window.DeepGISHud?.toggleHudPanel('flightPanel');
                return;
            }

            // Escape: stop orbit / climb (hud/drone.js listens too), then close panels / legend
            if (e.key === 'Escape') {
                if (window.DeepGISDrone?.isOrbiting?.() || window.DeepGISDrone?.isVerticalActive?.()) {
                    window.DeepGISDrone.stopOrbit?.();
                    window.DeepGISDrone.stopVertical?.();
                    return;
                }

                window.DeepGISHud?.closeActivePanel();
                const legend = document.getElementById('keyboardShortcutsLegend');
                if (legend && legend.classList.contains('visible')) {
                    legend.classList.remove('visible');
                }
                return;
            }
        });
    });
})();
