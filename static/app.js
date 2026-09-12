/* SST Viewer frontend. Plain Leaflet + Chart.js, no build step. */
"use strict";

const $ = id => document.getElementById(id);

// ---------------------------------------------------------- dd/mm/yyyy dates
// Chromium ties <input type=date> display order to the browser/OS language
// only (no per-element override, `lang` attribute included -- confirmed
// dead), so date entry is built from three explicit number fields instead.
// The stored/exchanged value is always ISO yyyy-mm-dd.
function dmyTripletHtml(iso, attrs, showYear = true) {
  const [y, m, d] = (iso || "").split("-");
  const yearPart = showYear
    ? `/<input type="number" class="dmyY" min="1900" max="2100" placeholder="yyyy" data-part="y" ${attrs} value="${y || ""}">`
    : "";
  return `<span class="dmy">` +
    `<input type="number" class="dmyD" min="1" max="31" placeholder="dd" data-part="d" ${attrs} value="${d || ""}">/` +
    `<input type="number" class="dmyM" min="1" max="12" placeholder="mm" data-part="m" ${attrs} value="${m || ""}">` +
    yearPart +
    `</span>`;
}
// defaultYear covers date-item triplets rendered without a year field
// (repeat-across-years mode): fmtMD strips whatever year is stored, so any
// placeholder works and one is needed to keep it.value/it.from/it.to a
// parseable ISO string.
function dmyToIso(wrap, defaultYear) {
  const d = wrap.querySelector('[data-part="d"]').value;
  const m = wrap.querySelector('[data-part="m"]').value;
  const yEl = wrap.querySelector('[data-part="y"]');
  const y = yEl ? yEl.value : (defaultYear || "");
  if (!d || !m || !y) return "";
  return `${y.padStart(4, "0")}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
}
// Data-tab date items are day/month ONLY -- years always come from the year
// section below, so no path through the UI can erase a typed date. They are
// stored under a fixed leap year (so 02-29 stays representable) and are kept
// as a PARTIAL iso while only one of the two fields is filled: committing
// half-typed input is what keeps a later re-render from throwing it away.
const MD_YEAR = "2000";
function mdPartialIso(wrap) {
  const d = wrap.querySelector('[data-part="d"]').value;
  const m = wrap.querySelector('[data-part="m"]').value;
  return `${MD_YEAR}-${m ? m.padStart(2, "0") : ""}-${d ? d.padStart(2, "0") : ""}`;
}
const isFullMD = v => /^\d{4}-\d{2}-\d{2}$/.test(v || "");

// Wires a hidden <input id=id> to a visible dd/mm/yyyy triplet, keeping the
// hidden input's .value as the ISO string so all existing get/set/onchange
// code elsewhere in this file keeps working unchanged.
function wireDMY(id) {
  const hidden = $(id);
  hidden.insertAdjacentHTML("afterend", dmyTripletHtml(""));
  const wrap = hidden.nextElementSibling;
  let internal = "";
  Object.defineProperty(hidden, "value", {
    get() { return internal; },
    set(v) {
      internal = v || "";
      const [y, m, d] = internal.split("-");
      wrap.querySelector('[data-part="d"]').value = d || "";
      wrap.querySelector('[data-part="m"]').value = m || "";
      wrap.querySelector('[data-part="y"]').value = y || "";
    },
  });
  wrap.querySelectorAll("input").forEach(inp => inp.addEventListener("change", () => {
    internal = dmyToIso(wrap);
    hidden.dispatchEvent(new Event("change", { bubbles: true }));
  }));
}

// ------------------------------------------------------------------- i18n
const I18N = {
  en: {
    sec_layer: "Layer", help_layer: "Which dataset and field are drawn on the map. OISST local = the project's offline files (May 20 – Jul 1, 2000–2025); OISST ERDDAP = the same 0.25° dataset from NOAA servers back to Sept 1981, all days; MUR = 1 km satellite SST (the map view covers the Okhotsk box; point charts and CSV export work for any coordinates on the globe). Remote dates download on demand the first time you view them.",
    lbl_dataset: "Dataset", lbl_variable: "Variable", lbl_opacity: "Overlay opacity",
    var_sst: "SST (°C)", var_anom: "SST anomaly (°C)", var_err: "Analysis error (°C)",
    var_analysed_sst: "SST (°C)", var_sea_ice_fraction: "Sea-ice fraction",
    sec_scale: "Color scale", help_scale: "Auto picks the 2–98 percentile range of the current frame. Fixed uses the min/max you type — required for comparing dates or running a timelapse, otherwise colors mean different temperatures in every frame.",
    lbl_auto: "Auto", lbl_fixed: "Fixed", lbl_to: "to",
    lbl_shared: "shared", help_shared: "Let the other accounts see this area (they can use it, but only you can change or delete it).",
    lbl_shared_by: who => `shared by ${who}`, btn_signout: "sign out",
    ds_unavailable: "that dataset's server is not answering right now",
    sec_date: "Date", help_date: "The picker snaps to the nearest available date of the selected dataset. Use ◀ ▶ or keyboard ← → to step.",
    sec_timelapse: "Timelapse", help_timelapse: "Plays through the available dates in the chosen range like an animation.",
    lbl_from: "from", lbl_gap: "step, days", help_gap: "How many calendar days to jump each frame (snapping to the nearest available date). 1 = every day. 365 ≈ the same day next year (use the checkbox below for a leap-safe version).",
    lbl_fps: "fps", lbl_sameday: "same day each year", help_sameday: "Show the same month/day (taken from the 'from' date) in every year of the range — e.g. every June 1 from 2000 to 2025.",
    txt_island: "Dataset, variable and date are set in the bar above the map.",
    tl_loading: "loading frames", tl_spec_bad: "fill in the day/month and year fields",
    sec_gifbox: "GIF area", help_gifbox: "The rectangle the exported GIF is cropped to, in degrees. Seeded from the current map view; edit the numbers, or pick a saved area to reuse exactly the same frame again. Save the box as an area to keep it for later.",
    opt_box_custom: "— custom box —", btn_box_from_map: "⤢ from map", btn_box_to_map: "zoom to box",
    btn_box_save: "💾 Save as new", ph_box_name: "name", box_need_name: "type a name for the area first",
    btn_box_draw: "▭ Draw on map", btn_box_update: "⤴ Update selected",
    btn_box_delete: "🗑 Delete", box_need_saved: "pick a saved area first",
    btn_play: "▶ Play", btn_pause: "⏸ Pause", btn_gif: "Export GIF", help_gif: "The server renders a GIF of the current timelapse settings, cropped to the visible map area. Land is gray in the GIF (no basemap).",
    tab_map: "Map", tab_tl: "Timelapse", tab_ab: "A/B", tab_data: "Data", tab_areas: "Areas",
    hl_ok: "reachable", hl_slow: "reachable but slow", hl_down: "unreachable",
    hl_unknown: "not checked yet", hl_checked: "checked", hl_ago: "ago",
    hl_tool_ok: "available", hl_tool_down: "NOT INSTALLED",
    hl_via_probe: "health probe", hl_via_traffic: "seen by a real request",
    hl_noserver: "source status unavailable (app server not responding)",
    hl_notices: "click to open this server's own status page (load, uptime, recent failures)",
    hl_via_server: "the server itself is not answering",
    hl_role_server: "the ERDDAP server: does it answer at all?",
    hl_role_dataset: "this dataset: does its data actually come through?",
    splash_sub: "Okhotsk Sea · sea-surface temperature",
    boot_sources: "Checking data sources…", boot_datasets: "Loading datasets…",
    boot_map: "Rendering the first map…", boot_areas: "Restoring saved areas…",
    boot_ready: "Ready",
    tip_scale: "Comparing two dates? Switch the color scale to Fixed. Auto rescales every frame, so the same color means a different temperature each time.",
    tip_health: "The dots under the title show whether each source is reachable right now — hover one for latency and the last error.",
    tip_global: "Point charts and CSV export work for any coordinates on the globe. The map box only limits the drawn overlay.",
    tip_sameday: "For a year-on-year animation use “same day each year” instead of a 365-day step — it stays aligned across leap years.",
    tip_data: "In the Data tab one row can repeat the same calendar days across many years — five days across 24 years is a single set.",
    tip_reports: "Tick “Also generate PDF(s)” for a per-point report. The template adapts to which days and years you picked.",
    sec_compare: "Compare two dates (A/B)", help_compare: "Splits the map with a draggable divider: left of it = date A (the main date above), right = date B. Click the map to see both values and the difference.",
    lbl_enable: "enable", lbl_dateb: "Date B", lbl_yr: "yr",
    txt_ab: "A = left, B = right. Scale is frozen while comparing.",
    sec_tools: "Tools", help_tools: "Distance measurement and extras.",
    btn_measure: "📏 Measure distance",
    btn_overlaypng: "Download overlay PNG", help_overlaypng: "Saves the raw SST overlay image for the current date (no basemap).",
    lbl_ice: "ice (≥15%)", lbl_nodata: "no data",
    sec_areas: "Saved areas", help_areas: "Draw a point, rectangle, circle or polygon on the map and save it with the current dataset/variable/date/scale. From the list you can jump back to it, make cropped snapshots or GIFs, and chart the spatial mean.",
    btn_draw_point: "• Point", btn_draw_rect: "▭ Rectangle", btn_draw_circle: "◯ Circle", btn_draw_poly: "⬠ Polygon",
    hint_point: "click the map to place the point",
    hint_rect: "click two opposite corners",
    hint_circle: "click the center, then a point on the rim",
    hint_poly: "click vertices; double-click to close",
    area_name_prompt: "Area name:", rename_prompt: "New name:",
    confirm_delete: n => `Delete area "${n}" and its media?`,
    confirm_media_delete: n => `Delete file "${n}"?`,
    btn_goto: "Go to", btn_snapshot: "PNG", btn_area_gif: "GIF", btn_area_chart: "Chart",
    lbl_show_areas: "show on map", no_areas: "no saved areas yet",
    generating: "generating…", mean_suffix: "area mean",
    sec_charts: "Charts", x_date: "x = date", x_doy: "x = day of year (one line per year)",
    btn_clear: "Clear", loading: "loading…", land: "land",
    loading_dates: "loading dataset dates…", remote_fetch: "fetching remote field…",
    chart_point: "Chart this point",
    sst: "SST", anomaly: "anomaly", error: "error", ice: "ice", none: "none",
    day: "day", yaxis: "SST (°C)", no_dates: "no dates in range", rendering: "rendering GIF on server…",
    snapped: (a, b) => `no data for ${a}, snapped to ${b}`,
    lbl_coords_dataset: "dataset (for these points)",
    sec_coords: "Coordinates", help_coords: "Paste coordinates, one \"lat, lon\" pair per line, then Add. Each row gets its own expandable date form — build a list of specific dates and/or date ranges, optionally repeated across years (either a year range or explicit non-consecutive years). Check the rows you want, then Download: builds one combined CSV, and optionally renders a PDF report per checked coordinate (RProject3-style trend analysis) as a background job.",
    btn_add_coords: "+ Add", btn_select_all: "Select all", btn_deselect_all: "Deselect all",
    coords_none: "no valid coordinates — one \"lat, lon\" per line",
    lbl_dates: "dates", btn_add_date: "+ date", btn_add_range: "+ date range",
    lbl_repeat_years: "repeat across years (set the years below)",
    lbl_years_section: "years to apply these dates to",
    btn_add_year: "+ year", btn_add_year_range: "+ year range",
    lbl_days: "days", lbl_years: "yrs",
    btn_copy_dates: "copy these dates to checked rows ↓",
    row_no_dates: "no dates added yet", row_bad_dates: "incomplete date/year fields",
    row_n_dates: (n, a, b) => `${n} date(s): ${a} … ${b}`,
    lbl_also_pdf: "Also generate PDF(s)", btn_download: "⬇ Download",
    rows_bad_dates: "These coordinates have no complete dates yet:",
    pdf_ready: "⬇ PDF report", csv_ready: "⬇ combined CSV",
    st_pending: "pending…", st_done: "done", st_error: "error",
    st_queued: "queued…", st_fetching: "fetching data…", st_rendering: "composing PDF…",
    point_name_prompt: "Geographic name for this point (used in the PDF title/header):",
    btn_rename_point: "✎ name",
    lbl_refresh_data: "Re-download data (ignore cache)", cached_note: "cached data, no download",
  },
  ru: {
    sec_layer: "Слой", help_layer: "Какой набор данных и поле рисуются на карте. OISST локально — офлайн-файлы проекта (20 мая – 1 июля, 2000–2025); OISST ERDDAP — тот же набор 0.25° с серверов NOAA с сентября 1981, все дни; MUR — спутниковая ТПМ 1 км (карта покрывает Охотский бокс; графики точек и экспорт CSV работают для любых координат на глобусе). Удалённые даты скачиваются по запросу при первом просмотре.",
    lbl_dataset: "Набор данных", lbl_variable: "Переменная", lbl_opacity: "Прозрачность слоя",
    var_sst: "ТПМ (°C)", var_anom: "Аномалия ТПМ (°C)", var_err: "Ошибка анализа (°C)",
    var_analysed_sst: "ТПМ (°C)", var_sea_ice_fraction: "Доля морского льда",
    sec_scale: "Цветовая шкала", help_scale: "«Авто» берёт диапазон 2–98 перцентилей текущего кадра. «Фикс.» использует введённые min/max — обязательно при сравнении дат и таймлапсе, иначе цвета в каждом кадре означают разные температуры.",
    lbl_auto: "Авто", lbl_fixed: "Фикс.", lbl_to: "до",
    lbl_shared: "общая", help_shared: "Показывать эту область другим аккаунтам (менять и удалять можете только вы).",
    lbl_shared_by: who => `общая от ${who}`, btn_signout: "выйти",
    ds_unavailable: "сервер этого набора сейчас не отвечает",
    sec_date: "Дата", help_date: "Выбор привязывается к ближайшей доступной дате выбранного набора. Листайте ◀ ▶ или клавишами ← →.",
    sec_timelapse: "Таймлапс", help_timelapse: "Проигрывает доступные даты в выбранном диапазоне как анимацию.",
    lbl_from: "с", lbl_gap: "шаг, дней", help_gap: "На сколько календарных дней прыгать каждый кадр (с привязкой к ближайшей доступной дате). 1 = каждый день. 365 ≈ тот же день следующего года (для точности лучше галочка ниже).",
    lbl_fps: "кадр/с", lbl_sameday: "тот же день каждый год", help_sameday: "Показывать одно и то же число (месяц/день берутся из даты «с») в каждом году диапазона — например, каждое 1 июня с 2000 по 2025.",
    txt_island: "Набор данных, переменная и дата задаются в полосе над картой.",
    tl_loading: "загрузка кадров", tl_spec_bad: "заполните поля дня/месяца и года",
    sec_gifbox: "Область GIF", help_gifbox: "Прямоугольник, по которому обрезается экспортируемый GIF, в градусах. Заполняется по текущему виду карты; измените числа или выберите сохранённую область, чтобы повторить тот же кадр. Кнопка сохранения кладёт рамку в список областей.",
    opt_box_custom: "— своя рамка —", btn_box_from_map: "⤢ с карты", btn_box_to_map: "показать рамку",
    btn_box_save: "💾 Сохранить новую", ph_box_name: "название", box_need_name: "сначала введите название области",
    btn_box_draw: "▭ Нарисовать", btn_box_update: "⤴ Обновить выбранную",
    btn_box_delete: "🗑 Удалить", box_need_saved: "сначала выберите сохранённую область",
    btn_play: "▶ Пуск", btn_pause: "⏸ Пауза", btn_gif: "Экспорт GIF", help_gif: "Сервер собирает GIF с текущими настройками таймлапса, обрезанный по видимой области карты. Суша в GIF серая (без подложки).",
    tab_map: "Карта", tab_tl: "Таймлапс", tab_ab: "A/B", tab_data: "Данные", tab_areas: "Области",
    hl_ok: "доступен", hl_slow: "доступен, но медленно", hl_down: "недоступен",
    hl_unknown: "ещё не проверялся", hl_checked: "проверено", hl_ago: "назад",
    hl_tool_ok: "доступно", hl_tool_down: "НЕ УСТАНОВЛЕНО",
    hl_via_probe: "проверка состояния", hl_via_traffic: "по реальному запросу",
    hl_noserver: "состояние источников недоступно (сервер приложения не отвечает)",
    hl_notices: "нажмите, чтобы открыть страницу состояния самого сервера (нагрузка, аптайм, последние сбои)",
    hl_via_server: "сам сервер не отвечает",
    hl_role_server: "сервер ERDDAP: отвечает ли он вообще?",
    hl_role_dataset: "этот набор данных: доходят ли сами данные?",
    splash_sub: "Охотское море · температура поверхности моря",
    boot_sources: "Проверка источников данных…", boot_datasets: "Загрузка наборов данных…",
    boot_map: "Отрисовка первой карты…", boot_areas: "Восстановление сохранённых областей…",
    boot_ready: "Готово",
    tip_scale: "Сравниваете две даты? Переключите шкалу на «Фиксированная». «Авто» пересчитывает диапазон в каждом кадре, поэтому один и тот же цвет означает разную температуру.",
    tip_health: "Точки под заголовком показывают, доступен ли сейчас каждый источник — наведите курсор, чтобы увидеть задержку и последнюю ошибку.",
    tip_global: "Графики по точке и экспорт CSV работают для любых координат на планете. Рамка карты ограничивает только отрисовку слоя.",
    tip_sameday: "Для анимации по годам используйте «тот же день каждый год» вместо шага в 365 дней — так дата не съедет из-за високосных лет.",
    tip_data: "На вкладке «Данные» одна строка может повторять одни и те же календарные дни во многих годах — пять дней за 24 года это один набор.",
    tip_reports: "Отметьте «Также создать PDF», чтобы получить отчёт по каждой точке. Шаблон подстраивается под выбранные дни и годы.",
    sec_compare: "Сравнение двух дат (A/B)", help_compare: "Делит карту перетаскиваемой линией: слева — дата A (основная дата выше), справа — дата B. Клик по карте покажет оба значения и разницу.",
    lbl_enable: "включить", lbl_dateb: "Дата B", lbl_yr: "г.",
    txt_ab: "A — слева, B — справа. Шкала фиксируется на время сравнения.",
    sec_tools: "Инструменты", help_tools: "Измерение расстояний и прочее.",
    btn_measure: "📏 Измерить расстояние",
    btn_overlaypng: "Скачать PNG слоя", help_overlaypng: "Сохраняет изображение SST-слоя за текущую дату (без подложки).",
    lbl_ice: "лёд (≥15%)", lbl_nodata: "нет данных",
    sec_areas: "Сохранённые области", help_areas: "Нарисуйте точку, прямоугольник, круг или полигон на карте и сохраните вместе с текущим набором/переменной/датой/шкалой. Из списка можно вернуться к области, сделать обрезанные снимки или GIF и построить график пространственного среднего.",
    btn_draw_point: "• Точка", btn_draw_rect: "▭ Прямоугольник", btn_draw_circle: "◯ Круг", btn_draw_poly: "⬠ Полигон",
    hint_point: "кликните карту, чтобы поставить точку",
    hint_rect: "кликните два противоположных угла",
    hint_circle: "кликните центр, затем точку на окружности",
    hint_poly: "кликайте вершины; двойной клик — замкнуть",
    area_name_prompt: "Название области:", rename_prompt: "Новое название:",
    confirm_delete: n => `Удалить область «${n}» и её файлы?`,
    confirm_media_delete: n => `Удалить файл «${n}»?`,
    btn_goto: "Перейти", btn_snapshot: "PNG", btn_area_gif: "GIF", btn_area_chart: "График",
    lbl_show_areas: "показывать на карте", no_areas: "пока нет сохранённых областей",
    generating: "создание…", mean_suffix: "среднее по области",
    sec_charts: "Графики", x_date: "x = дата", x_doy: "x = день года (линия на каждый год)",
    btn_clear: "Очистить", loading: "загрузка…", land: "суша",
    loading_dates: "загрузка списка дат…", remote_fetch: "загрузка поля с сервера…",
    chart_point: "График для этой точки",
    sst: "ТПМ", anomaly: "аномалия", error: "ошибка", ice: "лёд", none: "нет",
    day: "день", yaxis: "ТПМ (°C)", no_dates: "нет дат в диапазоне", rendering: "сервер собирает GIF…",
    snapped: (a, b) => `нет данных на ${a}, взято ${b}`,
    lbl_coords_dataset: "набор данных (для этих точек)",
    sec_coords: "Координаты", help_coords: "Вставьте координаты, по одной паре «шир., долг.» на строку, затем «Добавить». У каждой строки своя раскрывающаяся форма дат — список конкретных дат и/или диапазонов дат, можно повторить по годам (диапазон лет или явный список несмежных лет). Отметьте нужные строки и нажмите «Скачать»: соберётся один общий CSV, и по желанию для каждой отмеченной координаты будет отрендерен PDF-отчёт (анализ в стиле RProject3) фоновой задачей.",
    btn_add_coords: "+ Добавить", btn_select_all: "Выбрать все", btn_deselect_all: "Снять выбор",
    coords_none: "нет корректных координат — по одной паре «шир., долг.» на строку",
    lbl_dates: "даты", btn_add_date: "+ дата", btn_add_range: "+ диапазон дат",
    lbl_repeat_years: "повторять по годам (укажите годы ниже)",
    lbl_years_section: "годы, к которым применить эти даты",
    btn_add_year: "+ год", btn_add_year_range: "+ диапазон лет",
    lbl_days: "дней", lbl_years: "лет",
    btn_copy_dates: "скопировать эти даты в отмеченные строки ↓",
    row_no_dates: "даты ещё не добавлены", row_bad_dates: "не все поля дат/лет заполнены",
    row_n_dates: (n, a, b) => `дат: ${n}: ${a} … ${b}`,
    lbl_also_pdf: "Также создать PDF-отчёт(ы)", btn_download: "⬇ Скачать",
    rows_bad_dates: "У этих координат ещё нет полных дат:",
    pdf_ready: "⬇ PDF-отчёт", csv_ready: "⬇ общий CSV",
    st_pending: "ожидание…", st_done: "готово", st_error: "ошибка",
    st_queued: "в очереди…", st_fetching: "загрузка данных…", st_rendering: "сборка PDF…",
    lbl_refresh_data: "Перекачать данные (игнорировать кэш)", cached_note: "из кэша, без загрузки",
    point_name_prompt: "Географическое название этой точки (используется в заголовке PDF):",
    btn_rename_point: "✎ название",
  },
};
let lang = localStorage.getItem("sst_lang") || "en";
const t = key => I18N[lang][key] ?? I18N.en[key] ?? key;

function applyLang() {
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-title]").forEach(el => { el.title = t(el.dataset.i18nTitle); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  rebuildGifAreaSelect();
  $("langBtn").textContent = lang === "en" ? "RU" : "EN";
  if (state.playing) $("playBtn").textContent = t("btn_pause");
  rebuildVarSelect(); updateLegend(); updateStatus();
  if (chart) { chart.options.scales.y.title.text = t("yaxis"); chart.update(); }
  renderAreaList(); renderRows();
}

const state = {
  dataset: "oisst_local", meta: {}, dates: [], var: "sst", date: null, dateB: null,
  vmin: null, vmax: null, playing: null, comparing: false,
};
const meta = () => state.meta[state.dataset] || { variables: {}, name: "", resolution_label: "" };
const varLabel = v => I18N[lang]["var_" + v] ? t("var_" + v) : (meta().variables[v] || v);

let me = null;   // signed-in user name

// A session can expire mid-visit (30 days) or be dropped by a redeploy; every
// call funnels through here, so one check covers the whole app.
function bounceIfSignedOut(r) {
  if (r.status === 401) { location.href = "/login"; return true; }
  return false;
}

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (bounceIfSignedOut(r)) throw new Error("signed out");
  if (!r.ok) {
    let msg = await r.text();
    try { msg = JSON.parse(msg).detail || msg; } catch (e) { /* raw text */ }
    throw new Error(msg);
  }
  return r.json();
}

// ------------------------------------------------------------------ map
const MLAT = 85.05112878; // overlay PNGs are Mercator-resampled to this limit
const map = L.map("map", { center: [50, 148], zoom: 5, worldCopyJump: true });

// Esri World Imagery is the only basemap. Carto "Light" now needs a paid API
// key (serves an "API KEY REQUIRED" tile without one) and Esri's Ocean
// bathymetry has no real tiles over the NW Pacific past ~z11 -- every cell
// comes back "Map data not yet available". With one layer there is no picker.
L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { attribution: "Esri World Imagery", maxZoom: 17 }).addTo(map);
L.control.scale({ imperial: false }).addTo(map);

// Between the basemap tiles (pane 200) and Leaflet's own overlayPane (400):
// at 401/402 the SST image was painted OVER every vector -- coordinate dots and
// saved-area outlines both came out washed under an 85%-opaque raster.
map.createPane("ovA").style.zIndex = 250;
map.createPane("ovB").style.zIndex = 260;

// Overlay repeated on the -360/0/+360 world copies so panning never leaves it
const WORLD_OFFS = [-360, 0, 360];
function makeWorldOverlay(pane) {
  const copies = WORLD_OFFS.map(off =>
    L.imageOverlay("", [[-MLAT, -180 + off], [MLAT, 180 + off]], { pane, opacity: 0.85 }));
  return {
    addTo(m) { copies.forEach(o => o.addTo(m)); return this; },
    removeFrom(m) { copies.forEach(o => m.removeLayer(o)); },
    setUrl(u) { copies.forEach(o => o.setUrl(u)); },
    setOpacity(v) { copies.forEach(o => o.setOpacity(v)); },
    setBounds(b) { // [[s,w],[n,e]] per-dataset overlay bounds
      const [[s, w], [n, e]] = b;
      copies.forEach((o, i) => o.setBounds([[s, w + WORLD_OFFS[i]], [n, e + WORLD_OFFS[i]]]));
    },
  };
}
const overlayA = makeWorldOverlay("ovA").addTo(map);
const overlayB = makeWorldOverlay("ovB");

// ------------------------------------------------------- frame blob cache
const frameCache = new Map(); // url -> {blob, vmin, vmax}
// Raised to the frame count while a timelapse preloads, so the frames fetched
// at the start of a long run are still there when it wraps around.
let frameCacheCap = 80;
async function frameURL(url) {
  if (frameCache.has(url)) return frameCache.get(url);
  const r = await fetch(url);
  if (bounceIfSignedOut(r)) throw new Error("signed out");
  if (!r.ok) throw new Error(await r.text());
  const obj = { blob: URL.createObjectURL(await r.blob()),
                vmin: r.headers.get("X-Vmin"), vmax: r.headers.get("X-Vmax") };
  frameCache.set(url, obj);
  if (frameCache.size > frameCacheCap) { // ponytail: crude LRU, evict oldest insertion
    const k = frameCache.keys().next().value;
    URL.revokeObjectURL(frameCache.get(k).blob);
    frameCache.delete(k);
  }
  return obj;
}

function overlayURL(date, fixedScale) {
  let u = `/api/overlay?date=${date}&var=${state.var}&dataset=${state.dataset}`;
  if (fixedScale) u += `&vmin=${state.vmin}&vmax=${state.vmax}`;
  return u;
}

function scaleIsFixed() {
  return document.querySelector("input[name=scaleMode]:checked").value === "fixed"
         || state.comparing || state.playing;
}

async function refreshOverlay() {
  if (!state.date) return;
  if (scaleIsFixed()) { state.vmin = +$("vmin").value; state.vmax = +$("vmax").value; }
  const fixed = scaleIsFixed();
  const url = overlayURL(state.date, fixed);
  const remoteWait = meta().remote && !frameCache.has(url);
  if (remoteWait) islandMsg(t("remote_fetch"));
  try {
    const f = await frameURL(url);
    if (!fixed) {
      state.vmin = +f.vmin; state.vmax = +f.vmax;
      $("vmin").value = f.vmin; $("vmax").value = f.vmax;
    }
    overlayA.setUrl(f.blob);
    if (state.comparing) {
      const fb = await frameURL(overlayURL(state.dateB, true));
      overlayB.setUrl(fb.blob);
    }
    if (remoteWait) islandMsg("");
  } catch (err) {
    islandMsg("⚠ " + err.message.slice(0, 200), true);
  }
  updateLegend(); updateStatus();
}

function updateLegend() {
  $("legendTitle").textContent = varLabel(state.var) + " — " + (state.date || "") +
    (state.comparing ? ` vs ${state.dateB}` : "");
  $("legendImg").src = `/api/colorbar?var=${state.var}&dataset=${state.dataset}`;
  $("legendMin").textContent = state.vmin;
  $("legendMax").textContent = state.vmax;
}

// The status bar holds the live dataset/variable/date controls, so "update"
// means push state into them -- there is no separate text readout to render.
function updateStatus() {
  $("datasetSelect").value = state.dataset;
  if ($("varSelect").value !== state.var) $("varSelect").value = state.var;
  $("dateInput").value = state.date || "";
}

// One message line, in the island, where it is visible from every tab -- it
// used to sit in the Map tab's sidebar, so a slow or failing dataset switch
// looked like the app ignoring the click.
let islandMsgTimer = null;
function islandMsg(text, isError = false) {
  const el = $("dateInfo");
  clearTimeout(islandMsgTimer);
  el.textContent = text;
  el.title = text;                       // the island truncates; hover for all of it
  el.classList.toggle("err", isError && !!text);
  // An error about a dataset you did not end up using must not sit in the
  // island forever -- re-picking the working dataset fires no change event,
  // so nothing else would ever clear it.
  if (isError && text) islandMsgTimer = setTimeout(() => islandMsg(""), 8000);
}

// -------------------------------------------------------- dataset switch
function rebuildVarSelect() {
  const sel = $("varSelect");
  const vars = Object.keys(meta().variables);
  if (!vars.length) return;
  sel.innerHTML = "";
  for (const v of vars) {
    const o = document.createElement("option");
    o.value = v; o.textContent = varLabel(v);
    sel.appendChild(o);
  }
  if (!vars.includes(state.var)) state.var = vars[0];
  sel.value = state.var;
}

// Switching datasets used to look like nothing happening: the date axis of a
// remote dataset can take a minute (or fail), and the only sign of it was a
// message in the Map tab's sidebar, invisible from any other tab. Now the
// island says so, the picker is locked while it loads, and a failure puts the
// picker and the variable list back on the dataset that actually works --
// leaving them pointing at a dataset with no dates is what made every later
// variable switch silently do nothing too.
async function selectDataset(id) {
  stopPlay();
  const prev = state.dataset;
  const m = state.meta[id];
  // The health strip already knows this source is dark; asking anyway means
  // the server spends minutes retrying a dead host while the picker sits
  // locked, and the user learns nothing they could not have been told at once.
  if (!m.dates && srcStatus[id] === "down") {
    islandMsg(t("ds_unavailable"), true);
    $("datasetSelect").value = prev;
    return;
  }
  if (!m.dates) {
    $("datasetSelect").disabled = true;
    islandMsg(t("loading_dates"));
    try {
      // a first remote date axis legitimately takes ~90 s; beyond that the
      // host is not merely slow and the UI must not stay stuck on it
      m.dates = (await fetchJSON(`/api/dataset_dates?dataset=${id}`,
                                 { signal: AbortSignal.timeout(120000) })).dates;
      islandMsg("");
    } catch (err) {
      m.dates = null;
      islandMsg("⚠ " + err.message.slice(0, 160), true);
      $("datasetSelect").disabled = false;
      $("datasetSelect").value = prev;       // stay on something usable
      return;
    }
    $("datasetSelect").disabled = false;
  }
  state.dataset = id;
  $("datasetSelect").value = id;
  state.dates = m.dates;
  rebuildVarSelect();
  overlayA.setBounds(m.overlay_bounds);
  overlayB.setBounds(m.overlay_bounds);
  const first = state.dates[0], last = state.dates[state.dates.length - 1];
  for (const el of ["dateInput", "tlStart", "tlEnd", "dateB"]) {
    $(el).min = first; $(el).max = last;
  }
  setDate(state.date || last);
}

// ------------------------------------------------------------ date logic
function nearestDate(iso) {
  if (!state.dates.length) return iso;
  let best = state.dates[0], bd = Infinity;
  const tt = Date.parse(iso);
  for (const d of state.dates) {
    const dd = Math.abs(Date.parse(d) - tt);
    if (dd < bd) { bd = dd; best = d; }
  }
  return best;
}

function setDate(iso, snap = true) {
  const d = snap ? nearestDate(iso) : iso;
  islandMsg((snap && d !== iso) ? I18N[lang].snapped(iso, d) : "");
  state.date = d;
  $("dateInput").value = d;
  refreshOverlay();
}

function stepDate(dir) {
  const i = state.dates.indexOf(state.date);
  const j = Math.min(state.dates.length - 1, Math.max(0, i + dir));
  setDate(state.dates[j], false);
}

// -------------------------------------------------------------- timelapse
// Every frame is fetched BEFORE playback starts (progress bar while it runs),
// so playback itself never stutters on the network. `tlGen` is the cancel
// token: stopPlay() bumps it, and any preload/start still in flight sees the
// mismatch and bails -- that is what keeps a second click from starting a
// second interval, which is the old Play/Stop bug.
let tlDates = [], tlIdx = 0, tlTimer = null, tlGen = 0;

// Timelapse dates in "same day each year" mode use the SAME structured
// date/year editor as the Data tab (one pseudo-row, ridx -1).
const tlRow = { dateItems: [], yearItems: [] };
const specMode = () => $("sameDayYear").checked;

async function playbackDates() {
  if (specMode()) {
    const dates = resolveRowDates(tlRow);
    if (!dates) throw new Error(t("tl_spec_bad"));
    const avail = new Set(state.dates);
    return dates.filter(d => avail.has(d));
  }
  const q = `start=${$("tlStart").value}&end=${$("tlEnd").value}` +
            `&gap=${$("gapDays").value}&dataset=${state.dataset}`;
  return fetchJSON(`/api/playback_dates?${q}`);
}

async function preloadFrames(gen) {
  const prog = $("tlProg");
  prog.classList.remove("hidden");
  prog.max = tlDates.length; prog.value = 0;
  frameCacheCap = Math.max(80, tlDates.length + 8);
  const queue = tlDates.slice();
  let done = 0;
  const worker = async () => {
    while (queue.length && gen === tlGen) {
      const d = queue.shift();
      try { await frameURL(overlayURL(d, true)); } catch { /* frame stays missing */ }
      prog.value = ++done;
      $("tlInfo").textContent = `${t("tl_loading")} ${done}/${tlDates.length}`;
    }
  };
  await Promise.all([worker(), worker(), worker()]);   // 3 at a time
  prog.classList.add("hidden");
  return gen === tlGen;
}

function showFrame(i) {
  tlIdx = i;
  $("tlScrub").value = i;
  $("tlInfo").textContent = `${i + 1}/${tlDates.length} — ${tlDates[i]}`;
  setDate(tlDates[i], false);
}

async function togglePlay() {
  if (state.playing) { stopPlay(); return; }
  const gen = ++tlGen;
  state.playing = true;                      // also freezes the color scale
  $("playBtn").textContent = t("btn_pause");
  document.querySelector("input[name=scaleMode][value=fixed]").checked = true;
  state.vmin = +$("vmin").value; state.vmax = +$("vmax").value;
  let dates;
  try { dates = await playbackDates(); }
  catch (err) { $("tlInfo").textContent = "⚠ " + err.message.slice(0, 200); stopPlay(); return; }
  if (gen !== tlGen) return;                 // stopped while the list loaded
  if (dates.length < 2) { $("tlInfo").textContent = t("no_dates"); stopPlay(); return; }
  tlDates = dates;
  const scrub = $("tlScrub");
  scrub.max = dates.length - 1;
  if (tlIdx > scrub.max) tlIdx = 0;
  scrub.value = tlIdx;
  scrub.classList.remove("hidden");
  if (!await preloadFrames(gen)) return;
  showFrame(tlIdx);
  tlTimer = setInterval(() => showFrame((tlIdx + 1) % tlDates.length),
                        1000 / +$("fps").value);
}

function stopPlay() {
  tlGen++;                                   // cancels an in-flight preload
  clearInterval(tlTimer); tlTimer = null; state.playing = null;
  $("playBtn").textContent = t("btn_play");
  $("tlProg").classList.add("hidden");
}

// Range mode lets the server pick the frames; the date/year editor sends the
// resolved list, so both GIF endpoints get their frames the same way playback did.
function tlQuery() {
  const base = `start=${$("tlStart").value}&end=${$("tlEnd").value}`;
  return specMode()
    ? `${base}&dates=${(resolveRowDates(tlRow) || []).join(",")}`
    : `${base}&gap=${$("gapDays").value}`;
}

// ------------------------------------------------- GIF bounding box
// The GIF used to be cropped to whatever the map happened to show, so the
// same animation came out a different shape every time. It now has its own
// box: four editable numbers, seeded from the map, and any saved area can be
// recalled into them -- which is what makes a series of GIFs line up.
const boxLayer = L.rectangle([[0, 0], [0, 0]],
  { color: "#ff10c8", weight: 2, dashArray: "6,4", fillOpacity: 0.05 });

function readBox() {
  const v = id => parseFloat($(id).value);
  let [w, s, e, n] = [v("boxW"), v("boxS"), v("boxE"), v("boxN")];
  if ([w, s, e, n].some(Number.isNaN)) return null;
  if (s > n) [s, n] = [n, s];
  if (w > e) [w, e] = [e, w];
  return { w, s: Math.max(-90, s), e, n: Math.min(90, n) };
}

function drawBox() {
  const b = readBox();
  const onTab = localStorage.getItem("sst_tab") === "tl";
  if (!b || !onTab) { map.removeLayer(boxLayer); return; }
  boxLayer.setBounds([[b.s, b.w], [b.n, b.e]]).addTo(map);
}

function writeBox(b) {
  $("boxW").value = b.w.toFixed(2); $("boxS").value = b.s.toFixed(2);
  $("boxE").value = b.e.toFixed(2); $("boxN").value = b.n.toFixed(2);
  drawBox();
}

function boxFromMap() {
  const b = map.getBounds();
  writeBox({ w: b.getWest(), s: b.getSouth(), e: b.getEast(), n: b.getNorth() });
}

// Any saved shape can drive the box -- its bounding box is what the server
// crops to anyway (D.area_bbox), so a circle or polygon works as well as a rect.
function rebuildGifAreaSelect(keep) {
  const sel = $("gifArea");
  if (!sel) return;
  const cur = keep ?? sel.value;
  sel.innerHTML = `<option value="">${t("opt_box_custom")}</option>` +
    areas.map(a => `<option value="${a.id}">${SHAPE_ICON[a.geom.type] || ""} ${escHtml(a.name)}</option>`).join("");
  sel.value = areas.some(a => a.id === cur) ? cur : "";
}

async function boxApi(url, opts, keep) {
  try {
    const a = await fetchJSON(url, opts);
    await refreshAreas();
    rebuildGifAreaSelect(keep === undefined ? a.id : keep);
    $("boxHint").textContent = "";
    return a;
  } catch (err) { $("boxHint").textContent = "⚠ " + err.message.slice(0, 200); }
}

const jsonBody = body => ({ method: "PUT", headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(body) });

async function saveBoxAsArea() {
  const b = readBox();
  const name = $("boxName").value.trim();
  if (!b || !name) { $("boxHint").textContent = t("box_need_name"); return; }
  const a = await boxApi("/api/areas", {
    ...jsonBody({ name, geom: { type: "rect", ...b },
                  dataset: state.dataset, var: state.var, date: state.date,
                  vmin: state.vmin, vmax: state.vmax }), method: "POST" });
  if (a) $("boxName").value = "";
}

// Reshaping a saved area in place is what keeps a GIF series lined up after a
// tweak -- saving a second "... v2" area would defeat the point.
async function updateSelectedArea() {
  const id = $("gifArea").value, b = readBox();
  if (!id || !b) { $("boxHint").textContent = t("box_need_saved"); return; }
  const name = $("boxName").value.trim();
  await boxApi(`/api/areas/${id}`,
               jsonBody(name ? { name, geom: { type: "rect", ...b } }
                             : { geom: { type: "rect", ...b } }), id);
  $("boxName").value = "";
}

async function deleteSelectedArea() {
  const id = $("gifArea").value;
  if (!id) { $("boxHint").textContent = t("box_need_saved"); return; }
  const a = areas.find(x => x.id === id);
  if (!confirm(I18N[lang].confirm_delete(a.name))) return;
  await boxApi(`/api/areas/${id}`, { method: "DELETE" }, "");
}

function exportGif() {
  const b = readBox() || (() => {
    const m = map.getBounds();
    return { w: m.getWest(), s: m.getSouth(), e: m.getEast(), n: m.getNorth() };
  })();
  const bbox = [b.w, b.s, b.e, b.n].map(x => x.toFixed(2)).join(",");
  const u = `/api/export/timelapse?${tlQuery()}` +
    `&var=${state.var}&vmin=${$("vmin").value}&vmax=${$("vmax").value}` +
    `&fps=${$("fps").value}&bbox=${bbox}&dataset=${state.dataset}`;
  $("tlInfo").textContent = t("rendering");
  const a = document.createElement("a");
  a.href = u; a.download = "timelapse.gif"; a.click();
  setTimeout(() => { $("tlInfo").textContent = ""; }, 4000);
}

// ------------------------------------------------------- A/B swipe compare
const divider = $("swipeDivider");
let dividerX = null;
const labelA = L.DomUtil.create("div", "ab-label", map.getContainer());
const labelB = L.DomUtil.create("div", "ab-label", map.getContainer());
labelA.style.display = labelB.style.display = "none";

function updateClip() {
  if (!state.comparing) return;
  const nw = map.containerPointToLayerPoint([0, 0]);
  const se = map.containerPointToLayerPoint(map.getSize());
  const cx = map.containerPointToLayerPoint([dividerX, 0]).x;
  map.getPane("ovB").style.clip = `rect(${nw.y}px, ${se.x}px, ${se.y}px, ${cx}px)`;
  divider.style.left = dividerX + "px";
  labelA.style.left = (dividerX - 70) + "px"; labelA.textContent = "A " + state.date;
  labelB.style.left = (dividerX + 12) + "px"; labelB.textContent = "B " + state.dateB;
}

async function setCompare(on) {
  state.comparing = on;
  $("compareControls").classList.toggle("hidden", !on);
  divider.classList.toggle("hidden", !on);
  labelA.style.display = labelB.style.display = on ? "block" : "none";
  if (on) {
    document.querySelector("input[name=scaleMode][value=fixed]").checked = true;
    if (!state.dateB) state.dateB = state.date;
    $("dateB").value = state.dateB;
    dividerX = map.getSize().x / 2;
    overlayB.addTo(map);
    await refreshOverlay();
    updateClip();
  } else {
    overlayB.removeFrom(map);
    map.getPane("ovB").style.clip = "";
    refreshOverlay();
  }
}

divider.addEventListener("pointerdown", e => {
  e.preventDefault();
  const move = ev => { dividerX = Math.max(30, Math.min(map.getSize().x - 30, ev.clientX)); updateClip(); };
  const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up); };
  addEventListener("pointermove", move); addEventListener("pointerup", up);
});
map.on("move zoom resize", updateClip);

function shiftDateB(years) {
  const d = new Date(state.date + "T00:00:00Z");
  d.setUTCFullYear(d.getUTCFullYear() + years);
  state.dateB = nearestDate(d.toISOString().slice(0, 10));
  $("dateB").value = state.dateB;
  refreshOverlay().then(updateClip);
}

// --------------------------------------------------------------- measure
let measuring = false, measurePts = [], measureLine = null, measureTip = null;
function haversine(a, b) {
  const R = 6371, r = Math.PI / 180;
  const dlat = (b.lat - a.lat) * r, dlon = (b.lng - a.lng) * r;
  const h = Math.sin(dlat / 2) ** 2 +
    Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dlon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function clearMeasure() {
  measurePts = [];
  if (measureLine) { map.removeLayer(measureLine); measureLine = null; }
  if (measureTip) { map.removeLayer(measureTip); measureTip = null; }
}
function setMeasuring(on) {
  measuring = on;
  $("measureBtn").classList.toggle("active", on);
  map.getContainer().style.cursor = on ? "crosshair" : "";
  on ? map.doubleClickZoom.disable() : map.doubleClickZoom.enable();
  if (!on && measurePts.length < 2) clearMeasure();
}
function measureClick(latlng) {
  measurePts.push(latlng);
  if (!measureLine) measureLine = L.polyline(measurePts, { color: "#ff4136", weight: 3 }).addTo(map);
  else measureLine.setLatLngs(measurePts);
  let km = 0;
  for (let i = 1; i < measurePts.length; i++) km += haversine(measurePts[i - 1], measurePts[i]);
  const txt = km.toFixed(km < 100 ? 1 : 0) + " km";
  if (!measureTip) measureTip = L.marker(latlng, {
    icon: L.divIcon({ className: "measure-tip", html: txt, iconAnchor: [-8, 10] })
  }).addTo(map);
  else { measureTip.setLatLng(latlng); measureTip.getElement().innerHTML = txt; }
}

// ------------------------------------------------------------ draw shapes
let draw = null; // {type, pts:[LatLng], layer}
// Where a finished shape goes: null = save it as a new area (the Areas tab),
// "box" = feed the GIF crop box instead of saving anything.
let drawInto = null;
const DRAW_STYLE = { color: "#b10dc9", weight: 2, dashArray: "5,5", fillOpacity: 0.08 };

function normLon(lng) { return ((lng + 180) % 360 + 360) % 360 - 180; }

function startDraw(type, into = null) {
  setMeasuring(false); clearMeasure(); cancelDraw();
  draw = { type, pts: [], layer: null };
  drawInto = into;
  map.getContainer().style.cursor = "crosshair";
  map.doubleClickZoom.disable();
  $(into === "box" ? "boxHint" : "drawHint").textContent = t("hint_" + type);
}

function cancelDraw() {
  if (!draw) return;
  if (draw.layer) map.removeLayer(draw.layer);
  draw = null;
  map.getContainer().style.cursor = "";
  map.doubleClickZoom.enable();
  $("drawHint").textContent = "";
  $("boxHint").textContent = "";
}

function setDrawLayer(layer) {
  if (draw.layer) map.removeLayer(draw.layer);
  draw.layer = layer.addTo(map);
}

function drawPreview(cursor) {
  if (!draw || !draw.pts.length) return;
  const a = draw.pts[0];
  if (draw.type === "rect") {
    setDrawLayer(L.rectangle(L.latLngBounds(a, cursor), DRAW_STYLE));
  } else if (draw.type === "circle") {
    setDrawLayer(L.circle(a, { ...DRAW_STYLE, radius: map.distance(a, cursor) }));
  } else if (draw.type === "polygon") {
    setDrawLayer(L.polyline([...draw.pts, cursor], DRAW_STYLE));
  }
}

function drawClick(latlng) {
  const { type } = draw;
  if (type === "point") {
    finishDraw({ type: "point", lat: +latlng.lat.toFixed(4), lon: +normLon(latlng.lng).toFixed(4) });
  } else if (type === "rect") {
    if (!draw.pts.length) { draw.pts.push(latlng); return; }
    const b = L.latLngBounds(draw.pts[0], latlng);
    finishDraw({ type: "rect",
      w: +normLon(b.getWest()).toFixed(4), s: +b.getSouth().toFixed(4),
      e: +normLon(b.getEast()).toFixed(4), n: +b.getNorth().toFixed(4) });
  } else if (type === "circle") {
    if (!draw.pts.length) { draw.pts.push(latlng); return; }
    const c = draw.pts[0];
    finishDraw({ type: "circle", lat: +c.lat.toFixed(4), lon: +normLon(c.lng).toFixed(4),
                 radius_m: Math.round(map.distance(c, latlng)) });
  } else if (type === "polygon") {
    const last = draw.pts[draw.pts.length - 1];
    if (!last || map.distance(last, latlng) > 1) draw.pts.push(latlng);
    drawPreview(latlng);
  }
}

function closePolygon() {
  if (!draw || draw.type !== "polygon" || draw.pts.length < 3) { cancelDraw(); return; }
  finishDraw({ type: "polygon",
    latlngs: draw.pts.map(p => [+p.lat.toFixed(4), +normLon(p.lng).toFixed(4)]) });
}

async function finishDraw(geom) {
  const into = drawInto;
  drawInto = null;
  cancelDraw();
  if (into === "box") {                    // feeds the GIF crop box, saves nothing
    writeBox({ w: geom.w, s: geom.s, e: geom.e, n: geom.n });
    $("gifArea").value = "";
    return;
  }
  const name = prompt(t("area_name_prompt"));
  if (!name || !name.trim()) return;
  try {
    await fetchJSON("/api/areas", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim(), geom, dataset: state.dataset,
                             var: state.var, date: state.date,
                             vmin: state.vmin, vmax: state.vmax }),
    });
    await refreshAreas();
  } catch (err) { alert(err.message); }
}

// ------------------------------------------------------------ saved areas
let areas = [];
const areaMedia = {}; // id -> [{name,size}]
const areaLayer = L.layerGroup();   // added/removed by syncMapLayers
const SHAPE_ICON = { point: "•", rect: "▭", circle: "◯", polygon: "⬠" };

function areaBounds(g) {
  if (g.type === "point") return [[g.lat - 0.7, g.lon - 1], [g.lat + 0.7, g.lon + 1]];
  if (g.type === "rect") return [[g.s, g.w], [g.n, g.e]];
  if (g.type === "circle") {
    const dlat = g.radius_m / 111000;
    const dlon = g.radius_m / (111000 * Math.max(0.1, Math.cos(g.lat * Math.PI / 180)));
    return [[g.lat - dlat, g.lon - dlon], [g.lat + dlat, g.lon + dlon]];
  }
  const lats = g.latlngs.map(p => p[0]), lons = g.latlngs.map(p => p[1]);
  return [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]];
}

function geomLayer(g) {
  const st = { color: "#b10dc9", weight: 2, fillOpacity: 0.05 };
  if (g.type === "point") return L.circleMarker([g.lat, g.lon], { ...st, radius: 5 });
  if (g.type === "rect") return L.rectangle([[g.s, g.w], [g.n, g.e]], st);
  if (g.type === "circle") return L.circle([g.lat, g.lon], { ...st, radius: g.radius_m });
  return L.polygon(g.latlngs, st);
}

function renderAreaLayer() {
  areaLayer.clearLayers();
  for (const a of areas)
    geomLayer(a.geom).bindTooltip(a.name, { className: "station-tip" }).addTo(areaLayer);
}

async function setAreaShared(a, shared) {
  try {
    await fetchJSON(`/api/areas/${a.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shared }),
    });
    await refreshAreas();
  } catch (err) { alert(err.message); }
}

