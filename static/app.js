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
    sec_layer: "Layer", help_layer: "Which dataset and field are drawn on the map. OISST = the 0.25° NOAA dataset from ERDDAP, back to Sept 1981, all days; MUR = 1 km satellite SST over the Pacific box, downloaded as 5° tiles for whatever you have zoomed into. Zooming in past the MUR threshold switches to it automatically and zooming back out returns to OISST. Everything downloads on demand the first time you view it.",
    lbl_dataset: "Dataset", lbl_variable: "Variable", lbl_opacity: "Overlay opacity",
    lbl_basemap: "Satellite opacity", lbl_edgeblur: "Edge blur", lbl_grid: "Grid",
    lbl_auto_mur: "Auto 1 km on zoom",
    lbl_tl_dataset: "dataset (for playback and GIF)",
    mur_tiles: (d, n) => `${d} / ${n} tiles`,
    mur_failed: "1 km tiles unavailable, staying on 0.25°",
    var_sst: "SST (°C)", var_anom: "SST anomaly (°C)", var_err: "Analysis error (°C)",
    var_analysed_sst: "SST (°C)", var_sea_ice_fraction: "Sea-ice fraction",
    sec_scale: "Color scale", help_scale: "Auto picks the 2–98 percentile range of the current frame. Fixed uses the min/max you type — required for comparing dates or running a timelapse, otherwise colors mean different temperatures in every frame.",
    lbl_auto: "Auto", lbl_fixed: "Fixed", lbl_to: "to",
    ds_unavailable: "that dataset's server is not answering right now",
    sec_date: "Date", help_date: "The picker snaps to the nearest available date of the selected dataset. Use ◀ ▶ or keyboard ← → to step.",
    sec_timelapse: "Timelapse", help_timelapse: "Plays through the available dates in the chosen range like an animation.",
    lbl_from: "from", lbl_gap: "step, days", help_gap: "How many calendar days to jump each frame (snapping to the nearest available date). 1 = every day. 365 ≈ the same day next year (use the checkbox below for a leap-safe version).",
    lbl_fps: "fps", lbl_sameday: "same day each year", help_sameday: "Show the same month/day (taken from the 'from' date) in every year of the range — e.g. every June 1 from 2000 to 2025.",
    txt_island: "Dataset, variable and date are set in the bar above the map.",
    tl_loading: "loading frames", tl_tiles: "downloading 1 km tiles, frame",
    tl_spec_bad: "fill in the day/month and year fields",
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
    hl_cause: "ERDDAP status", hl_status_stale: "status page unreachable",
    hl_inherited: "not checked separately — the server it lives on is down",
    tip_global: "Point charts and CSV export work for any coordinates on the globe. The map box only limits the drawn overlay.",
    tip_sameday: "For a year-on-year animation use “same day each year” instead of a 365-day step — it stays aligned across leap years.",
    tip_data: "In the Data tab one row can repeat the same calendar days across many years — five days across 24 years is a single set.",
    tip_reports: "Tick “Also generate PDF(s)” for a per-point report. The template adapts to which days and years you picked.",
    sec_compare: "Compare two dates (A/B)", help_compare: "Splits the map with a draggable divider: left of it = date A (the main date above), right = date B. Click the map to see both values and the difference.",
    lbl_enable: "enable", lbl_dateb: "Date B", lbl_yr: "yr",
    txt_ab: "A = left, B = right. Scale is frozen while comparing.",
    sec_tools: "Tools", help_tools: "Distance measurement and extras.",
    btn_measure: "📏 Measure distance",
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
    lbl_also_compare: "Also generate one comparison PDF",
    compare_needs2: "Check at least 2 points to compare them",
    compare_ready: "⬇ comparison PDF (all points)", compare_label: "Comparison report",
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
    sec_layer: "Слой", help_layer: "Какой набор данных и поле рисуются на карте. OISST — набор 0.25° NOAA с ERDDAP, с сентября 1981, все дни; MUR — спутниковая ТПМ 1 км по тихоокеанскому боксу, скачивается тайлами по 5° для того, куда вы приблизились. Приближение переключает на MUR автоматически, отдаление возвращает OISST. Всё скачивается по запросу при первом просмотре.",
    lbl_dataset: "Набор данных", lbl_variable: "Переменная", lbl_opacity: "Прозрачность слоя",
    lbl_basemap: "Прозрачность снимка", lbl_edgeblur: "Размытие границ", lbl_grid: "Сетка",
    lbl_auto_mur: "Авто 1 км при зуме",
    lbl_tl_dataset: "набор данных (для проигрывания и GIF)",
    mur_tiles: (d, n) => `${d} / ${n} тайлов`,
    mur_failed: "тайлы 1 км недоступны, остаёмся на 0.25°",
    var_sst: "ТПМ (°C)", var_anom: "Аномалия ТПМ (°C)", var_err: "Ошибка анализа (°C)",
    var_analysed_sst: "ТПМ (°C)", var_sea_ice_fraction: "Доля морского льда",
    sec_scale: "Цветовая шкала", help_scale: "«Авто» берёт диапазон 2–98 перцентилей текущего кадра. «Фикс.» использует введённые min/max — обязательно при сравнении дат и таймлапсе, иначе цвета в каждом кадре означают разные температуры.",
    lbl_auto: "Авто", lbl_fixed: "Фикс.", lbl_to: "до",
    ds_unavailable: "сервер этого набора сейчас не отвечает",
    sec_date: "Дата", help_date: "Выбор привязывается к ближайшей доступной дате выбранного набора. Листайте ◀ ▶ или клавишами ← →.",
    sec_timelapse: "Таймлапс", help_timelapse: "Проигрывает доступные даты в выбранном диапазоне как анимацию.",
    lbl_from: "с", lbl_gap: "шаг, дней", help_gap: "На сколько календарных дней прыгать каждый кадр (с привязкой к ближайшей доступной дате). 1 = каждый день. 365 ≈ тот же день следующего года (для точности лучше галочка ниже).",
    lbl_fps: "кадр/с", lbl_sameday: "тот же день каждый год", help_sameday: "Показывать одно и то же число (месяц/день берутся из даты «с») в каждом году диапазона — например, каждое 1 июня с 2000 по 2025.",
    txt_island: "Набор данных, переменная и дата задаются в полосе над картой.",
    tl_loading: "загрузка кадров", tl_tiles: "загрузка тайлов 1 км, кадр",
    tl_spec_bad: "заполните поля дня/месяца и года",
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
    hl_cause: "состояние ERDDAP", hl_status_stale: "страница состояния недоступна",
    hl_inherited: "отдельно не проверялся — недоступен сервер, на котором он размещён",
    tip_global: "Графики по точке и экспорт CSV работают для любых координат на планете. Рамка карты ограничивает только отрисовку слоя.",
    tip_sameday: "Для анимации по годам используйте «тот же день каждый год» вместо шага в 365 дней — так дата не съедет из-за високосных лет.",
    tip_data: "На вкладке «Данные» одна строка может повторять одни и те же календарные дни во многих годах — пять дней за 24 года это один набор.",
    tip_reports: "Отметьте «Также создать PDF», чтобы получить отчёт по каждой точке. Шаблон подстраивается под выбранные дни и годы.",
    sec_compare: "Сравнение двух дат (A/B)", help_compare: "Делит карту перетаскиваемой линией: слева — дата A (основная дата выше), справа — дата B. Клик по карте покажет оба значения и разницу.",
    lbl_enable: "включить", lbl_dateb: "Дата B", lbl_yr: "г.",
    txt_ab: "A — слева, B — справа. Шкала фиксируется на время сравнения.",
    sec_tools: "Инструменты", help_tools: "Измерение расстояний и прочее.",
    btn_measure: "📏 Измерить расстояние",
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
    lbl_also_compare: "Также создать один сравнительный PDF",
    compare_needs2: "Отметьте хотя бы 2 точки, чтобы их сравнить",
    compare_ready: "⬇ сравнительный PDF (все точки)", compare_label: "Сравнительный отчёт",
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
  dataset: "oisst_remote", meta: {}, dates: [], var: "sst", date: null, dateB: null,
  vmin: null, vmax: null, playing: null, comparing: false,
  // viewport box (w,s,e,n) the tiled dataset is currently rendered for;
  // null = not on a tiled dataset
  bbox: null,
};
const meta = () => state.meta[state.dataset] || { variables: {}, name: "", resolution_label: "" };
const varLabel = v => I18N[lang]["var_" + v] ? t("var_" + v) : (meta().variables[v] || v);

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = await r.text();
    try { msg = JSON.parse(msg).detail || msg; } catch (e) { /* raw text */ }
    throw new Error(msg);
  }
  return r.json();
}

