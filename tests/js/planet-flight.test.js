// Run: docker run --rm -v "$PWD":/w -w /w node:22-alpine node --test 'tests/js/*.test.js'
const test = require('node:test');
const assert = require('node:assert/strict');
const F = require('../../staticfiles/web/js/planet-flight.js');

const MOON = 1737400;
const near = (actual, expected, tol, msg) =>
    assert.ok(Math.abs(actual - expected) <= tol, `${msg ?? ''} ${actual} vs ${expected} (±${tol})`);
const angleNear = (actual, expected, tol, msg) =>
    near(Math.abs(((actual - expected + 540) % 360) - 180), 0, tol, msg);

test('wrapLon folds into (-180, 180]', () => {
    assert.equal(F.wrapLon(190), -170);
    assert.equal(F.wrapLon(-180), 180);
    assert.equal(F.wrapLon(540), 180);
    assert.equal(F.wrapLon(-10), -10);
});

test('distance: a quarter meridian is a quarter of the circumference', () => {
    near(F.distance({ lon: 0, lat: 0 }, { lon: 0, lat: 90 }, MOON), Math.PI * MOON / 2, 1e-6);
    assert.equal(F.distance({ lon: 23.47, lat: 0.67 }, { lon: 23.47, lat: 0.67 }, MOON), 0);
});

test('destination and bearing invert each other, across the antimeridian too', () => {
    for (const [start, brg, dist] of [
        [{ lon: 23.47297, lat: 0.67408 }, 37, 25_000],
        [{ lon: 179.9, lat: -40 }, 90, 50_000],
        [{ lon: -11.36, lat: -43.31 }, 300, 400_000],
    ]) {
        const end = F.destination(start, brg, dist, MOON);
        near(F.distance(start, end, MOON), dist, 1e-3, 'distance');
        angleNear(F.bearing(start, end), brg, 1e-6, 'bearing');
    }
    near(F.destination({ lon: 179.9, lat: 0 }, 90, 50_000, MOON).lon, 179.9 + 50_000 / MOON * 180 / Math.PI - 360, 1e-9);
});

test('interpolate stays on the great circle', () => {
    const a = { lon: -23.42, lat: -3.01 }, b = { lon: 30.77, lat: 20.19 };
    const mid = F.interpolate(a, b, 0.5);
    near(F.distance(a, mid, MOON), F.distance(mid, b, MOON), 1e-3);
    near(F.distance(a, mid, MOON) * 2, F.distance(a, b, MOON), 1e-3);
    near(F.distance(F.interpolate(a, b, 0), a, MOON), 0, 1e-6);
    near(F.distance(F.interpolate(a, b, 1), b, MOON), 0, 1e-6);
});

test('lookAtPitch: straight down overhead, and steeper than flat-earth far away', () => {
    const p = { lon: 0, lat: 0 };
    assert.equal(F.lookAtPitch(p, 5000, p, 0, MOON), -90);
    const cam = F.destination(p, 0, 100_000, MOON);
    const flat = -Math.atan2(10_000, 100_000) * 180 / Math.PI;
    const curved = F.lookAtPitch(cam, 10_000, p, 0, MOON);
    assert.ok(curved < flat, `${curved} should be below ${flat}`);
    near(F.lookAtPitch(F.destination(p, 0, 1000, MOON), 1000, p, 0, MOON), -45, 0.02);
});

test('orbitPose sits on the circle and faces the centre', () => {
    const center = { lon: -11.36, lat: -43.31 };
    for (const angleDeg of [0, 90, 211, 359]) {
        const pose = F.orbitPose({ center, centerHeight: -1200, radiusM: 20_000, aglM: 15_000, angleDeg, radius: MOON });
        near(F.distance(center, pose, MOON), 20_000, 1e-3, 'radius');
        angleNear(F.bearing(center, pose), angleDeg, 1e-6, 'angle');
        assert.equal(pose.height, 13_800);
        const ahead = F.destination(pose, pose.heading, 20_000, MOON);
        near(F.distance(ahead, center, MOON), 0, 1e-3, 'heading points at the centre');
        assert.ok(pose.pitch < -36 && pose.pitch > -38, `look-at pitch ${pose.pitch}`);
    }
    const fixed = F.orbitPose({ center, radiusM: 1000, aglM: 500, angleDeg: 0, pitchDeg: -65, radius: MOON });
    assert.equal(fixed.pitch, -65);
    assert.throws(() => F.orbitPose({ center, radiusM: 0, aglM: 1, angleDeg: 0, radius: MOON }), RangeError);
});

test('orbitAngleAt counts revolutions on the small circle', () => {
    const radiusM = 300_000, speedMps = 1000;
    const circumference = F.orbitCircumference(radiusM, MOON);
    assert.ok(circumference < 2 * Math.PI * radiusM, 'a small circle on a sphere is shorter than flat');
    const oneLap = F.orbitAngleAt({ startAngleDeg: 45, speedMps, radiusM, elapsedS: circumference / speedMps, radius: MOON });
    near(oneLap.revolutions, 1, 1e-12);
    angleNear(oneLap.angleDeg, 45, 1e-9);
    const quarter = circumference / speedMps / 4;
    near(F.orbitAngleAt({ startAngleDeg: 45, speedMps, radiusM, elapsedS: quarter, radius: MOON }).angleDeg, 315, 1e-9, 'ccw');
    near(F.orbitAngleAt({ startAngleDeg: 45, speedMps, radiusM, elapsedS: quarter, clockwise: true, radius: MOON }).angleDeg, 135, 1e-9, 'cw');
    assert.equal(F.orbitAngleAt({ startAngleDeg: 10, speedMps, radiusM, elapsedS: -5, radius: MOON }).revolutions, 0);
});

test('flyForwardPlan flies the distance along the heading, eased, then holds', () => {
    const start = { lon: 23.47297, lat: 0.67408 };
    const plan = F.flyForwardPlan({ start, startHeight: 2000, headingDeg: 60, distM: 30_000, endHeight: 10_000, speedMps: 1000, radius: MOON });
    assert.equal(plan.durationS, 30);
    const s0 = plan.sample(0);
    near(F.distance(start, s0, MOON), 0, 1e-6);
    angleNear(s0.heading, 60, 1e-9);
    assert.equal(s0.height, 2000);
    const mid = plan.sample(15);
    near(F.distance(start, mid, MOON), 15_000, 1e-3, 'smoothstep is symmetric');
    assert.equal(mid.height, 6000);
    const end = plan.sample(30);
    assert.ok(end.done);
    near(F.distance(start, end, MOON), 30_000, 1e-3);
    angleNear(F.bearing(start, end), 60, 1e-6);
    assert.deepEqual(plan.sample(99), end);
    let last = -1;
    for (let s = 0; s <= 30; s += 1.5) {
        const d = F.distance(start, plan.sample(s), MOON);
        assert.ok(d >= last, 'progress never goes backwards');
        last = d;
    }
    assert.throws(() => F.flyForwardPlan({ start, startHeight: 0, headingDeg: 0, distM: 10, speedMps: 0, radius: MOON }), RangeError);
});
