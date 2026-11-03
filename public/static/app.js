"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  lat: null, lon: null, place: null, marker: null, plan: null, options: null,
  example: false, site: null, siteKey: null, charts: {}, maps: {},
};

// Shown on first visit so every page has real content before the visitor picks a field.
const EXAMPLE = { lat: 8.656, lon: 39.035, crop: "wheat", soil: "clay", daysSincePlanting: 55, place: "Bishoftu" };
const WEEK_CHIPS = [2, 4, 6, 8, 12, 16];

// ---------- helpers ----------
function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}
const num = (v, d = 1) => (v === null || v === undefined ? "–" : Number(v).toFixed(d));
const whole = (v) => Math.round(v).toLocaleString(locale());
const fmtDay = (iso, opts = { weekday: "short", day: "numeric", month: "short" }) =>
  new Date(iso + "T00:00:00").toLocaleDateString(locale(), opts);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}
const stageName = (s) => (s ? t(`stage.${s}`) : "–");

// ---------- pages ----------
const PAGES = ["home", "plan", "weather", "field", "guide"];
function showPage() {
  const page = PAGES.includes(location.hash.slice(1)) ? location.hash.slice(1) : "home";
  for (const p of PAGES) $(`page-${p}`).hidden = p !== page;
  for (const a of document.querySelectorAll(".tabs a")) {
    if (a.dataset.page === page) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  if (page === "plan") ensureMainMap();
  if (page === "field") renderField();
  if (page === "weather") renderWeather();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", showPage);

// ---------- theme and language ----------
function applyThemeButton() {
  const dark = document.documentElement.dataset.theme === "dark";
  $("theme-btn").setAttribute("aria-pressed", String(dark));
  $("theme-btn").querySelector(".icon").textContent = dark ? "☀" : "☾";
  $("theme-label").textContent = dark ? t("ui.theme_light") : t("ui.theme_dark");
  $("theme-btn").title = $("theme-label").textContent;
}
$("theme-btn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("ia-theme", next); } catch { /* private mode */ }
  applyThemeButton();
  rerenderAll();
});

function applyLanguage(lang) {
  setLanguage(lang);
  // The button shows the language you can switch to, like Addis Eats.
  $("lang-btn").textContent = currentLang === "am" ? "EN" : "አማ";
  applyThemeButton();
  if (state.options) fillOptions();
  renderChips();
  rerenderAll();
}
$("lang-btn").addEventListener("click", () => applyLanguage(currentLang === "am" ? "en" : "am"));

// Hero search: go to My plan and look the place up there.
$("hero-search").addEventListener("submit", (e) => {
  e.preventDefault();
  $("search-q").value = $("hero-q").value;
  location.hash = "#plan";
  setTimeout(() => $("search-form").requestSubmit(), 80);
});

function rerenderAll() {
  if (state.plan) renderPlan(state.plan);
  renderCoords();
  const page = location.hash.slice(1);
  if (page === "weather") renderWeather();
  if (page === "field") renderField();
}

// ---------- maps ----------
function tiles() {
  return L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; OpenStreetMap" });
}
function ensureMainMap() {
  if (!state.maps.main) {
    state.maps.main = L.map("map", { scrollWheelZoom: false }).setView([9.0, 39.5], 6);
    tiles().addTo(state.maps.main);
    state.maps.main.on("click", (e) => {
      state.example = false;
      setLocation(e.latlng.lat, e.latlng.lng, null, null);
    });
  }
  setTimeout(() => {
    state.maps.main.invalidateSize();
    if (state.lat !== null) placeMarker(13);
  }, 50);
}
function placeMarker(zoom) {
  const map = state.maps.main;
  if (!map) return;
  if (state.marker) state.marker.setLatLng([state.lat, state.lon]);
  else state.marker = L.marker([state.lat, state.lon]).addTo(map);
  if (zoom) map.setView([state.lat, state.lon], zoom);
}
function setLocation(lat, lon, zoom, place) {
  state.lat = Math.round(lat * 10000) / 10000;
  state.lon = Math.round(lon * 10000) / 10000;
  state.place = place;
  placeMarker(zoom);
  renderCoords();
  $("soil-msg").hidden = true;
}
function renderCoords() {
  if (state.lat === null) { $("coords-text").textContent = t("plan.map_hint"); return; }
  const where = t("plan.field_at", { lat: state.lat.toFixed(4), lon: state.lon.toFixed(4) });
  $("coords-text").textContent = state.place ? `${state.place} · ${where}` : where;
}
$("locate").addEventListener("click", () => {
  if (!navigator.geolocation) return showFormError(t("plan.err_place"));
  navigator.geolocation.getCurrentPosition(
    (pos) => { state.example = false; setLocation(pos.coords.latitude, pos.coords.longitude, 13, null); },
    () => showFormError(t("plan.err_place")),
  );
});

// ---------- place search (typed village or town name) ----------
$("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("search-q").value.trim();
  const list = $("search-results");
  list.innerHTML = "";
  list.hidden = true;
  $("search-msg").hidden = true;
  if (q.length < 2) return;
  try {
    const url = `https://geocoding-api.open-meteo.com/v1/search?count=6&format=json&language=${currentLang}&name=${encodeURIComponent(q)}`;
    const data = await (await fetch(url)).json();
    const results = data.results || [];
    if (!results.length) { $("search-msg").textContent = t("plan.search_none"); $("search-msg").hidden = false; return; }
    for (const r of results) {
      const btn = el("button", { type: "button" });
      btn.append(el("span", {}, r.name), el("br"), el("small", {}, [r.admin2, r.admin1, r.country].filter(Boolean).join(", ")));
      btn.addEventListener("click", () => {
        state.example = false;
        setLocation(r.latitude, r.longitude, 13, r.name);
        list.hidden = true;
      });
      const li = el("li");
      li.appendChild(btn);
      list.appendChild(li);
    }
    list.hidden = false;
  } catch {
    $("search-msg").textContent = t("plan.search_fail");
    $("search-msg").hidden = false;
  }
});

