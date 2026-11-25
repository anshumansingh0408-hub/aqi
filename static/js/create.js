/**
 * @fileoverview Form validation and handling for the plan creation page.
 * Uses strict DOM manipulation with textContent only.
 */

/* global el, loadSession, saveSession, clearSession, announce */

document.addEventListener("DOMContentLoaded", () => {
  initNoticeAndDetails();
  initNotesCounter();
  initExampleButton();
  initFormPrefill();
  initFormSubmit();
});

/**
 * Handle initial notice from failed lookups and query parameter flags.
 */
function initNoticeAndDetails() {
  const noticeBox = document.getElementById("saved-notice");
  const details = document.getElementById("manual-details");
  const savedNotice = loadSession("saans.notice");
  if (savedNotice && noticeBox) {
    noticeBox.textContent = String(savedNotice);
    noticeBox.classList.remove("hidden");
    clearSession("saans.notice");
  }
  const params = new URLSearchParams(window.location.search);
  if ((params.get("manual") === "1" || savedNotice) && details) {
    details.open = true;
  }
}

/**
 * Attach input listener to notes textarea to update character counter.
 */
function initNotesCounter() {
  const notes = document.getElementById("notes");
  const counter = document.getElementById("notes-counter");
  if (!notes || !counter) return;
  const update = () => {
    counter.textContent = `${notes.value.length} / 300`;
  };
  notes.addEventListener("input", update);
  update();
}

/**
 * Fill form fields with a realistic example dataset.
 */
function fillExampleData() {
  const setVal = (id, val) => {
    const field = document.getElementById(id);
    if (field) field.value = val;
  };
  const setCheck = (id, bool) => {
    const field = document.getElementById(id);
    if (field) field.checked = bool;
  };
  setVal("city", "Delhi");
  setVal("children", "1");
  setVal("elderly", "1");
  setCheck("respiratory", false);
  setCheck("heart", false);
  setCheck("pregnant", false);
  setVal("heating", "electric");
  setVal("cooking", "lpg");
  setVal("room_area_sqm", "18");
  setCheck("has_purifier", false);
  setCheck("smokers", false);
  setVal("commute_mode", "car_petrol");
  setVal("commute_km_one_way", "12");
  setVal("commute_days_per_week", "5");
  setVal("usual_outdoor_hour", "8");
  setVal("manual_pm25", "");
  setVal("notes", "");
  hideErrorSummary();
}

/**
 * Wire example button click.
 */
function initExampleButton() {
  const btn = document.getElementById("example-btn");
  if (btn) {
    btn.addEventListener("click", fillExampleData);
  }
}

/**
 * Pre-populate form fields if returning from plan page.
 */
function initFormPrefill() {
  const saved = loadSession("saans.inputs");
  if (!saved) return;
  const hh = saved.household || {};
  const ls = saved.lifestyle || {};
  const setVal = (id, val) => {
    const f = document.getElementById(id);
    if (f && val !== undefined && val !== null) f.value = val;
  };
  const setCheck = (id, val) => {
    const f = document.getElementById(id);
    if (f) f.checked = Boolean(val);
  };
  setVal("city", saved.city);
  setVal("children", hh.children);
  setVal("elderly", hh.elderly);
  setCheck("respiratory", hh.respiratory);
  setCheck("heart", hh.heart);
  setCheck("pregnant", hh.pregnant);
  setVal("heating", ls.heating);
  setVal("cooking", ls.cooking);
  setVal("room_area_sqm", ls.room_area_sqm);
  setCheck("has_purifier", ls.has_purifier);
  setCheck("smokers", ls.smokers);
  setVal("commute_mode", ls.commute_mode);
  setVal("commute_km_one_way", ls.commute_km_one_way);
  setVal("commute_days_per_week", ls.commute_days_per_week);
  setVal("usual_outdoor_hour", ls.usual_outdoor_hour);
  if (saved.manual_pm25 !== null && saved.manual_pm25 !== undefined) {
    setVal("manual_pm25", saved.manual_pm25);
    const details = document.getElementById("manual-details");
    if (details) details.open = true;
  }
  setVal("notes", saved.notes);
  const counter = document.getElementById("notes-counter");
  if (counter && saved.notes) {
    counter.textContent = `${saved.notes.length} / 300`;
  }
}

/**
 * Check numeric boundaries.
 * @param {string} valStr
 * @param {number} min
 * @param {number} max
 * @return {boolean}
 */
function isNumInRange(valStr, min, max) {
  if (valStr === "") return false;
  const n = Number(valStr);
  return !isNaN(n) && n >= min && n <= max;
}

/**
 * Validate all form fields collecting errors and field IDs.
 * @return {!Array<{id: string, msg: string}>}
 */
