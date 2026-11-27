/**
 * @fileoverview Interactive AQI calculation and explanation widget on About page.
 * Uses strict DOM manipulation with textContent only.
 */

/* global el */

document.addEventListener("DOMContentLoaded", () => {
  initAqiCalculator();
});

/**
 * Breakpoint table definitions matching Indian CPCB National AQI standards.
 */
const CPCB_BREAKPOINTS = [
  { key: "good", label: "Good", cLow: 0, cHigh: 30, iLow: 0, iHigh: 50, chipClass: "band-good" },
  { key: "satisfactory", label: "Satisfactory", cLow: 31, cHigh: 60, iLow: 51, iHigh: 100, chipClass: "band-satisfactory" },
  { key: "moderate", label: "Moderate", cLow: 61, cHigh: 90, iLow: 101, iHigh: 200, chipClass: "band-moderate" },
  { key: "poor", label: "Poor", cLow: 91, cHigh: 120, iLow: 201, iHigh: 300, chipClass: "band-poor" },
  { key: "very_poor", label: "Very Poor", cLow: 121, cHigh: 250, iLow: 301, iHigh: 400, chipClass: "band-very_poor" },
  { key: "severe", label: "Severe", cLow: 251, cHigh: 500, iLow: 401, iHigh: 500, chipClass: "band-severe" }
];

/**
 * Compute AQI and calculation steps from raw PM2.5 concentration.
 * @param {number} pm25
 * @return {!Object}
 */
function calculateAqiDetails(pm25) {
  const conc = Math.max(0, Math.min(1000, pm25));
  let bp = CPCB_BREAKPOINTS[CPCB_BREAKPOINTS.length - 1];

  for (let i = 0; i < CPCB_BREAKPOINTS.length; i++) {
    const item = CPCB_BREAKPOINTS[i];
    if (conc <= item.cHigh) {
      bp = item;
      break;
    }
  }

  let aqi;
  if (conc <= 30) {
    aqi = Math.round((50 / 30) * conc);
  } else if (conc <= 60) {
    aqi = Math.round(50 + (50 / 30) * (conc - 30));
  } else if (conc <= 90) {
    aqi = Math.round(100 + (100 / 30) * (conc - 60));
  } else if (conc <= 120) {
    aqi = Math.round(200 + (100 / 30) * (conc - 90));
  } else if (conc <= 250) {
    aqi = Math.round(300 + (100 / 130) * (conc - 120));
  } else {
    aqi = Math.min(500, Math.round(400 + (100 / 130) * (conc - 250)));
  }

  const iDiff = bp.iHigh - bp.iLow;
  const cDiff = bp.cHigh - bp.cLow;
  const concExcess = Math.max(0, conc - bp.cLow);
  const factor = (iDiff / cDiff).toFixed(2);
  const added = Math.round((iDiff / cDiff) * concExcess);

  return {
    conc,
    aqi,
    bp,
    formulaText: `AQI = ${bp.iLow} + [(${bp.iHigh} - ${bp.iLow}) / (${bp.cHigh} - ${bp.cLow})] × (${conc.toFixed(1)} - ${bp.cLow})`,
    arithmeticText: `AQI = ${bp.iLow} + (${factor} × ${concExcess.toFixed(1)}) = ${bp.iLow} + ${added} = ${aqi}`
  };
}

/**
 * Attach live recalculation listeners to interactive calculator widget.
 */
function initAqiCalculator() {
  const input = document.getElementById("calc-pm25-input");
  const aqiValEl = document.getElementById("calc-aqi-value");
  const bandBadgeEl = document.getElementById("calc-band-badge");
  const formulaEl = document.getElementById("calc-formula-step");
  const arithmeticEl = document.getElementById("calc-arithmetic-step");
  const pointerEl = document.getElementById("calc-spectrum-pointer");

  if (!input || !aqiValEl || !bandBadgeEl) return;

  const update = () => {
    const val = parseFloat(input.value || "0");
    const res = calculateAqiDetails(isNaN(val) ? 0 : val);

    aqiValEl.textContent = String(res.aqi);
    bandBadgeEl.textContent = res.bp.label;
    bandBadgeEl.className = `band-chip ${res.bp.chipClass} px-3 py-1 text-sm font-semibold rounded-full`;

    if (formulaEl) formulaEl.textContent = res.formulaText;
    if (arithmeticEl) arithmeticEl.textContent = res.arithmeticText;

    if (pointerEl) {
      const pct = Math.min(Math.max((res.aqi / 500) * 100, 2), 98);
      pointerEl.style.left = `${pct}%`;
    }
  };

  input.addEventListener("input", update);
  input.addEventListener("change", update);

  // Quick preset buttons
  document.querySelectorAll(".calc-preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pVal = btn.getAttribute("data-pm25");
      if (pVal) {
        input.value = pVal;
        update();
      }
    });
  });

  update();
}
