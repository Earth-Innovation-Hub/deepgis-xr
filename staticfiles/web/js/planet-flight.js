/**
 * Flight geometry for camera "drones" over any spherical body (Moon, Mars, ...).
 *
 * Pure functions only: no Cesium, no DOM, no clock. Every function takes the
 * body radius explicitly, works in degrees and metres, and returns plain
 * objects, so the same code drives the viewer and runs under `node --test`
 * (tests/js/planet-flight.test.js). The page owns time, terrain sampling and the
 * camera; this module only answers "where should the camera be".
 *
 * Bearings and headings are degrees clockwise from north in [0, 360). Pitch is
 * degrees, negative looking down (Cesium's convention).
 */
(function (root, factory) {
    if (typeof module === 'object' && module.exports) module.exports = factory();
    else root.PlanetFlight = factory();
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    const RAD = Math.PI / 180;
    const DEG = 180 / Math.PI;

    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    const wrap360 = (deg) => ((deg % 360) + 360) % 360;
    /** Longitude in (-180, 180]. */
    const wrapLon = (lon) => {
        const w = wrap360(lon + 180) - 180;
        return w === -180 ? 180 : w;
    };

    function requirePositive(name, value) {
        if (!(Number.isFinite(value) && value > 0)) {
            throw new RangeError(`${name} must be a positive number, got ${value}`);
        }
    }

    /** Great-circle distance in metres (haversine). */
    function distance(a, b, radius) {
        const dLat = (b.lat - a.lat) * RAD;
        const dLon = (b.lon - a.lon) * RAD;
        const h = Math.sin(dLat / 2) ** 2 +
            Math.cos(a.lat * RAD) * Math.cos(b.lat * RAD) * Math.sin(dLon / 2) ** 2;
        return 2 * radius * Math.asin(Math.min(1, Math.sqrt(h)));
    }

    /** Initial great-circle bearing from a to b. */
    function bearing(a, b) {
        const f1 = a.lat * RAD, f2 = b.lat * RAD, dl = (b.lon - a.lon) * RAD;
        const y = Math.sin(dl) * Math.cos(f2);
        const x = Math.cos(f1) * Math.sin(f2) - Math.sin(f1) * Math.cos(f2) * Math.cos(dl);
        return wrap360(Math.atan2(y, x) * DEG);
    }

    /** The point `dist` metres from `a` along `bearingDeg`. */
    function destination(a, bearingDeg, dist, radius) {
        const d = dist / radius, t = bearingDeg * RAD, f1 = a.lat * RAD;
        const f2 = Math.asin(clamp(
            Math.sin(f1) * Math.cos(d) + Math.cos(f1) * Math.sin(d) * Math.cos(t), -1, 1));
        const l2 = a.lon * RAD + Math.atan2(
            Math.sin(t) * Math.sin(d) * Math.cos(f1),
            Math.cos(d) - Math.sin(f1) * Math.sin(f2));
        return { lon: wrapLon(l2 * DEG), lat: f2 * DEG };
    }

    /** The point a fraction `f` of the way from a to b along the great circle. */
    function interpolate(a, b, f) {
        const d = distance(a, b, 1);
        if (d < 1e-12) return { lon: a.lon, lat: a.lat };
        const A = Math.sin((1 - f) * d) / Math.sin(d), B = Math.sin(f * d) / Math.sin(d);
        const f1 = a.lat * RAD, l1 = a.lon * RAD, f2 = b.lat * RAD, l2 = b.lon * RAD;
        const x = A * Math.cos(f1) * Math.cos(l1) + B * Math.cos(f2) * Math.cos(l2);
        const y = A * Math.cos(f1) * Math.sin(l1) + B * Math.cos(f2) * Math.sin(l2);
        const z = A * Math.sin(f1) + B * Math.sin(f2);
        return { lon: wrapLon(Math.atan2(y, x) * DEG), lat: Math.atan2(z, Math.hypot(x, y)) * DEG };
    }

    /**
     * Pitch that points a camera at `camera` (height `cameraHeight`) toward
     * `target` (height `targetHeight`), allowing for the body's curvature, which
     * matters on small bodies: 100 km away on the Moon the target sits ~2.9 km
     * below the camera's horizontal plane.
     */
    function lookAtPitch(camera, cameraHeight, target, targetHeight, radius) {
        const theta = distance(camera, target, radius) / radius;
        const horizontal = (radius + targetHeight) * Math.sin(theta);
        const vertical = (radius + targetHeight) * Math.cos(theta) - (radius + cameraHeight);
        if (horizontal < 1e-9) return vertical < 0 ? -90 : 90;
        return Math.atan2(vertical, horizontal) * DEG;
    }

    /** Circumference (m) of the small circle `radiusM` from a point. */
    function orbitCircumference(radiusM, radius) {
        return 2 * Math.PI * radius * Math.sin(Math.min(radiusM / radius, Math.PI / 2));
    }

    /**
     * Where an orbit is after `elapsedS` seconds at `speedMps` along the ground.
     * `angleDeg` is the bearing from the centre to the camera; counter-clockwise
     * seen from above (the default) means the bearing decreases.
     */
    function orbitAngleAt({ startAngleDeg, speedMps, radiusM, elapsedS, clockwise = false, radius }) {
        requirePositive('radiusM', radiusM);
        requirePositive('radius', radius);
        const revolutions = (speedMps * Math.max(0, elapsedS)) / orbitCircumference(radiusM, radius);
        const sweep = revolutions * 360 * (clockwise ? 1 : -1);
        return { angleDeg: wrap360(startAngleDeg + sweep), revolutions };
    }

    /**
     * Camera pose on an orbit: `radiusM` from `center` at bearing `angleDeg`,
     * `aglM` above the centre's ground height, heading toward the centre.
     * `pitchDeg` null aims the camera at the centre itself.
     */
    function orbitPose({ center, centerHeight = 0, radiusM, aglM, angleDeg, pitchDeg = null, radius }) {
        requirePositive('radiusM', radiusM);
        requirePositive('radius', radius);
        const ground = destination(center, angleDeg, radiusM, radius);
        const height = centerHeight + aglM;
        return {
            lon: ground.lon,
            lat: ground.lat,
            height,
            heading: bearing(ground, center),
            pitch: pitchDeg ?? lookAtPitch(ground, height, center, centerHeight, radius),
        };
    }

    /** Smoothstep: zero velocity at both ends, so moves start and stop gently. */
    const easeInOut = (t) => {
        const x = clamp(t, 0, 1);
        return x * x * (3 - 2 * x);
    };

    /**
     * A straight (great-circle) flight of `distM` along `headingDeg` from
     * `start`, changing height from `startHeight` to `endHeight`, at an average
     * ground speed of `speedMps`. `sample(s)` gives the pose `s` seconds in and
     * holds the end pose after `durationS`. The heading follows the track, which
     * curves in bearing on a sphere.
     */
    function flyForwardPlan({ start, startHeight, headingDeg, distM, endHeight = startHeight, speedMps, radius }) {
        requirePositive('distM', distM);
        requirePositive('speedMps', speedMps);
        requirePositive('radius', radius);
        const end = destination(start, headingDeg, distM, radius);
        const finalHeading = wrap360(bearing(end, start) + 180);
        const durationS = distM / speedMps;
        return {
            durationS,
            end,
            sample(seconds) {
                const f = easeInOut(seconds / durationS);
                const p = f >= 1 ? end : interpolate(start, end, f);
                return {
                    lon: p.lon,
                    lat: p.lat,
                    height: startHeight + (endHeight - startHeight) * f,
                    heading: f >= 1 ? finalHeading
                        : f < 0.5 ? bearing(p, end) : wrap360(bearing(p, start) + 180),
                    done: f >= 1,
                };
            },
        };
    }

    return {
        clamp,
        wrap360,
        wrapLon,
        distance,
        bearing,
        destination,
        interpolate,
        lookAtPitch,
        orbitCircumference,
        orbitAngleAt,
        orbitPose,
        easeInOut,
        flyForwardPlan,
    };
});