// ---------- form ----------
function fillSelect(select, items, prefix) {
  const keep = select.value;
  select.innerHTML = "";
  for (const item of items) select.appendChild(el("option", { value: item.id }, t(`${prefix}.${item.id}`)));
  if (keep) select.value = keep;
}
function fillOptions() {
  fillSelect($("crop"), state.options.crops, "crop");
  fillSelect($("soil"), state.options.soils, "soil");
  const keep = $("method").value;
  $("method").innerHTML = "";
  for (const m of state.options.methods) {
    $("method").appendChild(el("option", { value: m.id }, `${t(`method.${m.id}`)} (${t(`method.${m.id}_d`)})`));
  }
  if (keep) $("method").value = keep;
  syncDescriptions();
}
function syncDescriptions() {
  const crop = state.options.crops.find((c) => c.id === $("crop").value);
  $("planting-block").hidden = crop.perennial;
  $("crop-desc").textContent = t(`crop.${crop.id}_d`);
  $("soil-desc").textContent = t(`soil.${$("soil").value}_d`);
}
function renderChips() {
  const box = $("weeks-chips");
  box.innerHTML = "";
  for (const w of WEEK_CHIPS) {
    const b = el("button", { type: "button", "aria-pressed": String($("planting_date").value === isoDaysAgo(w * 7)) }, t("plan.weeks_ago", { n: w }));
    b.addEventListener("click", () => {
      $("planting_date").value = isoDaysAgo(w * 7);
      state.example = false;
      renderChips();
    });
    box.appendChild(b);
  }
}
async function loadOptions() {
  const res = await fetch("/api/options");
  state.options = await res.json();
  fillOptions();
  $("planting_date").max = isoDaysAgo(0);
  $("last_wet_date").max = isoDaysAgo(0);
  $("crop").addEventListener("change", syncDescriptions);
  $("soil").addEventListener("change", syncDescriptions);
  $("planting_date").addEventListener("change", renderChips);
}
function showFormError(message) {
  $("form-error").textContent = message;
  $("form-error").hidden = !message;
}
// Any change by the visitor means the next plan is theirs, not the example.
$("form").addEventListener("change", () => { state.example = false; });

