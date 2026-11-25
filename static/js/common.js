/**
 * @fileoverview Shared utilities, API client, and constants for Saans.
 * Adheres to strict DOM security: textContent and node construction only.
 */

/* eslint-disable no-unused-vars */

/** @const {!Object<string, string>} */
const TIER_LABELS = {
  normal: "Normal activity",
  caution: "Take extra care",
  restrict: "Limit time outdoors",
  avoid: "Avoid outdoor exertion"
};

/** @const {!Object<string, string>} */
const ACTIVITY_LABELS = {
  outdoor_exercise: "Outdoor exercise",
  errands: "Errands",
  window_ventilation: "Airing the home",
  kids_outdoor_play: "Children playing outside"
};

/** @const {!Object<string, string>} */
const BAND_CLASSES = {
  good: "band-good",
  satisfactory: "band-satisfactory",
  moderate: "band-moderate",
  poor: "band-poor",
  very_poor: "band-very_poor",
  severe: "band-severe"
};

/**
 * Create a DOM element with optional text and class name.
 * @param {string} tag - HTML tag name.
 * @param {string=} text - Optional text content.
 * @param {string=} className - Optional class name.
 * @return {!HTMLElement}
 */
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) {
    node.textContent = String(text);
  }
  if (className) {
    node.className = className;
  }
  return node;
}

/**
 * Execute an API call returning standardized status and data.
 * @param {string} path - Endpoint path.
 * @param {?Object=} payload - Optional request body dictionary.
 * @return {!Promise<{ok: boolean, status: number, data: *}>}
 */
async function api(path, payload) {
  const opts = {
    method: payload ? "POST" : "GET",
    headers: {"Accept": "application/json"}
  };
  if (payload) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(payload);
  }
  try {
    const res = await fetch(path, opts);
    const json = await res.json().catch(() => null);
    return {ok: res.ok, status: res.status, data: json || {}};
  } catch (err) {
    return {
      ok: false,
      status: 0,
      data: {
        error: "Network problem. Check your connection and try again.",
        code: "NETWORK"
      }
    };
  }
}

/**
 * Generate friendly error descriptions from API result.
 * @param {!{ok: boolean, status: number, data: *}} result
 * @return {string}
 */
function describeError(result) {
  const data = result.data || {};
  if (result.status === 400 && Array.isArray(data.details) && data.details.length) {
    return data.details.join(" ");
  }
  if (data.manual_hint) {
    return data.error || "City lookup failed. You can enter PM2.5 yourself.";
  }
  if (result.status === 429) {
    return "You are going quickly. Please wait a minute.";
  }
  if (result.status >= 500) {
    return "The service encountered an error. Please try again shortly.";
  }
  return data.error || "An unexpected error occurred. Please try again.";
}

/**
 * Load parsed object from sessionStorage.
 * @param {string} key
 * @return {*}
 */
function loadSession(key) {
  try {
    const val = window.sessionStorage.getItem(key);
    return val ? JSON.parse(val) : null;
  } catch (e) {
    return null;
  }
}

/**
 * Save serializable value to sessionStorage.
 * @param {string} key
 * @param {*} val
 */
function saveSession(key, val) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(val));
  } catch (e) {
    // Session storage write failures are ignored gracefully
  }
}

/**
 * Clear specific key from sessionStorage.
 * @param {string} key
 */
function clearSession(key) {
  try {
    window.sessionStorage.removeItem(key);
  } catch (e) {
    // Ignore clear errors
  }
}

/**
 * Announce messages to screen readers via live region.
 * @param {string} msg
 */
function announce(msg) {
  const region = document.getElementById("live-status");
  if (region) {
    region.textContent = msg;
  }
}

/**
 * Format 24-hour integer to time string.
 * @param {number} h
 * @return {string}
 */
function formatHour(h) {
  return `${h}:00`;
}

/**
 * Format forecast window into readable string.
 * @param {?{hour: number, avg_pm25: number}} w
 * @return {string}
 */
function formatWindow(w) {
  if (!w || typeof w.hour !== "number") {
    return "Forecast not available";
  }
  const nextHour = (w.hour + 1) % 24;
  return `${w.hour}:00 to ${nextHour}:00 (average ${w.avg_pm25.toFixed(1)} µg/m³)`;
}
