// DeepGIS camera drone, shared by the Earth, Moon and planet viewers: takeoff and
// land, live gimbal, QGC-style orbit and fly forward on the drone widgets, plus
// window.DeepGISDrone for the AI pilot. All positions use the globe's ellipsoid.
// ========== TAKEOFF AND LAND FUNCTIONALITY ==========
(function initTakeoffLand() {
    const takeoffBtn = document.getElementById('droneTakeoffBtn');
    const landBtn = document.getElementById('droneLandBtn');
    const verticalSpeedInput = document.getElementById('droneVerticalSpeed');

    if (!takeoffBtn || !landBtn || !verticalSpeedInput) {
        console.error('[Takeoff/Land] Missing required elements');
        return;
    }

    let isClimbing = false;
    let isDescending = false;
    let animationId = null;
    let targetHeight = null; // ellipsoid height to stop at (AI pilot); null = until stopped

    // Move along the local vertical; camera.moveUp follows the view's up
    // vector, which is horizontal when the gimbal points straight down.
    function moveVertical(viewer, distance) {
        const up = viewer.scene.globe.ellipsoid.geodeticSurfaceNormal(viewer.camera.position, new Cesium.Cartesian3());
        viewer.camera.move(up, distance);
    }

    // Seconds since the previous animation frame; rates hold at any refresh rate
    function frameClock() {
        let last = performance.now();
        return () => {
            const now = performance.now();
            const dt = Math.min(0.1, (now - last) / 1000);
            last = now;
            return dt;
        };
    }

    // Takeoff function
    function startTakeoff(target) {
        if (isClimbing) {
            stopVerticalMovement();
            return;
        }
        targetHeight = typeof target === 'number' ? target : null;

        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer || !viewer.camera) {
            console.error('[Takeoff] Viewer not available');
            return;
        }

        isClimbing = true;
        isDescending = false;
        takeoffBtn.classList.add('active');
        takeoffBtn.innerHTML = '<i class="fas fa-stop"></i> Stop';
        landBtn.disabled = true;

        const verticalSpeed = parseFloat(verticalSpeedInput.value) || 5;

        // Store initial heading when starting takeoff
        let currentHeading = viewer.camera.heading;
        const maxYawRate = 45; // degrees per second (same as joystick)

        console.log(`[Takeoff] Starting climb at ${verticalSpeed} m/s (gimbal + joystick yaw control enabled)`);

        const tick = frameClock();
        function climb() {
            if (!isClimbing) return;

            const camera = viewer.camera;
            if (targetHeight !== null && camera.positionCartographic.height >= targetHeight) {
                stopVerticalMovement();
                return;
            }
            const dt = tick();
            const moveDistance = verticalSpeed * dt;

            // Get joystick state for yaw rate control
            // Note: rightState = left physical stick (has yaw on X-axis)
            const rightJoystickState = window.rightJoystickState || { x: 0, y: 0 };
            const joystickYawRate = rightJoystickState.x * maxYawRate * (Math.PI / 180); // rad/s

            // Apply joystick yaw rate to current heading
            if (joystickYawRate !== 0) {
                currentHeading = currentHeading + (joystickYawRate * dt);
            }

            // Apply gimbal control (pitch and yaw offset from sliders)
            const pitchSlider = document.getElementById('droneOrbitPitch');
            const yawSlider = document.getElementById('droneOrbitYaw');

            if (pitchSlider && yawSlider) {
                const pitchDegrees = parseFloat(pitchSlider.value) || -10;
                const yawDegrees = parseFloat(yawSlider.value) || 0;

                // Apply yaw offset to current heading
                // Current heading includes joystick yaw adjustments
                // Yaw slider adds gimbal offset
                const yawOffsetRadians = Cesium.Math.toRadians(yawDegrees);
                const finalHeading = Cesium.Math.zeroToTwoPi(currentHeading + yawOffsetRadians);
                const finalPitch = Cesium.Math.toRadians(pitchDegrees);

                // Move up while maintaining orientation
            moveVertical(viewer, moveDistance);

                // Apply gimbal orientation (heading + yaw offset, pitch from slider)
                camera.setView({
                    destination: camera.position,
                    orientation: {
                        heading: finalHeading,
                        pitch: finalPitch,
                        roll: 0
                    }
                });
            } else {
                // Fallback: just move up without gimbal control
                moveVertical(viewer, moveDistance);
            }

            animationId = requestAnimationFrame(climb);
        }

        climb();
    }

    // Land function
    function startLanding(target) {
        if (isDescending) {
            stopVerticalMovement();
            return;
        }
        targetHeight = typeof target === 'number' ? target : null;

        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer || !viewer.camera) {
            console.error('[Land] Viewer not available');
            return;
        }

        isDescending = true;
        isClimbing = false;
        landBtn.classList.add('active');
        landBtn.innerHTML = '<i class="fas fa-stop"></i> Stop';
        takeoffBtn.disabled = true;

        const verticalSpeed = parseFloat(verticalSpeedInput.value) || 5;

        // Store initial heading when starting landing
        let currentHeading = viewer.camera.heading;
        const maxYawRate = 45; // degrees per second (same as joystick)

        console.log(`[Land] Starting descent at ${verticalSpeed} m/s (gimbal + joystick yaw control enabled)`);

        const tick = frameClock();
        function descend() {
            if (!isDescending) return;

            const camera = viewer.camera;
            const here = camera.positionCartographic;
            const ground = viewer.scene.globe.getHeight(here);
            if ((targetHeight !== null && here.height <= targetHeight) ||
                (ground !== undefined && here.height <= ground + 2)) {
                stopVerticalMovement();
                return;
            }
            const dt = tick();
            const moveDistance = verticalSpeed * dt;

            // Get joystick state for yaw rate control
            // Note: rightState = left physical stick (has yaw on X-axis)
            const rightJoystickState = window.rightJoystickState || { x: 0, y: 0 };
            const joystickYawRate = rightJoystickState.x * maxYawRate * (Math.PI / 180); // rad/s

            // Apply joystick yaw rate to current heading
            if (joystickYawRate !== 0) {
                currentHeading = currentHeading + (joystickYawRate * dt);
            }

            // Apply gimbal control (pitch and yaw offset from sliders)
            const pitchSlider = document.getElementById('droneOrbitPitch');
            const yawSlider = document.getElementById('droneOrbitYaw');

            if (pitchSlider && yawSlider) {
                const pitchDegrees = parseFloat(pitchSlider.value) || -10;
                const yawDegrees = parseFloat(yawSlider.value) || 0;

                // Apply yaw offset to current heading
                // Current heading includes joystick yaw adjustments
                // Yaw slider adds gimbal offset
                const yawOffsetRadians = Cesium.Math.toRadians(yawDegrees);
                const finalHeading = Cesium.Math.zeroToTwoPi(currentHeading + yawOffsetRadians);
                const finalPitch = Cesium.Math.toRadians(pitchDegrees);

                // Move down while maintaining orientation
            moveVertical(viewer, -moveDistance);

                // Apply gimbal orientation (heading + yaw offset, pitch from slider)
                camera.setView({
                    destination: camera.position,
                    orientation: {
                        heading: finalHeading,
                        pitch: finalPitch,
                        roll: 0
                    }
                });
            } else {
                // Fallback: just move down without gimbal control
                moveVertical(viewer, -moveDistance);
            }

            animationId = requestAnimationFrame(descend);
        }

        descend();
    }

    // Stop vertical movement
    function stopVerticalMovement() {
        if (animationId) {
            cancelAnimationFrame(animationId);
            animationId = null;
        }

        isClimbing = false;
        isDescending = false;
        targetHeight = null;

        takeoffBtn.classList.remove('active');
        takeoffBtn.innerHTML = '<i class="fas fa-arrow-up"></i> Takeoff';
        takeoffBtn.disabled = false;

        landBtn.classList.remove('active');
        landBtn.innerHTML = '<i class="fas fa-arrow-down"></i> Land';
        landBtn.disabled = false;

        console.log('[Vertical Movement] Stopped');
    }

    // Event listeners
    takeoffBtn.addEventListener('click', () => startTakeoff());
    landBtn.addEventListener('click', () => startLanding());

    // Programmatic control (AI pilot): climb/descend to an ellipsoid height
    window.DeepGISDrone = Object.assign(window.DeepGISDrone || {}, {
        climbTo(height) { stopVerticalMovement(); startTakeoff(height); },
        descendTo(height) { stopVerticalMovement(); startLanding(height); },
        stopVertical: stopVerticalMovement,
        isVerticalActive: () => isClimbing || isDescending,
    });

    // Stop on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && (isClimbing || isDescending)) {
            stopVerticalMovement();
        }
    });

    console.log('[Takeoff/Land] Initialized');
})();