async function refreshAreas() {
  try { areas = await fetchJSON("/api/areas"); } catch (err) { return; }
  await Promise.all(areas.map(async a => {
    try { areaMedia[a.id] = await fetchJSON(`/api/areas/${a.id}/media`); }
    catch (err) { areaMedia[a.id] = []; }
  }));
  renderAreaList(); renderAreaLayer(); rebuildGifAreaSelect();
}

function renderAreaList() {
  const box = $("areaList");
  if (!box) return;
  box.innerHTML = "";
  if (!areas.length) {
    box.innerHTML = `<span class="muted">${t("no_areas")}</span>`;
    return;
  }
  for (const a of areas) {
    const div = document.createElement("div");
    div.className = "areaItem";
    const dsName = (state.meta[a.dataset] || {}).name || a.dataset;
    const head = document.createElement("div");
    head.innerHTML = `<b>${SHAPE_ICON[a.geom.type] || ""} ${a.name}</b>` +
      `<div class="muted">${dsName} · ${a.var} · ${a.date || ""}</div>`;
    div.appendChild(head);

    const row = document.createElement("div");
    row.className = "row";
    const mk = (label, fn, title) => {
      const b = document.createElement("button");
      b.textContent = label; if (title) b.title = title;
      b.onclick = fn; row.appendChild(b); return b;
    };
    mk(t("btn_goto"), () => gotoArea(a));
    mk(t("btn_snapshot"), () => areaSnapshot(a, row));
    mk(t("btn_area_gif"), () => areaGif(a, row));
    mk(t("btn_area_chart"), () => areaChart(a));
    if (a.owner === me) {
      mk("✎", () => renameArea(a));
      mk("✕", () => deleteArea(a));
      const lab = document.createElement("label");
      lab.className = "check";
      lab.title = t("help_shared");
      lab.innerHTML = `<input type="checkbox" ${a.shared ? "checked" : ""}> ` +
        `<span>${t("lbl_shared")}</span>`;
      lab.querySelector("input").onchange = e => setAreaShared(a, e.target.checked);
      row.appendChild(lab);
    } else {
      const who = document.createElement("span");
      who.className = "muted";
      who.textContent = t("lbl_shared_by")(a.owner);
      row.appendChild(who);
    }
    div.appendChild(row);

    const media = areaMedia[a.id] || [];
    if (media.length) {
      const ul = document.createElement("div");
      ul.className = "mediaList";
      for (const f of media) {
        const li = document.createElement("div");
        const kb = (f.size / 1024).toFixed(0);
        li.innerHTML = `<a href="/library/${a.id}/${f.name}" target="_blank">${f.name}</a>` +
          ` <span class="muted">${kb} KB</span> `;
        const del = document.createElement("button");
        del.textContent = "✕"; del.className = "mini";
        del.onclick = async () => {
          if (!confirm(I18N[lang].confirm_media_delete(f.name))) return;
          await fetch(`/api/areas/${a.id}/media/${f.name}`, { method: "DELETE" });
          refreshAreas();
        };
        li.appendChild(del);
        ul.appendChild(li);
      }
      div.appendChild(ul);
    }
    box.appendChild(div);
  }
}

