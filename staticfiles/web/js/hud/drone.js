// DeepGIS camera drone, shared by the Earth, Moon and planet viewers. Drives the
// Flight panel (hud/flight_panel.html): takeoff and land to a target height, fly
// forward, orbit around the point in the centre of the view, camera pitch and yaw,
// plus window.DeepGISDrone for the AI pilot and the share links. All positions
// use the globe's ellipsoid; speeds come from the panel's H / V inputs (m/s).
(function initDrone() {
    const $ = (id) => document.getElementById(id);
    // The viewer, switched to 3D first: the page opens in 2D (core/cesium-init.js) and
    // the drone's vertical and circle maths only mean something on the globe. The
    // instant morph keeps the current view (see hud/panels.js).
    const peekViewer = () => window.AppState?.viewer || window.viewer;
    const getViewer = () => {
        const viewer = peekViewer();
        if (viewer?.scene && viewer.scene.mode !== Cesium.SceneMode.SCENE3D) viewer.scene.morphTo3D(0);
        return viewer;
    };
    const num = (el, fallback) => {
        const v = parseFloat(el?.value);
        return Number.isFinite(v) ? v : fallback;
    };
    const notify = (text, kind) => window.worldSamplerUI?.showNotification?.(text, kind);
    const fmtDeg = (v) => `${Math.round(v)}°`;

    const els = {
        hSpeed: $('droneHorizontalSpeed'),
        vSpeed: $('droneVerticalSpeed'),
        flyDistance: $('droneFlyDistance'),
        flyBtn: $('droneFlyBtn'),
        targetAgl: $('droneTargetAgl'),
        takeoffBtn: $('droneTakeoffBtn'),
        landBtn: $('droneLandBtn'),
        radius: $('droneOrbitRadius'),
        laps: $('droneOrbitRevolutions'),
        clockwise: $('droneOrbitClockwise'),
        orbitBtn: $('droneOrbitBtn'),
        stopOrbitBtn: $('stopOrbitBtn'),
        pauseOrbitBtn: $('pauseOrbitBtn'),
        stopOrbitContainer: $('stopOrbitContainer'),
        pauseOrbitContainer: $('pauseOrbitContainer'),
        progressContainer: $('orbitProgressContainer'),
        progressText: $('orbitProgressText'),
        pitch: $('droneOrbitPitch'),
        pitchValue: $('orbitPitchValue'),
        yaw: $('droneOrbitYaw'),
        yawValue: $('orbitYawValue'),
    };
    if (!els.takeoffBtn || !els.landBtn || !els.orbitBtn || !els.flyBtn || !els.stopOrbitBtn) {
        console.error('[Drone] Flight panel missing');
        return;
    }

    const hSpeed = () => Math.max(0.1, num(els.hSpeed, 30));
    const vSpeed = () => Math.max(0.1, num(els.vSpeed, 5));
    const pitchDeg = () => num(els.pitch, -45);
    const yawDeg = () => num(els.yaw, 0);
    const yawRateMax = Cesium.Math.toRadians(45); // joystick full deflection, rad/s

    // Flight state. vertical: { dir: 1|-1, target: ellipsoid height|null, speed, heading,
    // pitch, raf }. orbit: see startOrbit.
    let vertical = null;
    let orbit = null;

    // Move along the local vertical; camera.moveUp follows the view's up vector,
    // which is horizontal when the camera points straight down.
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

    // Ground height under a cartographic position (undefined until terrain tiles load)
    const groundAt = (viewer, carto) => viewer.scene.globe.getHeight(carto);

    function setButton(btn, active, idleHtml) {
        btn.classList.toggle('active', active);
        btn.innerHTML = active ? '<i class="fas fa-stop"></i> Stop' : idleHtml;
    }

    // ========== TAKEOFF AND LAND ==========
    // Climb or descend at V speed along the local vertical, holding heading and
    // pitch (the left joystick and the yaw slider can still turn it). Takeoff ends
    // at the panel's height above ground, or at the ellipsoid height the AI pilot
    // asked for; Land ends 2 m above the ground.
    function stopVertical() {
        if (!vertical) return;
        cancelAnimationFrame(vertical.raf);
        vertical = null;
        setButton(els.takeoffBtn, false, '<i class="fas fa-arrow-up"></i> Takeoff');
        setButton(els.landBtn, false, '<i class="fas fa-arrow-down"></i> Land');
        els.takeoffBtn.disabled = false;
        els.landBtn.disabled = false;
    }

    function startVertical(dir, target = null, speed = vSpeed()) {
        const viewer = getViewer();
        if (!viewer?.camera) return;
        stopVertical();
        const camera = viewer.camera;
        vertical = { dir, target, speed: Math.max(0.1, speed), heading: camera.heading, pitch: camera.pitch, raf: 0 };
        setButton(dir > 0 ? els.takeoffBtn : els.landBtn, true);
        (dir > 0 ? els.landBtn : els.takeoffBtn).disabled = true;

        const tick = frameClock();
        let first = true;
        const step = () => {
            if (!vertical) return;
            const here = camera.positionCartographic;
            const ground = groundAt(viewer, here);
            let goal = vertical.target;
            if (goal === null && ground !== undefined) {
                goal = dir > 0 ? ground + Math.max(1, num(els.targetAgl, 100)) : ground + 2;
            }
            const remaining = goal === null ? Infinity : dir * (goal - here.height);
            if (remaining <= 0) {
                if (first && target === null) {
                    notify(dir > 0 ? `Already above ${Math.round(goal - ground)} m over the ground` : 'Already on the ground', 'info');
                }
                stopVertical();
                return;
            }
            first = false;

            const dt = tick();
            const yawRate = (window.leftJoystickState?.x || 0) * yawRateMax;
            vertical.heading = Cesium.Math.zeroToTwoPi(vertical.heading + yawRate * dt);
            moveVertical(viewer, dir * Math.min(vertical.speed * dt, remaining));
            camera.setView({
                destination: camera.position,
                orientation: { heading: vertical.heading, pitch: vertical.pitch, roll: 0 },
            });
            vertical.raf = requestAnimationFrame(step);
        };
        step();
    }

    els.takeoffBtn.addEventListener('click', () => (vertical?.dir > 0 ? stopVertical() : startVertical(1)));
    els.landBtn.addEventListener('click', () => (vertical?.dir < 0 ? stopVertical() : startVertical(-1)));

    // ========== CAMERA PITCH AND YAW ==========
    // Pitch is the camera's pitch and follows the camera. Yaw turns the camera by
    // the slider's change while idle; while orbiting it is the look offset from
    // the orbit centre (0 = look at the centre).
    let yawBase = null;
    let draggingPitch = false;

    function setOrientation(heading, pitch) {
        const camera = peekViewer()?.camera;
        if (!camera) return;
        camera.setView({ destination: camera.position, orientation: { heading, pitch, roll: 0 } });
    }

    if (els.pitch) {
        els.pitch.addEventListener('pointerdown', () => { draggingPitch = true; });
        document.addEventListener('pointerup', () => { draggingPitch = false; });
        els.pitch.addEventListener('input', () => {
            const rad = Cesium.Math.toRadians(pitchDeg());
            els.pitchValue.textContent = fmtDeg(pitchDeg());
            if (vertical) vertical.pitch = rad;
            if (orbit) return; // the orbit loop reads the slider itself
            const camera = peekViewer()?.camera;
            if (camera) setOrientation(camera.heading, rad);
        });
    }

    if (els.yaw) {
        const begin = () => {
            const camera = peekViewer()?.camera;
            yawBase = camera ? camera.heading - Cesium.Math.toRadians(yawDeg()) : null;
        };
        els.yaw.addEventListener('pointerdown', begin);
        els.yaw.addEventListener('keydown', () => { if (yawBase === null) begin(); });
        document.addEventListener('pointerup', () => { yawBase = null; });
        els.yaw.addEventListener('input', () => {
            els.yawValue.textContent = fmtDeg(yawDeg());
            const camera = peekViewer()?.camera;
            if (!camera || orbit) return;
            if (yawBase === null) begin();
            const heading = Cesium.Math.zeroToTwoPi(yawBase + Cesium.Math.toRadians(yawDeg()));
            if (vertical) vertical.heading = heading;
            setOrientation(heading, camera.pitch);
        });
    }

    // Mirror the camera's pitch on the slider when something else moves the camera
    function watchCamera() {
        const viewer = peekViewer();
        if (!viewer?.scene) { setTimeout(watchCamera, 500); return; }
        viewer.scene.postRender.addEventListener(() => {
            if (!els.pitch || draggingPitch || orbit) return;
            const deg = Math.round(Cesium.Math.toDegrees(viewer.camera.pitch));
            if (deg <= 0 && deg >= -90 && deg !== Math.round(pitchDeg())) {
                els.pitch.value = deg;
                els.pitchValue.textContent = fmtDeg(deg);
            }
        });
    }
    watchCamera();

    // ========== ORBIT ==========
    // Circles a ground point at the current height. From the panel the centre is the
    // terrain under the middle of the screen and the radius defaults to the current
    // distance to it, so the orbit starts where the camera already is. The camera
    // looks at the centre (plus the yaw offset) with the slider's pitch.

    // Terrain point in the middle of the view, else the ellipsoid, else under the camera
    function viewCentre(viewer) {
        const scene = viewer.scene, camera = viewer.camera;
        const canvas = scene.canvas;
        const mid = new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2);
        let point = null;
        if (scene.mode === Cesium.SceneMode.SCENE3D) {
            const ray = camera.getPickRay(mid);
            if (ray) point = scene.globe.pick(ray, scene);
        }
        if (!point) point = camera.pickEllipsoid(mid, scene.globe.ellipsoid);
        if (!point) {
            const here = camera.positionCartographic;
            point = Cesium.Cartesian3.fromRadians(here.longitude, here.latitude, groundAt(viewer, here) || 0, scene.globe.ellipsoid);
        }
        return point;
    }

    // Horizontal distance and bearing of a position from the centre (local tangent plane)
    function polar(viewer, centreCarto, posCarto) {
        const R = viewer.scene.globe.ellipsoid.maximumRadius;
        const east = (posCarto.longitude - centreCarto.longitude) * Math.cos(centreCarto.latitude) * R;
        const north = (posCarto.latitude - centreCarto.latitude) * R;
        return { distance: Math.hypot(east, north), angle: Math.atan2(north, east) };
    }

    function showOrbitUi(active) {
        els.orbitBtn.classList.toggle('active', active);
        els.orbitBtn.innerHTML = active ? '<i class="fas fa-stop"></i> Stop' : '<i class="fas fa-circle-notch"></i> Orbit';
        els.stopOrbitContainer.style.display = active ? '' : 'none';
        if (els.pauseOrbitContainer) els.pauseOrbitContainer.style.display = active ? '' : 'none';
        if (els.progressContainer) els.progressContainer.style.display = active ? '' : 'none';
        if (els.pauseOrbitBtn) {
            els.pauseOrbitBtn.innerHTML = '<i class="fas fa-pause"></i> Pause';
            els.pauseOrbitBtn.classList.remove('active');
        }
    }

    function stopOrbit() {
        if (!orbit) return;
        cancelAnimationFrame(orbit.raf);
        orbit = null;
        showOrbitUi(false);
        if (els.radius?.dataset.auto === '1') { els.radius.value = ''; delete els.radius.dataset.auto; }
    }

    // opts: radius (m), speed (m/s), laps, clockwise, pitch (deg), yaw (deg)
    function startOrbit(centre, opts = {}) {
        const viewer = getViewer();
        if (!viewer?.camera) return;
        stopOrbit();
        const camera = viewer.camera;
        const ellipsoid = viewer.scene.globe.ellipsoid;
        const centreCarto = Cesium.Cartographic.fromCartesian(centre, ellipsoid);
        const here = camera.positionCartographic;
        const { distance, angle } = polar(viewer, centreCarto, here);

        let radius = Number.isFinite(opts.radius) ? opts.radius : num(els.radius, NaN);
        if (!Number.isFinite(radius) || radius <= 0) {
            radius = Math.max(5, distance);
            if (els.radius) { els.radius.value = Math.round(radius); els.radius.dataset.auto = '1'; }
        }
        const speed = Math.max(0.1, Number.isFinite(opts.speed) ? opts.speed : hSpeed());
        const laps = Math.max(0.05, Number.isFinite(opts.laps) ? opts.laps : num(els.laps, 1));
        const clockwise = opts.clockwise ?? !!els.clockwise?.checked;
        const alt = here.height;
        // Look at the centre unless a pitch was given: tilt down by the height over it
        const pitch = Number.isFinite(opts.pitch) ? opts.pitch
            : -Cesium.Math.toDegrees(Math.atan2(Math.max(0, alt - centreCarto.height), radius));
        if (els.pitch) { els.pitch.value = Math.round(pitch); els.pitchValue.textContent = fmtDeg(pitch); }
        if (els.yaw && Number.isFinite(opts.yaw)) { els.yaw.value = opts.yaw; els.yawValue.textContent = fmtDeg(opts.yaw); }

        orbit = {
            centreCarto, radius, speed, laps, dir: clockwise ? -1 : 1, alt,
            angle0: distance < 1 ? Math.PI / 2 : angle,
            t0: performance.now(), pausedMs: 0, pauseAt: null, lastProgress: 0, raf: 0,
        };
        showOrbitUi(true);

        const R = ellipsoid.maximumRadius;
        const step = () => {
            if (!orbit) return;
            orbit.raf = requestAnimationFrame(step);
            if (orbit.pauseAt !== null) return;
            const now = performance.now();
            const swept = orbit.speed / orbit.radius * (now - orbit.t0 - orbit.pausedMs) / 1000; // radians
            if (swept >= orbit.laps * 2 * Math.PI) { stopOrbit(); notify('Orbit complete', 'success'); return; }
            if (els.progressText && now - orbit.lastProgress > 200) {
                els.progressText.textContent = `Lap ${(swept / (2 * Math.PI)).toFixed(2)} / ${orbit.laps}`;
                orbit.lastProgress = now;
            }

            const a = orbit.angle0 + orbit.dir * swept;
            const lat = orbit.centreCarto.latitude + orbit.radius * Math.sin(a) / R;
            const lon = orbit.centreCarto.longitude + orbit.radius * Math.cos(a) / (R * Math.cos(orbit.centreCarto.latitude));
            if (vertical) orbit.alt = camera.positionCartographic.height; // takeoff / land alongside

            const toCentre = new Cesium.EllipsoidGeodesic(
                new Cesium.Cartographic(lon, lat), orbit.centreCarto, ellipsoid).startHeading;
            camera.setView({
                destination: Cesium.Cartesian3.fromRadians(lon, lat, orbit.alt, ellipsoid),
                orientation: {
                    heading: Cesium.Math.zeroToTwoPi(toCentre + Cesium.Math.toRadians(yawDeg())),
                    pitch: Cesium.Math.toRadians(pitchDeg()),
                    roll: 0,
                },
            });
        };
        step();
    }

    function togglePause() {
        if (!orbit || !els.pauseOrbitBtn) return;
        if (orbit.pauseAt === null) {
            orbit.pauseAt = performance.now();
            els.pauseOrbitBtn.innerHTML = '<i class="fas fa-play"></i> Resume';
            els.pauseOrbitBtn.classList.add('active');
        } else {
            orbit.pausedMs += performance.now() - orbit.pauseAt;
            orbit.pauseAt = null;
            els.pauseOrbitBtn.innerHTML = '<i class="fas fa-pause"></i> Pause';
            els.pauseOrbitBtn.classList.remove('active');
        }
    }

    const orbitView = (opts = {}) => {
        const viewer = getViewer();
        if (viewer?.camera) startOrbit(viewCentre(viewer), opts);
    };
    els.orbitBtn.addEventListener('click', () => (orbit ? stopOrbit() : orbitView()));
    els.stopOrbitBtn.addEventListener('click', stopOrbit);
    els.pauseOrbitBtn?.addEventListener('click', togglePause);
    els.radius?.addEventListener('input', () => { delete els.radius.dataset.auto; });

    // ========== FLY FORWARD ==========
    // Along the current heading at the current height, pitch and roll, at H speed.
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

    function flyForward(distance = num(els.flyDistance, 100), speedMps = hSpeed()) {
        const viewer = getViewer();
        if (!viewer?.camera) return;
        const camera = viewer.camera;
        const here = camera.positionCartographic;
        const { heading, pitch, roll } = camera;
        const speed = Math.max(0.1, speedMps);
        const headingDeg = Cesium.Math.toDegrees(heading).toFixed(0);
        els.flyBtn.classList.add('active');
        camera.flyTo({
            destination: destinationPoint(viewer.scene.globe.ellipsoid, here.longitude, here.latitude,
                                          here.height, heading, distance),
            duration: Math.max(0.5, distance / speed),
            orientation: { heading, pitch, roll },
            easingFunction: Cesium.EasingFunction.LINEAR_NONE,
            complete: () => {
                els.flyBtn.classList.remove('active');
                notify(`Flew ${distance} m on heading ${headingDeg}°`, 'success');
            },
            cancel: () => els.flyBtn.classList.remove('active'),
        });
        notify(`Flying ${distance} m forward at ${speed} m/s, heading ${headingDeg}°`, 'info');
    }
    els.flyBtn.addEventListener('click', () => flyForward());

    // ========== KEYS AND API ==========
    document.addEventListener('keydown', (e) => {
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
        if (e.key === 'Escape') { stopOrbit(); stopVertical(); }
        else if (e.key === ' ' && orbit) { e.preventDefault(); togglePause(); }
    });

    // Programmatic control (AI pilot, share links). Heights are ellipsoid heights.
    window.DeepGISDrone = Object.assign(window.DeepGISDrone || {}, {
        climbTo(height, speed) { startVertical(1, height, speed); },
        descendTo(height, speed) { startVertical(-1, height, speed); },
        stopVertical,
        isVerticalActive: () => !!vertical,
        orbitAround: startOrbit,
        orbitView,
        stopOrbit,
        isOrbiting: () => !!orbit,
        flyForward,
    });

    console.log('[Drone] Flight panel ready');
})();
