"use strict";

const $ = (id) => document.getElementById(id);
const state = { lat: null, lon: null, marker: null, plan: null, charts: {}, options: null };

// ---------- map ----------
const map = L.map("map", { scrollWheelZoom: false }).setView([9.0, 39.5], 6);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

function setLocation(lat, lon, zoom) {
  state.lat = Math.round(lat * 10000) / 10000;
  state.lon = Math.round(lon * 10000) / 10000;
  if (state.marker) state.marker.setLatLng([lat, lon]);
  else state.marker = L.marker([lat, lon]).addTo(map);
  if (zoom) map.setView([lat, lon], zoom);
  $("coords-text").textContent = `Field: ${state.lat.toFixed(4)}, ${state.lon.toFixed(4)}`;
}
map.on("click", (e) => setLocation(e.latlng.lat, e.latlng.lng));

$("locate").addEventListener("click", () => {
  if (!navigator.geolocation) return showFormError("This browser can't share its location.");
  navigator.geolocation.getCurrentPosition(
    (pos) => setLocation(pos.coords.latitude, pos.coords.longitude, 12),
    () => showFormError("Location permission was refused. Tap the map instead."),
  );
});

// ---------- form ----------
function fillSelect(select, items, label = (i) => i.name) {
  select.innerHTML = "";
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = label(item);
    select.appendChild(opt);
  }
}

function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function syncPerennial() {
  const crop = state.options.crops.find((c) => c.id === $("crop").value);
  $("planting-label").hidden = crop.perennial;
}

async function loadOptions() {
  const res = await fetch("/api/options");
  const options = await res.json();
  state.options = options;
  fillSelect($("crop"), options.crops);
  fillSelect($("soil"), options.soils);
  fillSelect($("method"), options.methods, (m) => `${m.name} (${Math.round(m.efficiency * 100)}% efficient)`);
  fillSelect($("language"), options.languages);
  $("planting_date").max = isoDaysAgo(0);
  $("last_wet_date").max = isoDaysAgo(0);
  $("crop").addEventListener("change", syncPerennial);
  syncPerennial();
}

function showFormError(message) {
  $("form-error").textContent = message;
  $("form-error").hidden = !message;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showFormError("");
  if (state.lat === null) return showFormError("Tap the map to place your field first.");
  const crop = state.options.crops.find((c) => c.id === $("crop").value);
  if (!crop.perennial && !$("planting_date").value) return showFormError("Enter the planting date.");

  const body = {
    lat: state.lat,
    lon: state.lon,
    crop: crop.id,
    soil: $("soil").value,
    method: $("method").value,
    planting_date: crop.perennial ? null : $("planting_date").value,
    last_wet_date: $("last_wet_date").value || null,
  };
  const button = $("submit");
  button.disabled = true;
  button.textContent = "Fetching weather…";
  try {
    const res = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) return showFormError(data.error || "Something went wrong.");
    state.plan = data;
    render(data);
    if (window.matchMedia("(max-width: 860px)").matches) $("results").scrollIntoView({ behavior: "smooth" });
  } catch {
    showFormError("Could not reach the server. Is it still running?");
  } finally {
    button.disabled = false;
    button.textContent = "Get my 7-day plan";
  }
});

// ---------- rendering ----------
const fmtDay = (iso, opts = { weekday: "short", day: "numeric", month: "short" }) =>
  new Date(iso + "T00:00:00").toLocaleDateString(undefined, opts);
const num = (v, d = 1) => (v === null || v === undefined ? "–" : Number(v).toFixed(d));
const litres = (v) => Math.round(v).toLocaleString();

function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

function render(plan) {
  $("empty").hidden = true;
  $("output").hidden = false;
  renderHeadline(plan);
  renderWarnings(plan.warnings);
  renderStats(plan);
  renderBalanceChart(plan);
  renderTable(plan);
  renderClimate(plan.climate);
  resetAi(plan);
}

