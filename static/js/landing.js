/**
 * @fileoverview Landing page preview logic for Saans.
 * Loads sample plan card from session storage or API.
 * Adheres to DOM security: textContent only.
 */

/* global api, loadSession, saveSession, formatHour, BAND_CLASSES */

document.addEventListener("DOMContentLoaded", async () => {
  const cardEl = document.getElementById("landing-example-card");
  if (!cardEl) return;

  const samplePayload = {
    city: "Delhi",
    household: {
      children: 1,
      elderly: 1,
      respiratory: true,
      heart: false,
      pregnant: false
    },
    lifestyle: {
      heating: "electric",
      cooking: "lpg",
      has_purifier: true,
      smokers: false,
      commute_mode: "metro_train",
      commute_km_one_way: 12,
      commute_days_per_week: 5,
      room_area_sqm: 25,
      usual_outdoor_hour: 8
    },
    manual_pm25: 180,
    notes: ""
  };

  let planData = loadSession("saans.landing_example");

  if (!planData) {
    const res = await api("/api/plan", samplePayload);
    if (res.ok && res.data) {
      planData = res.data;
      saveSession("saans.landing_example", planData);
    }
  }

  if (!planData) {
    // If API fails, card already has static fallback values in HTML
    return;
  }

  const advice = planData.advice || {};
  const reading = planData.reading || {};

  const pm25El = document.getElementById("example-pm25-val");
  if (pm25El && typeof reading.pm25 === "number") {
    pm25El.textContent = reading.pm25.toFixed(1);

    const pointerEl = document.getElementById("example-spectrum-pointer");
    if (pointerEl) {
      const pct = Math.min(Math.max((reading.pm25 / 300) * 100, 3), 97);
      pointerEl.style.left = `${pct}%`;
    }
  }

  const bandChip = document.getElementById("example-band-chip");
  if (bandChip && advice.air?.band) {
    bandChip.textContent = advice.air.band.label;
    const bandClass = BAND_CLASSES[advice.air.band.key] || "band-very_poor";
    bandChip.className = `band-chip ${bandClass}`;
  }

  const ventEl = document.getElementById("example-vent-window");
  if (ventEl) {
    const vent = advice.guidance?.window_ventilation;
    ventEl.textContent = vent && vent.allowed ? "Brief mid-day opening" : "Keep closed";
  }

  const bestWinEl = document.getElementById("example-best-window");
  if (bestWinEl) {
    const w = advice.windows?.outdoor_exercise;
    if (w && typeof w.hour === "number") {
      bestWinEl.textContent = `${formatHour(w.hour)} - ${formatHour((w.hour + 1) % 24)}`;
    } else {
      bestWinEl.textContent = "Mid-day dispersion";
    }
  }

  const sensNoteEl = document.getElementById("example-sensitive-note");
  if (sensNoteEl) {
    const groups = advice.sensitivity?.groups;
    sensNoteEl.textContent = groups && groups.length ? groups.join(", ") : "Children & Seniors";
  }
});