function validateClientInputs() {
  const errors = [];
  const city = document.getElementById("city")?.value.trim() || "";
  if (city.length < 2 || city.length > 60) {
    errors.push({id: "city", msg: "City must be between 2 and 60 characters."});
  }
  const ch = document.getElementById("children")?.value || "";
  if (!isNumInRange(ch, 0, 10)) {
    errors.push({id: "children", msg: "Children under 18 must be between 0 and 10."});
  }
  const elVal = document.getElementById("elderly")?.value || "";
  if (!isNumInRange(elVal, 0, 10)) {
    errors.push({id: "elderly", msg: "Adults 60 and over must be between 0 and 10."});
  }
  const room = document.getElementById("room_area_sqm")?.value || "";
  if (!isNumInRange(room, 5, 200)) {
    errors.push({id: "room_area_sqm", msg: "Room area must be between 5 and 200 square metres."});
  }
  const km = document.getElementById("commute_km_one_way")?.value || "";
  if (!isNumInRange(km, 0, 200)) {
    errors.push({id: "commute_km_one_way", msg: "Commute distance must be between 0 and 200 km."});
  }
  const days = document.getElementById("commute_days_per_week")?.value || "";
  if (!isNumInRange(days, 0, 7)) {
    errors.push({id: "commute_days_per_week", msg: "Commute days must be between 0 and 7."});
  }
  const mPm = document.getElementById("manual_pm25")?.value.trim() || "";
  if (mPm !== "" && !isNumInRange(mPm, 0, 1000)) {
    errors.push({id: "manual_pm25", msg: "Manual PM2.5 must be between 0 and 1000."});
  }
  return errors;
}

/**
 * Hide and clear error summary box.
 */
function hideErrorSummary() {
  const summary = document.getElementById("error-summary");
  const list = document.getElementById("error-list");
  if (summary) summary.classList.add("hidden");
  if (list) {
    while (list.firstChild) {
      list.removeChild(list.firstChild);
    }
  }
  document.querySelectorAll("[aria-invalid='true']").forEach(elem => {
    elem.removeAttribute("aria-invalid");
  });
}

/**
 * Display error summary and set focus.
 * @param {!Array<{id: string, msg: string}>} errors
 */
function showErrorSummary(errors) {
  const summary = document.getElementById("error-summary");
  const list = document.getElementById("error-list");
  if (!summary || !list) return;
  hideErrorSummary();
  errors.forEach(err => {
    const li = el("li");
    const link = el("a", err.msg, "underline hover:text-red-900 cursor-pointer");
    link.href = `#${err.id}`;
    link.addEventListener("click", e => {
      e.preventDefault();
      document.getElementById(err.id)?.focus();
    });
    li.appendChild(link);
    list.appendChild(li);
    const field = document.getElementById(err.id);
    if (field) field.setAttribute("aria-invalid", "true");
  });
  summary.classList.remove("hidden");
  summary.focus();
  announce("There are errors in the form. Please check the error list above.");
}

/**
 * Extract form values into the nested API payload schema.
 * @return {!Object}
 */
function buildPayloadFromForm() {
  const getVal = id => document.getElementById(id)?.value || "";
  const getCheck = id => Boolean(document.getElementById(id)?.checked);
  const mPm = getVal("manual_pm25").trim();
  return {
    city: getVal("city").trim(),
    household: {
      children: Number(getVal("children") || 0),
      elderly: Number(getVal("elderly") || 0),
      respiratory: getCheck("respiratory"),
      heart: getCheck("heart"),
      pregnant: getCheck("pregnant")
    },
    lifestyle: {
      heating: getVal("heating") || "none",
      cooking: getVal("cooking") || "lpg",
      has_purifier: getCheck("has_purifier"),
      smokers: getCheck("smokers"),
      commute_mode: getVal("commute_mode") || "car_petrol",
      commute_km_one_way: Number(getVal("commute_km_one_way") || 0),
      commute_days_per_week: Number(getVal("commute_days_per_week") || 0),
      room_area_sqm: Number(getVal("room_area_sqm") || 20),
      usual_outdoor_hour: Number(getVal("usual_outdoor_hour") || 8)
    },
    manual_pm25: mPm !== "" ? Number(mPm) : null,
    notes: getVal("notes")
  };
}

/**
 * Attach submit event handler to form.
 */
function initFormSubmit() {
  const form = document.getElementById("plan-form");
  if (!form) return;
  form.addEventListener("submit", e => {
    e.preventDefault();
    const errors = validateClientInputs();
    if (errors.length > 0) {
      showErrorSummary(errors);
      return;
    }
    hideErrorSummary();
    const submitBtn = document.getElementById("submit-btn");
    if (submitBtn) {
      submitBtn.setAttribute("disabled", "true");
      submitBtn.textContent = "Building plan...";
    }
    const payload = buildPayloadFromForm();
    saveSession("saans.inputs", payload);
    window.location.href = "/plan";
  });
}
