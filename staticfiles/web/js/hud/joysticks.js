// DeepGIS HUD virtual joysticks (QGC Mode 2), driving the camera on any body.
// Left stick: climb (Y) and yaw (X). Right stick: move over the ground along the
// heading (Y) and sideways (X). Movement is horizontal in the local tangent plane
// and climb is along the local vertical, whatever the camera's pitch; speeds come
// from the Flight panel's H / V inputs. Shown from the panel's Joysticks button or J.
(function initJoysticks() {
    const leftJoystick = document.getElementById('leftJoystick');
    const rightJoystick = document.getElementById('rightJoystick');
    const leftStick = document.getElementById('leftJoystickStick');
    const rightStick = document.getElementById('rightJoystickStick');
    const leftValue = document.getElementById('leftJoystickValue');
    const rightValue = document.getElementById('rightJoystickValue');
    const joystickBtn = document.getElementById('hudJoystickBtn');

    if (!leftJoystick || !rightJoystick || !leftStick || !rightStick || !joystickBtn) {
        console.error('[Joysticks] Missing required elements');
        return;
    }

    let leftState = { x: 0, y: 0 };
    let rightState = { x: 0, y: 0 };
    let animationFrameId = null;

    // Exposed for drone.js (takeoff / land read the left stick's yaw)
    window.leftJoystickState = leftState;
    window.rightJoystickState = rightState;

    const maxDistance = 45; // stick travel in pixels
    const deadzone = 0.1;
    const maxYawRate = Cesium.Math.toRadians(45); // rad/s at full deflection

    function getSpeedSettings() {
        return {
            horizontal: parseFloat(document.getElementById('droneHorizontalSpeed')?.value) || 30,
            vertical: parseFloat(document.getElementById('droneVerticalSpeed')?.value) || 5,
        };
    }

    function setVisible(on) {
        leftJoystick.classList.toggle('active', on);
        rightJoystick.classList.toggle('active', on);
        joystickBtn.classList.toggle('active', on);
        if (on) startCameraMovement(); else stopCameraMovement();
        // On a phone the panel spans the width and would sit over the sticks
        if (on && window.innerWidth <= 760) window.closeHudPanel?.('flightPanel');
    }
    joystickBtn.addEventListener('click', () => setVisible(!leftJoystick.classList.contains('active')));

    function setupJoystick(stick, base, valueDisplay, isLeft) {
        let isDragging = false;

        const setState = (x, y) => {
            const state = { x, y };
            if (isLeft) { leftState = state; window.leftJoystickState = state; }
            else { rightState = state; window.rightJoystickState = state; }
            valueDisplay.textContent = `${x.toFixed(2)}, ${y.toFixed(2)}`;
        };

        function handleStart(e) {
            e.preventDefault();
            isDragging = true;
            stick.style.transition = 'none';
            handleMove(e);
        }

        function handleMove(e) {
            if (!isDragging) return;
            e.preventDefault();
            const rect = base.getBoundingClientRect();
            let clientX, clientY;
            if (e.type.includes('touch')) {
                if (e.touches.length === 0) return;
                clientX = e.touches[0].clientX;
                clientY = e.touches[0].clientY;
            } else {
                clientX = e.clientX;
                clientY = e.clientY;
            }

            let dx = clientX - rect.left - rect.width / 2;
            let dy = clientY - rect.top - rect.height / 2;
            const distance = Math.hypot(dx, dy);
            if (distance > maxDistance) {
                dx *= maxDistance / distance;
                dy *= maxDistance / distance;
            }
            stick.style.left = `calc(50% + ${dx}px)`;
            stick.style.top = `calc(50% + ${dy}px)`;

            let x = dx / maxDistance;
            let y = -dy / maxDistance; // up is positive
            if (Math.abs(x) < deadzone) x = 0;
            if (Math.abs(y) < deadzone) y = 0;
            setState(x, y);
        }

        function handleEnd(e) {
            if (!isDragging) return;
            e.preventDefault();
            isDragging = false;
            stick.style.transition = 'all 0.2s ease';
            stick.style.left = '50%';
            stick.style.top = '50%';
            setState(0, 0);
        }

        base.addEventListener('mousedown', handleStart);
        document.addEventListener('mousemove', handleMove);
        document.addEventListener('mouseup', handleEnd);
        base.addEventListener('touchstart', handleStart, { passive: false });
        document.addEventListener('touchmove', handleMove, { passive: false });
        document.addEventListener('touchend', handleEnd);
        document.addEventListener('touchcancel', handleEnd);
    }

    setupJoystick(leftStick, leftJoystick.querySelector('.joystick-base'), leftValue, true);
    setupJoystick(rightStick, rightJoystick.querySelector('.joystick-base'), rightValue, false);

    // Seconds since the previous frame; rates hold at any refresh rate
    let lastFrame = 0;
    function frameDt() {
        const now = performance.now();
        const dt = lastFrame ? Math.min(0.1, (now - lastFrame) / 1000) : 0;
        lastFrame = now;
        return dt;
    }

    function updateCameraMovement() {
        animationFrameId = requestAnimationFrame(updateCameraMovement);
        const viewer = window.AppState?.viewer || window.viewer;
        const dt = frameDt();
        if (!viewer?.camera || dt === 0) return;
        if (!leftState.x && !leftState.y && !rightState.x && !rightState.y) return;

        const camera = viewer.camera;
        const ellipsoid = viewer.scene.globe.ellipsoid;
        const speeds = getSpeedSettings();

        // Local east / north / up at the camera
        const enu = Cesium.Transforms.eastNorthUpToFixedFrame(camera.position, ellipsoid);
        const east = Cesium.Matrix4.getColumn(enu, 0, new Cesium.Cartesian3());
        const north = Cesium.Matrix4.getColumn(enu, 1, new Cesium.Cartesian3());
        const up = Cesium.Matrix4.getColumn(enu, 2, new Cesium.Cartesian3());
        const heading = camera.heading;
        // Heading is clockwise from north: forward = north*cos + east*sin
        const forward = Cesium.Cartesian3.add(
            Cesium.Cartesian3.multiplyByScalar(north, Math.cos(heading), new Cesium.Cartesian3()),
            Cesium.Cartesian3.multiplyByScalar(east, Math.sin(heading), new Cesium.Cartesian3()),
            new Cesium.Cartesian3());
        const right = Cesium.Cartesian3.add(
            Cesium.Cartesian3.multiplyByScalar(east, Math.cos(heading), new Cesium.Cartesian3()),
            Cesium.Cartesian3.multiplyByScalar(north, -Math.sin(heading), new Cesium.Cartesian3()),
            new Cesium.Cartesian3());

        // Right stick: move over the ground
        if (rightState.y) camera.move(forward, rightState.y * speeds.horizontal * dt);
        if (rightState.x) camera.move(right, rightState.x * speeds.horizontal * dt);
        // Left stick: climb and yaw. Takeoff / land own the heading while they run.
        if (leftState.y) camera.move(up, leftState.y * speeds.vertical * dt);
        if (leftState.x && !window.DeepGISDrone?.isVerticalActive?.()) {
            camera.setView({
                destination: camera.position,
                orientation: {
                    heading: Cesium.Math.zeroToTwoPi(heading + leftState.x * maxYawRate * dt),
                    pitch: camera.pitch,
                    roll: camera.roll,
                },
            });
        }
    }

    function startCameraMovement() {
        if (!animationFrameId) {
            lastFrame = 0;
            animationFrameId = requestAnimationFrame(updateCameraMovement);
        }
    }

    function stopCameraMovement() {
        if (animationFrameId) {
            cancelAnimationFrame(animationFrameId);
            animationFrameId = null;
        }
        leftState = { x: 0, y: 0 };
        rightState = { x: 0, y: 0 };
        window.leftJoystickState = leftState;
        window.rightJoystickState = rightState;
    }

    window.DeepGISJoysticks = { show: () => setVisible(true), hide: () => setVisible(false) };
    console.log('[Joysticks] Ready (left: climb / yaw, right: move)');
})();