// ------------------------------------------------------------------ map
const MLAT = 85.05112878; // overlay PNGs are Mercator-resampled to this limit
// The whole app lives inside one Pacific box whose longitudes run 95..295 --
// i.e. it crosses the antimeridian and is NOT expressible in -180..180. That
// is why worldCopyJump must stay off: it re-wraps the centre into -180..180
// the moment you pan past 180, which walks the view straight out of maxBounds
// and then fights the viscosity to get back. Same reason nothing here calls
// LatLng.wrap().
const MAX_BOUNDS = [[-20, 95], [70, 295]];
const MUR_ZOOM = 6;              // at or above this zoom, MUR for the viewport
const map = L.map("map", {
  center: [25, 195], zoom: 3, worldCopyJump: false,
  maxBounds: MAX_BOUNDS, maxBoundsViscosity: 1.0,
});

// minZoom can only be computed once the container has a real size, so this is
// called from the boot sequence (and on resize) rather than inline.
function fitWholeBox() {
  map.invalidateSize();
  map.fitBounds(MAX_BOUNDS);
  map.setMinZoom(map.getZoom());   // the whole box fits here; no zooming past it
}
window.addEventListener("resize", () => {
  // a wider window can fit the box at a zoom the old minZoom forbids
  const z = map.getBoundsZoom(MAX_BOUNDS);
  if (z !== map.getMinZoom()) map.setMinZoom(z);
});