// ========== LIVE GIMBAL CONTROL (Pitch & Yaw) ==========
(function initLiveGimbalControl() {
    const pitchSlider = document.getElementById('droneOrbitPitch');
    const pitchValue = document.getElementById('orbitPitchValue');
    const yawSlider = document.getElementById('droneOrbitYaw');
    const yawValue = document.getElementById('orbitYawValue');

    if (!pitchSlider || !pitchValue || !yawSlider || !yawValue) {
        console.error('[Gimbal Control] Missing required elements');
        return;
    }

    // Check if orbit is active
    function isOrbitActive() {
        const orbitBtn = document.getElementById('droneOrbitBtn');
        return orbitBtn && orbitBtn.classList.contains('active');
    }

    // Check if takeoff or landing is active
    function isVerticalMovementActive() {
        const takeoffBtn = document.getElementById('droneTakeoffBtn');
        const landBtn = document.getElementById('droneLandBtn');
        return (takeoffBtn && takeoffBtn.classList.contains('active')) ||
               (landBtn && landBtn.classList.contains('active'));
    }

    // Update pitch display and camera (except during orbit/takeoff/landing - they handle it)
    pitchSlider.addEventListener('input', (e) => {
        const pitchDegrees = parseFloat(e.target.value);
        pitchValue.textContent = `${pitchDegrees}°`;

        // Only update camera if not orbiting, taking off, or landing
        // (those animations handle pitch/yaw themselves)
        if (!isOrbitActive() && !isVerticalMovementActive()) {
            const viewer = window.AppState?.viewer || window.viewer;
            if (!viewer || !viewer.camera) {
                return;
            }

            const camera = viewer.camera;
            const heading = camera.heading;
            const roll = camera.roll;
            const pitchRadians = Cesium.Math.toRadians(pitchDegrees);

            camera.setView({
                destination: camera.position,
                orientation: {
                    heading: heading,
                    pitch: pitchRadians,
                    roll: roll
                }
            });
        }
    });

    // Update yaw display and camera (except during orbit/takeoff/landing - they handle it)
    yawSlider.addEventListener('input', (e) => {
        const yawDegrees = parseFloat(e.target.value);
        yawValue.textContent = `${yawDegrees}°`;

        // Apply yaw rotation when not in special modes
        if (!isOrbitActive() && !isVerticalMovementActive()) {
            const viewer = window.AppState?.viewer || window.viewer;
            if (!viewer || !viewer.camera) {
                return;
            }

            const camera = viewer.camera;
            const pitch = camera.pitch;
            const roll = camera.roll;

            // Convert yaw offset to absolute heading
            const yawOffsetRadians = Cesium.Math.toRadians(yawDegrees);
            const baseHeading = 0; // North
            const newHeading = Cesium.Math.zeroToTwoPi(baseHeading + yawOffsetRadians);

            camera.setView({
                destination: camera.position,
                orientation: {
                    heading: newHeading,
                    pitch: pitch,
                    roll: roll
                }
            });
        }
        // During orbit/takeoff/landing, yaw is applied by those animations
    });

    console.log('[Gimbal Control] Live pitch and yaw control initialized (works with orbit, takeoff, and landing)');
})();

