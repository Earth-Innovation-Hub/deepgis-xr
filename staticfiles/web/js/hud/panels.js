// DeepGIS HUD panels and layout, shared by the Earth, Moon and planet viewers:
// toolbar panels, quick views, view-mode and perspective buttons, widget
// placement and #lat/lng/alt deep links. Positions use the globe's ellipsoid.
(function() {
    let activePanel = null;

    function closeHudPanel(panelId) {
        const panel = document.getElementById(panelId);
        if (panel) {
            panel.classList.remove('visible');
            const btn = document.querySelector(`[data-panel="${panelId}"]`);
            if (btn) btn.classList.remove('active');
            if (activePanel === panelId) activePanel = null;
        }
    }
    window.closeHudPanel = closeHudPanel; // Make globally accessible

    function toggleHudPanel(panelId) {
        const panel = document.getElementById(panelId);
        const btn = document.querySelector(`[data-panel="${panelId}"]`);

        // Close any open panel
        if (activePanel && activePanel !== panelId) {
            closeHudPanel(activePanel);
        }

        if (panel.classList.contains('visible')) {
            panel.classList.remove('visible');
            if (btn) btn.classList.remove('active');
            activePanel = null;
        } else {
            panel.classList.add('visible');
            if (btn) btn.classList.add('active');
            activePanel = panelId;
        }
    }

    window.DeepGISHud = {
        toggleHudPanel,
        closeActivePanel: () => activePanel && closeHudPanel(activePanel),
    };

    function initHUD() {
        // Setup toolbar button clicks
        document.querySelectorAll('.hud-btn[data-panel]').forEach(btn => {
            btn.addEventListener('click', () => {
                const panelId = btn.getAttribute('data-panel');
                toggleHudPanel(panelId);
            });
        });

        // Quick view buttons
        document.getElementById('quickView2D')?.addEventListener('click', () => {
            document.getElementById('view2D')?.click();
        });
        document.getElementById('quickView3D')?.addEventListener('click', () => {
            document.getElementById('view3D')?.click();
        });
        document.getElementById('quickHome')?.addEventListener('click', () => {
            document.getElementById('homeView')?.click();
        });

        // Close panel when clicking outside
        document.addEventListener('click', (e) => {
            if (activePanel) {
                const panel = document.getElementById(activePanel);
                const toolbar = document.getElementById('hudToolbar');
                if (panel && !panel.contains(e.target) && !toolbar.contains(e.target)) {
                    closeHudPanel(activePanel);
                }
            }

            // Close keyboard shortcuts legend when clicking outside
            const legend = document.getElementById('keyboardShortcutsLegend');
            if (legend && legend.classList.contains('visible') && !legend.contains(e.target)) {
                legend.classList.remove('visible');
            }
        });

        // Close keyboard shortcuts legend button
        document.getElementById('closeShortcutsLegend')?.addEventListener('click', () => {
            const legend = document.getElementById('keyboardShortcutsLegend');
            if (legend) {
                legend.classList.remove('visible');
            }
        });

        // Setup view mode buttons if they don't have handlers
        function setupViewModeButtons() {
            const viewer = window.AppState?.viewer || window.viewer;
            if (!viewer) {
                setTimeout(setupViewModeButtons, 500);
                return;
            }

            // 2D view button
            const btn2D = document.getElementById('view2D');
            if (btn2D && !btn2D.dataset.handlerAttached) {
                btn2D.addEventListener('click', () => {
                    if (viewer && viewer.scene) {
                        viewer.scene.morphTo2D(1.0);
                    }
                });
                btn2D.dataset.handlerAttached = 'true';
            }

            // 3D view button
            const btn3D = document.getElementById('view3D');
            if (btn3D && !btn3D.dataset.handlerAttached) {
                btn3D.addEventListener('click', () => {
                    if (viewer && viewer.scene) {
                        viewer.scene.morphTo3D(1.0);
                    }
                });
                btn3D.dataset.handlerAttached = 'true';
            }
        }

        // Setup perspective view buttons if they don't have handlers
        function setupPerspectiveViews() {
            const viewer = window.AppState?.viewer || window.viewer;
            if (!viewer) {
                // Retry after viewer is initialized
                setTimeout(setupPerspectiveViews, 500);
                return;
            }

            // North view
            const btnNorth = document.getElementById('viewNorth');
            if (btnNorth && !btnNorth.dataset.handlerAttached) {
                btnNorth.addEventListener('click', () => {
                    if (viewer && viewer.camera) {
                        const position = viewer.camera.positionCartographic;
                        const currentHeight = position.height;
                        viewer.camera.setView({
                            destination: Cesium.Cartesian3.fromDegrees(
                                Cesium.Math.toDegrees(position.longitude),
                                Cesium.Math.toDegrees(position.latitude),
                                currentHeight,
                                viewer.scene.globe.ellipsoid
                            ),
                            orientation: {
                                heading: Cesium.Math.toRadians(0), // North
                                pitch: Cesium.Math.toRadians(-45),
                                roll: 0.0
                            }
                        });
                    }
                });
                btnNorth.dataset.handlerAttached = 'true';
            }

            // South view
            const btnSouth = document.getElementById('viewSouth');
            if (btnSouth && !btnSouth.dataset.handlerAttached) {
                btnSouth.addEventListener('click', () => {
                    if (viewer && viewer.camera) {
                        const position = viewer.camera.positionCartographic;
                        const currentHeight = position.height;
                        viewer.camera.setView({
                            destination: Cesium.Cartesian3.fromDegrees(
                                Cesium.Math.toDegrees(position.longitude),
                                Cesium.Math.toDegrees(position.latitude),
                                currentHeight,
                                viewer.scene.globe.ellipsoid
                            ),
                            orientation: {
                                heading: Cesium.Math.toRadians(180), // South
                                pitch: Cesium.Math.toRadians(-45),
                                roll: 0.0
                            }
                        });
                    }
                });
                btnSouth.dataset.handlerAttached = 'true';
            }

            // West view
            const btnWest = document.getElementById('viewWest');
            if (btnWest && !btnWest.dataset.handlerAttached) {
                btnWest.addEventListener('click', () => {
                    if (viewer && viewer.camera) {
                        const position = viewer.camera.positionCartographic;
                        const currentHeight = position.height;
                        viewer.camera.setView({
                            destination: Cesium.Cartesian3.fromDegrees(
                                Cesium.Math.toDegrees(position.longitude),
                                Cesium.Math.toDegrees(position.latitude),
                                currentHeight,
                                viewer.scene.globe.ellipsoid
                            ),
                            orientation: {
                                heading: Cesium.Math.toRadians(90), // West
                                pitch: Cesium.Math.toRadians(-45),
                                roll: 0.0
                            }
                        });
                    }
                });
                btnWest.dataset.handlerAttached = 'true';
            }

            // East view
            const btnEast = document.getElementById('viewEast');
            if (btnEast && !btnEast.dataset.handlerAttached) {
                btnEast.addEventListener('click', () => {
                    if (viewer && viewer.camera) {
                        const position = viewer.camera.positionCartographic;
                        const currentHeight = position.height;
                        viewer.camera.setView({
                            destination: Cesium.Cartesian3.fromDegrees(
                                Cesium.Math.toDegrees(position.longitude),
                                Cesium.Math.toDegrees(position.latitude),
                                currentHeight,
                                viewer.scene.globe.ellipsoid
                            ),
                            orientation: {
                                heading: Cesium.Math.toRadians(270), // East
                                pitch: Cesium.Math.toRadians(-45),
                                roll: 0.0
                            }
                        });
                    }
                });
                btnEast.dataset.handlerAttached = 'true';
            }
        }

        // Setup OSM Buildings toggle.
        // Delegates to window.toggleOSMBuildings (exposed from main.js),
        // which wraps the canonical toggleOSMBuildings() in cesium-init.js.
        // Keeping one implementation path avoids the double-instantiation
        // bug the Tier-D plan flagged (previously an inline copy here kept
        // its own window.osmBuildingsTileset cache alongside AppState).
        function setupBuildingsToggle() {
            if (!document.getElementById('buildingsToggle')) return;
            if (typeof window.toggleOSMBuildings !== 'function' ||
                !(window.AppState?.viewer || window.viewer)) {
                setTimeout(setupBuildingsToggle, 500);
                return;
            }

            const buildingsToggle = document.getElementById('buildingsToggle');
            if (!buildingsToggle || buildingsToggle.dataset.handlerAttached) return;

            buildingsToggle.addEventListener('change', async (e) => {
                const enabled = e.target.checked;
                console.log(`[Buildings] Toggle ${enabled ? 'enabled' : 'disabled'}`);
                try {
                    const ok = await window.toggleOSMBuildings(enabled);
                    if (ok === false) throw new Error('toggleOSMBuildings returned false');
                } catch (error) {
                    console.error('[Buildings] Error:', error);
                    e.target.checked = !enabled;
                    alert(`Failed to ${enabled ? 'load' : 'hide'} buildings: ${error.message}`);
                }
            });
            buildingsToggle.dataset.handlerAttached = 'true';
            console.log('[Buildings] Toggle handler attached');
        }

        // Setup view mode buttons after a delay to ensure viewer is ready
        setTimeout(setupViewModeButtons, 1000);
        setTimeout(setupViewModeButtons, 3000);

        // Setup perspective views after a delay to ensure viewer is ready
        setTimeout(setupPerspectiveViews, 1000);
        setTimeout(setupPerspectiveViews, 3000);

        // Setup buildings toggle after viewer is ready
        setTimeout(setupBuildingsToggle, 1000);
        setTimeout(setupBuildingsToggle, 3000);

        console.log('[HUD] Initialized - Press H to show keyboard shortcuts');
    }

    // Force full-width cesium container (override main.js settings)
    function enforceFullWidthMap() {
        const cesium = document.getElementById('cesiumContainer');
        if (cesium) {
            cesium.style.setProperty('right', '0', 'important');
            cesium.style.setProperty('left', '0', 'important');
            cesium.style.setProperty('width', '100%', 'important');
        }
        const sidebar = document.getElementById('sidebar-wrapper');
        if (sidebar) {
            sidebar.style.setProperty('display', 'none', 'important');
        }
    }

    // Function to sync current location to 2D map
    // Workflow B entry — capture the current Cesium viewport, POST it
    // to /label/rocks/capture/, then redirect into the rock label editor
    // with no AI predictions pre-populated. The editor handles tile
    // selection, polygon drawing, and saving 400×400 .npy training tiles.
    async function captureForRockLabel() {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer || !viewer.camera || !viewer.scene) {
            alert('Cesium viewer not ready yet — try again in a moment.');
            return;
        }
        try {
            const cam = viewer.camera.positionCartographic;
            const lat = Cesium.Math.toDegrees(cam.latitude);
            const lon = Cesium.Math.toDegrees(cam.longitude);
            const alt = cam.height;
            const heading = Cesium.Math.toDegrees(viewer.camera.heading);
            const pitch = Cesium.Math.toDegrees(viewer.camera.pitch);

            // Force a render so the off-screen canvas reflects the
            // current frame before we serialize it.
            viewer.scene.requestRender();
            await new Promise(r => setTimeout(r, 50));

            const dataUrl = viewer.scene.canvas.toDataURL('image/png');

            const csrfInput = document.querySelector('input[name=csrfmiddlewaretoken]');
            const csrf = csrfInput ? csrfInput.value
                : (document.cookie.split('; ').find(r => r.startsWith('csrftoken='))?.split('=')[1] || '');

            const resp = await fetch('/label/rocks/capture/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrf,
                },
                body: JSON.stringify({
                    image_b64: dataUrl,
                    lat, lon, alt, heading, pitch,
                }),
            });
            const data = await resp.json();
            if (!resp.ok || !data.edit_url) {
                throw new Error(data.error || resp.statusText);
            }
            window.location.href = data.edit_url;
        } catch (err) {
            console.error('captureForRockLabel failed', err);
            alert('Capture failed: ' + (err.message || err));
        }
    }
    window.captureForRockLabel = captureForRockLabel;

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initHUD();
            enforceFullWidthMap();
        });
    } else {
        initHUD();
        enforceFullWidthMap();
    }

    // Re-enforce on resize (to override main.js resize handler)
    window.addEventListener('resize', enforceFullWidthMap);

    // Also enforce after a short delay to catch late initializations
    setTimeout(enforceFullWidthMap, 500);
    setTimeout(enforceFullWidthMap, 1500);

    // Check for incoming location from URL hash (e.g. from ai_analysis_report)
    function checkIncomingLocation() {
        const hash = window.location.hash;
        if (hash) {
            // Hash format: #lat/lng/alt
            const parts = hash.substring(1).split('/');
            if (parts.length >= 3) {
                const lat = parseFloat(parts[0]);
                const lng = parseFloat(parts[1]);
                const alt = parseFloat(parts[2]);

                if (!isNaN(lat) && !isNaN(lng) && !isNaN(alt)) {
                    console.log(`Incoming location from hash: lat=${lat}, lng=${lng}, alt=${alt}`);

                    // Wait for viewer to be ready
                    const tryFlyTo = () => {
                        const viewer = window.AppState?.viewer || window.viewer;
                        if (viewer && viewer.camera) {
                            viewer.camera.flyTo({
                                destination: Cesium.Cartesian3.fromDegrees(lng, lat, alt, viewer.scene.globe.ellipsoid),
                                orientation: {
                                    heading: Cesium.Math.toRadians(0),
                                    pitch: Cesium.Math.toRadians(-45),
                                    roll: 0.0
                                },
                                duration: 2.0
                            });
                            console.log('Camera flying to incoming location');
                            // Clear the hash after navigation
                            history.replaceState(null, null, window.location.pathname + window.location.search);
                        } else {
                            console.log('Viewer not ready, retrying...');
                            setTimeout(tryFlyTo, 500);
                        }
                    };

                    // Start trying after a delay to ensure viewer initialization
                    setTimeout(tryFlyTo, 1000);
                }
            }
        }
    }

    // Check for incoming location on page load
    checkIncomingLocation();

    // Style World Sampler when it appears in HUD container
    function styleWorldSamplerInHUD() {
        const worldSampler = document.getElementById('worldSamplerSection');
        const hudContainer = document.getElementById('hudSamplerContainer');
        if (worldSampler && hudContainer && hudContainer.contains(worldSampler)) {
            // Hide the accordion header since HUD panel already has one
            const header = worldSampler.querySelector('.layer-group-title.accordion-header');
            if (header) header.style.display = 'none';
            // Ensure content is expanded
            const content = worldSampler.querySelector('.accordion-content');
            if (content) {
                content.classList.add('expanded');
                content.style.maxHeight = 'none';
            }
            worldSampler.style.border = 'none';
            worldSampler.style.background = 'transparent';
            console.log('[HUD] World Sampler styled for HUD');
        }
    }

    // Check periodically until World Sampler is created
    setTimeout(styleWorldSamplerInHUD, 1000);
    setTimeout(styleWorldSamplerInHUD, 2000);
    setTimeout(styleWorldSamplerInHUD, 4000);

    // Ensure navigation widget and perspective views widget are positioned correctly
    function positionNavigationWidgets() {
        const quickViews = document.querySelector('.hud-quick-views');
        const navWidget = document.getElementById('navigationWidgetGroup');
        const perspectiveWidget = document.getElementById('perspectiveViewsWidget');

        if (quickViews && navWidget) {
            const quickViewsRect = quickViews.getBoundingClientRect();
            const quickViewsBottom = quickViewsRect.bottom;

            // Position navigation widget below quick view buttons with some spacing
            navWidget.style.position = 'fixed';
            navWidget.style.top = (quickViewsBottom + 20) + 'px';
            navWidget.style.right = '20px';

            // Position perspective views widget below navigation widget with more spacing
            if (perspectiveWidget) {
                const navWidgetRect = navWidget.getBoundingClientRect();
                const navWidgetBottom = navWidgetRect.bottom;
                perspectiveWidget.style.position = 'fixed';
                perspectiveWidget.style.top = (navWidgetBottom + 40) + 'px';  // Increased spacing from 20px to 40px
                perspectiveWidget.style.right = '20px';
            }
        }
    }

    // Position on load and resize
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            setTimeout(positionNavigationWidgets, 100);
            setTimeout(positionNavigationWidgets, 500);  // Second check after widgets render
        });
    } else {
        setTimeout(positionNavigationWidgets, 100);
        setTimeout(positionNavigationWidgets, 500);
    }

    window.addEventListener('resize', positionNavigationWidgets);
})();
