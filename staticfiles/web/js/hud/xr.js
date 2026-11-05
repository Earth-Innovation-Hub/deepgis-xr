// HUD VR panel (web/hud/vr_panel.html): immersive WebXR on headsets such as the Meta Quest.
// Cesium 1.111 has no WebXR support, so each XR frame draws the scene once per eye, with
// the camera at that eye's pose, and copies the picture into the eye's part of the XR
// framebuffer:
// - An eye's frustum is asymmetric, and Cesium's multi-frustum rendering keeps only a
//   symmetric PerspectiveFrustum correct, so the scene is drawn with a symmetric frustum
//   wide enough for every eye and the eye's part is cropped out with blitFramebuffer.
// - A multisampled canvas (desktop browsers) is resolved into a single-sample renderbuffer
//   first, since a multisampled blit can neither crop nor scale. Headset browsers get a
//   single-sample, XR-compatible canvas from the start (DeepGISXRContext below).
// - The head pose maps from the XR 'local' space (x right, y up, -z forward) into the
//   east-north-up frame at the rig origin, turned to the rig heading.
// Thumbsticks move the rig: the left one flies along and across where you look, the right
// one snap-turns (left, right) and climbs or descends (up, down), faster when higher above
// the ground.

// WebGL options for Cesium viewers; read by core/cesium-init.js and the planet viewer
window.DeepGISXRContext = /OculusBrowser|PicoBrowser|Wolvic/.test(navigator.userAgent)
    ? { xrCompatible: true, antialias: false } : {};

