// HUD VR panel (web/hud/vr_panel.html): immersive WebXR on headsets such as the Meta Quest.
// Cesium 1.111 has no WebXR support, so each XR frame draws the scene once per eye, with
// the camera at that eye's pose, and copies the picture into the eye's part of the
// headset's projection layer (or XRWebGLLayer where WebXR Layers are missing):
// - An eye's frustum is asymmetric, and Cesium's multi-frustum rendering keeps only a
//   symmetric PerspectiveFrustum correct, so the scene is drawn with a symmetric frustum
//   wide enough for every eye and the eye's part is cropped out with blitFramebuffer.
// - A multisampled canvas (desktop browsers) is resolved into a single-sample renderbuffer
//   first, since a multisampled blit can neither crop nor scale. Headset browsers get a
//   single-sample, XR-compatible canvas from the start (DeepGISXRContext below).
// - The head pose maps from the XR 'local' space (x right, y up, -z forward) into the
//   east-north-up frame at the rig origin, turned to the rig heading.
// - Flights, orbits and climbs (hud/actions.js, hud/drone.js) still move the camera: each
//   frame starts from the rig's level pose, runs the page's animation frames and Cesium's
//   tweens, and a camera they moved carries the rig along.
// Controls: the left stick flies along and across where you look (left grip boosts); the
// right stick snap-turns and climbs or descends. The right controller's laser clicks the
// cockpit (hud/xr-cockpit.js) or, on the ground, flies there with the trigger (grip and
// trigger orbits). B stops, X shows the cockpit in front of you or hides it, Y the layers
// wing, A the AI pilot comms; the wrist menu on the left controller does all three and
// re-centres them. Comms' TYPE focuses a hidden text field, which brings up the headset's
// system keyboard (and its dictation mic); Enter or SEND asks the pilot (hud/pilot.js).
// The Robots panel flies to a robot or rides on it (follow_vehicle, stepped from advance);
// taking the sticks lets go. A comfort vignette darkens the edges of view while the ground
// streams past, and short WebAudio tones mark hovers, presses and the pilot's replies
// (both can be switched off in the VR panel).

// WebGL options for Cesium viewers; read by core/cesium-init.js and the planet viewer
window.DeepGISXRContext = /OculusBrowser|PicoBrowser|Wolvic/.test(navigator.userAgent)
    ? { xrCompatible: true, antialias: false } : {};