async function gotoArea(a) {
  map.fitBounds(areaBounds(a.geom), { padding: [30, 30], maxZoom: 10 });
  if (state.meta[a.dataset]) await selectDataset(a.dataset);
  if (meta().variables[a.var]) { state.var = a.var; $("varSelect").value = a.var; }
  if (a.vmin != null && a.vmax != null) {
    document.querySelector("input[name=scaleMode][value=fixed]").checked = true;
    $("vmin").value = a.vmin; $("vmax").value = a.vmax;
  }
  if (a.date) setDate(a.date);
  else refreshOverlay();
}

function busy(row, on) {
  row.querySelectorAll("button").forEach(b => { b.disabled = on; });
}

async function areaSnapshot(a, row) {
  busy(row, true);
  state.vmin = +$("vmin").value; state.vmax = +$("vmax").value;
  try {
    await fetchJSON(`/api/areas/${a.id}/snapshot?dataset=${state.dataset}` +
      `&date=${state.date}&var=${state.var}&vmin=${state.vmin}&vmax=${state.vmax}`,
      { method: "POST" });
    await refreshAreas();
  } catch (err) { alert(err.message); busy(row, false); }
}

async function areaGif(a, row) {
  busy(row, true);
  $("drawHint").textContent = t("generating");
  try {
    await fetchJSON(`/api/areas/${a.id}/gif?dataset=${state.dataset}&${tlQuery()}` +
      `&var=${state.var}` +
      `&vmin=${$("vmin").value}&vmax=${$("vmax").value}&fps=${$("fps").value}`,
      { method: "POST" });
    await refreshAreas();
  } catch (err) { alert(err.message); busy(row, false); }
  $("drawHint").textContent = "";
}