function renderHeadline(plan) {
  const s = plan.summary;
  const box = $("headline");
  box.innerHTML = "";
  box.classList.toggle("ok", !s.irrigation_events.length);
  if (!s.irrigation_events.length) {
    box.append(
      el("p", { class: "big" }, "No irrigation needed in the next 7 days"),
      el("p", { class: "small" }, `Forecast rain and stored soil water cover the ${plan.inputs.crop_name.toLowerCase()} this week.`),
    );
    return;
  }
  const first = s.irrigation_events[0];
  const when = s.irrigate_today ? "today" : fmtDay(first.date, { weekday: "long", day: "numeric", month: "long" });
  box.append(
    el("p", { class: "big" }, `Irrigate ${when}: apply ${num(first.gross_mm)} mm`),
    el("p", { class: "small" },
      `That is about ${litres(first.litres_per_ha)} litres per hectare with ${plan.inputs.method_name.toLowerCase()} ` +
      `(${num(first.net_mm)} mm reaches the roots). ` +
      (s.irrigation_events.length > 1
        ? `${s.irrigation_events.length} waterings this week, ${num(s.irrigation_gross_mm)} mm in total.`
        : "One watering this week.")),
  );
}

function renderWarnings(warnings) {
  const list = $("warnings");
  list.innerHTML = "";
  for (const w of warnings) list.appendChild(el("li", {}, w));
}

function renderStats(plan) {
  const s = plan.summary;
  const stats = [
    ["Crop water use, 7 days", `${num(s.week_crop_water_use_mm)} mm`, `Reference ET₀ ${num(s.week_et0_mm)} mm`],
    ["Rain forecast, 7 days", `${num(s.week_rain_mm)} mm`, `${num(s.week_effective_rain_mm)} mm useful to the crop`],
    ["Soil water used so far", `${num(s.soil_depletion_start_of_today_mm)} mm`, `Water at ${num(s.raw_mm)} mm · empty at ${num(s.taw_mm)} mm`],
    ["Crop stage", s.stage ? s.stage[0].toUpperCase() + s.stage.slice(1) : "–",
      `Kc ${num(s.kc_today, 2)} · roots ${num(s.root_depth_m, 2)} m` + (s.days_after_planting !== null ? ` · day ${s.days_after_planting}` : "")],
  ];
  const box = $("stats");
  box.innerHTML = "";
  for (const [label, value, note] of stats) {
    const card = el("div", { class: "stat" });
    card.append(el("div", { class: "label" }, label), el("div", { class: "value" }, value), el("div", { class: "note" }, note));
    box.appendChild(card);
  }
}

function renderBalanceChart(plan) {
  const days = plan.days.filter((d) => d.stage);
  const labels = days.map((d) => fmtDay(d.date, { day: "numeric", month: "short" }) + (d.date === plan.summary.today ? " (today)" : ""));
  state.charts.balance?.destroy();
  state.charts.balance = new Chart($("balance-chart"), {
    data: {
      labels,
      datasets: [
        { type: "bar", label: "Crop water use (mm)", data: days.map((d) => d.etc), backgroundColor: "#c08a52", yAxisID: "y" },
        { type: "bar", label: "Rain (mm)", data: days.map((d) => d.rain), backgroundColor: "#7fb3e0", yAxisID: "y" },
        { type: "line", label: "Soil water used (mm)", data: days.map((d) => d.depletion_before_irrigation), borderColor: "#155c39",
          tension: 0.2, yAxisID: "y2",
          // Irrigation days get a large blue point: the soil is refilled after that day.
          pointRadius: days.map((d) => (d.irrigation_net ? 7 : 2)),
          pointBackgroundColor: days.map((d) => (d.irrigation_net ? "#1f6fb2" : "#155c39")),
          pointBorderColor: days.map((d) => (d.irrigation_net ? "#1f6fb2" : "#155c39")),
          segment: { borderDash: (ctx) => (days[ctx.p1DataIndex]?.forecast ? [5, 4] : undefined) } },
        { type: "line", label: "Water before this (RAW)", data: days.map((d) => d.raw), borderColor: "#b42318",
          borderDash: [3, 3], pointRadius: 0, borderWidth: 1.5, yAxisID: "y2" },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            footer: (items) => {
              const d = days[items[0].dataIndex];
              return d.irrigation_net ? `Irrigate: ${num(d.irrigation_gross)} mm applied (${num(d.irrigation_net)} mm to the roots)` : "";
            },
          },
        },
      },
      scales: {
        y: { position: "left", title: { display: true, text: "mm per day" }, beginAtZero: true },
        y2: { position: "right", reverse: true, beginAtZero: true, title: { display: true, text: "soil water used (mm)" },
          grid: { drawOnChartArea: false } },
        x: { ticks: { maxRotation: 60, autoSkip: true, font: { size: 10 } } },
      },
    },
  });
}

