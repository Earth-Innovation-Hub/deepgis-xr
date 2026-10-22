// DeepGIS QR code overlay for the shared experience URL.
// ========== QR CODE OVERLAY ==========
(function initQRCode() {
    console.log('[QR Code] Initializing QR code overlay...');

    const qrBtn = document.getElementById('quickQR');
    const qrOverlay = document.getElementById('qrCodeOverlay');
    const qrContainer = document.getElementById('qrCodeContainer');
    const qrRefreshBtn = document.getElementById('qrRefreshBtn');
    const qrCloseBtn = document.getElementById('qrCloseBtn');

    if (!qrBtn || !qrOverlay || !qrContainer) {
        console.warn('[QR Code] Required elements not found');
        return;
    }

    let currentQRCode = null;
    let autoRefreshInterval = null;

    // Generate QR code from current experience state
    function generateQRCode() {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer) {
            console.warn('[QR Code] Viewer not available');
            return;
        }

        // Capture current state (reuse experience sharing logic)
        const camera = viewer.camera;
        const position = camera.positionCartographic;

        const state = {
            lon: Cesium.Math.toDegrees(position.longitude).toFixed(6),
            lat: Cesium.Math.toDegrees(position.latitude).toFixed(6),
            alt: position.height.toFixed(2),
            heading: Cesium.Math.toDegrees(camera.heading).toFixed(2),
            pitch: Cesium.Math.toDegrees(camera.pitch).toFixed(2),
            roll: Cesium.Math.toDegrees(camera.roll).toFixed(2),
        };

        // Get view mode
        const sceneMode = viewer.scene.mode;
        if (sceneMode === Cesium.SceneMode.SCENE2D) {
            state.viewMode = '2d';
        } else if (sceneMode === Cesium.SceneMode.COLUMBUS_VIEW) {
            state.viewMode = 'columbus';
        } else {
            state.viewMode = '3d';
        }

        // Get drone settings
        const flyDistanceEl = document.getElementById('droneFlyDistance');
        const horizontalSpeedEl = document.getElementById('droneHorizontalSpeed');
        const verticalSpeedEl = document.getElementById('droneVerticalSpeed');
        const orbitRadiusEl = document.getElementById('droneOrbitRadius');
        const orbitPitchEl = document.getElementById('droneOrbitPitch');
        const orbitYawEl = document.getElementById('droneOrbitYaw');

        if (flyDistanceEl) state.flyDist = flyDistanceEl.value;
        if (horizontalSpeedEl) state.hSpeed = horizontalSpeedEl.value;
        if (verticalSpeedEl) state.vSpeed = verticalSpeedEl.value;
        if (orbitRadiusEl) state.orbRadius = orbitRadiusEl.value;
        if (orbitPitchEl) state.orbPitch = orbitPitchEl.value;
        if (orbitYawEl) state.orbYaw = orbitYawEl.value;

        // Check if orbit is active
        const orbitBtn = document.getElementById('droneOrbitBtn');
        if (orbitBtn && orbitBtn.classList.contains('active')) {
            state.orbiting = '1';
        }

        // Build URL
        const url = new URL(window.location.href);
        url.search = '';
        Object.keys(state).forEach(key => {
            url.searchParams.set(key, state[key]);
        });

        const experienceURL = url.toString();
        console.log('[QR Code] Generating QR for URL:', experienceURL);

        // Clear previous QR code
        qrContainer.innerHTML = '';

        // Generate new QR code
        try {
            currentQRCode = new QRCode(qrContainer, {
                text: experienceURL,
                width: 128,
                height: 128,
                colorDark: "#000000",
                colorLight: "#ffffff",
                correctLevel: QRCode.CorrectLevel.M
            });
            console.log('[QR Code] QR code generated successfully');
        } catch (error) {
            console.error('[QR Code] Error generating QR code:', error);
            qrContainer.innerHTML = '<div style="color: red; font-size: 10px; padding: 10px;">QR generation failed</div>';
        }
    }

    // Start auto-refresh timer
    function startAutoRefresh() {
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
        }

        autoRefreshInterval = setInterval(() => {
            console.log('[QR Code] Auto-refreshing QR code...');
            generateQRCode();
        }, 5000); // Refresh every 5 seconds

        console.log('[QR Code] Auto-refresh started (every 5 seconds)');
    }

    // Stop auto-refresh timer
    function stopAutoRefresh() {
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
            console.log('[QR Code] Auto-refresh stopped');
        }
    }

    // Show QR overlay
    function showQROverlay() {
        generateQRCode();
        qrOverlay.classList.add('visible');
        qrBtn.classList.add('active');
        startAutoRefresh();
        console.log('[QR Code] Overlay shown');
    }

    // Hide QR overlay
    function hideQROverlay() {
        qrOverlay.classList.remove('visible');
        qrBtn.classList.remove('active');
        stopAutoRefresh();
        console.log('[QR Code] Overlay hidden');
    }

    // Toggle QR overlay
    qrBtn.addEventListener('click', () => {
        if (qrOverlay.classList.contains('visible')) {
            hideQROverlay();
        } else {
            showQROverlay();
        }
    });

    // Refresh QR code
    qrRefreshBtn.addEventListener('click', () => {
        console.log('[QR Code] Manual refresh triggered');
        generateQRCode();
    });

    // Close button
    qrCloseBtn.addEventListener('click', () => {
        hideQROverlay();
    });

    // Keyboard shortcut: Q key to toggle QR
    document.addEventListener('keydown', (e) => {
        if (e.key === 'q' || e.key === 'Q') {
            // Don't trigger if typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            e.preventDefault();
            qrBtn.click();
        }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && qrOverlay.classList.contains('visible')) {
            hideQROverlay();
        }
    });

    console.log('[QR Code] QR code overlay initialized (Press Q to toggle, auto-refresh every 5s)');
})();