// Esri World Imagery is the only basemap. Carto "Light" now needs a paid API
// key (serves an "API KEY REQUIRED" tile without one) and Esri's Ocean
// bathymetry has no real tiles over the NW Pacific past ~z11 -- every cell
// comes back "Map data not yet available". With one layer there is no picker.
// kept in a variable so #basemapOpacity can fade it out from under the SST
const basemap = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { attribution: "Esri World Imagery", maxZoom: 17 }).addTo(map);
L.control.scale({ imperial: false }).addTo(map);

// Between the basemap tiles (pane 200) and Leaflet's own overlayPane (400):
// at 401/402 the SST image was painted OVER every vector -- coordinate dots and
// saved-area outlines both came out washed under an 85%-opaque raster.
map.createPane("ovA").style.zIndex = 250;
map.createPane("ovB").style.zIndex = 260;
// own pane: the cell grid must stay crisp when #edgeBlur blurs ovA/ovB, and
// must not be clipped away by the A/B swipe divider
map.createPane("cells").style.zIndex = 270;

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

// ------------------------------------------------- edge sharpness / blur
// Set on the two overlay PANES, not on the <img>es: setUrl() replaces the
// image's src on every frame and any per-image style would have to be
// re-applied each time. `image-rendering` inherits, so the pane is enough.
// Slider at 0 = exact cell edges (pixelated, no browser interpolation).
function applyEdgeBlur(px) {
  for (const p of ["ovA", "ovB"]) {
    const el = map.getPane(p);
    el.style.imageRendering = px > 0 ? "auto" : "pixelated";
    el.style.filter = px > 0 ? `blur(${px * 0.6}px)` : "";
  }
}

// --------------------------------------------------------- data-cell grid
// The real cell boundaries of the ACTIVE dataset. Spacing comes from the
// meta's resolution_label ("0.25°" / "0.01°") -- dataset_meta carries no
// dlat/dlon and datasets.py belongs to another agent.
// ponytail: lines are drawn on multiples of the step rather than on the true
// half-cell-offset grid origin; at the >=4 px/cell where this is legible the
// difference is a couple of pixels. Use real lat0/lon0 if that ever matters.

// The grid draws EVERY data cell -- one line per real cell boundary, never a
// coarser stand-in -- so it gets denser as you zoom and always shows exactly
// where the squares are.
//
// Two things it has to get right:
//
// 1. PHASE. lat0/lon0 from the server are cell CENTRES, so an edge is at
//    lat0 + (k + 0.5)*d. Drawing on the round multiples of d instead puts
//    every line through the middle of a cell -- off by half a cell (500 m for
//    MUR), which still looks like a grid and is simply wrong.
// 2. WIDTH. A fixed 1 px line on a 1 px cell is 100% ink, which is what turns
//    the whole map black when zoomed out. So the width is a fraction of the
//    cell, capped at 1 px: crisp and thin once cells are big, thinning and
//    fading out on its own as they shrink.
const CELL_LINE_RATIO = 10;      // width = cell / 10 ...
const CELL_LINE_MAX_PX = 1;      // ... but never heavier than a hairline
const MIN_CELL_PX = 1.5;         // below this the line is invisible anyway

const CellGrid = L.GridLayer.extend({
  createTile(coords) {
    const c = L.DomUtil.create("canvas"), size = this.getTileSize();
    c.width = size.x; c.height = size.y;
    const gr = meta().grid;
    if (!gr) return c;
    const nw = map.unproject(coords.scaleBy(size), coords.z);
    // L.Point has add(), not plus() -- plus() threw on every single tile, so
    // the checkbox silently did nothing at all.
    const se = map.unproject(coords.add([1, 1]).scaleBy(size), coords.z);
    const dLon = se.lng - nw.lng, dLat = nw.lat - se.lat;
    const dvg = state.lattice ? state.lattice.div : 1;
    const pxX = size.x * gr.dlon * dvg / dLon, pxY = size.y * gr.dlat * dvg / dLat;
    if (pxX < MIN_CELL_PX || pxY < MIN_CELL_PX) return c;
    const g = c.getContext("2d");
    g.strokeStyle = "rgba(0,0,0,0.55)";
    g.lineWidth = Math.min(CELL_LINE_MAX_PX, Math.min(pxX, pxY) / CELL_LINE_RATIO);
    g.beginPath();
    // The renderer rasterises each cell edge to a whole output row, so the
    // boundary you can SEE sits at Minv(round(scale*m(lat))/scale) rather than
    // at the ideal latitude. Draw there, or the line and the colour step
    // disagree by up to half a row -- 0.5 px at z10 but 7 px at z14, which is
    // exactly the "grid does not match the squares" everyone notices.
    // The image is stretched linearly in Mercator between its bounds, and the
    // renderer built it north-up by REVERSING a south-up row stack. So a cell
    // edge does not land at rint(scale*m(lat)) on screen -- it lands at row
    // H-(P(k)-P0) of that stretch. Reproducing the whole expression, rather
    // than just the rint, is what takes the residual from ~0.4 of an output
    // row down to nothing.
    const LT = state.lattice;
    const mOf = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
    let snapLat = lat => lat;
    if (LT && LT.n > LT.s) {
      const P0 = Math.round(LT.scale * mOf(LT.s));
      const H = Math.round(LT.scale * mOf(LT.n)) - P0;
      const mN = mOf(LT.n), mS = mOf(LT.s);
      if (H > 0) snapLat = lat => {
        const frac = (H - (Math.round(LT.scale * mOf(lat)) - P0)) / H;
        return (Math.atan(Math.sinh(mN - frac * (mN - mS))) * 180) / Math.PI;
      };
    }
    // columns are exact (longitude is linear in Mercator) but step by `div`
    // cells when the renderer had to merge them
    const dv = LT ? LT.div : 1;
    let k = Math.ceil((nw.lng - gr.lon0) / (gr.dlon * dv) - 0.5);
    for (let lon = gr.lon0 + (k + 0.5) * gr.dlon * dv; lon < se.lng;
         lon = gr.lon0 + (++k + 0.5) * gr.dlon * dv) {
      const x = (lon - nw.lng) / dLon * size.x;
      g.moveTo(x, 0); g.lineTo(x, size.y);
    }
    const y0 = coords.y * size.y;
    let j = Math.ceil((se.lat - gr.lat0) / (gr.dlat * dv) - 0.5);
    for (let lat = gr.lat0 + (j + 0.5) * gr.dlat * dv; lat < nw.lat;
         lat = gr.lat0 + (++j + 0.5) * gr.dlat * dv) {
      if (Math.abs(lat) >= MLAT) continue;
      const y = map.project([snapLat(lat), 0], coords.z).y - y0;
      g.moveTo(0, y); g.lineTo(size.x, y);
    }
    g.stroke();
    return c;
  },
});
const cellGrid = new CellGrid({ pane: "cells" });