// ========== QGROUNDCONTROL-STYLE ORBIT IMPLEMENTATION (ENHANCED) ==========
(function initDroneOrbit() {
    const orbitBtn = document.getElementById('droneOrbitBtn');
    const stopOrbitBtn = document.getElementById('stopOrbitBtn');
    const pauseOrbitBtn = document.getElementById('pauseOrbitBtn');
    const stopOrbitContainer = document.getElementById('stopOrbitContainer');
    const pauseOrbitContainer = document.getElementById('pauseOrbitContainer');
    const orbitProgressContainer = document.getElementById('orbitProgressContainer');
    const orbitProgressText = document.getElementById('orbitProgressText');
    const orbitRadiusInput = document.getElementById('droneOrbitRadius');
    const orbitPitchInput = document.getElementById('droneOrbitPitch');
    const horizontalSpeedInput = document.getElementById('droneHorizontalSpeed');
    const revolutionsInput = document.getElementById('droneOrbitRevolutions');

    if (!orbitBtn || !stopOrbitBtn) {
        console.error('[Orbit] Missing required elements');
        return;
    }

    let isOrbiting = false;
    let isPaused = false;
    let orbitAnimationId = null;
    let orbitStartTime = null;
    let orbitLastFrameTime = null;
    let orbitPausedTime = 0; // Total time spent paused
    let orbitCenterPoint = null;
    let orbitInitialAngle = 0; // Starting angle in orbit (radians)
    let orbitDirection = 1; // 1 = counter-clockwise seen from above, -1 = clockwise
    let orbitStartAltitude = 0; // Altitude when orbit started (maintains current altitude)
    let lastVerificationTime = 0; // For performance optimization
    let lastProgressUpdateTime = 0; // For UI updates

    // Start orbit (QGC-style: use current position as center by default)
    function startOrbit() {
        if (isOrbiting) {
            stopOrbit();
            return;
        }

        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer || !viewer.camera) {
            console.error('[Orbit] Viewer not available');
            return;
        }

        orbitDirection = 1;

        // QGC behavior: Use current camera position as orbit center
        const camera = viewer.camera;
        const currentPosition = camera.positionCartographic;

        // Set center point at ground level (directly below current camera position)
        orbitCenterPoint = Cesium.Cartesian3.fromRadians(
            currentPosition.longitude,
            currentPosition.latitude,
            0, // Ground level
            viewer.scene.globe.ellipsoid
        );

        // Log center point for debugging
        const centerCart = Cesium.Cartographic.fromCartesian(orbitCenterPoint, viewer.scene.globe.ellipsoid);
        console.log(`[Orbit] Center set at: ${Cesium.Math.toDegrees(centerCart.longitude).toFixed(6)}°, ${Cesium.Math.toDegrees(centerCart.latitude).toFixed(6)}°`);
        console.log(`[Orbit] Current camera at: ${Cesium.Math.toDegrees(currentPosition.longitude).toFixed(6)}°, ${Cesium.Math.toDegrees(currentPosition.latitude).toFixed(6)}°, ${currentPosition.height.toFixed(1)}m`);

        startOrbitWithCenter();
    }

    // Start orbit with established center point
    function startOrbitWithCenter() {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer || !viewer.camera || !orbitCenterPoint) {
            console.error('[Orbit] Cannot start orbit');
            return;
        }

        // Get parameters
        const radius = parseFloat(orbitRadiusInput.value) || 5000;
        const horizontalSpeed = parseFloat(horizontalSpeedInput.value) || 50; // m/s
        const maxRevolutions = parseFloat(revolutionsInput?.value) || 10;

        const camera = viewer.camera;
        const currentPosition = camera.positionCartographic;

        // Store current altitude - orbit will maintain this altitude
        orbitStartAltitude = currentPosition.height;

        // Initialize orbit state BEFORE calculating angle
        console.log(`[Orbit] Starting enhanced orbit: ${radius}m radius, ${maxRevolutions} revolutions, altitude ${orbitStartAltitude.toFixed(1)}m`);
        isOrbiting = true;
        isPaused = false;
        orbitStartTime = Date.now();
        orbitLastFrameTime = Date.now();
        orbitPausedTime = 0;
        lastVerificationTime = 0;
        lastProgressUpdateTime = 0;

        // Update UI
        orbitBtn.classList.add('active');
        orbitBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Orbit';
        stopOrbitContainer.style.display = 'block';
        if (pauseOrbitContainer) pauseOrbitContainer.style.display = 'block';
        if (orbitProgressContainer) orbitProgressContainer.style.display = 'block';

        // Calculate initial angle from current position
        calculateInitialAngle(currentPosition);

        function calculateInitialAngle(position) {
            // Calculate initial angle based on position relative to center
            const centerCartographic = Cesium.Cartographic.fromCartesian(orbitCenterPoint, viewer.scene.globe.ellipsoid);
            // Scale longitude to ground distance so the angle matches the east/north
            // offsets used by animateOrbit (otherwise the camera jumps at high latitude).
            const deltaLon = (position.longitude - centerCartographic.longitude) * Math.cos(centerCartographic.latitude);
            const deltaLat = position.latitude - centerCartographic.latitude;

            // If camera is directly above center (or very close), start at angle 0 (north)
            const distanceFromCenter = Math.sqrt(deltaLon * deltaLon + deltaLat * deltaLat);
            if (distanceFromCenter < 0.00001) { // Less than ~1 meter
                orbitInitialAngle = 0; // Start pointing north
                console.log(`[Orbit] Camera at center, starting from north (0°)`);
            } else {
                orbitInitialAngle = Math.atan2(deltaLat, deltaLon);
                console.log(`[Orbit] Initial angle: ${(orbitInitialAngle * 180 / Math.PI).toFixed(1)}°`);
            }

            // Start orbit animation with smooth transition
            startOrbitAnimation();
        }
    }

    // Start orbit animation (called after initial angle is calculated)
    function startOrbitAnimation() {
        if (!isOrbiting) return;

        // Enhanced orbit animation with all improvements
        function animateOrbit() {
            if (!isOrbiting) return;

            // Handle pause state
            if (isPaused) {
                orbitAnimationId = requestAnimationFrame(animateOrbit);
                return;
            }

            const viewer = window.AppState?.viewer || window.viewer;
            if (!viewer || !viewer.camera) {
                stopOrbit();
                return;
            }

            const camera = viewer.camera;
            const pitchRaw = parseFloat(orbitPitchInput.value);
            const pitchDegrees = Number.isFinite(pitchRaw) ? pitchRaw : -10;
            const yawRaw = parseFloat(document.getElementById('droneOrbitYaw')?.value);
            const yawOffsetDegrees = Number.isFinite(yawRaw) ? yawRaw : 50;
            const radius = parseFloat(orbitRadiusInput.value) || 5000;
            const horizontalSpeed = parseFloat(horizontalSpeedInput.value) || 50; // m/s
            const maxRevolutions = parseFloat(revolutionsInput?.value) || 10;

            // Validate radius
            if (radius <= 0) {
                console.error('[Orbit] Invalid radius, stopping');
                stopOrbit();
                return;
            }

            // Calculate angular velocity (radians per second)
            const angularVelocity = horizontalSpeed / radius; // rad/s

            // Calculate angle based on elapsed time (accounting for paused time)
            const currentTime = Date.now();
            const elapsed = (currentTime - orbitStartTime - orbitPausedTime) / 1000; // seconds
            const deltaTime = (currentTime - orbitLastFrameTime) / 1000; // seconds since last frame
            orbitLastFrameTime = currentTime;

            // Calculate current angle from elapsed time
            const currentRadiansFromStart = angularVelocity * elapsed;
            const orbitAngle = orbitInitialAngle + orbitDirection * currentRadiansFromStart;

            // ========== REVOLUTION COUNTING & AUTO-STOP ==========
            const totalRadians = maxRevolutions * 2 * Math.PI;
            const completedRevolutions = currentRadiansFromStart / (2 * Math.PI);

            // Check if completed all revolutions
            if (currentRadiansFromStart >= totalRadians) {
                console.log(`[Orbit] Completed ${maxRevolutions} revolutions - auto-stopping`);
                stopOrbit();
                return;
            }

            // Update progress display (throttled to every 100ms)
            if (orbitProgressText && currentTime - lastProgressUpdateTime > 100) {
                orbitProgressText.textContent = `Revolution: ${completedRevolutions.toFixed(2)} / ${maxRevolutions.toFixed(2)}`;
                lastProgressUpdateTime = currentTime;
            }

            // ========== PERFECT CIRCLE COORDINATE TRANSFORMATION ==========
            const centerCartographic = Cesium.Cartographic.fromCartesian(orbitCenterPoint, viewer.scene.globe.ellipsoid);
            const ellipsoid = viewer.scene.globe.ellipsoid;

            // Use small-circle mathematics for perfect circular orbits
            // This maintains constant distance from center (not great circle)
            const bearing = orbitAngle;
            const centerLon = centerCartographic.longitude;
            const centerLat = centerCartographic.latitude;

            // Calculate offset in local tangent plane (ENU coordinates)
            // East component
            const east = radius * Math.cos(bearing);
            // North component
            const north = radius * Math.sin(bearing);

            // Convert ENU offset to lat/lon changes
            // This creates a perfect circle in the local tangent plane
            const earthRadius = ellipsoid.maximumRadius;

            // Delta latitude (north-south is simple)
            const deltaLat = north / earthRadius;

            // Delta longitude (east-west requires latitude correction)
            // At higher latitudes, longitude lines are closer together
            const deltaLon = east / (earthRadius * Math.cos(centerLat));

            // Calculate final position
            const cameraLatitude = centerLat + deltaLat;
            const cameraLongitude = centerLon + deltaLon;

            // ========== CIRCLE ACCURACY VERIFICATION ==========
            const VERIFICATION_INTERVAL = 5000; // 5 seconds
            if (currentTime - lastVerificationTime > VERIFICATION_INTERVAL) {
                const currentPos = Cesium.Cartesian3.fromRadians(cameraLongitude, cameraLatitude, orbitStartAltitude, ellipsoid);
                const actualDistance = Cesium.Cartesian3.distance(currentPos, orbitCenterPoint);
                const error = Math.abs(actualDistance - radius);
                const errorPercent = (error / radius * 100).toFixed(3);
                const bearing = Cesium.Math.toDegrees(orbitAngle % (2 * Math.PI));
                console.log(`[Orbit] Circle Check: Distance=${actualDistance.toFixed(1)}m, Target=${radius}m, Error=${error.toFixed(1)}m (${errorPercent}%), Bearing=${bearing.toFixed(0)}°, Rev=${completedRevolutions.toFixed(2)}`);
                lastVerificationTime = currentTime;
            }

            // QGC-style: Maintain current altitude (can be modified by takeoff/land)
            let finalAltitude = orbitStartAltitude;

            // Check if takeoff/land is active
            const takeoffBtn = document.getElementById('droneTakeoffBtn');
            const landBtn = document.getElementById('droneLandBtn');
            const isTakeoffActive = takeoffBtn && takeoffBtn.classList.contains('active');
            const isLandActive = landBtn && landBtn.classList.contains('active');

            // If takeoff/land is active, integrate their altitude changes
            if (isTakeoffActive || isLandActive) {
                const currentAlt = camera.positionCartographic.height;
                const verticalSpeed = parseFloat(document.getElementById('droneVerticalSpeed')?.value) || 5;
                const altitudeChange = (isTakeoffActive ? verticalSpeed : -verticalSpeed) * deltaTime;
                finalAltitude = currentAlt + altitudeChange;
                orbitStartAltitude = finalAltitude; // Update reference altitude
            }

            // ========== IMPROVED HEADING CALCULATION ==========
            // Calculate accurate geodesic bearing from camera to center
            const cameraCart = new Cesium.Cartographic(cameraLongitude, cameraLatitude, 0);
            const geodesic = new Cesium.EllipsoidGeodesic(cameraCart, centerCartographic, ellipsoid);

            // Get the initial bearing (heading) from camera towards center
            let headingToCenter = geodesic.startHeading;

            // Apply yaw offset for gimbal control
            const yawOffsetRadians = Cesium.Math.toRadians(yawOffsetDegrees);
            const finalHeading = Cesium.Math.zeroToTwoPi(headingToCenter + yawOffsetRadians);

            // Set camera position and orientation
            // This emulates a drone with gimbal: drone orbits, gimbal points at center + offset
            camera.setView({
                destination: Cesium.Cartesian3.fromRadians(
                    cameraLongitude,
                    cameraLatitude,
                    finalAltitude,
                    ellipsoid
                ),
                orientation: {
                    heading: finalHeading,
                    pitch: Cesium.Math.toRadians(pitchDegrees),
                    roll: 0.0
                }
            });

            orbitAnimationId = requestAnimationFrame(animateOrbit);
        }

        animateOrbit();
    }

    // Pause/Resume orbit
    function togglePause() {
        if (!isOrbiting) return;

        const pauseStartTime = Date.now();
        isPaused = !isPaused;

        if (isPaused) {
            // Store when we paused
            window.orbitPauseStartTime = pauseStartTime;
            if (pauseOrbitBtn) {
                pauseOrbitBtn.innerHTML = '<i class="fas fa-play"></i> Resume (Space)';
                pauseOrbitBtn.classList.add('active');
            }
            console.log('[Orbit] Paused');
        } else {
            // Calculate how long we were paused and add to total
            const pauseDuration = pauseStartTime - (window.orbitPauseStartTime || pauseStartTime);
            orbitPausedTime += pauseDuration;
            orbitLastFrameTime = Date.now(); // Reset frame time to avoid jump

            if (pauseOrbitBtn) {
                pauseOrbitBtn.innerHTML = '<i class="fas fa-pause"></i> Pause (Space)';
                pauseOrbitBtn.classList.remove('active');
            }
            console.log('[Orbit] Resumed (paused for ' + (pauseDuration/1000).toFixed(1) + 's)');
        }
    }

    // Stop orbit
    function stopOrbit() {
        if (orbitAnimationId) {
            cancelAnimationFrame(orbitAnimationId);
            orbitAnimationId = null;
        }

        isOrbiting = false;
        isPaused = false;
        orbitStartTime = null;
        orbitLastFrameTime = null;
        orbitPausedTime = 0;
        orbitCenterPoint = null;
        orbitInitialAngle = 0;
        orbitDirection = 1;
        orbitStartAltitude = 0;
        lastVerificationTime = 0;
        lastProgressUpdateTime = 0;

        // Update UI
        orbitBtn.classList.remove('active');
        orbitBtn.innerHTML = '<i class="fas fa-circle-notch"></i> Orbit';
        stopOrbitContainer.style.display = 'none';
        if (pauseOrbitContainer) pauseOrbitContainer.style.display = 'none';
        if (orbitProgressContainer) orbitProgressContainer.style.display = 'none';
        if (pauseOrbitBtn) {
            pauseOrbitBtn.innerHTML = '<i class="fas fa-pause"></i> Pause (Space)';
            pauseOrbitBtn.classList.remove('active');
        }

        console.log('[Orbit] Stopped');
    }

    // Event listeners
    orbitBtn.addEventListener('click', startOrbit);
    stopOrbitBtn.addEventListener('click', stopOrbit);
    if (pauseOrbitBtn) {
        pauseOrbitBtn.addEventListener('click', togglePause);
    }

    // Programmatic control (AI pilot): orbit a given ground point from the
    // camera's current position, at the current height and widget settings
    window.DeepGISDrone = Object.assign(window.DeepGISDrone || {}, {
        orbitAround(center, { clockwise = false } = {}) {
            if (isOrbiting) stopOrbit();
            orbitCenterPoint = center;
            orbitDirection = clockwise ? -1 : 1;
            startOrbitWithCenter();
        },
        stopOrbit() { if (isOrbiting) stopOrbit(); },
        isOrbiting: () => isOrbiting,
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isOrbiting) {
            stopOrbit();
        } else if (e.key === ' ' && isOrbiting && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
            e.preventDefault(); // Prevent page scroll
            togglePause();
        }
    });

    console.log('[Orbit] Enhanced orbit system initialized with all improvements');
})();