async function areaChart(a) {
  ensureChart();
  const label = `${a.name} — ${t("mean_suffix")} (${a.var})`;
  const tmp = { label: label + " — " + t("loading"), points: [] };
  chartSeries.push(tmp); rebuildChart();
  try {
    const r = await fetchJSON(`/api/areas/${a.id}/mean_series?dataset=${a.dataset}&var=${a.var}`);
    tmp.label = label; tmp.points = r.points;
  } catch (err) {
    chartSeries.splice(chartSeries.indexOf(tmp), 1);
    alert(err.message);
  }
  rebuildChart();
}

async function renameArea(a) {
  const name = prompt(t("rename_prompt"), a.name);
  if (!name || !name.trim() || name.trim() === a.name) return;
  await fetchJSON(`/api/areas/${a.id}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name.trim() }),
  });
  refreshAreas();
}

async function deleteArea(a) {
  if (!confirm(I18N[lang].confirm_delete(a.name))) return;
  await fetch(`/api/areas/${a.id}`, { method: "DELETE" });
  refreshAreas();
}

// -------------------------------------------------------- map interaction
map.on("mousemove", e => { if (draw) drawPreview(e.latlng); });
map.on("dblclick", () => {
  if (draw && draw.type === "polygon") { closePolygon(); return; }
  if (draw) { cancelDraw(); return; }
  if (measuring) setMeasuring(false);
});
addEventListener("keydown", e => {
  if (e.key === "Escape") { cancelDraw(); setMeasuring(false); }
  if (e.target.tagName === "INPUT") return;
  if (e.key === "ArrowLeft") stepDate(-1);
  if (e.key === "ArrowRight") stepDate(1);
});

// ---------------------------------------------------------- click inspect
map.on("click", async e => {
  if (draw) { drawClick(e.latlng); return; }
  if (measuring) { measureClick(e.latlng); return; }
  const { lat, lng } = e.latlng;
  const lon = normLon(lng);
  const pop = L.popup().setLatLng(e.latlng).setContent(t("loading")).openOn(map);
  try {
    const a = await fetchJSON(`/api/point?lat=${lat}&lon=${lon}&date=${state.date}&dataset=${state.dataset}`);
    if (a.land) { pop.setContent(t("land")); return; }
    const fmt = v => v == null ? "—" : v;
    let html = `<b>${lat.toFixed(2)}°, ${lon.toFixed(2)}°</b><br>`;
    if (state.comparing) {
      const b = await fetchJSON(`/api/point?lat=${lat}&lon=${lon}&date=${state.dateB}&dataset=${state.dataset}`);
      const va = a.values[state.var], vb = b.values[state.var];
      const diff = (va != null && vb != null) ? (vb - va).toFixed(2) : "—";
      html += `A ${state.date}: <b>${fmt(va)}</b><br>B ${state.dateB}: <b>${fmt(vb)}</b><br>Δ (B−A): <b>${diff}</b><br>`;
    } else {
      for (const [v, val] of Object.entries(a.values))
        html += `${varLabel(v)}: <b>${fmt(val)}</b><br>`;
      html += `${t("ice")}: ${a.ice_fraction == null ? t("none") :
        (a.ice_fraction * 100).toFixed(0) + "%"}${a.is_ice ? " ❄" : ""}<br>`;
    }
    html += `<button onclick="chartPoint(${lat.toFixed(3)},${lon.toFixed(3)})">${t("chart_point")}</button>`;
    pop.setContent(html);
  } catch (err) { pop.setContent("error: " + err.message.slice(0, 200)); }
});

// ------------------------------------------------------------------ charts
const PALETTE = ["#0074d9", "#ff4136", "#2ecc40", "#ff851b", "#b10dc9",
                 "#39cccc", "#85144b", "#3d9970", "#111111", "#aaaaaa"];
let chart = null;
const chartSeries = []; // {label, points:[{date,value}]}

function ensureChart() {
  $("chartPanel").classList.remove("collapsed");
  if (chart) return;
  chart = new Chart($("chart"), {
    type: "line",
    data: { datasets: [] },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      parsing: false, normalized: true,
      scales: {
        x: { type: "linear", ticks: { callback: v => xTickLabel(v) } },
        y: { title: { display: true, text: t("yaxis") } },
      },
      plugins: {
        legend: { display: false }, // scrollable HTML legend instead
        tooltip: { callbacks: { title: it => xTickLabel(it[0].parsed.x) } },
      },
      elements: { point: { radius: 2 } },
    },
  });
}
const DAY = 86400000;
function xTickLabel(v) {
  return $("xMode").value === "doy" ? t("day") + " " + Math.round(v)
    : new Date(v * DAY).toISOString().slice(0, 10);
}
function doy(iso) {
  const d = new Date(iso + "T00:00:00Z");
  return Math.round((d - new Date(Date.UTC(d.getUTCFullYear(), 0, 0))) / DAY);
}

function rebuildHtmlLegend() {
  const box = $("chartLegend");
  box.innerHTML = "";
  chart.data.datasets.forEach((ds, i) => {
    const item = document.createElement("span");
    item.className = "legendItem" + (ds.hidden ? " off" : "");
    item.innerHTML = `<i style="background:${ds.borderColor}"></i>${ds.label}`;
    item.onclick = () => {
      ds.hidden = !ds.hidden;
      chart.update(); rebuildHtmlLegend();
    };
    box.appendChild(item);
  });
}

function rebuildChart() {
  ensureChart();
  const mode = $("xMode").value;
  const ds = [];
  let c = 0;
  for (const s of chartSeries) {
    if (mode === "date") {
      ds.push({
        label: s.label, borderColor: PALETTE[c % 10], backgroundColor: PALETTE[c % 10],
        data: s.points.filter(p => p.value != null)
          .map(p => ({ x: Date.parse(p.date) / DAY, y: p.value })),
        spanGaps: false, borderWidth: 1.5,
      });
      c++;
    } else {
      const byYear = {};
      for (const p of s.points) {
        if (p.value == null) continue;
        (byYear[p.date.slice(0, 4)] ??= []).push({ x: doy(p.date), y: p.value });
      }
      for (const [y, pts] of Object.entries(byYear)) {
        ds.push({ label: `${s.label} ${y}`, borderColor: PALETTE[c % 10],
                  backgroundColor: PALETTE[c % 10], data: pts, borderWidth: 1.2 });
        c++;
      }
    }
  }
  chart.data.datasets = ds;
  chart.update();
  rebuildHtmlLegend();
}

window.chartPoint = async (lat, lon, label, spec, dsid, varName) => {
  ensureChart();
  dsid = dsid || state.dataset;
  varName = varName || state.var;
  label = label || `${lat.toFixed(2)}°, ${lon.toFixed(2)}° (${state.meta[dsid].name} ${varName})`;
  const tmp = { label: label + " — " + t("loading"), points: [] };
  chartSeries.push(tmp); rebuildChart();
  try {
    tmp.points = await fetchPointSeries(lat, lon, spec, dsid, varName);
    tmp.label = label;
  } catch (err) {
    chartSeries.splice(chartSeries.indexOf(tmp), 1);
    alert(err.message.slice(0, 300));
  }
  rebuildChart();
  map.closePopup();
};
/* Date spec grammar, used internally by the Data tab's per-coordinate date
   builder (resolveRowDates serializes structured UI state to this grammar
   rather than users typing it):
     spec  = item (";" item)*
     item  = dates ["@" years]        with @: dates use DD-MM; without: DD-MM-YYYY
     dates = tok ("," tok)*           tok = date | date..date, optional /stepDays
     years = y ("," y)*               y = YYYY | YYYY..YYYY, optional /stepYears
   Returns a sorted unique ISO date list, or null for empty input.
   Throws Error(badToken) on syntax errors. */
function parseDateSpec(text) {
  text = text.trim();
  if (!text) return null;
  const out = new Set();
  for (const item of text.split(";")) {
    if (!item.trim()) continue;
    const [dpart, ypart] = item.split("@");
    let years = [null];
    if (ypart !== undefined) {
      years = [];
      for (const yt of ypart.split(",")) {
        const m = yt.trim().match(/^(\d{4})(?:\.\.(\d{4}))?(?:\/(\d+))?$/);
        if (!m) throw new Error(yt.trim());
        for (let y = +m[1]; y <= +(m[2] ?? m[1]); y += +(m[3] ?? 1)) years.push(y);
      }
    }
    const re = ypart === undefined
      ? /^(\d{2}-\d{2}-\d{4})(?:\.\.(\d{2}-\d{2}-\d{4}))?(?:\/(\d+))?$/
      : /^(\d{2}-\d{2})(?:\.\.(\d{2}-\d{2}))?(?:\/(\d+))?$/;
    // "dd-mm[-yyyy]" -> ISO "yyyy-mm-dd" (year from @years part if absent)
    const iso = (tok, y) => {
      const p = tok.split("-");
      return p.length === 3 ? `${p[2]}-${p[1]}-${p[0]}` : `${y}-${p[1]}-${p[0]}`;
    };
    for (const dt of dpart.split(",")) {
      const tok = dt.trim();
      if (!tok) continue;
      const m = tok.match(re);
      if (!m || +(m[3] ?? 1) < 1) throw new Error(tok);
      // Date.parse rolls invalid days over (Feb 29 -> Mar 1); round-trip
      // check turns them into NaN so they are skipped, not shifted
      const parseDay = s => {
        const n = Date.parse(s + "T00:00:00Z");
        return new Date(n).toISOString().slice(0, 10) === s ? n : NaN;
      };
      for (const y of years) {
        const a = parseDay(iso(m[1], y));
        const b = m[2] ? parseDay(iso(m[2], y)) : a;
        for (let d = a; d <= b; d += +(m[3] ?? 1) * DAY)
          out.add(new Date(d).toISOString().slice(0, 10));
      }
    }
  }
  if (!out.size) throw new Error(text.slice(0, 30));
  return [...out].sort();
}

function dateRuns(dates) { // consecutive-day runs -> [[first, last], ...]
  const runs = [];
  for (const d of dates) {
    const last = runs[runs.length - 1];
    if (last && Date.parse(d) - Date.parse(last[1]) === DAY) last[1] = d;
    else runs.push([d, d]);
  }
  return runs;
}

async function fetchPointSeries(lat, lon, spec, dsid, varName) {
  dsid = dsid || state.dataset;
  varName = varName || state.var;
  const base = `/api/series?lat=${lat}&lon=${lon}&var=${varName}&dataset=${dsid}`;
  if (!spec) return (await fetchJSON(base)).points;
  let runs = dateRuns(spec);
  // ponytail: many sparse runs -> one min..max request, filter client-side
  if (runs.length > 30) runs = [[spec[0], spec[spec.length - 1]]];
  const want = new Set(spec), pts = [];
  for (const [a, b] of runs) {
    const r = await fetchJSON(`${base}&start=${a}&end=${b}`);
    for (const p of r.points) if (want.has(p.date)) pts.push(p);
  }
  return pts;
}

// the coordinate tool has its own dataset (default MUR), independent of the map
const coordsDs = () => $("coordsDataset").value;

// ---------------------------------------------------- data tab: coordinates
// Each row: {lat, lon, name, checked, expanded, dateItems:[], yearItems:[]}
// dateItems: {type:"date", value:"YYYY-MM-DD"} | {type:"range", from, to, step}
// yearItems: {type:"year", value:N} | {type:"yearRange", from, to, step}
// name: geographic name for this point, used as the PDF title/header ("" until named)
let coordRows = [];

// Every coordinate row is a dot on the map with a permanent label above it
// (its name, or "lat, lon" until named). Redrawn wholesale on every change --
// the list is short.
const coordLayer = L.layerGroup().addTo(map);
const escHtml = s => String(s).replace(/[<>&]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));

function renderCoordLayer() {
  coordLayer.clearLayers();
  for (const row of coordRows) {
    const label = row.name || `${row.lat.toFixed(3)}, ${row.lon.toFixed(3)}`;
    // Magenta with a white ring: the one hue that appears in neither the SST
    // ramp (viridis: purple->green->yellow) nor the anomaly ramp (blue-white-
    // red), and the ring keeps it readable on whichever of those it lands on.
    L.circleMarker([row.lat, row.lon],
      { radius: 6, color: "#ffffff", weight: 3, fillColor: "#ff10c8",
        opacity: 1, fillOpacity: 1 })
      .bindTooltip(escHtml(label),
        { permanent: true, direction: "top", offset: [0, -4], className: "station-tip" })
      .addTo(coordLayer);
  }
}

function addCoordsFromText() {
  let added = 0;
  for (const line of $("coordsAdd").value.split("\n")) {
    const m = line.match(/-?\d+(?:\.\d+)?/g);
    if (m && m.length >= 2 && Math.abs(+m[0]) <= 90) {
      coordRows.push({ lat: +m[0], lon: +m[1], name: "", checked: true, expanded: true,
                       dateItems: [], yearItems: [] });
      added++;
    }
  }
  if (!added) { alert(t("coords_none")); return; }
  $("coordsAdd").value = "";
  renderCoordRows();
  fitCoords();
}

// Frame every coordinate row so a newly added point is always visible.
// maxZoom keeps a single point from slamming to street level.
function fitCoords() {
  if (!coordRows.length) return;
  map.fitBounds(L.latLngBounds(coordRows.map(r => [r.lat, r.lon])).pad(0.25),
                { maxZoom: 12 });
}

const fmtMD = iso => { const [, m, d] = (iso || "").split("-"); return `${d}-${m}`; };

// Serializes a row's structured date/year items into the parseDateSpec
// grammar (never shown to the user) so date resolution reuses that one
// tested implementation instead of a second parallel one.
function rowSpecText(row) {
  if (!row.dateItems.length || !row.yearItems.length) return null;
  for (const it of row.dateItems) {
    if (it.type === "date" ? !isFullMD(it.value)
                           : !(isFullMD(it.from) && isFullMD(it.to))) return null;
  }
  for (const it of row.yearItems) {
    if (it.type === "year" ? !it.value : (!it.from || !it.to)) return null;
  }
  const dparts = row.dateItems.map(it => {
    const s = it.type === "date" ? fmtMD(it.value) : `${fmtMD(it.from)}..${fmtMD(it.to)}`;
    return (it.type === "range" && it.step > 1) ? `${s}/${it.step}` : s;
  });
  const yparts = row.yearItems.map(it => {
    const s = it.type === "year" ? String(it.value) : `${it.from}..${it.to}`;
    return (it.type === "yearRange" && it.step > 1) ? `${s}/${it.step}` : s;
  });
  return dparts.join(",") + "@" + yparts.join(",");
}

function resolveRowDates(row) { // ISO date array, or null (incomplete/bad)
  const text = rowSpecText(row);
  if (!text) return null;
  try { return parseDateSpec(text); }
  catch (err) { return null; }
}

function rowSummary(row) {
  if (!row.dateItems.length) return t("row_no_dates");
  const dates = resolveRowDates(row);
  if (!dates) return t("row_bad_dates");
  return t("row_n_dates")(dates.length, dates[0], dates[dates.length - 1]);
}

function dateItemHtml(row, it, ridx, iidx) {
  const k = `data-kind="dateItem" data-ridx="${ridx}" data-iidx="${iidx}"`;
  const rm = `<button class="mini" data-act="removeDateItem" data-ridx="${ridx}" data-iidx="${iidx}">✕</button>`;
  if (it.type === "date")
    return `<div class="row">${dmyTripletHtml(it.value, `${k} data-field="value"`, false)}${rm}</div>`;
  return `<div class="row">${dmyTripletHtml(it.from, `${k} data-field="from"`, false)}` +
    ` .. ${dmyTripletHtml(it.to, `${k} data-field="to"`, false)} / ` +
    `<input type="number" ${k} data-field="step" min="1" value="${it.step}" style="width:3.5em"> ` +
    `<span class="muted">${t("lbl_days")}</span>${rm}</div>`;
}

function yearItemHtml(it, ridx, iidx) {
  const k = `data-kind="yearItem" data-ridx="${ridx}" data-iidx="${iidx}"`;
  const rm = `<button class="mini" data-act="removeYearItem" data-ridx="${ridx}" data-iidx="${iidx}">✕</button>`;
  if (it.type === "year")
    return `<div class="row"><input type="number" ${k} data-field="value" value="${it.value ?? ""}" style="width:5.5em">${rm}</div>`;
  return `<div class="row"><input type="number" ${k} data-field="from" value="${it.from ?? ""}" style="width:5.5em">` +
    `.. <input type="number" ${k} data-field="to" value="${it.to ?? ""}" style="width:5.5em"> / ` +
    `<input type="number" ${k} data-field="step" min="1" value="${it.step}" style="width:3.5em"> ` +
    `<span class="muted">${t("lbl_years")}</span>${rm}</div>`;
}

// The dates+years form of one row. Shared by the Data tab (ridx = the row's
// index) and the Timelapse tab's single pseudo-row (ridx -1, see tlRow).
function dateYearFormHtml(row, ridx) {
  // A row's items are one kind or the other, never mixed -- once the
  // first item picks "date"/"range" (or "year"/"yearRange"), the other
  // add-button is hidden until the list is emptied again.
  const dateKind = row.dateItems[0]?.type;
  const yearKind = row.yearItems[0]?.type;
  return `<div class="dateItems">` +
    row.dateItems.map((it, iidx) => dateItemHtml(row, it, ridx, iidx)).join("") +
    `</div><div class="row">` +
    (dateKind !== "range" ? `<button class="mini" data-act="addDate" data-ridx="${ridx}">${t("btn_add_date")}</button>` : "") +
    (dateKind !== "date" ? `<button class="mini" data-act="addRange" data-ridx="${ridx}">${t("btn_add_range")}</button>` : "") +
    `</div>` +
    `<div class="row muted yearsHead">${t("lbl_years_section")}</div>` +
    `<div class="yearItems">` +
    row.yearItems.map((it, iidx) => yearItemHtml(it, ridx, iidx)).join("") +
    `</div><div class="row">` +
    (yearKind !== "yearRange" ? `<button class="mini" data-act="addYear" data-ridx="${ridx}">${t("btn_add_year")}</button>` : "") +
    (yearKind !== "year" ? `<button class="mini" data-act="addYearRange" data-ridx="${ridx}">${t("btn_add_year_range")}</button>` : "") +
    `</div>`;
}

// ridx -1 addresses the timelapse pseudo-row, any other value a Data-tab row,
// so one pair of handlers drives both editors.
const rowAt = ridx => (ridx < 0 ? tlRow : coordRows[ridx]);

function renderTlSpec() {
  const box = $("tlSpec");
  if (!box) return;
  box.classList.toggle("hidden", !specMode());
  box.innerHTML = specMode()
    ? `<div class="rowForm">${dateYearFormHtml(tlRow, -1)}` +
      `<span class="muted rowSummary">${rowSummary(tlRow)}</span></div>`
    : "";
  $("tlRangeRows").classList.toggle("hidden", specMode());
}

function renderRows() { renderCoordRows(); renderTlSpec(); }

function renderCoordRows() {
  const box = $("coordRows");
  if (!box) return;
  box.innerHTML = "";
  coordRows.forEach((row, ridx) => {
    const div = document.createElement("div");
    div.className = "coordRow";
    let html = `<div class="row">` +
      `<input type="checkbox" class="rowCheck" data-ridx="${ridx}" ${row.checked ? "checked" : ""}>` +
      `<b>${row.name ? row.name + " — " : ""}${row.lat.toFixed(3)}, ${row.lon.toFixed(3)}</b>` +
      `<button class="mini" data-act="renameRow" data-ridx="${ridx}">${t("btn_rename_point")}</button>` +
      `<button class="mini" data-act="toggleExpand" data-ridx="${ridx}">${row.expanded ? "▴" : "▾"} ${t("lbl_dates")}</button>` +
      `<button class="mini" data-act="removeRow" data-ridx="${ridx}">✕</button></div>`;
    if (row.expanded) {
      html += `<div class="rowForm">` + dateYearFormHtml(row, ridx);
      html += `<div class="row"><button class="mini" data-act="copyToChecked" data-ridx="${ridx}">${t("btn_copy_dates")}</button></div>` +
        `<span class="muted rowSummary">${rowSummary(row)}</span></div>`;
    }
    div.innerHTML = html;
    box.appendChild(div);
  });
  renderCoordLayer();
}

function rowFormClick(e) {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const ridx = +b.dataset.ridx, row = rowAt(ridx);
  const iidx = b.dataset.iidx !== undefined ? +b.dataset.iidx : null;
  const act = b.dataset.act;
  if (act === "toggleExpand") row.expanded = !row.expanded;
  else if (act === "removeRow") coordRows.splice(ridx, 1);
  else if (act === "renameRow") {
    const name = prompt(t("point_name_prompt"), row.name || `${row.lat}, ${row.lon}`);
    if (name) row.name = name.trim();
  }
  else if (act === "addDate") row.dateItems.push({ type: "date", value: "" });
  else if (act === "addRange") row.dateItems.push({ type: "range", from: "", to: "", step: 1 });
  else if (act === "removeDateItem") row.dateItems.splice(iidx, 1);
  else if (act === "addYear") row.yearItems.push({ type: "year", value: new Date(state.date || "2020").getFullYear() });
  else if (act === "addYearRange") row.yearItems.push({ type: "yearRange", from: 2003, to: new Date(state.date || "2020").getFullYear(), step: 1 });
  else if (act === "removeYearItem") row.yearItems.splice(iidx, 1);
  else if (act === "copyToChecked") {
    coordRows.forEach((r, i) => {
      if (r.checked && i !== ridx) {
        r.dateItems = JSON.parse(JSON.stringify(row.dateItems));
        r.yearItems = JSON.parse(JSON.stringify(row.yearItems));
      }
    });
  }
  renderRows();
}

function rowFormChange(e) {
  const el = e.target;
  if (el.dataset.ridx === undefined) return;
  const row = rowAt(+el.dataset.ridx);
  if (el.classList.contains("rowCheck")) { row.checked = el.checked; return; }
  if (el.dataset.iidx === undefined) return;
  const iidx = +el.dataset.iidx, field = el.dataset.field;
  const it = (el.dataset.kind === "dateItem" ? row.dateItems : row.yearItems)[iidx];
  if (!it) return;
  if (el.dataset.part) {
    // Commit even a half-typed day/month, and refresh only the summary --
    // re-rendering the row here is what used to erase what the user typed.
    it[field] = mdPartialIso(el.closest(".dmy"));
    const sum = el.closest(".coordRow")?.querySelector(".rowSummary");
    if (sum) sum.textContent = rowSummary(row);
    return;
  }
  it[field] = field === "step" ? Math.max(1, +el.value || 1)
    : el.type === "number" ? +el.value : el.value;
  renderRows();
}

for (const id of ["coordRows", "tlSpec"]) {
  $(id)?.addEventListener("click", rowFormClick);
  $(id)?.addEventListener("change", rowFormChange);
}

// ------------------------------------------------------ data tab: download
async function startDownload() {
  const checked = coordRows.filter(r => r.checked);
  if (!checked.length) { alert(t("coords_none")); return; }
  const wantPdf = $("alsoPdf").checked;
  const bad = [], points = [];
  for (const r of checked) {
    const dates = resolveRowDates(r);
    if (!dates) { bad.push(`${r.lat}, ${r.lon}`); continue; }
    if (wantPdf && !r.name) {
      r.name = (prompt(t("point_name_prompt"), `${r.lat}, ${r.lon}`) || `${r.lat}, ${r.lon}`).trim();
    }
    points.push({ lat: r.lat, lon: r.lon, label: r.name || `${r.lat}, ${r.lon}`, dates });
  }
  if (bad.length) { alert(t("rows_bad_dates") + "\n" + bad.join("\n")); return; }
  renderCoordRows();

  $("downloadBtn").disabled = true;
  $("batchProg").classList.remove("hidden");
  $("batchProg").max = points.length; $("batchProg").value = 0;
  $("batchResults").innerHTML = "";
  try {
    const job = await fetchJSON("/api/batch_job", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset: coordsDs(), points,
                             generate_pdf: $("alsoPdf").checked,
                             refresh_data: $("refreshData").checked }),
    });
    await pollBatchJob(job.id);
  } catch (err) {
    $("batchResults").textContent = "⚠ " + err.message.slice(0, 300);
  }
  $("downloadBtn").disabled = false;
  $("batchProg").classList.add("hidden");
}

const STAGE_KEY = { queued: "st_queued", fetching: "st_fetching", rendering: "st_rendering" };

// Fetch is one bulk request per point (deliberately -- not one request per
// date, which would hammer remote APIs), so there's no real "37/77 dates"
// signal to show: an indeterminate native <progress> (no value attr) is the
// honest representation of "in progress, fraction unknown". Render progress
// IS real -- parsed live from Quarto's own per-chunk console output.
function stageBarsHtml(p) {
  const fetchBar = p.stage === "fetching"
    ? `<progress class="stageBar stageFetch"></progress>`
    : `<progress class="stageBar stageFetch" value="1" max="1"></progress>`;
  const renderBar = p.stage === "rendering"
    ? `<progress class="stageBar stageRender" value="${p.render_frac ?? 0}" max="1"></progress>`
    : "";
  return `<div class="stageBars">${fetchBar}${renderBar}</div>`;
}

function renderBatchResults(job) {
  $("batchProg").value = job.done; $("batchProg").max = job.total;
  const lines = job.points.map(p => {
    const cached = p.from_cache ? ` <span class="muted">(${t("cached_note")})</span>` : "";
    // `download` (not target=_blank): a PDF link would otherwise open in
    // Chrome's viewer, while the CSV downloads only because Chrome cannot
    // render it inline. Same-origin, so the attribute is honoured.
    if (p.pdf_url) return `<div>${p.label}: <a href="${p.pdf_url}" download>${t("pdf_ready")}</a>${cached}</div>`;
    if (p.error) return `<div>${p.label}: ⚠ ${p.error}</div>`;
    if (p.status === "done") return `<div>${p.label}: ${t("st_done")}${cached}</div>`;
    const bars = (p.stage === "fetching" || p.stage === "rendering") ? stageBarsHtml(p) : "";
    return `<div>${p.label}: ${t(STAGE_KEY[p.stage] || "st_pending")}${bars}</div>`;
  });
  if (job.csv_url) lines.push(`<div><a href="${job.csv_url}" download>${t("csv_ready")}</a></div>`);
  $("batchResults").innerHTML = lines.join("");
}

async function pollBatchJob(id) {
  for (;;) {
    const job = await fetchJSON(`/api/batch_job_status?id=${id}`);
    renderBatchResults(job);
    if (job.state === "done") return;
    await new Promise(r => setTimeout(r, 1000));
  }
}

function chartCsv() {
  let rows = ["series,date,value"];
  for (const s of chartSeries)
    for (const p of s.points)
      rows.push(`"${s.label}",${p.date},${p.value ?? ""}`);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
  a.download = "sst_chart_data.csv"; a.click();
}

// -------------------------------------------------------------- wire up UI
$("signoutBtn").onclick = async () => {
  await fetch("/api/logout", { method: "POST" });
  location.href = "/login";
};
$("langBtn").onclick = () => { lang = lang === "en" ? "ru" : "en"; localStorage.setItem("sst_lang", lang); applyLang(); };
$("datasetSelect").onchange = e => selectDataset(e.target.value);
$("varSelect").onchange = e => { state.var = e.target.value; refreshOverlay(); };
$("opacity").oninput = e => { overlayA.setOpacity(e.target.value / 100); overlayB.setOpacity(e.target.value / 100); };
document.querySelectorAll("input[name=scaleMode]").forEach(r => r.onchange = refreshOverlay);
$("vmin").onchange = $("vmax").onchange = () => { if (scaleIsFixed()) refreshOverlay(); };
$("dateInput").onchange = e => setDate(e.target.value);
$("prevBtn").onclick = () => stepDate(-1);
$("nextBtn").onclick = () => stepDate(1);
$("playBtn").onclick = togglePlay;
$("sameDayYear").onchange = () => { stopPlay(); renderTlSpec(); };
$("tlScrub").oninput = e => { if (tlDates.length) showFrame(+e.target.value); };
$("fps").onchange = () => { if (tlTimer) { clearInterval(tlTimer);
  tlTimer = setInterval(() => showFrame((tlIdx + 1) % tlDates.length), 1000 / +$("fps").value); } };
$("exportGifBtn").onclick = exportGif;
$("gifArea").onchange = e => {
  const a = areas.find(x => x.id === e.target.value);
  if (!a) return;
  const [[s, w], [n, ee]] = areaBounds(a.geom);
  writeBox({ w, s, e: ee, n });
};
for (const id of ["boxW", "boxS", "boxE", "boxN"])
  $(id).oninput = () => { $("gifArea").value = ""; drawBox(); };
$("boxFromMapBtn").onclick = boxFromMap;
$("boxToMapBtn").onclick = () => {
  const b = readBox();
  if (b) map.fitBounds([[b.s, b.w], [b.n, b.e]]);
};
$("boxSaveBtn").onclick = saveBoxAsArea;
$("boxDrawBtn").onclick = () => startDraw("rect", "box");
$("boxUpdateBtn").onclick = updateSelectedArea;
$("boxDeleteBtn").onclick = deleteSelectedArea;
$("coordsAddBtn").onclick = addCoordsFromText;
$("selectAllBtn").onclick = () => { coordRows.forEach(r => r.checked = true); renderCoordRows(); };
$("deselectAllBtn").onclick = () => { coordRows.forEach(r => r.checked = false); renderCoordRows(); };
$("downloadBtn").onclick = startDownload;
function setTab(id) {
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === id));
  document.querySelectorAll(".tabPane").forEach(p => p.classList.toggle("hidden", p.id !== "tab-" + id));
  localStorage.setItem("sst_tab", id);
  syncMapLayers();
}

// Map furniture follows the open tab: the GIF crop box belongs to Timelapse
// and the saved-area outlines to Areas. Leaving either on the map from every
// other tab is just clutter over the data. The Areas tab's "show on map"
// checkbox still wins inside its own tab.
function syncMapLayers() {
  const tab = localStorage.getItem("sst_tab");
  if (tab === "tl") drawBox(); else map.removeLayer(boxLayer);
  if (tab === "areas" && $("areasToggle").checked) areaLayer.addTo(map);
  else map.removeLayer(areaLayer);
}
document.querySelectorAll("#tabs button").forEach(b => { b.onclick = () => setTab(b.dataset.tab); });
setTab(localStorage.getItem("sst_tab") || "map");
$("compareToggle").onchange = e => setCompare(e.target.checked);
$("dateB").onchange = e => { state.dateB = nearestDate(e.target.value); $("dateB").value = state.dateB; refreshOverlay().then(updateClip); };
$("minusYearBtn").onclick = () => shiftDateB(-1);
$("plusYearBtn").onclick = () => shiftDateB(1);
$("measureBtn").onclick = () => { cancelDraw(); clearMeasure(); setMeasuring(!measuring); };
$("clearMeasureBtn").onclick = () => { setMeasuring(false); clearMeasure(); };
$("areasToggle").onchange = syncMapLayers;
$("drawPointBtn").onclick = () => startDraw("point");
$("drawRectBtn").onclick = () => startDraw("rect");
$("drawCircleBtn").onclick = () => startDraw("circle");
$("drawPolyBtn").onclick = () => startDraw("polygon");
$("downloadOverlayBtn").onclick = () => {
  const a = document.createElement("a");
  a.href = overlayURL(state.date, true);
  a.download = `${state.dataset}_${state.date}_${state.var}.png`; a.click();
};
$("xMode").onchange = rebuildChart;
$("chartPngBtn").onclick = () => {
  if (!chart) return;
  const a = document.createElement("a");
  a.href = chart.toBase64Image(); a.download = "sst_chart.png"; a.click();
};
$("chartCsvBtn").onclick = chartCsv;
$("chartClearBtn").onclick = () => { chartSeries.length = 0; if (chart) rebuildChart(); };
$("chartCollapseBtn").onclick = () => $("chartPanel").classList.toggle("collapsed");

// ------------------------------------------------------------------- init
// ------------------------------------------------------------ loading screen
// Upper bound on how long the splash waits for the first health sweep. The
// server's cold sweep probes every source at once on a short timeout, so this
// resolves in ~1 s when the sources are healthy and ~6 s worst case when one
// is dead (FIRST_PROBE_TIMEOUT_S x the host's two DNS addresses). The cap is
// only a safety net against a pathological hang -- reaching it means the dots
// are still grey when the app opens, which is the thing we are avoiding.
const SPLASH_HEALTH_CAP_MS = 12000;
const SPLASH_MIN_MS = 900;      // don't flash-and-vanish on a warm cache
const TIP_ROTATE_MS = 6500;
const TIPS = ["tip_scale", "tip_health", "tip_global",
              "tip_sameday", "tip_data", "tip_reports"];

function splashSet(frac, stepKey) {
  $("splashBar").style.width = Math.round(frac * 100) + "%";
  if (stepKey) $("splashStep").textContent = t(stepKey);
}

function startSplashTips() {
  const box = $("splashTip").parentElement;
  let i = Math.floor(Math.random() * TIPS.length);
  $("splashTip").textContent = t(TIPS[i]);
  return setInterval(() => {
    box.classList.add("fade");
    setTimeout(() => {
      i = (i + 1) % TIPS.length;
      $("splashTip").textContent = t(TIPS[i]);
      box.classList.remove("fade");
    }, 400);
  }, TIP_ROTATE_MS);
}

async function waitFirstHealthSweep(capMs, onProgress) {
  const t0 = Date.now();
  while (Date.now() - t0 < capMs) {
    try {
      const h = await (await fetch("/api/health")).json();
      if (h.sources.every(s => s.status !== "unknown")) return true;
    } catch { /* server still coming up */ }
    // this is the one step that can take seconds, so it reports its own
    // progress against the cap -- a bar frozen at 0% reads as a hang
    if (onProgress) onProgress((Date.now() - t0) / capMs);
    await new Promise(r => setTimeout(r, 350));
  }
  return false;
}

// Warm the remote date axes so the first switch to MUR/ERDDAP is instant
// instead of a multi-second stall (the server disk-caches them for 24 h).
// Deliberately after the splash and fire-and-forget, and only for sources the
// probe just said are reachable -- a dead host costs nothing.
async function prefetchRemoteDates() {
  try {
    const h = await (await fetch("/api/health")).json();
    for (const s of h.sources)
      if (s.kind === "remote" && s.status === "ok" && state.meta[s.id])
        fetch(`/api/dataset_dates?dataset=${encodeURIComponent(s.id)}`).catch(() => {});
  } catch { /* nothing to warm */ }
}

(async function init() {
  const t0 = Date.now();
  applyLang();                 // so the splash text is in the right language
  $("splashSub").textContent = t("splash_sub");
  const tipTimer = startSplashTips();
  pollHealth();                // strip is live behind the splash

  try {
    me = (await fetchJSON("/api/me")).user;
    $("whoami").textContent = me;
    // The public server ships no R/Quarto/TeX, so hide the PDF option there
    // rather than letting every point in a batch fail on a missing toolchain.
    const caps = await fetchJSON("/api/capabilities");
    if (!caps.pdf) {
      $("alsoPdf").checked = false;
      $("alsoPdf").closest("label").classList.add("hidden");
    }
  } catch { /* the 401 path has already redirected */ }

  const steps = [
    ["boot_sources", sub => waitFirstHealthSweep(SPLASH_HEALTH_CAP_MS, sub)],
    ["boot_datasets", async () => {
      ["dateInput", "tlStart", "tlEnd", "dateB"].forEach(wireDMY);
      const info = await fetchJSON("/api/datasets");
      const sel = $("datasetSelect"), csel = $("coordsDataset");
      for (const m of info.gridded) {
        state.meta[m.id] = m;
        for (const s of [sel, csel]) {
          const o = document.createElement("option");
          o.value = m.id; o.textContent = `${m.name} — ${m.resolution_label}`;
          s.appendChild(o);
        }
      }
      // point extraction defaults to MUR (1 km, full range), not local OISST
      csel.value = state.meta.mur_okhotsk ? "mur_okhotsk" : info.gridded[0].id;
      applyLang();
      const local = state.meta.oisst_local;
      const last = local.dates[local.dates.length - 1];
      $("tlStart").value = last.slice(0, 4) + "-05-20";
      $("tlEnd").value = last;
      const lastYear = +last.slice(0, 4);
      tlRow.dateItems = [{ type: "date", value: MD_YEAR + "-06-01" }];
      tlRow.yearItems = [{ type: "yearRange", from: lastYear - 5, to: lastYear, step: 1 }];
      renderTlSpec();
    }],
    ["boot_map", async () => { await selectDataset("oisst_local"); boxFromMap(); }],
    ["boot_areas", async () => refreshAreas()],
  ];

  const n = steps.length;
  for (let i = 0; i < n; i++) {
    splashSet(i / n, steps[i][0]);
    try {
      await steps[i][1](p => splashSet((i + Math.min(p, 1)) / n));
    } catch (e) {
      // a failed step must not strand the user behind the splash forever
      console.error("boot step", steps[i][0], "failed:", e);
    }
  }
  splashSet(1, "boot_ready");

  const held = Date.now() - t0;
  if (held < SPLASH_MIN_MS) await new Promise(r => setTimeout(r, SPLASH_MIN_MS - held));
  clearInterval(tipTimer);
  const sp = $("splash");
  sp.classList.add("done");
  setTimeout(() => sp.remove(), 600);   // drop it so it can never trap clicks
  prefetchRemoteDates();
})();

// ------------------------------------------------------- live source health
// /api/health is served from the server's in-memory state, so polling it is
// free -- it never triggers an outbound request to NOAA. The actual probing
// is rate-limited server-side (health.py).
const HEALTH_POLL_MS = 10000;
// id -> "ok"|"slow"|"down"|"unknown", so the dataset picker can refuse a
// source the prober already knows is dark instead of hanging on it
const srcStatus = {};

function healthLine(s) {
  // "reachable" is wrong for a local toolchain -- it is installed or it isn't
  const pre = s.kind === "tool" && (s.status === "ok" || s.status === "down")
    ? "hl_tool_" : "hl_";
  const bits = [t(pre + s.status)];
  if (s.latency_ms != null) bits.push(`${s.latency_ms} ms`);
  if (s.age_s != null) bits.push(`${t("hl_checked")} ${Math.round(s.age_s)}s ${t("hl_ago")}`);
  if (s.via) bits.push(t({ traffic: "hl_via_traffic", server: "hl_via_server" }[s.via]
                         || "hl_via_probe"));
  if (s.kind === "remote" && s.host) bits.push(s.host);
  if (s.error) bits.push("\n" + s.error);
  bits.push("\n" + t(s.kind === "host" ? "hl_role_server" : "hl_role_dataset"));
  if (s.notices) bits.push("\n" + t("hl_notices"));
  return `${s.name}: ${bits.join(" · ")}`;
}

async function pollHealth() {
  const box = $("srcHealth");
  try {
    const h = await (await fetch("/api/health")).json();
    for (const s of h.sources) srcStatus[s.id] = s.status;
    box.innerHTML = "";
    // The ERDDAP server itself, then the datasets on it -- three dots that
    // answer three different questions. Local files and the PDF toolchain
    // stay out: they either work or they don't, and "reachable" says nothing
    // useful about them.
    for (const s of h.sources.filter(s => s.kind === "host" || s.kind === "remote")) {
      // clickable when the source publishes a status page, a plain chip
      // otherwise -- same look either way
      const el = document.createElement(s.notices ? "a" : "span");
      if (s.notices) { el.href = s.notices; el.target = "_blank"; el.rel = "noopener"; }
      el.className = "src " + s.status;
      el.title = healthLine(s);
      const dot = document.createElement("i");
      dot.className = "dot";
      el.append(dot, s.name);
      box.appendChild(el);
    }
  } catch {
    box.textContent = t("hl_noserver");
  }
  setTimeout(pollHealth, HEALTH_POLL_MS);
}