// ------------------------------------------------------- frame blob cache
const frameCache = new Map(); // url -> {blob, vmin, vmax}
// Raised to the frame count while a timelapse preloads, so the frames fetched
// at the start of a long run are still there when it wraps around.
let frameCacheCap = 80;

// Evict cached frames whose URL matches. Needed because a tiled dataset's
// image can change WITHOUT its URL changing: the same box renders empty before
// its tiles are downloaded and correct afterwards.
function dropFrames(pred) {
  for (const [u, v] of frameCache) {
    if (!pred(u)) continue;
    URL.revokeObjectURL(v.blob);
    frameCache.delete(u);
  }
}
async function frameURL(url) {
  if (frameCache.has(url)) return frameCache.get(url);
  const r = await fetch(url);
  if (!r.ok) throw new Error(await r.text());
  const obj = { blob: URL.createObjectURL(await r.blob()),
                vmin: r.headers.get("X-Vmin"), vmax: r.headers.get("X-Vmax"),
                // "s,w,n,e" of what the server ACTUALLY drew -- for a tiled
                // dataset it snaps the box outward to whole tiles, so the
                // image is bigger than the bbox we asked for and placing it
                // on the requested box would shift the imagery.
                bounds: r.headers.get("X-Bounds"),
                // "scale,over,div" of the raster lattice the server drew on.
                // The grid overlay snaps to this so its lines sit on the cell
                // boundaries the IMAGE actually has, not the ideal ones -- the
                // two differ by up to half an output row, which is invisible on
                // the ground (~40 m) but several screen pixels past z12.
                lattice: r.headers.get("X-Lattice") };
  frameCache.set(url, obj);
  if (frameCache.size > frameCacheCap) { // ponytail: crude LRU, evict oldest insertion
    const k = frameCache.keys().next().value;
    URL.revokeObjectURL(frameCache.get(k).blob);
    frameCache.delete(k);
  }
  return obj;
}

// The Timelapse tab has its own dataset picker, so every frame fetched while
// playing (preload AND the live refresh behind showFrame) comes from that
// dataset -- otherwise the preview would not match the GIF you export.
const tlDs = () => $("tlDataset").value || state.dataset;
const overlayDs = () => (state.playing && tlDs()) || state.dataset;

// The Timelapse picker is independent of the map's variable selector, and the
// two datasets do not share variable NAMES (OISST "sst" vs MUR "analysed_sst").
// Sending the map's variable to the other dataset is a plain 400. Translate by
// label -- that is what the user actually picked -- and fall back to its first.
function varFor(dsid) {
  const m = state.meta[dsid];
  if (!m || !m.variables || m.variables[state.var]) return state.var;
  const want = (meta().variables || {})[state.var];
  return Object.keys(m.variables).find(k => m.variables[k] === want)
         || Object.keys(m.variables)[0];
}

// Auto scale, locked per dataset+variable+date. Without this, every pan is a
// new box, every box gets its own 2nd/98th percentile, and the whole map
// recolours -- the same 16 C pixel comes out mid-green in one view and dark
// blue in the next, which reads as the data changing when only the palette
// did. The FIRST view of a date establishes the range; panning and zooming
// then keep it. Changing date, variable or dataset picks a new one, and the
// Fixed radio still overrides everything.
const autoScale = new Map();
const scaleKey = (ds, v, date) => `${ds}|${v}|${date}`;

