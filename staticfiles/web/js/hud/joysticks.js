// DeepGIS HUD virtual joysticks (QGC Mode 2), driving the camera on any body.
// ========== VIRTUAL JOYSTICK IMPLEMENTATION ==========
(function initJoysticks() {
    const leftJoystick = document.getElementById('leftJoystick');
    const rightJoystick = document.getElementById('rightJoystick');
    const leftStick = document.getElementById('leftJoystickStick');
    const rightStick = document.getElementById('rightJoystickStick');
    const leftValue = document.getElementById('leftJoystickValue');
    const rightValue = document.getElementById('rightJoystickValue');
    const joystickBtn = document.getElementById('hudJoystickBtn');

    // Verify all elements exist
    if (!leftJoystick || !rightJoystick || !leftStick || !rightStick || !joystickBtn) {
        console.error('[Joysticks] Missing required elements:', {
            leftJoystick: !!leftJoystick,
            rightJoystick: !!rightJoystick,
            leftStick: !!leftStick,
            rightStick: !!rightStick,
            joystickBtn: !!joystickBtn
        });
        return;
    }

    console.log('[Joysticks] All elements found, initializing...');

    let leftActive = false;
    let rightActive = false;
    let leftState = { x: 0, y: 0 };
    let rightState = { x: 0, y: 0 };
    let animationFrameId = null;

    // Expose joystick states globally for takeoff/landing integration
    window.leftJoystickState = leftState;
    window.rightJoystickState = rightState;

    // Joystick parameters
    const maxDistance = 45; // pixels from center
    const deadzone = 0.1; // 10% deadzone
    const maxYawRate = 45; // degrees per second

    // Get speed settings from inputs
    function getSpeedSettings() {
        const horizontalSpeedInput = document.getElementById('droneHorizontalSpeed');
        const verticalSpeedInput = document.getElementById('droneVerticalSpeed');

        return {
            horizontal: parseFloat(horizontalSpeedInput?.value) || 50,
            vertical: parseFloat(verticalSpeedInput?.value) || 5
        };
    }

    // Toggle joysticks visibility
    joystickBtn.addEventListener('click', () => {
        console.log('[Joysticks] Button clicked');
        const isActive = leftJoystick.classList.contains('active');
        if (isActive) {
            leftJoystick.classList.remove('active');
            rightJoystick.classList.remove('active');
            joystickBtn.classList.remove('active');
            stopCameraMovement();
            console.log('[Joysticks] Disabled');
        } else {
            leftJoystick.classList.add('active');
            rightJoystick.classList.add('active');
            joystickBtn.classList.add('active');
            startCameraMovement();
            console.log('[Joysticks] Enabled');
        }
    });

    // Handle joystick interaction
    function setupJoystick(stick, base, valueDisplay, isLeft) {
        let isDragging = false;

        function handleStart(e) {
            e.preventDefault();
            isDragging = true;
            if (isLeft) leftActive = true;
            else rightActive = true;
            stick.style.transition = 'none';
            console.log(`[Joystick] ${isLeft ? 'Left' : 'Right'} joystick activated`);

            // Handle the first movement immediately
            handleMove(e);
        }

        function handleMove(e) {
            if (!isDragging) return;

            e.preventDefault();
            const rect = base.getBoundingClientRect();
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;

            let clientX, clientY;
            if (e.type.includes('touch')) {
                if (e.touches.length === 0) return;
                clientX = e.touches[0].clientX;
                clientY = e.touches[0].clientY;
            } else {
                clientX = e.clientX;
                clientY = e.clientY;
            }

            let deltaX = clientX - rect.left - centerX;
            let deltaY = clientY - rect.top - centerY;

            // Limit to maxDistance
            const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
            if (distance > maxDistance) {
                const angle = Math.atan2(deltaY, deltaX);
                deltaX = Math.cos(angle) * maxDistance;
                deltaY = Math.sin(angle) * maxDistance;
            }

            // Update stick position
            stick.style.left = `calc(50% + ${deltaX}px)`;
            stick.style.top = `calc(50% + ${deltaY}px)`;

            // Normalize to -1 to 1
            let normalizedX = deltaX / maxDistance;
            let normalizedY = -deltaY / maxDistance; // Invert Y for intuitive up/down

            // Apply deadzone
            if (Math.abs(normalizedX) < deadzone) normalizedX = 0;
            if (Math.abs(normalizedY) < deadzone) normalizedY = 0;

            // Update state
            if (isLeft) {
                leftState = { x: normalizedX, y: normalizedY };
                window.leftJoystickState = leftState;
                valueDisplay.textContent = `${normalizedX.toFixed(2)}, ${normalizedY.toFixed(2)}`;
            } else {
                rightState = { x: normalizedX, y: normalizedY };
                window.rightJoystickState = rightState;
                valueDisplay.textContent = `${normalizedX.toFixed(2)}, ${normalizedY.toFixed(2)}`;
            }
        }

        function handleEnd(e) {
            if (!isDragging) return;

            e.preventDefault();
            isDragging = false;
            if (isLeft) leftActive = false;
            else rightActive = false;

            stick.style.transition = 'all 0.2s ease';
            stick.style.left = '50%';
            stick.style.top = '50%';

            if (isLeft) {
                leftState = { x: 0, y: 0 };
                window.leftJoystickState = leftState;
                valueDisplay.textContent = '0,0';
            } else {
                rightState = { x: 0, y: 0 };
                window.rightJoystickState = rightState;
                valueDisplay.textContent = '0,0';
            }

            console.log(`[Joystick] ${isLeft ? 'Left' : 'Right'} joystick released`);
        }

        // Mouse events - attach to the entire base for QGC-style interaction
        base.addEventListener('mousedown', handleStart);
        document.addEventListener('mousemove', handleMove);
        document.addEventListener('mouseup', handleEnd);

        // Touch events - attach to the entire base
        base.addEventListener('touchstart', handleStart, { passive: false });
        document.addEventListener('touchmove', handleMove, { passive: false });
        document.addEventListener('touchend', handleEnd);
        document.addEventListener('touchcancel', handleEnd);
    }

    setupJoystick(leftStick, leftJoystick.querySelector('.joystick-base'), leftValue, true);
    setupJoystick(rightStick, rightJoystick.querySelector('.joystick-base'), rightValue, false);

    // Camera movement loop - QGC Mode 2 mapping
    function updateCameraMovement() {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer || !viewer.camera) {
            animationFrameId = requestAnimationFrame(updateCameraMovement);
            return;
        }

        const camera = viewer.camera;
        const position = camera.positionCartographic;

        // Get current orientation
        const heading = camera.heading;
        const pitch = camera.pitch;
        const roll = camera.roll;

        // Get current speed settings
        const speeds = getSpeedSettings();

        // ========== QGC MODE 2: LEFT PHYSICAL STICK = THROTTLE (Y) + YAW (X) ==========
        // Note: rightState = left physical stick (CSS: left: 40px)
        // Right joystick element: altitude/throttle (Y) and yaw/rotation (X)
        if (rightState.x !== 0 || rightState.y !== 0) {
            const yawRate = rightState.x * maxYawRate * (Math.PI / 180); // Convert to radians
            const climbRate = rightState.y * speeds.vertical;

            // Yaw rotation (left/right rotation)
            if (rightState.x !== 0) {
                const newHeading = heading + (yawRate * 0.016);
                camera.setView({
                    destination: camera.position,
                    orientation: {
                        heading: newHeading,
                        pitch: pitch,
                        roll: roll
                    }
                });
            }

            // Throttle (altitude up/down)
            if (rightState.y !== 0) {
                const moveDistance = climbRate * 0.016;
                camera.moveUp(moveDistance);
            }
        }

        // ========== QGC MODE 2: RIGHT PHYSICAL STICK = PITCH (Y) + ROLL (X) ==========
        // Note: leftState = right physical stick (CSS: right: 40px)
        // Left joystick element: pitch/forward-backward (Y) and roll/strafe (X)
        if (leftState.x !== 0 || leftState.y !== 0) {
            const forwardSpeed = leftState.y * speeds.horizontal; // Pitch: Forward/backward
            const strafeSpeed = leftState.x * speeds.horizontal; // Roll: Left/right strafe

            // Calculate movement in world space
            const forwardVector = Cesium.Cartesian3.normalize(
                new Cesium.Cartesian3(
                    Math.sin(heading),
                    Math.cos(heading),
                    0
                ),
                new Cesium.Cartesian3()
            );

            const rightVector = Cesium.Cartesian3.normalize(
                new Cesium.Cartesian3(
                    Math.cos(heading),
                    -Math.sin(heading),
                    0
                ),
                new Cesium.Cartesian3()
            );

            // Move camera
            const moveDistance = forwardSpeed * 0.016; // ~60fps
            const strafeDistance = strafeSpeed * 0.016;

            camera.moveForward(moveDistance);
            camera.moveRight(strafeDistance);
        }

        animationFrameId = requestAnimationFrame(updateCameraMovement);
    }

    function startCameraMovement() {
        if (!animationFrameId) {
            updateCameraMovement();
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

    console.log('[Joysticks] Virtual joysticks initialized (QGC Mode 2: Left Physical=Throttle+Yaw, Right Physical=Pitch+Roll)');
})();