// ---------- soil suggestion from soil maps ----------
async function loadSite() {
  if (state.lat === null) return null;
  const key = `${state.lat},${state.lon}`;
  if (state.siteKey === key && state.site) return state.site;
  const res = await fetch(`/api/site?lat=${state.lat}&lon=${state.lon}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "site");
  state.site = data;
  state.siteKey = key;
  return data;
}
$("soil-suggest").addEventListener("click", async () => {
  const msg = $("soil-msg");
  msg.hidden = false;
  if (state.lat === null) { msg.textContent = t("plan.soil_need_place"); return; }
  msg.textContent = t("plan.soil_suggesting");
  try {
    const site = await loadSite();
    if (!site.soil) { msg.textContent = t("field.soil_fail"); return; }
    $("soil").value = site.soil.suggested_soil;
    syncDescriptions();
    state.example = false;
    msg.textContent = t("plan.soil_suggested", { soil: t(`soil.${site.soil.suggested_soil}`), texture: t(`texture.${site.soil.texture}`) });
  } catch {
    msg.textContent = t("field.soil_fail");
  }
});

// ---------- plan ----------
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  showFormError("");
  if (state.lat === null) return showFormError(t("plan.err_place"));
  const crop = state.options.crops.find((c) => c.id === $("crop").value);
  if (!crop.perennial && !$("planting_date").value) return showFormError(t("plan.err_planting"));
  const body = {
    lat: state.lat, lon: state.lon, crop: crop.id, soil: $("soil").value, method: $("method").value,
    planting_date: crop.perennial ? null : $("planting_date").value,
    last_wet_date: $("last_wet_date").value || null,
  };
  const button = $("submit");
  button.disabled = true;
  button.textContent = t("plan.fetching");
  try {
    const res = await fetch("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) return showFormError(data.error || t("plan.err_server"));
    data.place = state.place;
    data.example = state.example;
    state.plan = data;
    renderPlan(data);
    if (!state.example && window.matchMedia("(max-width: 900px)").matches) $("results").scrollIntoView({ behavior: "smooth" });
  } catch {
    showFormError(t("plan.err_server"));
  } finally {
    button.disabled = false;
    button.textContent = t("plan.submit");
  }
});

function headlineText(plan) {
  const s = plan.summary;
  if (!s.irrigation_events.length) {
    return { ok: true, big: t("res.none_t"), small: t("res.none", { crop: t(`crop.${plan.inputs.crop}`) }) };
  }
  const first = s.irrigation_events[0];
  const when = s.irrigate_today ? t("res.today") : fmtDay(first.date, { weekday: "long", day: "numeric", month: "long" });
  const more = s.irrigation_events.length > 1
    ? t("res.go_many", { n: s.irrigation_events.length, total: num(s.irrigation_gross_mm) })
    : t("res.go_once");
  return {
    ok: false,
    big: t("res.go_t", { when, mm: num(first.gross_mm) }),
    small: `${t("res.go", {
      litres: whole(first.litres_per_ha), perm2: num(first.gross_mm, 0),
      method: t(`method.${plan.inputs.method}`), net: num(first.net_mm),
    })} ${more}`,
  };
}

function renderPlan(plan) {
  $("plan-loading").hidden = true;
  $("output").hidden = false;
  $("example-note").hidden = !plan.example;
  const h = headlineText(plan);
  const box = $("headline");
  box.innerHTML = "";
  box.classList.toggle("ok", h.ok);
  box.append(el("p", { class: "big" }, h.big), el("p", { class: "small" }, h.small));
  // Home page card.
  $("home-today").hidden = false;
  $("home-today-head").textContent = h.big;
  $("home-today-sub").textContent = `${plan.place || EXAMPLE.place} · ${t(`crop.${plan.inputs.crop}`)} · ${h.small}`;
  $("home-today").querySelector("h2").textContent = plan.example ? t("home.today_t") : `${t("nav.plan")}: ${plan.place || ""}`.trim();

  const list = $("warnings");
  list.innerHTML = "";
  (plan.warning_codes || []).forEach((w, i) => {
    const key = `warn.${w.code}`;
    const text = STRINGS.en[key] ? t(key, { date: w.date ? fmtDay(w.date, { day: "numeric", month: "long" }) : "" }) : plan.warnings[i];
    list.appendChild(el("li", {}, text));
  });

  const s = plan.summary;
  const stats = [
    [t("res.stat_use"), `${num(s.week_crop_water_use_mm)} mm`, t("res.stat_use_n", { et0: num(s.week_et0_mm) })],
    [t("res.stat_rain"), `${num(s.week_rain_mm)} mm`, t("res.stat_rain_n", { eff: num(s.week_effective_rain_mm) })],
    [t("res.stat_soil"), `${num(s.soil_depletion_start_of_today_mm)} mm`, t("res.stat_soil_n", { raw: num(s.raw_mm), taw: num(s.taw_mm) })],
    [t("res.stat_stage"), stageName(s.stage), t("res.stat_stage_n", { kc: num(s.kc_today, 2), root: num(s.root_depth_m, 2), day: s.days_after_planting ?? "–" })],
  ];
  const statBox = $("stats");
  statBox.innerHTML = "";
  for (const [label, value, note] of stats) {
    const card = el("div", { class: "stat" });
    card.append(el("div", { class: "label" }, label), el("div", { class: "value" }, value), el("div", { class: "note" }, note));
    statBox.appendChild(card);
  }
  renderBalanceChart(plan);
  renderTable(plan);
  resetAi(plan);
}

function chartDefaults() {
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--chart-grid");
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
}

function renderBalanceChart(plan) {
  chartDefaults();
  const days = plan.days.filter((d) => d.stage);
  const water = css("--water");
  const green = css("--accent");
  const labels = days.map((d) => fmtDay(d.date, { day: "numeric", month: "short" }) + (d.date === plan.summary.today ? ` (${t("res.today")})` : ""));
  state.charts.balance?.destroy();
  state.charts.balance = new Chart($("balance-chart"), {
    data: {
      labels,
      datasets: [
        { type: "bar", label: t("chart.use"), data: days.map((d) => d.etc), backgroundColor: "#c08a52", yAxisID: "y" },
        { type: "bar", label: t("chart.rain"), data: days.map((d) => d.rain), backgroundColor: "#7fb3e0", yAxisID: "y" },
        { type: "line", label: t("chart.used"), data: days.map((d) => d.depletion_before_irrigation), borderColor: green, tension: 0.2, yAxisID: "y2",
          pointRadius: days.map((d) => (d.irrigation_net ? 7 : 2)),
          pointBackgroundColor: days.map((d) => (d.irrigation_net ? water : green)),
          pointBorderColor: days.map((d) => (d.irrigation_net ? water : green)),
          segment: { borderDash: (ctx) => (days[ctx.p1DataIndex]?.forecast ? [5, 4] : undefined) } },
        { type: "line", label: t("chart.limit"), data: days.map((d) => d.raw), borderColor: css("--error"), borderDash: [3, 3], pointRadius: 0, borderWidth: 1.5, yAxisID: "y2" },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: { footer: (items) => {
          const d = days[items[0].dataIndex];
          return d.irrigation_net ? t("chart.irrigate", { gross: num(d.irrigation_gross), net: num(d.irrigation_net) }) : "";
        } } },
      },
      scales: {
        y: { position: "left", title: { display: true, text: t("chart.mm_day") }, beginAtZero: true },
        y2: { position: "right", reverse: true, beginAtZero: true, title: { display: true, text: t("chart.soil_used") }, grid: { drawOnChartArea: false } },
        x: { ticks: { maxRotation: 60, autoSkip: true, font: { size: 10 } } },
      },
    },
  });
}

function renderTable(plan) {
  const table = $("days-table");
  table.innerHTML = "";
  const head = el("tr");
  for (const k of ["date", "stage", "et0", "kc", "use", "rain", "soil", "irrigate", "litres"]) head.appendChild(el("th", {}, t(`tbl.${k}`)));
  const thead = el("thead");
  thead.appendChild(head);
  const tbody = el("tbody");
  for (const d of plan.days) {
    const today = d.date === plan.summary.today;
    const row = el("tr", { class: today ? "today" : d.forecast ? "" : "past" });
    const dep = d.depletion_before_irrigation;
    const cells = [
      fmtDay(d.date) + (today ? ` · ${t("res.today")}` : ""),
      d.stage ? stageName(d.stage) : t("tbl.not_in_field"),
      num(d.et0), num(d.kc, 2), num(d.etc), num(d.rain),
      dep === undefined || dep === null ? "–" : `${num(dep)} / ${num(d.raw)}`,
      d.irrigation_gross ? `${num(d.irrigation_gross)} mm` : "",
      d.irrigation_gross ? whole(d.irrigation_gross * 10000) : "",
    ];
    cells.forEach((c, i) => row.appendChild(el("td", i >= 7 && c ? { class: "irrigate" } : {}, c)));
    tbody.appendChild(row);
  }
  table.append(thead, tbody);
}

// ---------- AI explanation ----------
function resetAi(plan) {
  $("ai-text").innerHTML = "";
  $("explain").disabled = !plan.ai_available;
  $("ai-note").textContent = plan.ai_available ? t("res.ai_on") : t("res.ai_off");
}
function renderAiText(text) {
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
  button.textContent = t("res.ai_writing");
  $("ai-text").innerHTML = "";
  try {
    const res = await fetch("/api/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: state.plan.plan_id, plan: state.plan, language: currentLang }),
    });
    const data = await res.json();
    if (!res.ok) { $("ai-text").appendChild(el("p", { class: "error" }, data.error || t("res.ai_fail"))); return; }
    renderAiText(data.text);
    $("ai-text").appendChild(el("p", { class: "meta" }, t("res.ai_by", { model: data.model })));
  } catch {
    $("ai-text").appendChild(el("p", { class: "error" }, t("plan.err_server")));
  } finally {
    button.disabled = false;
    button.textContent = t("res.ai_btn");
  }
});

// ---------- weather page ----------
function weatherIcon(d) {
  if (d.rain >= 10) return "🌧️";
  if (d.rain >= 1 || (d.rain_chance ?? 0) >= 60) return "🌦️";
  if ((d.tmax ?? 0) >= 28) return "☀️";
  return "⛅";
}
function renderWeather() {
  const plan = state.plan;
  $("wx-none").hidden = !!plan;
  $("wx-body").hidden = !plan;
  if (!plan) return;
  $("wx-place").textContent = `${plan.place || EXAMPLE.place} · ${plan.inputs.lat}, ${plan.inputs.lon}`;
  const next = plan.weather.filter((d) => d.forecast);
  const past = plan.weather.filter((d) => !d.forecast);
  const rain = next.reduce((a, d) => a + d.rain, 0);
  const et0 = next.reduce((a, d) => a + d.et0, 0);
  const box = $("wx-summary");
  box.innerHTML = "";
  box.append(el("strong", {}, rain < et0 / 2 ? t("wx.dry_week") : t("wx.wet_week")),
    document.createTextNode(t("wx.week_sum", { rain: num(rain), et0: num(et0) })));

  const irrigate = new Set(plan.summary.irrigation_events.map((e) => e.date));
  const cards = $("wx-days");
  cards.innerHTML = "";
  for (const d of next) {
    const today = d.date === plan.summary.today;
    const card = el("div", { class: `day${today ? " today" : ""}${irrigate.has(d.date) ? " water" : ""}` });
    card.append(
      el("div", { class: "d" }, today ? t("res.today") : fmtDay(d.date, { weekday: "short", day: "numeric" })),
      el("div", { class: "icon", "aria-hidden": "true" }, weatherIcon(d)),
    );
    const temp = el("div", { class: "temp" }, `${num(d.tmax, 0)}°`);
    temp.appendChild(el("span", {}, ` / ${num(d.tmin, 0)}°`));
    card.appendChild(temp);
    card.appendChild(el("div", { class: "row rain" }, `${t("wx.rain")} ${num(d.rain)} mm` + (d.rain_chance != null ? ` · ${d.rain_chance}%` : "")));
    if (d.wind_max != null) card.appendChild(el("div", { class: "row" }, `${t("wx.wind")} ${num(d.wind_max, 0)} km/h`));
    card.appendChild(el("div", { class: "row" }, `${t("wx.thirst")} ${num(d.et0)} mm`));
    if (irrigate.has(d.date)) card.appendChild(el("div", { class: "row rain" }, "💧 " + t("tbl.irrigate")));
    cards.appendChild(card);
  }

  chartDefaults();
  state.charts.weather?.destroy();
  state.charts.weather = new Chart($("wx-chart"), {
    data: {
      labels: past.map((d) => fmtDay(d.date, { day: "numeric", month: "short" })),
      datasets: [
        { type: "bar", label: t("chart.rain"), data: past.map((d) => d.rain), backgroundColor: "#7fb3e0", yAxisID: "y" },
        { type: "bar", label: t("wx.et0"), data: past.map((d) => d.et0), backgroundColor: "#c08a52", yAxisID: "y" },
        { type: "line", label: t("wx.t_max"), data: past.map((d) => d.tmax), borderColor: "#e0663a", tension: 0.3, yAxisID: "y2", pointRadius: 2 },
        { type: "line", label: t("wx.t_min"), data: past.map((d) => d.tmin), borderColor: css("--water"), tension: 0.3, yAxisID: "y2", pointRadius: 2 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "mm" } },
        y2: { position: "right", title: { display: true, text: "°C" }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

// ---------- field page ----------
async function renderField() {
  const has = state.lat !== null;
  $("field-none").hidden = has;
  $("field-body").hidden = !has;
  if (!has) return;
  $("field-coords").textContent = `${state.lat.toFixed(4)}, ${state.lon.toFixed(4)}${state.place ? ` (${state.place})` : ""}`;
  if (!state.maps.field) {
    state.maps.field = L.map("field-map", { zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false });
    tiles().addTo(state.maps.field);
  }
  setTimeout(() => {
    state.maps.field.invalidateSize();
    state.maps.field.setView([state.lat, state.lon], 13);
    state.fieldMarker = state.fieldMarker ? state.fieldMarker.setLatLng([state.lat, state.lon]) : L.marker([state.lat, state.lon]).addTo(state.maps.field);
  }, 50);
  const samePlace = state.plan && state.plan.inputs.lat === state.lat && state.plan.inputs.lon === state.lon;
  renderClimate(samePlace ? state.plan.climate : null);

  const box = $("soil-box");
  if (!(state.site && state.siteKey === `${state.lat},${state.lon}`)) {
    box.innerHTML = "";
    box.appendChild(el("p", { class: "sub" }, t("ui.loading")));
    $("field-elev").textContent = "…";
  }
  let site;
  try { site = await loadSite(); } catch { site = null; }
  $("field-elev").textContent = site?.elevation_m != null ? `${whole(site.elevation_m)} m` : (state.plan?.location?.elevation_m != null ? `${whole(state.plan.location.elevation_m)} m` : "–");
  box.innerHTML = "";
  if (!site || !site.soil) { box.appendChild(el("p", { class: "sub" }, t("field.soil_fail"))); return; }
  const s = site.soil;
  const bar = el("div", { class: "texture-bar", role: "img", "aria-label": `${t("field.sand")} ${s.sand_pct}%, ${t("field.silt")} ${s.silt_pct}%, ${t("field.clay")} ${s.clay_pct}%` });
  for (const [cls, v] of [["sand", s.sand_pct], ["silt", s.silt_pct], ["clay", s.clay_pct]]) {
    const part = el("div", { class: cls, style: `width:${v}%` }, `${Math.round(v)}%`);
    bar.appendChild(part);
  }
  const legend = el("div", { class: "legend" });
  for (const [cls, color] of [["sand", "#d4a85a"], ["silt", "#9a8466"], ["clay", "#6b4a2f"]]) {
    const item = el("span");
    item.append(el("i", { style: `background:${color}` }), document.createTextNode(t(`field.${cls}`)));
    legend.appendChild(item);
  }
  box.append(bar, legend,
    el("p", { class: "soil-result" }, t("field.suggest", { soil: t(`soil.${s.suggested_soil}`) })),
    el("p", { class: "sub" }, t("field.texture", { texture: t(`texture.${s.texture}`) })));
  const kv = el("div", { class: "kv" });
  if (s.ph != null) {
    const note = s.ph < 5.5 ? t("field.ph_acid") : s.ph > 7.8 ? t("field.ph_alk") : t("field.ph_ok");
    const p = el("p");
    p.append(el("b", {}, `${t("field.ph")}: ${num(s.ph)}`), document.createTextNode(` ${note}`));
    kv.appendChild(p);
  }
  if (s.organic_carbon_g_per_kg != null) {
    const oc = s.organic_carbon_g_per_kg;
    const note = oc < 6 ? t("field.oc_low") : oc > 15 ? t("field.oc_high") : t("field.oc_ok");
    const p = el("p");
    p.append(el("b", {}, `${t("field.oc")}: ${num(oc)} g/kg`), document.createTextNode(` ${note}`));
    kv.appendChild(p);
  }
  box.appendChild(kv);
  if (s.likely_vertisol) box.appendChild(el("p", { class: "vertisol" }, t("field.vertisol")));
  const use = el("button", { type: "button", class: "secondary small" }, t("field.use_soil"));
  const done = el("p", { class: "help strong", hidden: "" }, t("field.soil_used"));
  use.addEventListener("click", () => {
    $("soil").value = s.suggested_soil;
    syncDescriptions();
    state.example = false;
    done.hidden = false;
  });
  box.append(el("p", { class: "help" }, t("field.soil_src")), use, done);
}

function renderClimate(climate) {
  $("climate-panel").hidden = !climate;
  state.charts.climate?.destroy();
  if (!climate) return;
  chartDefaults();
  const m = climate.this_month;
  const monthName = (i) => new Date(2026, i, 1).toLocaleDateString(locale(), { month: "short" });
  const thisIndex = climate.months.findIndex((x) => x.month === m.month);
  $("climate-text").textContent = t("field.climate", {
    period: String(climate.period).replace(" average", ""), annual: whole(climate.annual_rain_mm),
    month: new Date(2026, thisIndex, 1).toLocaleDateString(locale(), { month: "long" }), rain: m.rain_mm, temp: m.temp_c,
  });
  state.charts.climate = new Chart($("climate-chart"), {
    type: "bar",
    data: {
      labels: climate.months.map((_, i) => monthName(i)),
      datasets: [{ label: "mm", data: climate.months.map((x) => x.rain_mm),
        backgroundColor: climate.months.map((x) => (x.month === m.month ? css("--water") : "#a9c9e6")) }],
    },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, title: { display: true, text: "mm" } } } },
  });
}

// ---------- start ----------
function runExample() {
  $("crop").value = EXAMPLE.crop;
  $("soil").value = EXAMPLE.soil;
  syncDescriptions();
  $("planting_date").value = isoDaysAgo(EXAMPLE.daysSincePlanting);
  renderChips();
  setLocation(EXAMPLE.lat, EXAMPLE.lon, null, EXAMPLE.place);
  state.example = true;
  $("form").requestSubmit();
}

applyLanguage(currentLang);
showPage();
loadOptions()
  .then(runExample)
  .catch(() => showFormError(t("plan.err_options")));