function overlayURL(date, fixedScale) {
  const ds = overlayDs();
  let u = `/api/overlay?date=${date}&var=${varFor(ds)}&dataset=${ds}`;
  if (fixedScale) u += `&vmin=${state.vmin}&vmax=${state.vmax}`;
  else {
    const lock = autoScale.get(scaleKey(ds, varFor(ds), date));
    if (lock) u += `&vmin=${lock[0]}&vmax=${lock[1]}`;
  }
  // A tiled dataset has no whole-grid image (180M cells); it must always be
  // asked for a box, so fall back to the live viewport if none is pinned.
  if (state.meta[ds] && state.meta[ds].tiled)
    u += `&bbox=${(state.bbox || viewBbox()).map(x => x.toFixed(3)).join(",")}`;
  return u;
}

function viewBbox() {
  const b = map.getBounds();
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
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
      const ds = overlayDs();
      const key = scaleKey(ds, varFor(ds), state.date);
      if (!autoScale.has(key)) autoScale.set(key, [f.vmin, f.vmax]);
      state.vmin = +f.vmin; state.vmax = +f.vmax;
      $("vmin").value = f.vmin; $("vmax").value = f.vmax;
    }
    if (f.lattice && f.bounds) {
      const [sc, ov, dv] = f.lattice.split(",").map(Number);
      const [bsy, , bny] = f.bounds.split(",").map(Number);
      const changed = !state.lattice || state.lattice.scale !== sc
                      || state.lattice.div !== dv || state.lattice.s !== bsy;
      state.lattice = { scale: sc, over: ov, div: dv, s: bsy, n: bny };
      if (changed && map.hasLayer(cellGrid)) cellGrid.redraw();
    }
    if (f.bounds) {
      const [s, w, n, e] = f.bounds.split(",").map(Number);
      overlayA.setBounds([[s, w], [n, e]]);
      overlayB.setBounds([[s, w], [n, e]]);
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
  const m = state.meta[state.dataset];
  $("datasetName").textContent = m ? `${m.name} — ${m.resolution_label}` : "";
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
    return;
  }
  if (!m.dates) {
    $("datasetName").classList.add("busy");
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
      $("datasetName").classList.remove("busy");
      return;                                // caller stays on `prev`
    }
    $("datasetName").classList.remove("busy");
  }
  state.dataset = id;
  state.dates = m.dates;
  // a tiled dataset is always rendered for a box; a whole-grid one never is
  state.bbox = m.tiled ? (state.bbox || viewBbox()) : null;
  rebuildVarSelect();
  if (map.hasLayer(cellGrid)) cellGrid.redraw();   // cell size changed
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
  // a new date needs its own MUR tiles; harmless no-op on a whole-grid dataset
  scheduleResolution();
}

function stepDate(dir) {
  const i = state.dates.indexOf(state.date);
  const j = Math.min(state.dates.length - 1, Math.max(0, i + dir));
  setDate(state.dates[j], false);
}

// ------------------------------------------------- resolution follows zoom
// Zoomed out you get the 0.25 deg global OISST; zoomed in past MUR_ZOOM the
// visible box is served from MUR at 1 km. Neither switch ever moves the map.
//
// MUR tiles are downloaded on demand, so entering a new area starts a tile job
// and shows a progress bar. "Automatic, but only once per view": every snapped
// tile-box we have already pulled for the current (date, var) is remembered,
// so panning back is instant and silent. `murGen` is the cancel token -- the
// same trick stopPlay/tlGen uses -- so a user who keeps zooming abandons the
// stale job's polling instead of racing two overlays onto the map.
const MUR_ID = "mur_okhotsk";
const VIEW_DEBOUNCE_MS = 600, MUR_POLL_MS = 700;
// How much of the visible map MUR's rendered box must cover before MUR is
// allowed on screen. Below this you get a rectangle of 1 km data with bare
// satellite imagery around it and a hard straight edge between them -- so the
// map stays on the dataset that covers everything until MUR can too.
const MUR_COVER = 0.95;
let murGen = 0, viewTimer = null;
let murBox = null;                // snapped [w,s,e,n] currently drawn as MUR
const murDone = new Set();        // "date|var|snapped box" already fetched
// Boxes whose tile job failed (typically "too many tiles - zoom in further").
// Without this, falling back to OISST re-fires the zoom handler, which retries
// MUR, which fails again: a silent request loop. Keyed by box only, so zooming
// in -- which is what the error asks for -- produces a new box and a new try.
const murBlocked = new Set();

function murProgress(done, total) {
  const el = $("murProgress");
  if (total == null) { el.hidden = true; return; }
  el.hidden = false;
  $("murProgressBar").style.width = (total ? done / total * 100 : 0) + "%";
  $("murProgressText").textContent = I18N[lang].mur_tiles
    ? I18N[lang].mur_tiles(done, total) : `${done} / ${total}`;
}