function renderTable(plan) {
  const table = $("days-table");
  table.innerHTML = "";
  const head = el("tr");
  for (const h of ["Date", "Stage", "ET₀", "Kc", "Crop use", "Rain", "Soil water used", "Irrigate (applied)", "Litres/ha"]) head.appendChild(el("th", {}, h));
  const thead = el("thead");
  thead.appendChild(head);
  const tbody = el("tbody");
  for (const d of plan.days) {
    const row = el("tr", { class: d.date === plan.summary.today ? "today" : d.forecast ? "" : "past" });
    const cells = [
      fmtDay(d.date) + (d.date === plan.summary.today ? " · today" : ""),
      d.stage || "not in field",
      num(d.et0), num(d.kc, 2), num(d.etc), num(d.rain),
      d.depletion_before_irrigation === undefined || d.depletion_before_irrigation === null ? "–" : `${num(d.depletion_before_irrigation)} / ${num(d.raw)}`,
      d.irrigation_gross ? `${num(d.irrigation_gross)} mm` : "",
      d.irrigation_gross ? litres(d.irrigation_gross * 10000) : "",
    ];
    cells.forEach((c, i) => row.appendChild(el("td", i >= 7 && c ? { class: "irrigate" } : {}, c)));
    tbody.appendChild(row);
  }
  table.append(thead, tbody);
}

function renderClimate(climate) {
  const panel = $("climate-panel");
  panel.hidden = !climate;
  state.charts.climate?.destroy();
  if (!climate) return;
  const m = climate.this_month;
  $("climate-text").textContent =
    `NASA POWER (${climate.period}): about ${climate.annual_rain_mm} mm of rain a year here. ` +
    `${m.month} normally gets ${m.rain_mm} mm with a mean temperature of ${m.temp_c} °C.`;
  state.charts.climate = new Chart($("climate-chart"), {
    type: "bar",
    data: {
      labels: climate.months.map((x) => x.month),
      datasets: [{
        label: "Normal rainfall (mm/month)",
        data: climate.months.map((x) => x.rain_mm),
        backgroundColor: climate.months.map((x) => (x.month === m.month ? "#1f6fb2" : "#a9c9e6")),
      }],
    },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, title: { display: true, text: "mm" } } } },
  });
}

// ---------- AI explanation ----------
function resetAi(plan) {
  $("ai-text").innerHTML = "";
  const available = plan.ai_available;
  $("explain").disabled = !available;
  $("language").disabled = !available;
  $("ai-note").textContent = available
    ? "AI turns the numbers above into simple advice. It explains the plan; it does not change it."
    : "AI explanations are off: add an ANTHROPIC_API_KEY to the .env file and restart the server. The plan above does not need it.";
}

function renderAiText(text) {
  // Plain text from the model, rendered safely: "Heading:" lines and "- " bullets.
  const box = $("ai-text");
  box.innerHTML = "";
  let list = null;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) { list = null; continue; }
    if (line.startsWith("- ")) {
      if (!list) { list = el("ul"); box.appendChild(list); }
      list.appendChild(el("li", {}, line.slice(2)));
    } else if (line.endsWith(":") && line.length < 60) {
      list = null;
      box.appendChild(el("h3", {}, line.slice(0, -1)));
    } else {
      list = null;
      box.appendChild(el("p", {}, line));
    }
  }
}

$("explain").addEventListener("click", async () => {
  if (!state.plan) return;
  const button = $("explain");
  button.disabled = true;
  button.textContent = "Writing…";
  $("ai-text").innerHTML = "";
  try {
    const res = await fetch("/api/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: state.plan.plan_id, language: $("language").value }),
    });
    const data = await res.json();
    if (!res.ok) {
      $("ai-text").appendChild(el("p", { class: "error" }, data.error || "The explanation failed."));
      return;
    }
    renderAiText(data.text);
    $("ai-text").appendChild(el("p", { class: "meta" }, `Written by ${data.model} in ${data.language}. Check advice against conditions in the field.`));
  } catch {
    $("ai-text").appendChild(el("p", { class: "error" }, "Could not reach the server."));
  } finally {
    button.disabled = false;
    button.textContent = "Explain this plan";
  }
});

loadOptions().catch(() => showFormError("Could not load the crop list. Is the server running?"));
