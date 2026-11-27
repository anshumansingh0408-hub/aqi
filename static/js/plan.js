/**
 * @fileoverview Plan page logic for Saans.
 * Renders tabbed interface (Today, Indoors, Commute, Explain, Ask).
 * Complies with strict accessibility, WAI-ARIA tabs, and DOM security.
 */

/* global el, api, describeError, loadSession, saveSession, announce, formatHour, ACTIVITY_LABELS, BAND_CLASSES */

document.addEventListener("DOMContentLoaded", () => {
  const inputs = loadSession("saans.inputs");
  if (!inputs || !inputs.city) {
    window.location.href = "/create";
    return;
  }

  // DOM elements
  const loadingEl = document.getElementById("plan-loading");
  const errorEl = document.getElementById("plan-error");
  const errorMsgEl = document.getElementById("plan-error-message");
  const retryBtn = document.getElementById("btn-plan-retry");
  const contentEl = document.getElementById("plan-content");

  // Tab buttons and panels
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  const panels = Array.from(document.querySelectorAll('[role="tabpanel"]'));

  // Tab switcher
  function switchTab(newTab) {
    tabs.forEach((tab) => {
      const isSelected = tab === newTab;
      tab.setAttribute("aria-selected", isSelected ? "true" : "false");
      tab.tabIndex = isSelected ? 0 : -1;
      if (isSelected) {
        tab.classList.add("border-primary", "text-primary");
        tab.classList.remove("border-transparent", "text-muted");
      } else {
        tab.classList.remove("border-primary", "text-primary");
        tab.classList.add("border-transparent", "text-muted");
      }
    });

    const targetPanelId = newTab.getAttribute("aria-controls");
    panels.forEach((panel) => {
      if (panel.id === targetPanelId) {
        panel.removeAttribute("hidden");
      } else {
        panel.setAttribute("hidden", "hidden");
      }
    });
    newTab.focus();
  }

  // Keyboard navigation for WAI-ARIA tablist
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => switchTab(tab));
    tab.addEventListener("keydown", (e) => {
      let targetIndex = null;
      if (e.key === "ArrowRight") {
        targetIndex = (index + 1) % tabs.length;
      } else if (e.key === "ArrowLeft") {
        targetIndex = (index - 1 + tabs.length) % tabs.length;
      } else if (e.key === "Home") {
        targetIndex = 0;
      } else if (e.key === "End") {
        targetIndex = tabs.length - 1;
      }
      if (targetIndex !== null) {
        e.preventDefault();
        switchTab(tabs[targetIndex]);
      }
    });
  });

  // Action button events
  document.getElementById("btn-print-plan")?.addEventListener("click", () => {
    window.print();
  });

  document.getElementById("btn-refresh-reading")?.addEventListener("click", () => {
    fetchPlan();
  });

  retryBtn?.addEventListener("click", () => {
    fetchPlan();
  });

  // Render Plan Data
  function renderPlan(data) {
    const advice = data.advice || {};
    const reading = data.reading || {};

    // Header & Meta
    const cityDisplay = document.getElementById("plan-city-display");
    if (cityDisplay) {
      cityDisplay.textContent = advice.location?.name || inputs.city;
    }

    const locMeta = document.getElementById("plan-location-meta");
    if (locMeta) {
      const loc = advice.location;
      if (loc) {
        const parts = [loc.name, loc.admin1, loc.country].filter(Boolean);
        locMeta.textContent = `Matched location: ${parts.join(", ")}`;
      } else {
        locMeta.textContent = "";
      }
    }

    const sourceText = document.getElementById("plan-source-text");
    if (sourceText) {
      if (reading.source === "live") {
        sourceText.textContent = `Live atmospheric model estimate (${reading.pm25.toFixed(1)} µg/m³) from Open-Meteo. Observed at ${reading.observed_at || "today"}. Model estimates can differ from ground-level monitors.`;
      } else {
        sourceText.textContent = `Manual reading entered (${reading.pm25.toFixed(1)} µg/m³). Hourly forecast is unavailable.`;
      }
      if (advice.limits && advice.limits.length) {
        sourceText.textContent += ` Note: ${advice.limits.join(" ")}`;
      }
    }

    const medicalNote = document.getElementById("plan-medical-note");
    if (medicalNote) {
      medicalNote.textContent = advice.medical_note || "These are general precautions, not medical advice.";
    }

    // Dynamic ambient tinting for gauge card
    const gaugeCard = document.getElementById("plan-gauge-card");
    if (gaugeCard && advice.air?.band) {
      const bandKey = advice.air.band.key || "moderate";
      gaugeCard.className = `saans-card p-6 border space-y-4 ambient-${bandKey}`;
    }

    // Render Today Tab
    renderToday(advice, reading);

    // Render Indoors Tab
    renderIndoors(advice);

    // Render Commute Tab
    renderCommute(advice);
  }

  function renderToday(advice, reading) {
    // Air Quality Gauge Card (Spectrum)
    const gaugeVal = document.getElementById("plan-gauge-val");
    if (gaugeVal) {
      gaugeVal.textContent = reading.pm25.toFixed(1);
    }
    const gaugeChip = document.getElementById("plan-gauge-chip");
    if (gaugeChip && advice.air?.band) {
      gaugeChip.textContent = advice.air.band.label || "Unknown";
      const bandClass = BAND_CLASSES[advice.air.band.key] || "band-moderate";
      gaugeChip.className = `band-chip ${bandClass}`;
    }
    const gaugePointer = document.getElementById("plan-spectrum-pointer");
    if (gaugePointer && typeof reading.pm25 === "number") {
      const pct = Math.min(Math.max((reading.pm25 / 300) * 100, 3), 97);
      gaugePointer.style.left = `${pct}%`;
    }

    // Dual-Anchor Fields (Outdoor vs Indoor)
    const dualOutdoorVal = document.getElementById("dual-outdoor-val");
    if (dualOutdoorVal) dualOutdoorVal.textContent = reading.pm25.toFixed(1);

    const dualOutdoorChip = document.getElementById("dual-outdoor-chip");
    if (dualOutdoorChip && advice.air?.band) {
      dualOutdoorChip.textContent = advice.air.band.label || "Unknown";
      const bClass = BAND_CLASSES[advice.air.band.key] || "band-moderate";
      dualOutdoorChip.className = `band-chip text-xs ${bClass}`;
    }

    const dualOutdoorSource = document.getElementById("dual-outdoor-source");
    if (dualOutdoorSource) {
      dualOutdoorSource.textContent = reading.source === "live" ? "Open-Meteo Model" : "Manual Sensor";
    }

    const dualOutdoorDesc = document.getElementById("dual-outdoor-desc");
    if (dualOutdoorDesc) {
      dualOutdoorDesc.textContent = advice.sensitivity?.sensitive
        ? "Elevated precautions for sensitive members"
        : "Standard daylight precautions apply";
    }

    const dualIndoorCadr = document.getElementById("dual-indoor-cadr");
    if (dualIndoorCadr && advice.purifier) {
      dualIndoorCadr.textContent = String(advice.purifier.min_cadr_m3h);
    }

    const dualIndoorWin = document.getElementById("dual-indoor-window");
    if (dualIndoorWin) {
      const vent = advice.guidance?.window_ventilation;
      if (vent && vent.allowed) {
        dualIndoorWin.textContent = "Airing: Allowed mid-day";
        dualIndoorWin.className = "text-xs font-semibold text-emerald-800 bg-emerald-50 px-2.5 py-1 rounded-full";
      } else {
        dualIndoorWin.textContent = "Windows: Keep closed";
        dualIndoorWin.className = "text-xs font-semibold text-amber-900 bg-amber-50 px-2.5 py-1 rounded-full";
      }
    }

    const dualIndoorDesc = document.getElementById("dual-indoor-desc");
    if (dualIndoorDesc && advice.purifier) {
      dualIndoorDesc.textContent = `Target 4 ACH for ${advice.purifier.room_area_sqm} m² living area`;
    }

    // Tile 1: PM2.5 & Band Chip
    const pm25Val = document.getElementById("tile-pm25-val");
    if (pm25Val) {
      pm25Val.textContent = reading.pm25.toFixed(1);
    }
    const pm25Chip = document.getElementById("tile-pm25-chip");
    if (pm25Chip && advice.air?.band) {
      pm25Chip.textContent = advice.air.band.label || "Unknown";
      const bandClass = BAND_CLASSES[advice.air.band.key] || "band-moderate";
      pm25Chip.className = `band-chip ${bandClass}`;
    }

    // Tile 2: Guidance Level
    const guidanceTitle = document.getElementById("tile-guidance-title");
    const guidanceSub = document.getElementById("tile-guidance-sub");
    if (guidanceTitle) {
      guidanceTitle.textContent = advice.sensitivity?.sensitive ? "Sensitive Care" : "General Population";
    }
    if (guidanceSub) {
      guidanceSub.textContent = advice.sensitivity?.groups?.length
        ? advice.sensitivity.groups.join(", ")
        : "Standard health precautions";
    }

    // Tile 3: Best window
    const bestWin = document.getElementById("tile-best-window");
    const bestWinSub = document.getElementById("tile-best-window-sub");
    if (bestWin && bestWinSub) {
      const exerciseWin = advice.windows?.outdoor_exercise;
      if (exerciseWin && typeof exerciseWin.hour === "number") {
        bestWin.textContent = `${formatHour(exerciseWin.hour)} - ${formatHour((exerciseWin.hour + 1) % 24)}`;
        bestWinSub.textContent = `Estimated avg: ${exerciseWin.avg_pm25.toFixed(1)} µg/m³`;
      } else {
        bestWin.textContent = "Unavailable";
        bestWinSub.textContent = "Requires live forecast";
      }
    }

    // Tile 4: Sensitive groups
    const sensGroups = document.getElementById("tile-sensitive-groups");
    if (sensGroups) {
      sensGroups.textContent = advice.sensitivity?.groups?.length
        ? advice.sensitivity.groups.join(", ")
        : "None identified";
    }

    // Activity Guidance Cards
    const actList = document.getElementById("activity-guidance-list");
    if (actList) {
      actList.textContent = "";
      const guidance = advice.guidance || {};
      const order = ["outdoor_exercise", "errands", "window_ventilation", "kids_outdoor_play"];
      order.forEach((key) => {
        const item = guidance[key];
        if (!item) return;

        let badgeText = "Fine";
        let badgeClass = "band-chip band-good";
        let borderClass = "border-l-4 border-l-emerald-500";
        if (!item.allowed) {
          badgeText = "Not advised";
          badgeClass = "band-chip band-severe";
          borderClass = "border-l-4 border-l-red-500";
        } else if (
          item.advice.toLowerCase().includes("care") ||
          item.advice.toLowerCase().includes("mask") ||
          item.advice.toLowerCase().includes("limit")
        ) {
          badgeText = "With care";
          badgeClass = "band-chip band-moderate";
          borderClass = "border-l-4 border-l-amber-500";
        }

        const card = el("div", null, `p-5 rounded-xl border border-border bg-white shadow-xs flex flex-col justify-between ${borderClass}`);
        const topRow = el("div", null, "flex items-center justify-between mb-2");
        const actName = el("h3", ACTIVITY_LABELS[key] || key, "font-bold text-ink text-base");

        const badge = el("span", badgeText, badgeClass);
        topRow.appendChild(actName);
        topRow.appendChild(badge);

        const desc = el("p", item.advice, "text-sm text-muted leading-relaxed");
        card.appendChild(topRow);
        card.appendChild(desc);
        actList.appendChild(card);
      });
    }

    // Best Times Today Table & Hourly Scroller
    const bestTimesContainer = document.getElementById("best-times-container");
    if (bestTimesContainer) {
      bestTimesContainer.textContent = "";
      const windows = advice.windows || {};
      const hasAny = windows.outdoor_exercise || windows.errands || windows.window_ventilation;
      if (hasAny) {
        // Horizontal timeline scroller
        if (windows.outdoor_exercise && typeof windows.outdoor_exercise.hour === "number") {
          const bestHr = windows.outdoor_exercise.hour;
          const ventHr = windows.window_ventilation?.hour;
          const isVentAllowed = windows.window_ventilation?.allowed;

          const scrollerWrap = el("div", null, "mb-6 space-y-2");
          const scrollerLabel = el("div", null, "flex justify-between items-center text-xs font-semibold text-muted");
          scrollerLabel.appendChild(el("span", "Daylight Hours Timeline (6:00 - 20:00)"));
          scrollerLabel.appendChild(el("span", "Scroll horizontally →", "text-primary text-[11px] font-medium"));
          scrollerWrap.appendChild(scrollerLabel);

          const scroller = el("div", null, "timeline-scroller py-2");
          for (let h = 6; h <= 20; h++) {
            const isBest = (h === bestHr);
            const isVent = (h === ventHr && isVentAllowed);
            const cardClass = (isBest || isVent)
              ? "timeline-card timeline-card-highlight shadow-sm"
              : "timeline-card hover:border-primary/40";
            const card = el("div", null, cardClass);
            card.appendChild(el("p", formatHour(h), "font-bold text-xs text-ink"));

            if (isBest) {
              card.appendChild(el("span", "Best Time", "inline-block text-[10px] font-bold text-emerald-800 bg-emerald-100 px-1.5 py-0.5 rounded-full my-1.5"));
              card.appendChild(el("p", `${windows.outdoor_exercise.avg_pm25.toFixed(0)} µg/m³`, "text-xs font-semibold text-emerald-700"));
            } else if (isVent) {
              card.appendChild(el("span", "Airing", "inline-block text-[10px] font-bold text-sky-800 bg-sky-100 px-1.5 py-0.5 rounded-full my-1.5"));
              card.appendChild(el("p", "Ventilate", "text-[11px] text-sky-700"));
            } else {
              card.appendChild(el("span", "Daylight", "inline-block text-[10px] text-muted bg-surface px-1.5 py-0.5 rounded-full my-1.5"));
              card.appendChild(el("p", "Inversion", "text-[11px] text-muted"));
            }
            scroller.appendChild(card);
          }
          scrollerWrap.appendChild(scroller);
          bestTimesContainer.appendChild(scrollerWrap);
        }

        const tableWrap = el("div", null, "table-container");
        const table = el("table", null, "w-full text-left text-sm border-collapse");
        const thead = el("thead", null, "border-b border-border text-muted bg-surface/50");
        const hRow = el("tr");
        hRow.appendChild(el("th", "Activity", "py-2.5 px-3 font-semibold"));
        hRow.appendChild(el("th", "Recommended Window", "py-2.5 px-3 font-semibold"));
        hRow.appendChild(el("th", "Estimated Average PM2.5", "py-2.5 px-3 font-semibold"));
        thead.appendChild(hRow);
        table.appendChild(thead);

        const tbody = el("tbody", null, "divide-y divide-border");
        const acts = [
          { key: "outdoor_exercise", label: "Outdoor exercise" },
          { key: "errands", label: "Errands" },
          { key: "window_ventilation", label: "Airing the home" }
        ];

        acts.forEach((act) => {
          const w = windows[act.key];
          const row = el("tr");
          row.appendChild(el("td", act.label, "py-3 px-3 font-medium text-ink"));
          if (w && typeof w.hour === "number") {
            row.appendChild(el("td", `${formatHour(w.hour)} - ${formatHour((w.hour + 1) % 24)}`, "py-3 px-3 text-ink font-semibold"));
            row.appendChild(el("td", `${w.avg_pm25.toFixed(1)} µg/m³`, "py-3 px-3 text-muted"));
          } else {
            row.appendChild(el("td", "No safe window found", "py-3 px-3 text-muted italic"));
            row.appendChild(el("td", "--", "py-3 px-3 text-muted"));
          }
          tbody.appendChild(row);
        });
        table.appendChild(tbody);
        tableWrap.appendChild(table);
        bestTimesContainer.appendChild(tableWrap);
      } else {
        const notice = el("div", null, "p-4 bg-surface rounded-xl border border-border text-sm text-muted");
        notice.appendChild(el("p", "Hourly forecast is not available for manual PM2.5 entries or when atmospheric forecast data is missing."));
        bestTimesContainer.appendChild(notice);
      }
    }

    // Usual vs Best Visual Comparison
    const usualContainer = document.getElementById("usual-vs-best-container");
    if (usualContainer) {
      usualContainer.textContent = "";
      const uvb = advice.usual_vs_best;
      if (uvb) {
        const card = el("div", null, "p-6 bg-gradient-to-r from-surface to-white rounded-xl border border-border space-y-5");
        const topRow = el("div", null, "flex flex-col sm:flex-row sm:items-center justify-between gap-3");
        const titleCol = el("div");
        titleCol.appendChild(el("h3", "Exposure Reduction by Timing", "font-bold text-ink text-base"));
        titleCol.appendChild(el("p", "Shift outdoor tasks to the daylight inversion window.", "text-xs text-muted"));
        const badge = el("span", `${uvb.reduction_pct.toFixed(0)}% lower exposure`, "band-chip band-good self-start sm:self-center");
        topRow.appendChild(titleCol);
        topRow.appendChild(badge);
        card.appendChild(topRow);

        // Visual bars
        const maxVal = Math.max(uvb.usual_pm25, uvb.best_pm25, 10);
        const bars = el("div", null, "space-y-3 pt-2");

        // Usual bar
        const usualRow = el("div", null, "space-y-1");
        const usualMeta = el("div", null, "flex justify-between text-xs font-medium");
        usualMeta.appendChild(el("span", `Your Usual Schedule (${formatHour(uvb.usual_hour)})`, "text-muted"));
        usualMeta.appendChild(el("span", `${uvb.usual_pm25.toFixed(1)} µg/m³`, "text-ink font-bold"));
        const usualTrack = el("div", null, "bar-track");
        const usualFill = el("div", null, "bar-fill bar-fill-usual");
        usualFill.style.width = `${Math.min(100, (uvb.usual_pm25 / maxVal) * 100)}%`;
        usualTrack.appendChild(usualFill);
        usualRow.appendChild(usualMeta);
        usualRow.appendChild(usualTrack);
        bars.appendChild(usualRow);

        // Best bar
        const bestRow = el("div", null, "space-y-1");
        const bestMeta = el("div", null, "flex justify-between text-xs font-medium");
        bestMeta.appendChild(el("span", `Cleanest Window (${formatHour(uvb.best_hour)})`, "text-primary font-semibold"));
        bestMeta.appendChild(el("span", `${uvb.best_pm25.toFixed(1)} µg/m³`, "text-primary font-bold"));
        const bestTrack = el("div", null, "bar-track");
        const bestFill = el("div", null, "bar-fill bar-fill-best");
        bestFill.style.width = `${Math.min(100, (uvb.best_pm25 / maxVal) * 100)}%`;
        bestTrack.appendChild(bestFill);
        bestRow.appendChild(bestMeta);
        bestRow.appendChild(bestTrack);
        bars.appendChild(bestRow);

        card.appendChild(bars);
        card.appendChild(el("p", uvb.note, "text-xs text-muted pt-2 border-t border-border"));
        usualContainer.appendChild(card);
      } else {
        const notice = el("p", "Schedule comparison requires an active 24-hour forecast.", "text-sm text-muted");
        usualContainer.appendChild(notice);
      }
    }
  }

  function renderIndoors(advice) {
    const checklistItems = document.getElementById("indoor-checklist-items");
    if (checklistItems) {
      checklistItems.textContent = "";
      const list = advice.indoor_checklist || [];
      list.forEach((item) => {
        const row = el("div", null, "p-4 rounded-xl border border-border bg-surface flex flex-col sm:flex-row sm:items-start justify-between gap-3");
        const left = el("div");
        left.appendChild(el("h3", item.action, "font-bold text-ink text-base mb-1"));
        left.appendChild(el("p", item.why, "text-sm text-muted leading-relaxed"));

        const badgeClass = item.effort === "easy" ? "bg-emerald-100 text-emerald-800" : "bg-sky-100 text-sky-800";
        const badge = el("span", item.effort === "easy" ? "Easy" : "Moderate", `text-xs px-2.5 py-1 rounded-full font-semibold self-start sm:self-center ${badgeClass}`);

        row.appendChild(left);
        row.appendChild(badge);
        checklistItems.appendChild(row);
      });
    }

    const purifierContainer = document.getElementById("purifier-details-container");
    if (purifierContainer && advice.purifier) {
      purifierContainer.textContent = "";
      const p = advice.purifier;
      const grid = el("div", null, "grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4");

      const roomCard = el("div", null, "p-5 bg-surface rounded-xl border border-border");
      roomCard.appendChild(el("span", "Room Dimensions", "text-xs font-semibold uppercase tracking-wider text-muted block mb-1"));
      roomCard.appendChild(el("p", `${p.room_area_sqm} m² (${p.volume_m3.toFixed(1)} m³ volume)`, "text-2xl font-bold text-ink font-serif"));
      grid.appendChild(roomCard);

      const cadrCard = el("div", null, "p-5 bg-surface rounded-xl border border-border");
      cadrCard.appendChild(el("span", "Recommended Minimum CADR", "text-xs font-semibold uppercase tracking-wider text-muted block mb-1"));
      cadrCard.appendChild(el("p", `${p.min_cadr_m3h} m³/h (${p.min_cadr_cfm} CFM)`, "text-2xl font-bold text-ink font-serif"));
      grid.appendChild(cadrCard);

      purifierContainer.appendChild(grid);
      if (p.assumption) {
        purifierContainer.appendChild(el("p", p.assumption, "text-xs text-muted"));
      }
    }
  }

  function renderCommute(advice) {
    const commute = advice.commute || {};
    const currKg = document.getElementById("commute-current-kg");
    if (currKg) {
      currKg.textContent = commute.current_monthly_kg !== undefined ? commute.current_monthly_kg.toFixed(1) : "--";
    }

    const tbody = document.getElementById("commute-alternatives-body");
    if (tbody) {
      tbody.textContent = "";
      const alts = commute.alternatives || [];
      const baseVal = Math.max(commute.current_monthly_kg || 1, 1);

      alts.forEach((alt) => {
        const row = el("tr");
        row.appendChild(el("td", alt.mode, "py-3 px-3 font-medium text-ink"));
        row.appendChild(el("td", `${alt.monthly_kg.toFixed(1)} kg`, "py-3 px-3 text-ink font-semibold"));

        const savingCell = el("td", null, "py-3 px-3");
        if (alt.saving_kg > 0) {
          const chip = el("span", `${alt.saving_kg.toFixed(1)} kg saved`, "band-chip band-good text-xs");
          savingCell.appendChild(chip);
        } else {
          savingCell.textContent = "0.0 kg";
        }
        row.appendChild(savingCell);

        // Visual footprint comparison bar
        const compCell = el("td", null, "py-3 px-3 min-w-[120px]");
        const relPct = Math.min(100, Math.max(0, (alt.monthly_kg / baseVal) * 100));
        const track = el("div", null, "bar-track h-2.5 bg-border/60");
        const fill = el("div", null, "bar-fill " + (relPct < 50 ? "bar-fill-best" : "bar-fill-usual"));
        fill.style.width = `${relPct}%`;
        track.appendChild(fill);
        compCell.appendChild(track);
        row.appendChild(compCell);

        row.appendChild(el("td", alt.assumption, "py-3 px-3 text-xs text-muted"));
        tbody.appendChild(row);
      });
    }

    const climateNote = document.getElementById("commute-climate-note");
    if (climateNote) {
      climateNote.textContent = advice.climate_note || "";
    }
  }

  // Fetch plan API
  async function fetchPlan() {
    loadingEl?.classList.remove("hidden");
    contentEl?.classList.add("hidden");
    errorEl?.classList.add("hidden");
    retryBtn?.classList.add("hidden");

    const result = await api("/api/plan", inputs);
    loadingEl?.classList.add("hidden");

    if (!result.ok) {
      if (result.data?.manual_hint) {
        saveSession("saans.notice", result.data.error || "City lookup failed. Enter PM2.5 manually.");
        window.location.href = "/create?manual=1";
        return;
      }
      errorEl?.classList.remove("hidden");
      if (errorMsgEl) {
        errorMsgEl.textContent = describeError(result);
      }
      if (result.status === 429) {
        retryBtn?.classList.remove("hidden");
      }
      announce("Failed to load air plan. Please review errors.");
      return;
    }

    contentEl?.classList.remove("hidden");
    renderPlan(result.data);
    announce("Air plan loaded successfully.");
  }

  // Explain Feature
  const explainBtn = document.getElementById("btn-explain");
  const explainLoading = document.getElementById("explain-loading");
  const explainOutput = document.getElementById("explain-output");

  explainBtn?.addEventListener("click", async () => {
    explainBtn.disabled = true;
    explainLoading?.classList.remove("hidden");
    explainOutput?.classList.add("hidden");

    const result = await api("/api/explain", inputs);
    explainLoading?.classList.add("hidden");
    explainBtn.disabled = false;

    if (!result.ok) {
      alert(describeError(result));
      return;
    }

    const exp = result.data?.explanation || {};
    explainOutput?.classList.remove("hidden");

    // Warnings
    const fallbackAlert = document.getElementById("explain-fallback-alert");
    if (fallbackAlert) {
      if (exp.source === "fallback") {
        fallbackAlert.classList.remove("hidden");
      } else {
        fallbackAlert.classList.add("hidden");
      }
    }

    const groundingAlert = document.getElementById("explain-grounding-alert");
    const groundingText = document.getElementById("explain-grounding-text");
    if (groundingAlert && groundingText) {
      if (exp.grounding_removed && exp.grounding_removed > 0) {
        groundingText.textContent = `Removed ${exp.grounding_removed} ungrounded numeric claim(s) from AI output.`;
        groundingAlert.classList.remove("hidden");
      } else {
        groundingAlert.classList.add("hidden");
      }
    }

    // Populate Structured Fields
    const summaryEl = document.getElementById("explain-summary");
    if (summaryEl) summaryEl.textContent = exp.summary || "";

    // Daily routine: array of {time_of_day, suggestion, reason}
    const routineList = document.getElementById("explain-daily-routine");
    if (routineList) {
      routineList.textContent = "";
      (exp.daily_routine || []).forEach((item) => {
        const li = el("li", null, "mb-2 text-ink");
        if (typeof item === "object" && item !== null) {
          const timeBadge = el("span", `[${item.time_of_day || "Schedule"}] `, "font-semibold text-primary");
          const sugg = el("span", item.suggestion || "");
          li.appendChild(timeBadge);
          li.appendChild(sugg);
          if (item.reason) {
            const r = el("span", ` — ${item.reason}`, "text-xs text-muted block mt-0.5");
            li.appendChild(r);
          }
        } else {
          li.textContent = String(item);
        }
        routineList.appendChild(li);
      });
    }

    // Indoor tips: array of {action, impact}
    const indoorList = document.getElementById("explain-indoor-tips");
    if (indoorList) {
      indoorList.textContent = "";
      (exp.indoor_tips || []).forEach((item) => {
        const li = el("li", null, "mb-2 text-ink");
        if (typeof item === "object" && item !== null) {
          const act = el("span", item.action || "Action", "font-semibold text-ink");
          li.appendChild(act);
          if (item.impact) {
            const imp = el("span", ` — ${item.impact}`, "text-xs text-muted block mt-0.5");
            li.appendChild(imp);
          }
        } else {
          li.textContent = String(item);
        }
        indoorList.appendChild(li);
      });
    }

    const fillList = (id, items) => {
      const listEl = document.getElementById(id);
      if (listEl) {
        listEl.textContent = "";
        (items || []).forEach((txt) => {
          listEl.appendChild(el("li", txt));
        });
      }
    };

    fillList("explain-impacts", exp.impact_statements);
    fillList("explain-community", exp.community_actions);
    fillList("explain-watchouts", exp.watch_outs);

    const commuteHead = document.getElementById("explain-commute-headline");
    const commuteText = document.getElementById("explain-commute-text");
    if (commuteHead) commuteHead.textContent = exp.commute_swap?.headline || "Commute Swap";
    if (commuteText) commuteText.textContent = exp.commute_swap?.explanation || "";

    const disclaimerEl = document.getElementById("explain-disclaimer");
    if (disclaimerEl) disclaimerEl.textContent = result.data?.disclaimer || "";

    announce("Plain language explanation generated.");
  });

  // Ask Feature
  const askForm = document.getElementById("ask-form");
  const askInput = document.getElementById("ask-input");
  const askCharCount = document.getElementById("ask-char-count");
  const askBtn = document.getElementById("btn-ask");
  const askSpinner = document.getElementById("ask-spinner");
  const answersStream = document.getElementById("ask-answers-stream");
  const askEmptyNotice = document.getElementById("ask-empty-notice");

  askInput?.addEventListener("input", () => {
    if (askCharCount) {
      askCharCount.textContent = `${askInput.value.length}/300`;
    }
  });

  document.querySelectorAll(".btn-sample-q").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (askInput) {
        askInput.value = btn.textContent.trim();
        if (askCharCount) {
          askCharCount.textContent = `${askInput.value.length}/300`;
        }
        askInput.focus();
      }
    });
  });

  askForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = (askInput?.value || "").trim();
    if (!q) return;

    if (askBtn) askBtn.disabled = true;
    askSpinner?.classList.remove("hidden");

    const payload = Object.assign({}, inputs, { question: q });
    const result = await api("/api/ask", payload);

    if (askBtn) askBtn.disabled = false;
    askSpinner?.classList.add("hidden");

    if (!result.ok) {
      alert(describeError(result));
      return;
    }

    askEmptyNotice?.classList.add("hidden");

    // Prepend Q&A Card with Chat Bubble styling
    const qaCard = el("div", null, "p-5 rounded-2xl border border-border bg-white shadow-2xs space-y-4");

    // User question bubble
    const userBubble = el("div", null, "chat-bubble-user p-4 space-y-1");
    const userMeta = el("div", null, "flex items-center gap-1.5 text-xs font-bold text-muted uppercase tracking-wider");
    userMeta.appendChild(el("span", "Your Question"));
    userBubble.appendChild(userMeta);
    userBubble.appendChild(el("p", q, "text-sm font-semibold text-ink"));
    qaCard.appendChild(userBubble);

    // AI answer bubble
    const aiBubble = el("div", null, "chat-bubble-ai p-4 space-y-1.5");
    const aiMeta = el("div", null, "flex items-center justify-between text-xs text-primary font-bold");
    aiMeta.appendChild(el("span", "Saans Assistant"));
    aiMeta.appendChild(el("span", result.data.source === "fallback" ? "Rule Engine Verified" : "Plan Verified", "text-[11px] font-medium text-muted"));
    aiBubble.appendChild(aiMeta);
    aiBubble.appendChild(el("p", result.data.answer || "No response.", "text-sm text-ink leading-relaxed"));
    qaCard.appendChild(aiBubble);

    const footer = el("div", null, "pt-1 flex items-center justify-between text-[11px] text-muted");
    footer.appendChild(el("span", "Strictly grounded in your computed plan"));
    footer.appendChild(el("span", "General precaution, not medical advice"));
    qaCard.appendChild(footer);

    if (answersStream) {
      answersStream.insertBefore(qaCard, answersStream.firstChild);
    }

    if (askInput) {
      askInput.value = "";
      if (askCharCount) {
        askCharCount.textContent = "0/300";
      }
    }

    announce("Answer received.");
  });

  // Initial load
  fetchPlan();
});