(function initXR() {
    const statusEl = document.getElementById('vrStatus');
    const checkBtn = document.getElementById('checkVRSupport');
    const enterBtn = document.getElementById('enterVR');
    const exitBtn = document.getElementById('exitVR');
    const scaleSel = document.getElementById('vrResolution');
    if (!statusEl || !enterBtn || !exitBtn) return;

    const DEADZONE = 0.15;
    const SNAP_TURN = Cesium.Math.toRadians(30);
    const MIN_CLEARANCE_M = 2;
    const VR_SSE = 4;

    let supported = false;
    let xr = null;

    function status(text, color = '#94a3b8') {
        statusEl.textContent = `VR Status: ${text}`;
        statusEl.style.color = color;
    }

    async function check() {
        if (!navigator.xr) {
            status(window.isSecureContext ? 'this browser has no WebXR; open the page in the headset browser'
                : 'WebXR needs HTTPS', '#ef4444');
            return false;
        }
        supported = await navigator.xr.isSessionSupported('immersive-vr').catch(() => false);
        if (!xr) enterBtn.disabled = !supported;
        if (!xr) {
            status(supported ? 'immersive VR available' : 'no immersive VR device; open the page in the headset browser',
                supported ? '#10b981' : '#f59e0b');
        }
        return supported;
    }

    // XR vector (x right, y up, z back) -> ECEF, through the rig's heading and ENU frame
    function toWorld(enu, heading, x, y, z, result) {
        const s = Math.sin(heading), c = Math.cos(heading);
        const e = x * c - z * s, n = -x * s - z * c;
        return Cesium.Matrix3.multiplyByVector(enu, new Cesium.Cartesian3(e, n, y), result || new Cesium.Cartesian3());
    }

    function enuRotation(origin, ellipsoid) {
        return Cesium.Matrix4.getMatrix3(Cesium.Transforms.eastNorthUpToFixedFrame(origin, ellipsoid), new Cesium.Matrix3());
    }

    function placeCamera(camera, enu, rig, m) {
        const offset = toWorld(enu, rig.heading, m[12], m[13], m[14]);
        camera.position = Cesium.Cartesian3.add(rig.origin, offset, new Cesium.Cartesian3());
        camera.direction = Cesium.Cartesian3.normalize(toWorld(enu, rig.heading, -m[8], -m[9], -m[10]), new Cesium.Cartesian3());
        camera.up = Cesium.Cartesian3.normalize(toWorld(enu, rig.heading, m[4], m[5], m[6]), new Cesium.Cartesian3());
        camera.right = Cesium.Cartesian3.normalize(
            Cesium.Cartesian3.cross(camera.direction, camera.up, new Cesium.Cartesian3()), new Cesium.Cartesian3());
    }

    function resolveTarget(gl, cache, width, height) {
        if (cache.fb && cache.width === width && cache.height === height) return cache.fb;
        if (cache.fb) {
            gl.deleteFramebuffer(cache.fb);
            gl.deleteRenderbuffer(cache.rb);
        }
        cache.rb = gl.createRenderbuffer();
        gl.bindRenderbuffer(gl.RENDERBUFFER, cache.rb);
        // A multisample resolve needs the default framebuffer's own format
        gl.renderbufferStorage(gl.RENDERBUFFER, gl.getContextAttributes().alpha ? gl.RGBA8 : gl.RGB8, width, height);
        gl.bindRenderbuffer(gl.RENDERBUFFER, null);
        cache.fb = gl.createFramebuffer();
        gl.bindFramebuffer(gl.FRAMEBUFFER, cache.fb);
        gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.RENDERBUFFER, cache.rb);
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        Object.assign(cache, { width, height });
        return cache.fb;
    }

    function freeResolve(gl, cache) {
        if (!cache.fb) return;
        gl.deleteFramebuffer(cache.fb);
        gl.deleteRenderbuffer(cache.rb);
        cache.fb = cache.rb = null;
    }

    // Draws every view of pose into layer ({framebuffer, getViewport(view)}) from rig
    // ({origin, heading}); cache keeps the resolve buffer between frames.
    function drawEyes(viewer, pose, layer, rig, cache) {
        const scene = viewer.scene, camera = viewer.camera, canvas = scene.canvas;
        const gl = scene.context._gl;
        const eyes = [...pose.views].map((view) => {
            const p = view.projectionMatrix;
            return {
                view, vp: layer.getViewport(view),
                l: (p[8] - 1) / p[0], r: (p[8] + 1) / p[0], b: (p[9] - 1) / p[5], t: (p[9] + 1) / p[5],
            };
        }).filter(e => e.vp && e.vp.width && e.vp.height);
        if (!eyes.length) return;
        // Half-widths of the symmetric frustum (tangent units) and the pixels it needs
        const hx = Math.max(...eyes.flatMap(e => [-e.l, e.r]));
        const hy = Math.max(...eyes.flatMap(e => [-e.b, e.t]));
        const kx = Math.max(...eyes.map(e => e.vp.width / (e.r - e.l)));
        const ky = Math.max(...eyes.map(e => e.vp.height / (e.t - e.b)));
        const width = Math.ceil(2 * hx * kx), height = Math.ceil(2 * hy * ky);
        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width;
            canvas.height = height;
        }
        if (!(camera.frustum instanceof Cesium.PerspectiveFrustum)) camera.frustum = new Cesium.PerspectiveFrustum();
        camera.frustum.aspectRatio = hx / hy;
        camera.frustum.fov = 2 * Math.atan(hx > hy ? hx : hy);

        scene.initializeFrame();
        const time = viewer.clock.tick();
        const enu = enuRotation(rig.origin, scene.globe.ellipsoid);
        const dw = gl.drawingBufferWidth, dh = gl.drawingBufferHeight;
        const multisampled = gl.getContextAttributes().antialias;
        for (const e of eyes) {
            placeCamera(camera, enu, rig, e.view.transform.matrix);
            scene.render(time);
            const scissor = gl.isEnabled(gl.SCISSOR_TEST);
            if (scissor) gl.disable(gl.SCISSOR_TEST);
            let source = null;
            if (multisampled) {
                source = resolveTarget(gl, cache, dw, dh);
                gl.bindFramebuffer(gl.READ_FRAMEBUFFER, null);
                gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, source);
                gl.blitFramebuffer(0, 0, dw, dh, 0, 0, dw, dh, gl.COLOR_BUFFER_BIT, gl.NEAREST);
            }
            gl.bindFramebuffer(gl.READ_FRAMEBUFFER, source);
            gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, layer.framebuffer);
            const sx = (v) => Math.round((v + hx) / (2 * hx) * dw);
            const sy = (v) => Math.round((v + hy) / (2 * hy) * dh);
            gl.blitFramebuffer(sx(e.l), sy(e.b), sx(e.r), sy(e.t),
                e.vp.x, e.vp.y, e.vp.x + e.vp.width, e.vp.y + e.vp.height, gl.COLOR_BUFFER_BIT, gl.LINEAR);
            gl.bindFramebuffer(gl.FRAMEBUFFER, null);
            if (scissor) gl.enable(gl.SCISSOR_TEST);
        }
    }

    const dead = (v) => (Math.abs(v) < DEADZONE ? 0 : v);

    function move(viewer, session, pose, rig, dt) {
        let lx = 0, ly = 0, rx = 0, ry = 0;
        for (const src of session.inputSources) {
            const a = src.gamepad?.axes;
            if (!a || a.length < 4) continue;
            if (src.handedness === 'left') [lx, ly] = [dead(a[2]), dead(a[3])];
            else if (src.handedness === 'right') [rx, ry] = [dead(a[2]), dead(a[3])];
        }
        if (Math.abs(rx) < 0.3) rig.turnLatched = false;
        else if (Math.abs(rx) > 0.7 && !rig.turnLatched) {
            rig.turnLatched = true;
            rig.heading += Math.sign(rx) * SNAP_TURN;
        }
        if (!lx && !ly && !ry) return;
        const globe = viewer.scene.globe;
        const carto = Cesium.Cartographic.fromCartesian(rig.origin, globe.ellipsoid);
        const ground = globe.getHeight(carto) ?? 0;
        const speed = Cesium.Math.clamp((carto.height - ground) * 0.5, 5, 200000);
        // Along and across the gaze, kept level
        const m = pose.transform.matrix;
        let fx = -m[8], fz = -m[10];
        const len = Math.hypot(fx, fz) || 1;
        fx /= len;
        fz /= len;
        const step = speed * dt;
        const x = (fx * -ly + -fz * lx) * step, z = (fz * -ly + fx * lx) * step, y = -ry * step;
        const enu = enuRotation(rig.origin, globe.ellipsoid);
        const moved = Cesium.Cartesian3.add(rig.origin, toWorld(enu, rig.heading, x, y, z), new Cesium.Cartesian3());
        const c = Cesium.Cartographic.fromCartesian(moved, globe.ellipsoid);
        const floor = (globe.getHeight(c) ?? 0) + MIN_CLEARANCE_M;
        if (c.height < floor) c.height = floor;
        rig.origin = Cesium.Cartographic.toCartesian(c, globe.ellipsoid);
    }

    function onFrame(time, frame) {
        if (!xr) return;
        xr.session.requestAnimationFrame(onFrame);
        const pose = frame.getViewerPose(xr.space);
        if (!pose) return;
        const dt = xr.last == null ? 0 : Math.min(0.1, (time - xr.last) / 1000);
        xr.last = time;
        try {
            if (dt) move(xr.viewer, xr.session, pose, xr.rig, dt);
            drawEyes(xr.viewer, pose, xr.session.renderState.baseLayer, xr.rig, xr.cache);
        } catch (e) {
            console.error('XR frame failed', e);
        }
    }

    async function start(session, viewer) {
        const scene = viewer.scene, camera = viewer.camera, canvas = scene.canvas;
        const gl = scene.context._gl;
        window.DeepGISActions?.stop();
        camera.cancelFlight();
        if (scene.mode !== Cesium.SceneMode.SCENE3D) scene.morphTo3D(0);
        camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
        xr = {
            session, viewer, cache: {}, last: null,
            rig: { origin: Cesium.Cartesian3.clone(camera.positionWC), heading: camera.heading, turnLatched: false },
            saved: {
                frustum: camera.frustum.clone(), loop: viewer.useDefaultRenderLoop,
                requestRenderMode: scene.requestRenderMode, inputs: scene.screenSpaceCameraController.enableInputs,
                sse: scene.globe.maximumScreenSpaceError, fxaa: scene.postProcessStages.fxaa.enabled,
                width: canvas.width, height: canvas.height,
            },
        };
        session.addEventListener('end', onEnd);
        viewer.useDefaultRenderLoop = false;
        scene.requestRenderMode = false;
        scene.screenSpaceCameraController.enableInputs = false;
        scene.globe.maximumScreenSpaceError = Math.max(VR_SSE, xr.saved.sse);
        if (!gl.getContextAttributes().antialias) scene.postProcessStages.fxaa.enabled = true;
        if (!(gl instanceof WebGL2RenderingContext)) throw new Error('VR needs WebGL 2');
        await gl.makeXRCompatible();
        const layer = new XRWebGLLayer(session, gl, {
            antialias: false, depth: false, framebufferScaleFactor: parseFloat(scaleSel?.value) || 0.7,
        });
        await session.updateRenderState({ baseLayer: layer });
        xr.space = await session.requestReferenceSpace('local');
        session.requestAnimationFrame(onFrame);
        enterBtn.disabled = true;
        exitBtn.disabled = false;
        status('in VR: left stick flies, right stick turns and climbs', '#10b981');
    }

    function onEnd() {
        const s = xr;
        xr = null;
        if (!s) return;
        const { viewer, saved, rig } = s;
        const scene = viewer.scene, camera = viewer.camera, canvas = scene.canvas;
        freeResolve(scene.context._gl, s.cache);
        canvas.width = saved.width;
        canvas.height = saved.height;
        camera.frustum = saved.frustum;
        // Stay where the flight ended, looking the way the rig faced
        camera.setView({ destination: rig.origin, orientation: { heading: rig.heading, pitch: Cesium.Math.toRadians(-25), roll: 0 } });
        scene.globe.maximumScreenSpaceError = saved.sse;
        scene.postProcessStages.fxaa.enabled = saved.fxaa;
        scene.screenSpaceCameraController.enableInputs = saved.inputs;
        scene.requestRenderMode = saved.requestRenderMode;
        viewer.useDefaultRenderLoop = saved.loop;
        viewer.cesiumWidget._forceResize = true;
        viewer.resize();
        scene.requestRender();
        enterBtn.disabled = !supported;
        exitBtn.disabled = true;
        status('session ended');
    }

    async function enter() {
        if (xr) return;
        const viewer = window.viewer;
        if (!viewer) {
            status('the globe is still loading', '#f59e0b');
            return;
        }
        let session;
        try {
            // First, while the click still counts as a user gesture
            session = await navigator.xr.requestSession('immersive-vr');
        } catch (e) {
            status(`could not start VR: ${e.message}`, '#ef4444');
            return;
        }
        try {
            await start(session, viewer);
        } catch (e) {
            console.error('VR setup failed', e);
            status(`VR failed: ${e.message}`, '#ef4444');
            session.end().catch(() => {});
        }
    }

    checkBtn?.addEventListener('click', check);
    enterBtn.addEventListener('click', enter);
    exitBtn.addEventListener('click', () => xr?.session.end());
    check();

    window.DeepGISXR = { check, enter, exit: () => xr?.session.end(), drawEyes, active: () => !!xr };
})();