// The server snaps the requested box outward to whole tiles. Mirroring that
// here gives both the cache key (two viewports inside the same tiles are one
// fetch) and the extent to test coverage against.
function snapBox(bbox, tile) {
  const [[bs, bw], [bn, be]] = MAX_BOUNDS;
  const f = x => Math.floor(x / tile) * tile, c = x => Math.ceil(x / tile) * tile;
  return [Math.max(bw, f(bbox[0])), Math.max(bs, f(bbox[1])),
          Math.min(be, c(bbox[2])), Math.min(bn, c(bbox[3]))];
}

// Fraction of `view`'s area that `box` covers. Plain lat/lon area is fine --
// this only ever compares two boxes at the same latitude.
function coverFrac(view, box) {
  if (!box) return 0;
  const w = Math.max(0, Math.min(view[2], box[2]) - Math.max(view[0], box[0]));
  const h = Math.max(0, Math.min(view[3], box[3]) - Math.max(view[1], box[1]));
  const area = (view[2] - view[0]) * (view[3] - view[1]);
  return area > 0 ? (w * h) / area : 0;
}

async function toOisst(msg) {
  murProgress(null);
  if (msg) islandMsg("⚠ " + msg.slice(0, 160), true);
  murBox = null;
  state.bbox = null;
  if (state.dataset !== "oisst_remote") await selectDataset("oisst_remote");
  else refreshOverlay();
}

async function applyResolution() {
  // A/B compare and timelapse both need a frozen dataset underneath them
  if (state.playing || state.comparing) return;
  const gen = ++murGen;
  const murMeta = state.meta[MUR_ID];
  const bbox = viewBbox();

  // The 1 km switch is opt-IN, and off by default: each new area costs a tile
  // download of tens of MB, so zooming in should not silently start one. The
  // map stays on OISST at every zoom until you tick the box.
  if (!$("autoMur").checked || map.getZoom() < MUR_ZOOM || !murMeta || !murMeta.tiled) {
    if (state.dataset !== "oisst_remote") await toOisst();
    else murProgress(null);
    return;
  }

  const snapped = snapBox(bbox, murMeta.tile_deg || 5);
  const box = snapped.join(",");
  if (murBlocked.has(box)) {
    if (state.dataset !== "oisst_remote") await toOisst();
    else murProgress(null);
    return;
  }

  // varFor(MUR_ID), not state.var: this runs BEFORE the dataset switch, so
  // state.var is still the outgoing dataset's name ('sst' for OISST) and the
  // memo would be keyed to a variable MUR does not have.
  const key = `${state.date}|${varFor(MUR_ID)}|${box}`;
  if (!murDone.has(key)) {
    // Tiles are missing for this view. Showing MUR now is what paints its
    // rectangle over part of the screen with raw satellite around it, so drop
    // back to the dataset that covers the whole map -- unless what is already
    // drawn still covers essentially all of it, in which case leaving it is
    // smoother than a flicker down to 25 km and back.
    if (state.dataset === MUR_ID && coverFrac(bbox, murBox) < MUR_COVER) {
      await toOisst();
      if (gen !== murGen) return;
    }
    let job;
    try {
      job = await fetchJSON("/api/tile_job", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset: MUR_ID, date: state.date, bbox: snapped, vars: null }),
      });
    } catch (err) { if (gen === murGen) { murBlocked.add(box); await toOisst(err.message); } return; }
    if (gen !== murGen) return;

    // total 0 = every tile already on disk; no bar flash, straight to the image
    if (job.total > 0) {
      murProgress(0, job.total);
      for (;;) {
        let st;
        try { st = await fetchJSON(`/api/tile_job_status?id=${job.id}`); }
        catch (err) { if (gen === murGen) { murBlocked.add(box); await toOisst(err.message); } return; }
        if (gen !== murGen) { murProgress(null); return; }
        murProgress(st.done, st.total);
        if (st.state === "error") {
          murBlocked.add(box);
          await toOisst(st.error || t("mur_failed"));
          return;
        }
        if (st.state === "done") break;
        await new Promise(r => setTimeout(r, MUR_POLL_MS));
      }
      murProgress(null);
    }
    murDone.add(key);
    // A box lands in murBlocked on any job failure, including the socket
    // timeouts and TLS resets this host serves for weeks at a time. One success
    // proves the network is back, so stop punishing boxes that only failed then.
    murBlocked.clear();
  }

  if (gen !== murGen) return;
  // Only now, with every tile for this box on disk, is MUR safe to show.
  murBox = snapped;
  state.bbox = snapped;
  if (state.dataset !== MUR_ID) {
    await selectDataset(MUR_ID);
    if (gen !== murGen || state.dataset !== MUR_ID) return;
    // selectDataset -> setDate -> scheduleResolution queued a re-entry for
    // this very box; letting it fire again would just redo the work
    clearTimeout(viewTimer);
  }
  // The overlay URL does not change when tiles arrive -- same date, var and
  // box -- so frameCache would hand back the EMPTY image it cached from the
  // render that ran before the download, and the area would stay blank for
  // good. New tiles make every cached MUR frame stale; drop them.
  dropFrames(u => u.includes(`dataset=${MUR_ID}`));
  refreshOverlay();
}