// ========== FLY FORWARD ==========
// Along the current heading at the current height, pitch and roll. Speed is
// clamped to the input's own range, which each body's widgets set.
(function initFlyForward() {
    const flyBtn = document.getElementById('droneFlyBtn');
    const distanceInput = document.getElementById('droneFlyDistance');
    const speedInput = document.getElementById('droneFlySpeed');
    if (!flyBtn || !distanceInput || !speedInput) {
        console.error('[Fly Forward] Missing required elements');
        return;
    }

    const notify = (text, kind) => window.worldSamplerUI?.showNotification?.(text, kind);
    const bounded = (input, value) => {
        const lo = parseFloat(input.min), hi = parseFloat(input.max);
        return Math.min(Number.isFinite(hi) ? hi : Infinity, Math.max(Number.isFinite(lo) ? lo : 0, value));
    };

    // Great-circle destination at the radius of curvature under the camera
    function destinationPoint(ellipsoid, lon, lat, height, bearing, distance) {
        const a = ellipsoid.maximumRadius, b = ellipsoid.minimumRadius;
        const e2 = 1 - (b * b) / (a * a);
        const sinLat = Math.sin(lat), cosLat = Math.cos(lat);
        const d = distance / (a / Math.sqrt(1 - e2 * sinLat * sinLat) + height);
        const destLat = Math.asin(sinLat * Math.cos(d) + cosLat * Math.sin(d) * Math.cos(bearing));
        const destLon = lon + Math.atan2(Math.sin(bearing) * Math.sin(d) * cosLat,
                                         Math.cos(d) - sinLat * Math.sin(destLat));
        return Cesium.Cartesian3.fromRadians(destLon, destLat, height, ellipsoid);
    }

    function flyForward(distance = parseFloat(distanceInput.value) || 100,
                        speedKmh = parseFloat(speedInput.value) || 100) {
        const viewer = window.AppState?.viewer || window.viewer;
        if (!viewer || !viewer.camera) {
            console.error('[Fly Forward] Viewer not available');
            return;
        }
        const speed = bounded(speedInput, speedKmh);
        if (speed !== speedKmh) speedInput.value = speed;
        const camera = viewer.camera;
        const here = camera.positionCartographic;
        const heading = camera.heading, pitch = camera.pitch, roll = camera.roll;
        const duration = Math.max(0.5, distance / (speed / 3.6));
        const headingDeg = Cesium.Math.toDegrees(heading).toFixed(1);
        camera.flyTo({
            destination: destinationPoint(viewer.scene.globe.ellipsoid, here.longitude, here.latitude,
                                          here.height, heading, distance),
            duration,
            orientation: { heading, pitch, roll },
            complete: () => notify(`Flew ${distance}m forward at ${speed} km/h (heading: ${headingDeg}°)`, 'success'),
        });
        notify(`Flying ${distance}m forward at ${speed} km/h along heading ${headingDeg}°...`, 'info');
    }

    const updateLabel = () => {
        flyBtn.innerHTML = `<i class="fas fa-paper-plane"></i> Fly Forward ${distanceInput.value || 100}m @ ${speedInput.value || 100} km/h`;
    };
    flyBtn.addEventListener('click', () => flyForward());
    distanceInput.addEventListener('input', updateLabel);
    speedInput.addEventListener('input', updateLabel);

    window.DeepGISDrone = Object.assign(window.DeepGISDrone || {}, { flyForward });
})();