(function initXR() {
    const statusEl = document.getElementById('vrStatus');
    const checkBtn = document.getElementById('checkVRSupport');
    const enterBtn = document.getElementById('enterVR');
    const exitBtn = document.getElementById('exitVR');
    const scaleSel = document.getElementById('vrResolution');
    const comfortBox = document.getElementById('vrComfort');
    const soundBox = document.getElementById('vrSounds');
    if (!statusEl || !enterBtn || !exitBtn) return;

    const DEADZONE = 0.15;
    const SNAP_TURN = Cesium.Math.toRadians(30);
    const MIN_CLEARANCE_M = 2;
    const VR_SSE = 4;
    const VR_NEAR_M = 0.05;
    const BOOST = 5;
    const LASER_REACH_M = 20;
    // xr-standard gamepad buttons
    const TRIGGER = 0, GRIP = 1, PRIMARY = 4, SECONDARY = 5;

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
        if (!xr) {
            enterBtn.disabled = !supported;
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

    const worldPoint = (enu, rig, x, y, z) => Cesium.Cartesian3.add(rig.origin, toWorld(enu, rig.heading, x, y, z), new Cesium.Cartesian3());

    function placeCamera(camera, enu, rig, m) {
        camera.position = worldPoint(enu, rig, m[12], m[13], m[14]);
        camera.direction = Cesium.Cartesian3.normalize(toWorld(enu, rig.heading, -m[8], -m[9], -m[10]), new Cesium.Cartesian3());
        camera.up = Cesium.Cartesian3.normalize(toWorld(enu, rig.heading, m[4], m[5], m[6]), new Cesium.Cartesian3());
        camera.right = Cesium.Cartesian3.normalize(
            Cesium.Cartesian3.cross(camera.direction, camera.up, new Cesium.Cartesian3()), new Cesium.Cartesian3());
    }

    // Head yaw in the XR space (radians, counter-clockwise from -z)
    const yawOf = (m) => Math.atan2(m[8], m[10]);

    function resolveTarget(gl, cache, width, height) {
        if (cache.fb && cache.width === width && cache.height === height) return cache.fb;
        freeResolve(gl, cache);
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
        if (cache.fb) {
            gl.deleteFramebuffer(cache.fb);
            gl.deleteRenderbuffer(cache.rb);
        }
        if (cache.drawFb) gl.deleteFramebuffer(cache.drawFb);
        cache.fb = cache.rb = cache.drawFb = null;
    }

    // Where each eye's picture goes: {viewport(view), bind(view)} for an XRWebGLLayer or,
    // through an XRWebGLBinding, a projection layer's per-view textures
    function layerTarget(gl, layer) {
        return {
            viewport: (view) => layer.getViewport(view),
            bind: () => gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, layer.framebuffer),
        };
    }

    function projectionTarget(gl, binding, layer, cache) {
        const subs = new Map();
        const sub = (view) => {
            if (!subs.has(view)) subs.set(view, binding.getViewSubImage(layer, view));
            return subs.get(view);
        };
        return {
            viewport: (view) => sub(view).viewport,
            bind(view) {
                cache.drawFb = cache.drawFb || gl.createFramebuffer();
                gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, cache.drawFb);
                gl.framebufferTexture2D(gl.DRAW_FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, sub(view).colorTexture, 0);
            },
        };
    }

    // Draws every view of pose into target from rig ({origin, heading}) at Cesium time;
    // cache keeps the resolve buffer between frames.
    function drawEyes(viewer, pose, target, rig, cache, time) {
        const scene = viewer.scene, camera = viewer.camera, canvas = scene.canvas;
        const gl = scene.context._gl;
        const eyes = [...pose.views].map((view) => {
            const p = view.projectionMatrix;
            return {
                view, vp: target.viewport(view),
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
        camera.frustum.near = VR_NEAR_M;

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
            target.bind(e.view);
            const sx = (v) => Math.round((v + hx) / (2 * hx) * dw);
            const sy = (v) => Math.round((v + hy) / (2 * hy) * dh);
            gl.blitFramebuffer(sx(e.l), sy(e.b), sx(e.r), sy(e.t),
                e.vp.x, e.vp.y, e.vp.x + e.vp.width, e.vp.y + e.vp.height, gl.COLOR_BUFFER_BIT, gl.LINEAR);
            gl.bindFramebuffer(gl.FRAMEBUFFER, null);
            if (scissor) gl.enable(gl.SCISSOR_TEST);
        }
    }

    // The page's requestAnimationFrame callbacks (drone climbs and orbits) run from XR
    // frames during a session; the window's own frames may stop while the headset shows.
    const frames = { queue: null, next: 1, request: null, cancel: null };

    function captureAnimationFrames() {
        frames.request = window.requestAnimationFrame;
        frames.cancel = window.cancelAnimationFrame;
        frames.queue = new Map();
        window.requestAnimationFrame = (cb) => {
            const id = frames.next++;
            frames.queue.set(id, cb);
            return id;
        };
        window.cancelAnimationFrame = (id) => { frames.queue?.delete(id); };
    }

    function flushAnimationFrames(now) {
        const due = [...frames.queue.values()];
        frames.queue.clear();
        due.forEach((cb) => {
            try {
                cb(now);
            } catch (e) {
                console.error('Animation frame failed', e);
            }
        });
    }

    function releaseAnimationFrames() {
        if (!frames.queue) return;
        window.requestAnimationFrame = frames.request;
        window.cancelAnimationFrame = frames.cancel;
        const due = [...frames.queue.values()];
        frames.queue = null;
        due.forEach(cb => frames.request.call(window, cb));
    }

    // Level rig pose -> animation frames, tweens and a vehicle follow -> a camera they moved
    // carries the rig
    function advance(viewer, rig, now) {
        const camera = viewer.camera;
        camera.setView({ destination: rig.origin, orientation: { heading: rig.heading, pitch: 0, roll: 0 } });
        const base = Cesium.Cartesian3.clone(camera.positionWC);
        const heading = camera.heading;
        flushAnimationFrames(now);
        viewer.scene.initializeFrame();
        window.DeepGISActions?.followStep?.();
        const time = viewer.clock.tick();
        rig.auto = Cesium.Cartesian3.distance(camera.positionWC, base) > 1e-3 ||
            Math.abs(Cesium.Math.negativePiToPi(camera.heading - heading)) > 1e-5;
        if (rig.auto) {
            rig.origin = Cesium.Cartesian3.clone(camera.positionWC);
            rig.heading = camera.heading;
        }
        return time;
    }

    const dead = (v) => (Math.abs(v) < DEADZONE ? 0 : v);

    function readInput(session, frame, space, held) {
        const input = { lx: 0, ly: 0, rx: 0, ry: 0, held: new Set(), pressed: new Set(), ray: null };
        const rays = {};
        for (const src of session.inputSources) {
            const hand = src.handedness, gp = src.gamepad;
            if (gp) {
                const a = gp.axes;
                if (a.length >= 4) {
                    if (hand === 'left') [input.lx, input.ly] = [dead(a[2]), dead(a[3])];
                    else if (hand === 'right') [input.rx, input.ry] = [dead(a[2]), dead(a[3])];
                }
                gp.buttons.forEach((b, i) => {
                    if (!b.pressed) return;
                    const key = `${hand}${i}`;
                    input.held.add(key);
                    if (!held.has(key)) input.pressed.add(key);
                });
            }
            const p = src.targetRaySpace && frame.getPose(src.targetRaySpace, space);
            if (p) rays[hand] = { matrix: p.transform.matrix, source: src, hand };
        }
        input.ray = rays.right || rays.left || null;
        return input;
    }

    function buzz(source, strength = 0.4, ms = 25) {
        source?.gamepad?.hapticActuators?.[0]?.pulse?.(strength, ms);
    }

    function groundBelow(globe, point) {
        const c = Cesium.Cartographic.fromCartesian(point, globe.ellipsoid);
        return { carto: c, ground: globe.getHeight(c) ?? 0 };
    }

    function move(viewer, pose, rig, input, dt) {
        if (Math.abs(input.rx) < 0.3) rig.turnLatched = false;
        else if (Math.abs(input.rx) > 0.7 && !rig.turnLatched) {
            rig.turnLatched = true;
            rig.heading += Math.sign(input.rx) * SNAP_TURN;
        }
        const { lx, ly, ry } = input;
        if (!lx && !ly && !ry) return false;
        const globe = viewer.scene.globe;
        const { carto, ground } = groundBelow(globe, rig.origin);
        const boost = input.held.has(`left${GRIP}`) ? BOOST : 1;
        const speed = Cesium.Math.clamp((carto.height - ground) * 0.5, 5, 200000) * boost;
        // Along and across the gaze, kept level
        const m = pose.transform.matrix;
        let fx = -m[8], fz = -m[10];
        const len = Math.hypot(fx, fz) || 1;
        fx /= len;
        fz /= len;
        const step = speed * dt;
        const x = (fx * -ly + -fz * lx) * step, z = (fz * -ly + fx * lx) * step, y = -ry * step;
        const moved = worldPoint(enuRotation(rig.origin, globe.ellipsoid), rig, x, y, z);
        const c = Cesium.Cartographic.fromCartesian(moved, globe.ellipsoid);
        const floor = (globe.getHeight(c) ?? 0) + MIN_CLEARANCE_M;
        if (c.height < floor) c.height = floor;
        rig.origin = Cesium.Cartographic.toCartesian(c, globe.ellipsoid);
        return true;
    }

    // The laser: what it points at on the cockpit or the ground, drawn by Cesium in both eyes
    function aim(s, input) {
        const { viewer, rig, laser, marker } = s;
        const scene = viewer.scene;
        const result = { panel: null, ground: null, source: input.ray?.source };
        if (!input.ray) {
            laser.show = marker.show = false;
            return result;
        }
        const m = input.ray.matrix;
        const o = [m[12], m[13], m[14]], d = [-m[8], -m[9], -m[10]];
        const enu = enuRotation(rig.origin, scene.globe.ellipsoid);
        result.panel = s.cockpit?.pick(o, d, input.ray.hand) || null;
        const start = worldPoint(enu, rig, o[0] + d[0] * 0.05, o[1] + d[1] * 0.05, o[2] + d[2] * 0.05);
        const dir = Cesium.Cartesian3.normalize(toWorld(enu, rig.heading, d[0], d[1], d[2]), new Cesium.Cartesian3());
        let end;
        if (result.panel) {
            end = worldPoint(enu, rig, o[0] + d[0] * result.panel.dist, o[1] + d[1] * result.panel.dist, o[2] + d[2] * result.panel.dist);
        } else {
            result.ground = scene.globe.pick(new Cesium.Ray(start, dir), scene) || null;
            end = result.ground || Cesium.Cartesian3.add(start, Cesium.Cartesian3.multiplyByScalar(dir, LASER_REACH_M, new Cesium.Cartesian3()), new Cesium.Cartesian3());
        }
        laser.show = true;
        laser.positions = [start, end];
        marker.show = !!result.ground;
        if (result.ground) marker.position = result.ground;
        return result;
    }

    // The cockpit's status line shows the latest message, so the closing "Done" is dropped.
    // msg returns a line the runners may remove() once its step is over.
    function sinkFor(s) {
        const line = { remove() {} };
        return {
            msg: (kind, text) => {
                if (kind !== 'step' || text !== 'Done') s.cockpit?.status(text, kind);
                return line;
            },
            legend: (spec) => s.cockpit?.status(spec.title, 'step'),
            described: () => {},
        };
    }

    // A layers wing row: show the layer around the point in view, or hide it
    function toggleLayer(s, kind, title) {
        const hud = window.DeepGISActions, ck = s.cockpit;
        if (!hud || !ck || ck.busy(kind)) return;
        const on = hud.shown().includes(kind);
        ck.setBusy(kind, true);
        ck.status(`${on ? 'Hiding' : 'Loading'} ${title}`, 'step');
        const plan = on ? [{ type: 'hide_layer', kind }] : [{ type: 'show_layer', kind, frame: false }];
        Promise.resolve(hud.run(plan, sinkFor(s)))
            .catch(e => ck.status(e.message || String(e), 'error'))
            .finally(() => ck.setBusy(kind, false));
    }

    // The field the system keyboard types into; its text is mirrored on the comms panel
    function keyboardField(s) {
        if (s.kbd) return s.kbd;
        const el = document.createElement('input');
        el.type = 'text';
        el.autocomplete = 'off';
        el.enterKeyHint = 'send';
        el.setAttribute('aria-label', 'Message for the AI pilot');
        el.style.cssText = 'position:fixed;left:0;bottom:0;width:1px;height:1px;opacity:0;border:0;padding:0;';
        el.addEventListener('input', () => s.cockpit?.typed(el.value));
        el.addEventListener('focus', () => s.cockpit?.keyboard(true));
        el.addEventListener('blur', () => s.cockpit?.keyboard(false));
        el.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            sendTyped(s);
        });
        document.body.appendChild(el);
        s.kbd = el;
        return el;
    }

    function openKeyboard(s, head) {
        const ck = s.cockpit;
        if (!ck || !window.DeepGISPilot) return;
        ck.showComms(head);
        if (s.session.isSystemKeyboardSupported === false) {
            ck.status('No system keyboard in this browser: use the quick prompts', 'error');
            return;
        }
        keyboardField(s).focus();
    }

    function ask(s, text) {
        const pilot = window.DeepGISPilot;
        if (!pilot || !text.trim()) return false;
        if (pilot.busy()) {
            s.cockpit?.status('The pilot is still answering', 'step');
            return false;
        }
        pilot.ask(text);
        return true;
    }

    function sendTyped(s) {
        const el = s.kbd;
        if (!el || !ask(s, el.value)) return;
        el.value = '';
        el.blur();
        s.cockpit?.typed('');
    }

    // Robots panel: fly to the robot, ride its camera, chase it, or let go
    function robotCommand(s, { robotCmd, id, name }) {
        const hud = window.DeepGISActions;
        if (!hud) return;
        if (robotCmd === 'release') {
            const was = hud.following();
            hud.stop();
            s.cockpit?.status(was ? `Released ${was.id}` : 'Not following a robot', 'step');
            return;
        }
        const v = hud.vehicles().list.find(x => x.id === id);
        if (!v) {
            s.cockpit?.status(`${name || id} is not in the fleet any more`, 'error');
            return;
        }
        const plan = robotCmd === 'fly'
            ? [{ type: 'goto', lat: v.lat, lon: v.lon, alt_m: 120, pitch_deg: -60 }]
            : [{ type: 'follow_vehicle', vehicle: v.id, view: robotCmd === 'chase' ? 'chase' : 'camera' }];
        hud.run(plan, sinkFor(s));
        sfxPlay(s, 'engage');
    }

    // Cockpit sounds: short synthesized tones, so there is nothing to download
    function createSfx() {
        let ctx = null;
        const tone = (freq, ms, { type = 'sine', gain = 0.05, slide = 1, delay = 0 } = {}) => {
            const t = ctx.currentTime + delay / 1000, end = t + ms / 1000;
            const o = ctx.createOscillator(), g = ctx.createGain();
            o.type = type;
            o.frequency.setValueAtTime(freq, t);
            if (slide !== 1) o.frequency.exponentialRampToValueAtTime(freq * slide, end);
            g.gain.setValueAtTime(gain, t);
            g.gain.exponentialRampToValueAtTime(0.0001, end);
            o.connect(g).connect(ctx.destination);
            o.start(t);
            o.stop(end + 0.02);
        };
        const SOUNDS = {
            tick: () => tone(2200, 18, { type: 'square', gain: 0.012 }),
            click: () => tone(880, 70, { type: 'triangle', gain: 0.05, slide: 1.6 }),
            engage: () => { tone(420, 160, { slide: 2, gain: 0.05 }); tone(840, 120, { delay: 90, gain: 0.03 }); },
            reply: () => { tone(660, 120, { gain: 0.04 }); tone(990, 180, { delay: 110, gain: 0.04 }); },
            alert: () => { tone(320, 140, { type: 'sawtooth', gain: 0.03 }); tone(260, 160, { type: 'sawtooth', gain: 0.03, delay: 160 }); },
        };
        return {
            enabled: true,
            // Called from a user gesture (Enter VR) so the browser lets it play
            resume() {
                try {
                    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
                    ctx.resume?.();
                } catch (e) {
                    ctx = null;
                }
            },
            play(name) {
                if (!this.enabled || !ctx || ctx.state !== 'running') return;
                try { SOUNDS[name]?.(); } catch (e) { /* audio is best effort */ }
            },
            close() {
                ctx?.close?.();
                ctx = null;
            },
        };
    }
    const sfx = createSfx();
    const sfxPlay = (s, name) => s.sfx?.play(name);

    function setSound(s, on) {
        s.sfx.enabled = on;
        if (soundBox) soundBox.checked = on;
        s.cockpit?.sound(on);
        if (on) s.sfx.play('click');
    }

    // Comfort vignette: stronger as the ground streams past faster (speed over height above
    // it, in radians per second) and while the view turns
    function comfort(s, dt) {
        if (!s.cockpit || !comfortBox?.checked || !dt) return;
        const { rig, viewer } = s;
        const prev = s.comfortPrev;
        s.comfortPrev = { origin: Cesium.Cartesian3.clone(rig.origin), heading: rig.heading };
        if (!prev) return;
        const { carto, ground } = groundBelow(viewer.scene.globe, rig.origin);
        const flow = Cesium.Cartesian3.distance(rig.origin, prev.origin) / dt / Math.max(carto.height - ground, 20);
        const turn = Math.abs(Cesium.Math.negativePiToPi(rig.heading - prev.heading)) / dt;
        const target = Math.min(0.85, Math.max(0, (flow - 0.08) / 0.6) + Math.max(0, (turn - 0.3) / 2));
        s.vignette += (target - s.vignette) * Math.min(1, dt * (target > s.vignette ? 8 : 3));
        s.cockpit.vignette(s.vignette);
    }

    function act(s, action, source, head) {
        const hud = window.DeepGISActions, ck = s.cockpit;
        if (action === 'stop') {
            hud?.stop();
            ck?.status('Stopped', 'step');
        } else if (action === 'hide') {
            ck?.hide();
        } else if (action === 'cockpit') {
            ck?.toggle(head);
        } else if (action === 'layers') {
            if (ck && !ck.toggleWing(head)) ck.status('No data layers on this body', 'step');
        } else if (action === 'centre') {
            ck?.centre(head);
        } else if (action === 'robots') {
            if (ck && !ck.toggleRobots(head)) ck.status('No robots report positions on this body', 'step');
        } else if (action?.robot) {
            ck?.selectRobot(action.robot);
        } else if (action?.robotCmd) {
            robotCommand(s, action);
        } else if (action === 'sound') {
            setSound(s, !s.sfx.enabled);
        } else if (action === 'pilot') {
            if (ck && !ck.toggleComms(head)) ck.status('The AI pilot is not on this page', 'step');
        } else if (action === 'type') {
            openKeyboard(s, head);
        } else if (action === 'send') {
            sendTyped(s);
        } else if (action === 'clear') {
            if (s.kbd) s.kbd.value = '';
            ck?.typed('');
        } else if (action?.prompt) {
            ask(s, action.prompt);
        } else if (action?.layer) {
            toggleLayer(s, action.layer, action.title);
        } else if (action?.locked) {
            ck?.status(`${action.title} is fetched through the server: sign in on the page first`, 'error');
        }
        if (action !== 'sound' && !action?.robotCmd) sfxPlay(s, 'click');
        buzz(source);
    }

    function flyToGround(s, point, orbit) {
        const hud = window.DeepGISActions;
        if (!hud) return;
        const globe = s.viewer.scene.globe;
        const c = Cesium.Cartographic.fromCartesian(point, globe.ellipsoid);
        const lat = Cesium.Math.toDegrees(c.latitude), lon = Cesium.Math.toDegrees(c.longitude);
        const { carto, ground } = groundBelow(globe, s.rig.origin);
        const a = orbit ? { type: 'orbit', lat, lon }
            : { type: 'goto', lat, lon, alt_m: Cesium.Math.clamp(carto.height - ground, 100, 50000), pitch_deg: -60 };
        hud.run([a], sinkFor(s));
    }

    function readout(s, pose) {
        const { viewer, rig } = s;
        const globe = viewer.scene.globe;
        const { carto, ground } = groundBelow(globe, rig.origin);
        const now = performance.now();
        if (s.lastOrigin && now > s.lastSpeedAt + 250) {
            s.speed = Cesium.Cartesian3.distance(rig.origin, s.lastOrigin) / ((now - s.lastSpeedAt) / 1000);
            s.lastOrigin = Cesium.Cartesian3.clone(rig.origin);
            s.lastSpeedAt = now;
        } else if (!s.lastOrigin) {
            s.lastOrigin = Cesium.Cartesian3.clone(rig.origin);
            s.lastSpeedAt = now;
        }
        const hud = window.DeepGISActions;
        return {
            body: hud?.body || 'earth',
            agl: carto.height - ground,
            speed: s.speed || 0,
            heading: Cesium.Math.zeroToTwoPi(rig.heading - yawOf(pose.transform.matrix)),
            lat: Cesium.Math.toDegrees(carto.latitude),
            lon: Cesium.Math.toDegrees(carto.longitude),
            auto: rig.auto,
            layers: hud?.shown().length || 0,
            target: s.aimed?.ground ? Cesium.Cartesian3.distance(rig.origin, s.aimed.ground) : null,
        };
    }

    function onFrame(time, frame) {
        if (!xr) return;
        const s = xr;
        s.session.requestAnimationFrame(onFrame);
        const pose = frame.getViewerPose(s.space);
        if (!pose) return;
        const dt = s.last == null ? 0 : Math.min(0.1, (time - s.last) / 1000);
        s.last = time;
        try {
            const input = readInput(s.session, frame, s.space, s.held);
            s.held = input.held;
            // Taking the sticks stops an autopilot flight or orbit
            const flying = input.lx || input.ly || input.ry;
            if (flying && s.rig.auto) window.DeepGISActions?.stop();
            const t = advance(s.viewer, s.rig, time);
            if (dt) move(s.viewer, pose, s.rig, input, dt);
            comfort(s, dt);
            const head = pose.transform.matrix;
            s.cockpit?.track(frame, head);
            s.aimed = aim(s, input);
            if (s.cockpit?.hover(s.aimed.panel)) {
                buzz(s.aimed.source, 0.15, 10);
                sfxPlay(s, 'tick');
            }
            if (input.pressed.has(`right${TRIGGER}`) || input.pressed.has(`left${TRIGGER}`)) {
                const source = s.aimed.source;
                if (s.aimed.panel) {
                    const action = s.cockpit.click(s.aimed.panel);
                    if (action) act(s, action, source, head);
                } else if (s.aimed.ground) {
                    flyToGround(s, s.aimed.ground, input.held.has(`right${GRIP}`));
                    buzz(source, 0.6, 40);
                    sfxPlay(s, 'engage');
                }
            }
            if (input.pressed.has(`right${SECONDARY}`)) act(s, 'stop', s.aimed.source, head);
            if (input.pressed.has(`left${PRIMARY}`)) s.cockpit?.toggle(head);
            if (input.pressed.has(`left${SECONDARY}`)) act(s, 'layers', null, head);
            if (input.pressed.has(`right${PRIMARY}`)) act(s, 'pilot', null, head);
            s.cockpit?.update(frame, pose.transform.matrix, readout(s, pose));
            const target = s.projection ? projectionTarget(s.gl, s.binding, s.projection, s.cache)
                : layerTarget(s.gl, s.session.renderState.baseLayer);
            drawEyes(s.viewer, pose, target, s.rig, s.cache, t);
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
            session, viewer, gl, cache: {}, last: null, held: new Set(),
            rig: { origin: Cesium.Cartesian3.clone(camera.positionWC), heading: camera.heading, turnLatched: false, auto: false },
            sfx, vignette: 0, comfortPrev: null,
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
        captureAnimationFrames();
        xr.lasers = scene.primitives.add(new Cesium.PolylineCollection());
        xr.laser = xr.lasers.add({
            positions: [Cesium.Cartesian3.ZERO, Cesium.Cartesian3.UNIT_X], width: 2, show: false,
            material: Cesium.Material.fromType('Color', { color: Cesium.Color.fromCssColorString('#38bdf8').withAlpha(0.85) }),
        });
        xr.markers = scene.primitives.add(new Cesium.PointPrimitiveCollection());
        xr.marker = xr.markers.add({
            position: Cesium.Cartesian3.ZERO, pixelSize: 12, show: false,
            color: Cesium.Color.fromCssColorString('#38bdf8'), outlineColor: Cesium.Color.BLACK, outlineWidth: 2,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
        });
        if (!gl.getContextAttributes().antialias) scene.postProcessStages.fxaa.enabled = true;
        if (!(gl instanceof WebGL2RenderingContext)) throw new Error('VR needs WebGL 2');
        await gl.makeXRCompatible();
        const scaleFactor = parseFloat(scaleSel?.value) || 0.7;
        xr.space = await session.requestReferenceSpace('local');
        if (typeof XRWebGLBinding === 'function') {
            xr.binding = new XRWebGLBinding(session, gl);
            xr.projection = xr.binding.createProjectionLayer({ textureType: 'texture', colorFormat: gl.RGBA8, depthFormat: 0, scaleFactor });
            const viewerSpace = await session.requestReferenceSpace('viewer');
            try {
                xr.cockpit = window.DeepGISCockpit?.create({
                    binding: xr.binding, gl, session, space: xr.space, viewerSpace,
                    present: (layers) => session.updateRenderState({ layers: [xr.projection, ...layers] }),
                });
            } catch (e) {
                console.warn('VR cockpit unavailable', e);
                xr.cockpit = null;
            }
            if (!xr.cockpit) await session.updateRenderState({ layers: [xr.projection] });
            const s = xr;
            s.cockpit?.sound(sfx.enabled);
            if (s.cockpit && window.DeepGISPilot) {
                s.unsubscribePilot = window.DeepGISPilot.on((e) => {
                    s.cockpit?.pilotEvent(e);
                    if (e.kind === 'ai') sfxPlay(s, 'reply');
                    else if (e.kind === 'error' || e.kind === 'robot') sfxPlay(s, 'alert');
                });
                // Focusing inside the select event counts as a user gesture for the keyboard
                session.addEventListener('select', () => {
                    if (xr !== s || !s.aimed?.panel) return;
                    if (s.cockpit.click(s.aimed.panel) === 'type') keyboardField(s).focus();
                });
            }
        } else {
            const layer = new XRWebGLLayer(session, gl, { antialias: false, depth: false, framebufferScaleFactor: scaleFactor });
            await session.updateRenderState({ baseLayer: layer });
        }
        session.requestAnimationFrame(onFrame);
        enterBtn.disabled = true;
        exitBtn.disabled = false;
        status(xr.cockpit ? 'in VR: X cockpit, Y layers, A AI pilot; trigger flies to where the laser points'
            : 'in VR (no cockpit panels on this headset): sticks fly, trigger flies to the laser', '#10b981');
    }

    function onEnd() {
        const s = xr;
        xr = null;
        if (!s) return;
        const { viewer, saved, rig } = s;
        const scene = viewer.scene, camera = viewer.camera, canvas = scene.canvas;
        s.cockpit?.destroy();
        s.unsubscribePilot?.();
        s.kbd?.remove();
        if (s.lasers) scene.primitives.remove(s.lasers);
        if (s.markers) scene.primitives.remove(s.markers);
        releaseAnimationFrames();
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
        sfx.enabled = soundBox ? soundBox.checked : true;
        sfx.resume();
        try {
            // First, while the click still counts as a user gesture
            session = await navigator.xr.requestSession('immersive-vr', { optionalFeatures: ['layers'] });
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

    soundBox?.addEventListener('change', () => { if (xr) setSound(xr, soundBox.checked); });
    checkBtn?.addEventListener('click', check);
    enterBtn.addEventListener('click', enter);
    exitBtn.addEventListener('click', () => xr?.session.end());
    check();

    window.DeepGISXR = { check, enter, exit: () => xr?.session.end(), active: () => !!xr, state: () => xr };
})();
