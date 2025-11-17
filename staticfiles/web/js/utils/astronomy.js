/**
 * Astronomical Calculation Utilities
 * Lazy loaded when astronomy calculations are needed
 */

export function calculateSunPosition(date, latitude, longitude) {
  const jd = getJulianDate(date);
  const n = jd - 2451545.0;
  
  let L = (280.460 + 0.9856474 * n) % 360;
  if (L < 0) L += 360;
  
  let g = Math.PI / 180 * ((357.528 + 0.9856003 * n) % 360);
  const lambda = Math.PI / 180 * (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g));
  const epsilon = Math.PI / 180 * (23.439 - 0.0000004 * n);
  
  const alpha = Math.atan2(Math.cos(epsilon) * Math.sin(lambda), Math.cos(lambda));
  const delta = Math.asin(Math.sin(epsilon) * Math.sin(lambda));
  
  const gmst = (18.697374558 + 24.06570982441908 * n) % 24;
  const lmst = (gmst + longitude / 15) % 24;
  const ha = Math.PI / 180 * (lmst * 15 - alpha * 180 / Math.PI);
  
  const lat_rad = Math.PI / 180 * latitude;
  
  const elevation = Math.asin(
    Math.sin(lat_rad) * Math.sin(delta) + 
    Math.cos(lat_rad) * Math.cos(delta) * Math.cos(ha)
  );
  
  const azimuth = Math.atan2(
    -Math.sin(ha),
    Math.tan(delta) * Math.cos(lat_rad) - Math.sin(lat_rad) * Math.cos(ha)
  );
  
  return {
    azimuth: (azimuth * 180 / Math.PI + 360) % 360,
    elevation: elevation * 180 / Math.PI,
    isVisible: elevation > 0
  };
}

export function calculateMoonPosition(date, latitude, longitude) {
  const jd = getJulianDate(date);
  const T = (jd - 2451545.0) / 36525;
  
  let L = (218.3164477 + 481267.88123421 * T) % 360;
  if (L < 0) L += 360;
  
  let M = (134.9633964 + 477198.8675055 * T) % 360;
  if (M < 0) M += 360;
  
  let Ms = (357.5291092 + 35999.0502909 * T) % 360;
  if (Ms < 0) Ms += 360;
  
  let F = (93.2720950 + 483202.0175233 * T) % 360;
  if (F < 0) F += 360;
  
  L *= Math.PI / 180;
  M *= Math.PI / 180;
  Ms *= Math.PI / 180;
  F *= Math.PI / 180;
  
  const dL = 6.289 * Math.sin(M) + 1.274 * Math.sin(2 * L - M) - 0.658 * Math.sin(2 * L);
  const lambda = L + dL * Math.PI / 180;
  
  const dB = 5.128 * Math.sin(F) + 0.281 * Math.sin(M + F);
  const beta = dB * Math.PI / 180;
  
  const epsilon = 23.439 * Math.PI / 180;
  
  const alpha = Math.atan2(
    Math.sin(lambda) * Math.cos(epsilon) - Math.tan(beta) * Math.sin(epsilon),
    Math.cos(lambda)
  );
  
  const delta = Math.asin(
    Math.sin(beta) * Math.cos(epsilon) + Math.cos(beta) * Math.sin(epsilon) * Math.sin(lambda)
  );
  
  const gmst = (18.697374558 + 24.06570982441908 * (jd - 2451545.0)) % 24;
  const lmst = (gmst + longitude / 15) % 24;
  const ha = Math.PI / 180 * (lmst * 15 - alpha * 180 / Math.PI);
  
  const lat_rad = Math.PI / 180 * latitude;
  
  const elevation = Math.asin(
    Math.sin(lat_rad) * Math.sin(delta) + 
    Math.cos(lat_rad) * Math.cos(delta) * Math.cos(ha)
  );
  
  const azimuth = Math.atan2(
    -Math.sin(ha),
    Math.tan(delta) * Math.cos(lat_rad) - Math.sin(lat_rad) * Math.cos(ha)
  );
  
  const phase = calculateMoonPhase(jd);
  
  return {
    azimuth: (azimuth * 180 / Math.PI + 360) % 360,
    elevation: elevation * 180 / Math.PI,
    isVisible: elevation > 0,
    phase: phase
  };
}

function calculateMoonPhase(jd) {
  const daysSinceNew = (jd - 2451549.5) % 29.53058868;
  const phase = daysSinceNew / 29.53058868;
  
  if (phase < 0.0625) return "New";
  else if (phase < 0.1875) return "Waxing Crescent";
  else if (phase < 0.3125) return "First Quarter";
  else if (phase < 0.4375) return "Waxing Gibbous";
  else if (phase < 0.5625) return "Full";
  else if (phase < 0.6875) return "Waning Gibbous";
  else if (phase < 0.8125) return "Last Quarter";
  else if (phase < 0.9375) return "Waning Crescent";
  else return "New";
}

function getJulianDate(date) {
  const a = Math.floor((14 - (date.getMonth() + 1)) / 12);
  const y = date.getFullYear() + 4800 - a;
  const m = (date.getMonth() + 1) + 12 * a - 3;
  
  const jdn = date.getDate() + Math.floor((153 * m + 2) / 5) + 365 * y + 
             Math.floor(y / 4) - Math.floor(y / 100) + Math.floor(y / 400) - 32045;
  
  const jd = jdn + (date.getHours() - 12) / 24 + date.getMinutes() / 1440 + 
            date.getSeconds() / 86400 + date.getMilliseconds() / 86400000;
  
  return jd;
}

export default {
  calculateSunPosition,
  calculateMoonPosition
};

