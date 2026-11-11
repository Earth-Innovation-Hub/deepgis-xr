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
            if (orbit) { // the orbit takes the slider's tilt from now on
                orbit.aim = false;
                orbit.pitch = orbit.pitchTarget = pitchDeg();
                return;
            }
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

    const ORBIT_EASE_SEC = 1.5; // time constant for retuned radius, height, tilt and speed

    function showPitch(deg) {
        if (!els.pitch || draggingPitch || Math.round(deg) === Math.round(pitchDeg())) return;
        els.pitch.value = Math.round(deg);
        els.pitchValue.textContent = fmtDeg(deg);
    }

    // opts: radius (m), speed (m/s), laps (Infinity = until stopped), clockwise, pitch (deg;
    // omit to keep aiming at the centre as the height and radius change), yaw (deg)
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
        const laps = opts.laps === Infinity ? Infinity
            : Math.max(0.05, Number.isFinite(opts.laps) ? opts.laps : num(els.laps, 1));
        const clockwise = opts.clockwise ?? !!els.clockwise?.checked;
        const alt = here.height;
        const aim = !Number.isFinite(opts.pitch);
        const pitch = aim ? aimPitch(alt, centreCarto.height, radius) : opts.pitch;
        if (els.pitch) { els.pitch.value = Math.round(pitch); els.pitchValue.textContent = fmtDeg(pitch); }
        if (els.yaw && Number.isFinite(opts.yaw)) { els.yaw.value = opts.yaw; els.yawValue.textContent = fmtDeg(opts.yaw); }

        // radius, alt, pitch and speed ease toward their *Target (retuneOrbit); swept is the
        // angle flown so far, so a change of radius or speed carries on from where the camera is
        orbit = {
            centreCarto, radius, speed, laps, dir: clockwise ? -1 : 1, alt, pitch, aim,
            radiusTarget: radius, altTarget: alt, pitchTarget: pitch, speedTarget: speed,
            angle0: distance < 1 ? Math.PI / 2 : angle, swept: 0,
            last: performance.now(), pauseAt: null, lastProgress: 0, raf: 0,
        };
        showOrbitUi(true);

        const R = ellipsoid.maximumRadius;
        const step = () => {
            if (!orbit) return;
            orbit.raf = requestAnimationFrame(step);
            const now = performance.now();
            const dt = Math.min(0.1, (now - orbit.last) / 1000);
            orbit.last = now;
            if (orbit.pauseAt !== null) return;
            const k = 1 - Math.exp(-dt / ORBIT_EASE_SEC);
            orbit.radius += (orbit.radiusTarget - orbit.radius) * k;
            orbit.speed += (orbit.speedTarget - orbit.speed) * k;
            if (vertical) orbit.alt = orbit.altTarget = camera.positionCartographic.height; // takeoff / land alongside
            else orbit.alt += (orbit.altTarget - orbit.alt) * k;
            if (orbit.aim) orbit.pitchTarget = aimPitch(orbit.alt, orbit.centreCarto.height, orbit.radius);
            orbit.pitch += (orbit.pitchTarget - orbit.pitch) * k;
            showPitch(orbit.pitch);

            orbit.swept += orbit.speed / orbit.radius * dt;
            if (orbit.swept >= orbit.laps * 2 * Math.PI) { stopOrbit(); notify('Orbit complete', 'success'); return; }
            if (els.progressText && now - orbit.lastProgress > 200) {
                const lap = (orbit.swept / (2 * Math.PI)).toFixed(2);
                els.progressText.textContent = orbit.laps === Infinity ? `Lap ${lap} (until stopped)` : `Lap ${lap} / ${+orbit.laps.toFixed(2)}`;
                orbit.lastProgress = now;
            }

            const a = orbit.angle0 + orbit.dir * orbit.swept;
            const lat = orbit.centreCarto.latitude + orbit.radius * Math.sin(a) / R;
            const lon = orbit.centreCarto.longitude + orbit.radius * Math.cos(a) / (R * Math.cos(orbit.centreCarto.latitude));

            const toCentre = new Cesium.EllipsoidGeodesic(
                new Cesium.Cartographic(lon, lat), orbit.centreCarto, ellipsoid).startHeading;
            camera.setView({
                destination: Cesium.Cartesian3.fromRadians(lon, lat, orbit.alt, ellipsoid),
                orientation: {
                    heading: Cesium.Math.zeroToTwoPi(toCentre + Cesium.Math.toRadians(yawDeg())),
                    pitch: Cesium.Math.toRadians(orbit.pitch),
                    roll: 0,
                },
            });
        };
        step();
    }

    // Tilt that looks at the centre: down by the height over it
    function aimPitch(alt, centreHeight, radius) {
        return -Cesium.Math.toDegrees(Math.atan2(Math.max(0, alt - centreHeight), radius));
    }

    // Changes the running orbit without restarting it. opts: radius (m), alt (ellipsoid
    // height, m), pitch (deg; aim: true to look at the centre again), speed (m/s), laps
    // (more laps from here; Infinity = until stopped). false when nothing is orbiting.
    function retuneOrbit(opts = {}) {
        if (!orbit) return false;
        if (Number.isFinite(opts.radius) && opts.radius > 0) orbit.radiusTarget = Math.max(5, opts.radius);
        if (Number.isFinite(opts.alt)) orbit.altTarget = Math.max(orbit.centreCarto.height + 2, opts.alt);
        if (Number.isFinite(opts.speed) && opts.speed > 0) orbit.speedTarget = opts.speed;
        if (Number.isFinite(opts.pitch)) {
            orbit.aim = false;
            orbit.pitchTarget = Math.max(-90, Math.min(0, opts.pitch));
        } else if (opts.aim) {
            orbit.aim = true;
        }
        if (opts.laps === Infinity) orbit.laps = Infinity;
        else if (Number.isFinite(opts.laps) && opts.laps > 0) orbit.laps = orbit.swept / (2 * Math.PI) + opts.laps;
        return true;
    }

    // Where the orbit is and is heading; null when not orbiting. Heights are ellipsoid heights.
    function orbitInfo() {
        if (!orbit) return null;
        const o = orbit;
        const settled = Math.abs(o.radius - o.radiusTarget) < Math.max(1, o.radiusTarget * 0.02)
            && Math.abs(o.alt - o.altTarget) < Math.max(1, Math.abs(o.altTarget - o.centreCarto.height) * 0.02)
            && Math.abs(o.pitch - o.pitchTarget) < 0.5 && Math.abs(o.speed - o.speedTarget) < Math.max(0.5, o.speedTarget * 0.02);
        return {
            centre: o.centreCarto, radius: o.radiusTarget, alt: o.altTarget, pitch: o.pitchTarget,
            speed: o.speedTarget, aim: o.aim, continuous: o.laps === Infinity,
            lapsLeft: o.laps === Infinity ? Infinity : Math.max(0, o.laps - o.swept / (2 * Math.PI)),
            settled,
        };
    }

    function togglePause() {
        if (!orbit || !els.pauseOrbitBtn) return;
        if (orbit.pauseAt === null) {
            orbit.pauseAt = performance.now();
            els.pauseOrbitBtn.innerHTML = '<i class="fas fa-play"></i> Resume';
            els.pauseOrbitBtn.classList.add('active');
        } else {
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
        retuneOrbit,
        orbitInfo,
        isOrbiting: () => !!orbit,
        flyForward,
    });

    console.log('[Drone] Flight panel ready');
})();