const scheduleResolution = () => {
  clearTimeout(viewTimer);
  viewTimer = setTimeout(applyResolution, VIEW_DEBOUNCE_MS);
};
map.on("zoomend moveend", scheduleResolution);

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
    const avail = new Set((state.meta[tlDs()] || {}).dates || state.dates);
    return dates.filter(d => avail.has(d));
  }
  // the Timelapse tab's own picker: playback frames, and the GIF built from
  // exactly those frames, must both come from the dataset chosen here
  const q = `start=${$("tlStart").value}&end=${$("tlEnd").value}` +
            `&gap=${$("gapDays").value}&dataset=${tlDs()}`;
  return fetchJSON(`/api/playback_dates?${q}`);
}

// Play preloads each frame from /api/overlay, which renders ONLY from tiles
// already on disk -- so a MUR timelapse over dates you have not browsed on the
// map comes out blank, frame after frame. Fetch each frame's tiles first,
// through the same job the map uses. Progress is counted in FRAMES, because
// that is the unit actually chosen; the per-frame tile bar rides along on the
// map's own progress island.
async function preloadTiles(gen, dates, dsid) {
  const m = state.meta[dsid];
  if (!m || !m.tiled) return true;
  const box = snapBox(viewBbox(), m.tile_deg || 5);
  state.bbox = box;                       // frames must ask for the same box
  const prog = $("tlProg");
  prog.classList.remove("hidden");
  prog.max = dates.length; prog.value = 0;
  const fail = msg => {
    murProgress(null);
    $("tlInfo").textContent = "⚠ " + String(msg).slice(0, 200);
    return false;
  };
  for (let i = 0; i < dates.length; i++) {
    if (gen !== tlGen) return false;
    let job;
    try {
      job = await fetchJSON("/api/tile_job", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset: dsid, date: dates[i], bbox: box, vars: null }),
      });
    } catch (err) { return fail(err.message); }
    while (job.total > 0) {
      let st;
      try { st = await fetchJSON(`/api/tile_job_status?id=${job.id}`); }
      catch (err) { return fail(err.message); }
      if (gen !== tlGen) { murProgress(null); return false; }
      if (st.state === "error") return fail(st.error || t("mur_failed"));
      if (st.state === "done") break;
      murProgress(st.done, st.total);
      await new Promise(r => setTimeout(r, MUR_POLL_MS));
    }
    murProgress(null);
    prog.value = i + 1;
    $("tlInfo").textContent = `${t("tl_tiles")} ${i + 1}/${dates.length}`;
  }
  // Any of these frames may already be cached from a render that ran before
  // its tiles existed -- same URL, empty image. Drop them.
  dropFrames(u => u.includes(`dataset=${dsid}`));
  return true;
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
  if (!await preloadTiles(gen, dates, tlDs())) { stopPlay(); return; }
  if (gen !== tlGen) return;
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
    `&var=${varFor(tlDs())}&vmin=${$("vmin").value}&vmax=${$("vmax").value}` +
    `&fps=${$("fps").value}&bbox=${bbox}&dataset=${tlDs()}`;
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
    mk("✎", () => renameArea(a));
    mk("✕", () => deleteArea(a));
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
    // an area GIF is built from tlQuery()'s frames, so it follows the same
    // Timelapse-tab dataset picker the main GIF export does
    await fetchJSON(`/api/areas/${a.id}/gif?dataset=${tlDs()}&${tlQuery()}` +
      `&var=${varFor(tlDs())}` +
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
  syncCompareBox();
}

// A comparison needs 2+ checked points: below that the box is greyed out and
// ignored (its tick is kept, so it comes back once a second point is checked).
function syncCompareBox() {
  const ok = coordRows.filter(r => r.checked).length >= 2;
  $("alsoCompare").disabled = !ok;
  $("alsoCompareLbl").title = ok ? "" : t("compare_needs2");
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
  if (el.classList.contains("rowCheck")) { row.checked = el.checked; syncCompareBox(); return; }
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
                             generate_compare: $("alsoCompare").checked && !$("alsoCompare").disabled,
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
  if (job.compare_url) lines.push(`<div><a href="${job.compare_url}" download>${t("compare_ready")}</a></div>`);
  else if (job.compare_error) lines.push(`<div>${t("compare_label")}: ⚠ ${job.compare_error}</div>`);
  else if (job.compare_state === "rendering") lines.push(`<div>${t("compare_label")}: ${t("st_rendering")}</div>`);
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
$("langBtn").onclick = () => { lang = lang === "en" ? "ru" : "en"; localStorage.setItem("sst_lang", lang); applyLang(); };
$("varSelect").onchange = e => { state.var = e.target.value; refreshOverlay(); scheduleResolution(); };
$("opacity").oninput = e => { overlayA.setOpacity(e.target.value / 100); overlayB.setOpacity(e.target.value / 100); };
$("basemapOpacity").oninput = e => basemap.setOpacity(e.target.value / 100);
$("edgeBlur").oninput = e => applyEdgeBlur(+e.target.value);
$("autoMur").onchange = () => applyResolution();
$("gridToggle").onchange = e => {
  if (e.target.checked) cellGrid.addTo(map); else map.removeLayer(cellGrid);
};
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
// a different dataset means different available dates and different frames --
// whatever is playing was built from the old one
$("tlDataset").onchange = stopPlay;
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
// Upper bound on how long the splash waits for the first health sweep. There
// is no short "cold" probe any more: the server gives every source the full
// PROBE_TIMEOUT_S (15 s), so the first sweep is honest but can take ~30 s when
// a host is dark (the timeout x its two DNS addresses). The splash is supposed
// to wait for that real verdict however long it takes -- the cap exists only
// so a pathological hang (server wedged, sweep never finishing) cannot trap
// the user behind the splash forever.
const SPLASH_HEALTH_CAP_MS = 45000;
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

  const steps = [
    ["boot_sources", sub => waitFirstHealthSweep(SPLASH_HEALTH_CAP_MS, sub)],
    ["boot_datasets", async () => {
      ["dateInput", "tlStart", "tlEnd", "dateB"].forEach(wireDMY);
      const info = await fetchJSON("/api/datasets");
      const csel = $("coordsDataset"), tsel = $("tlDataset");
      for (const m of info.gridded) {
        state.meta[m.id] = m;
        for (const s of [csel, tsel]) {
          const o = document.createElement("option");
          o.value = m.id; o.textContent = `${m.name} — ${m.resolution_label}`;
          s.appendChild(o);
        }
      }
      // point extraction defaults to MUR (1 km, full range)
      csel.value = state.meta[MUR_ID] ? MUR_ID : info.gridded[0].id;
      // ...but a timelapse spans many dates, so it defaults to the dataset
      // that has every one of them cheaply
      tsel.value = "oisst_remote";
      applyLang();
      const remote = state.meta.oisst_remote;
      const last = remote.dates[remote.dates.length - 1];
      $("tlStart").value = last.slice(0, 4) + "-05-20";
      $("tlEnd").value = last;
      const lastYear = +last.slice(0, 4);
      tlRow.dateItems = [{ type: "date", value: MD_YEAR + "-06-01" }];
      tlRow.yearItems = [{ type: "yearRange", from: lastYear - 5, to: lastYear, step: 1 }];
      renderTlSpec();
    }],
    ["boot_map", async () => {
      // whole Pacific box, newest available date, 0.25 deg -- and this is
      // where minZoom is pinned, because only now does #map have a size
      fitWholeBox();
      applyEdgeBlur(+$("edgeBlur").value);
      basemap.setOpacity($("basemapOpacity").value / 100);
      if ($("gridToggle").checked) cellGrid.addTo(map);
      await selectDataset("oisst_remote");
      boxFromMap();
    }],
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

function healthLine(s, inherited) {
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
  // A dot that is red only because its host is red should say so rather than
  // implying the dataset was probed and failed on its own.
  if (inherited || s.via === "server") bits.push("\n" + t("hl_inherited"));
  // ...and the server dot carries WHY, lifted off ERDDAP's own status page.
  if (s.cause) bits.push("\n\n" + t("hl_cause") + ":\n" + s.cause);
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
    // The datasets LIVE ON the server, so draw them as its children: one
    // glance says whether the host is the problem or just one dataset.
    const host = h.sources.filter(s => s.kind === "host");
    const kids = h.sources.filter(s => s.kind === "remote");
    // When the host is down, nothing about a dataset ON it was actually
    // established -- a failed probe there says "could not reach the server",
    // not "this dataset is broken". `via` is not a reliable marker for that:
    // passive traffic observation stamps via="traffic" on exactly the same
    // situation. So key off the host's own state.
    const hostDown = host.some(s => s.status === "down");
    const rows = [];
    for (const s of host) rows.push([s, ""]);
    kids.forEach((s, i) => rows.push([s, i === kids.length - 1 ? "└─ " : "├─ "]));

    for (const [s, prefix] of rows) {
      const el = document.createElement(s.notices ? "a" : "span");
      if (s.notices) { el.href = s.notices; el.target = "_blank"; el.rel = "noopener"; }
      // `inherited` = this dataset was not judged on its own evidence; the
      // host is down and took it with it. Rendered grey, not red, so the red
      // stays on the thing that is actually broken.
      const inherited = prefix && (hostDown || s.via === "server");
      el.className = "src " + s.status + (inherited ? " inherited" : "")
                     + (prefix ? " child" : " parent");
      el.title = healthLine(s, inherited);
      if (prefix) {
        const tw = document.createElement("i");
        tw.className = "twig";
        tw.textContent = prefix;
        el.appendChild(tw);
      }
      const dot = document.createElement("i");
      dot.className = "dot";
      el.append(dot, s.name);
      box.appendChild(el);
    }
    if (h.status_error) {
      const warn = document.createElement("span");
      warn.className = "src statusWarn";
      warn.textContent = "⚠ " + t("hl_status_stale");
      warn.title = h.status_error;
      box.appendChild(warn);
    }
  } catch {
    box.textContent = t("hl_noserver");
  }
  setTimeout(pollHealth, HEALTH_POLL_MS);
}
