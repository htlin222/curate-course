// app.js — 載入課程資料、渲染、互動與進度追蹤
import { mountIcons, icon } from "./icons.js";
import {
  renderChapter, renderStance, renderHome, setDrillEvidence, setConfig, setAccess, UI, t,
} from "./render.js";
// 文案契約只有一份（見 copy.js），建置期的等價實作在 src/build/seo.py
import { esc, rich, text, fillTokens } from "./copy.js";
import * as paywall from "./paywall.js";
import { renderFacetPanel, syncFacetChips, applyFilters as runFilters } from "./filters.js";
import { THEME_KEY, keysFor, migrateLegacy } from "./store.js";
import {
  buildPlaylist, renderPlaylist, play, stop, fitFrame, watchFrame, initResizer, setLanguages,
} from "./player.js";
import { bindKeys, listen as ytListen } from "./keys.js";
import * as discuss from "./discuss.js";

/** bindEvents() 內的 scroll-spy 掛上來，讓章節重繪後能重算側欄高亮 */
let syncNav = () => {};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** 鍵名要等 course.json 載入、知道 site.project 之後才決定（見 store.js）。
    在那之前沒有任何東西該碰 localStorage。 */
let STORE = { theme: THEME_KEY };

/** playlist 的 url -> index，讓課程內容的影片連結能導向站內播放 */
const urlIndex = new Map();

const state = {
  course: null,
  done: new Set(),
  filter: "all",
  query: "",
  facets: new Set(),
  tab: "course",
  playlist: [],
  playing: -1,
  playlistQuery: "",
  onlyTodo: false,
  lockedNote: "", // paywall 鎖住幾章，寫在篩選列的計數旁邊
};

/* --- 儲存 ---------------------------------------------------------------- */

function load(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function save(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 隱私模式下寫入會失敗，靜默忽略 */
  }
}

/** 把 course.config.json 的文案寫進 header、Hero 與頁尾 */
function applyChrome(data) {
  const c = data.config || {};
  const site = c.site || {};
  const set = (sel, html) => {
    const el = $(sel);
    if (el && html != null) el.innerHTML = html;
  };

  // document.title 與 setAttribute 都是純文字 sink，逸出反而會讓使用者看到 &amp;
  document.title = text(site.title || site.name || document.title);
  document.documentElement.lang = site.locale || "zh-Hant";
  set(".AppHeader__brand span", rich(site.name || ""));
  // 品牌圖示：index.html 裡的那顆只是預設值，換主題一定要從設定檔重畫，
  // 否則 header 會一直掛著上一個主題的圖示（稽核查得到 brandIcon 有打包，
  // 但查不到前端有沒有真的去讀它）。
  const brandSvg = $(".AppHeader__brand svg");
  if (brandSvg && site.brandIcon) {
    brandSvg.outerHTML = icon(site.brandIcon, 20);
  }
  // setAttribute 吃純文字（瀏覽器不會再解析一次），所以這裡直接給原字串去掉 ** 記號
  $("#search")?.setAttribute("placeholder", text(c.ui?.searchPlaceholder || "搜尋…"));
  $("#playlistSearch")?.setAttribute("placeholder", text(c.ui?.playlistSearch || ""));
  set(".ProgressPanel__title", rich(c.ui?.progressLabel || ""));
  set("#facetToggle span:first-of-type", rich(c.ui?.facetLabel || ""));
  // 分面面板的圖示同理：index.html 那顆只是預設值，設定檔有指定就換掉
  const facetSvg = $("#facetToggle > svg");
  if (facetSvg && c.ui?.facetIcon) facetSvg.outerHTML = icon(c.ui.facetIcon, 16);
  applyFavicon(site.brandIcon);

  for (const [key, label] of Object.entries(c.ui?.tabs || {})) {
    set(`.TabNav__item[data-tab="${key}"] .TabNav__label`, rich(label));
  }

  set(".Hero__eyebrow", `${$(".Hero__eyebrow svg")?.outerHTML || ""} ${rich(c.hero?.eyebrow || "")}`);
  set(".Hero h1", rich(c.hero?.heading || ""));
  set(".Hero__lede", rich(fillTokens(c.hero?.lede || "", data.meta)));
  // disclaimer 以前是唯一一個 raw 的頁尾欄位，credits 就在隔壁卻是逸出的。現在一致。
  set(".AppFooter__disclaimer", rich(c.footer?.disclaimer || ""));
  set(".AppFooter__credits", rich(c.footer?.credits || ""));
}

/** favicon 也跟著 site.brandIcon 走。index.html 裡那顆只是首屏用的中性預設值，
    不從設定檔重畫的話，換主題後分頁上會一直掛著框架的通用圖示——
    這正是「寫死的預設值會活過換主題」那一類問題。 */
function applyFavicon(name) {
  const symbol = name && document.getElementById(`i-${name}`);
  const link = $('link[rel="icon"]');
  if (!symbol || !link) return;
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
    'stroke="#0969da" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    `${symbol.innerHTML}</svg>`;
  link.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/* --- 瀏覽次數 -------------------------------------------------------------
   設定檔沒有 counter 區塊就整個不做。API 失敗（沒綁 D1、離線、本機預覽）
   就讓徽章維持隱藏——寧可沒有這個功能，也不要顯示一個壞掉的空殼。 */

async function renderHits(cfg) {
  const conf = cfg?.counter;
  if (!conf) return;

  const box = $("#hitCounter");
  if (!box) return;

  try {
    const res = await fetch("/api/hits", {
      method: "POST",
      headers: { "content-type": "application/json" },
      cache: "no-store",
    });
    if (!res.ok) return;
    const { hits } = await res.json();
    if (typeof hits !== "number") return;

    $("#hitCount").textContent = hits.toLocaleString();
    $("#hitLabel").textContent = text(conf.label || "");
    box.title = text(conf.title || "");
    box.hidden = false;
  } catch {
    /* 靜默失敗：計數器不該影響課程本身 */
  }
}

/* --- 統計 ---------------------------------------------------------------- */

function renderStats() {
  const { meta, config } = state.course;
  // 顯示哪些數字由 course.config.json 決定，全部是能從資料實際算出來的
  $("#heroStats").innerHTML = (config.ui?.stats || [])
    .map(
      (s) => `
        <div class="Stat">
          <span class="Stat__value">${icon(s.icon, 16)}<span>${esc(meta[s.field] ?? "")}</span></span>
          <span class="Stat__label">${rich(s.label)}</span>
        </div>`,
    )
    .join("");

  // 單元數／影片欄位數／去重後支數是三個不同的東西，講清楚免得對不上
  // 名詞全部來自設定檔，一樣走文案契約——這裡以前是唯一一處把 ui.*Noun 直接串進
  // innerHTML 的地方，設定檔寫一個 & 就會產生壞掉的 HTML
  $("#heroNote").innerHTML =
    `${meta.lesson_units} ${rich(UI.unitNoun || "個單元")}，每個單元 1 ${rich(UI.lessonNoun || "堂主課")} + 共 ${meta.drill_units} ${rich(UI.drillNoun || "支跟練影片")}。` +
    `另有 ${meta.alt_lessons} 支多語言版本，播放清單共 ${meta.video_slots} 支；` +
    `扣掉跨單元共用的，實際是 ${meta.video_unique} 支不重複影片，` +
    `每個語言版本都看過的話總長 ${meta.duration_all}。`;
}

/* --- 側欄 ---------------------------------------------------------------- */

function renderNav() {
  const groups = (state.course.config.nav || []).map((g) => ({
    title: g.title,
    codes: g.chapters,
  }));

  $("#nav").innerHTML = groups
    .map(
      (g) => `
      <div class="NavList__group-title">${rich(g.title)}</div>
      ${g.codes
        .map((code) => {
          const ch = state.course.chapters.find((c) => c.code === code);
          if (!ch) return "";
          const done = ch.units.filter((u) => state.done.has(u.id)).length;
          return `
            <a class="NavList__item" href="#${esc(code)}" data-nav="${esc(code)}">
              <span class="NavList__icon">${icon(ch.icon || "circle-dot", 16)}</span>
              <span class="NavList__label">${esc(ch.title)}</span>
              <span class="Counter">${done}/${ch.units.length}</span>
            </a>`;
        })
        .join("")}`,
    )
    .join("");
}

/* --- 進度 ---------------------------------------------------------------- */

function totalUnits() {
  return state.course.chapters.reduce((n, c) => n + c.units.length, 0);
}

function renderProgress() {
  const total = totalUnits();
  const done = state.done.size;
  $("#progressValue").textContent = `${done} / ${total}`;
  $("#progressFill").style.width = total ? `${(done / total) * 100}%` : "0%";
}

function toggleDone(unitId) {
  state.done.has(unitId) ? state.done.delete(unitId) : state.done.add(unitId);
  save(STORE.done, [...state.done]);

  const el = $(`[data-unit="${CSS.escape(unitId)}"]`);
  if (el) {
    const done = state.done.has(unitId);
    el.classList.toggle("is-done", done);
    $(".Unit__check", el)?.setAttribute("aria-checked", String(done));
  }

  renderProgress();
  renderNav();
  updateChapterMeta();
}

function updateChapterMeta() {
  state.course.chapters.forEach((ch) => {
    const el = $(`[data-chapter="${CSS.escape(ch.code)}"]`);
    if (!el) return;
    const done = ch.units.filter((u) => state.done.has(u.id)).length;
    const pct = ch.units.length ? (done / ch.units.length) * 100 : 0;
    $(".Chapter__progress .ProgressBar__fill", el).style.width = `${pct}%`;
    const drillTotal = ch.units.reduce((n, u) => n + (u.drills?.length || 0), 0);
    $(".Chapter__meta", el).textContent =
      `${ch.units.length} ${text(UI.unitNoun || "個單元")}${drillTotal ? ` · ${drillTotal} ${text(UI.drillNoun || "支跟練影片")}` : ""}${done ? ` · 已完成 ${done}` : ""}`;
  });
}

/* --- 搜尋與篩選（實作在 filters.js） -------------------------------------- */

function applyFilters() {
  runFilters(state, state.course);
  syncFacetChips(state.facets);
}

/* --- 分頁 ---------------------------------------------------------------- */

function setTab(tab) {
  state.tab = tab;
  save(STORE.tab, tab);
  document.body.dataset.tab = tab; // 給 CSS 用（上課模式要吃滿版、隱藏頁尾）

  $$(".TabNav__item").forEach((b) => {
    const on = b.dataset.tab === tab;
    b.classList.toggle("is-selected", on);
    on ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current");
  });

  $("#view-home").hidden = tab !== "home";
  $("#main").hidden = tab !== "course";
  $("#view-stance").hidden = tab !== "stance";
  $("#view-player").hidden = tab !== "player";
  scrollTo({ top: 0 });

  if (tab === "player") {
    refreshPlaylist();
    requestAnimationFrame(fitFrame);
  }
  else stop(); // 離開上課模式就卸掉 iframe，不要背景播放
}

/* --- 上課模式 ------------------------------------------------------------ */

function refreshPlaylist() {
  renderPlaylist(state.playlist, {
    doneSet: state.done,
    currentIndex: state.playing,
    query: state.playlistQuery,
    onlyTodo: state.onlyTodo,
    canPlay: (it) => paywall.canAccess(it.chCode),
  });
}

function playAt(i) {
  if (i < 0 || i >= state.playlist.length) return;
  // 唯一的播放入口，所以 gate 只要擋這裡（清單點擊、鍵盤上下部、深連結都會經過）
  if (!paywall.canAccess(state.playlist[i].chCode)) return paywall.openGate();
  state.playing = i;
  save(STORE.playing, i);
  play(state.playlist[i], { total: state.playlist.length });
  setTimeout(ytListen, 900); // iframe 載入後才收得到 infoDelivery
  if (load(STORE.wide, false)) {
    $(".Player").classList.add("is-wide");
    $("[data-list-label]").textContent = t("listShow", "顯示清單");
  }
  refreshPlaylist();
  $(".PlaylistItem.is-playing")?.scrollIntoView({ block: "nearest" });
}

/* --- 事件 ---------------------------------------------------------------- */

/* --- paywall -------------------------------------------------------------
   能不能看的判定只有 paywall.canAccess() 一個來源（見 docs/PAYWALL.md）。
   解鎖後這裡負責把受影響的畫面重畫一次。 */

function renderChapters() {
  $("#chapters").innerHTML = state.course.chapters
    .map((ch) => renderChapter(ch, state.done))
    .join("");
  const locked = state.course.chapters.filter((ch) => !paywall.canAccess(ch.code)).length;
  state.lockedNote = locked ? `${locked} ${t("chaptersLocked", "章尚未解鎖")}` : "";
  syncNav(); // 解鎖後章節重畫，高亮要跟著重算
}

function onPaywallChange(payload) {
  renderChapters();
  $("#landingBody").innerHTML = renderHome(state.course);
  renderNav();
  refreshPlaylist();
  applyFilters();
  if (payload?.start) setTab("player");
}

function bindEvents() {
  // 分頁切換
  $$(".TabNav__item").forEach((b) =>
    b.addEventListener("click", () => setTab(b.dataset.tab)),
  );

  // paywall：鎖頭、招呼卡、購物車鈕。全站只有這三個入口
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-pw-gate]")) {
      e.preventDefault();
      return paywall.openGate();
    }
    if (e.target.closest("[data-pw-receipt]")) {
      e.preventDefault();
      return paywall.openReceipt();
    }
  });

  $("#cartBtn")?.addEventListener("click", () => paywall.openFromHeader());

  // 品牌與首頁上的按鈕都走同一個入口
  document.addEventListener("click", (e) => {
    const link = e.target.closest("[data-tab-link]");
    if (link) {
      e.preventDefault();
      return setTab(link.dataset.tabLink);
    }
    const goCh = e.target.closest("[data-goto-chapter]");
    if (goCh) {
      setTab("course");
      const el = $(`[data-chapter="${CSS.escape(goCh.dataset.gotoChapter)}"]`);
      el?.classList.add("is-open");
      el?.scrollIntoView({ block: "start" });
    }
  });

  // 分面篩選：側欄 chip 與項目內的標籤共用同一組 data-facet
  document.addEventListener("click", (e) => {
    const chip = e.target.closest("[data-facet]");
    if (!chip) return;
    e.preventDefault();
    e.stopPropagation();
    const f = chip.dataset.facet;
    state.facets.has(f) ? state.facets.delete(f) : state.facets.add(f);
    if (state.tab !== "course") setTab("course");
    applyFilters();
  });

  $("#facetToggle")?.addEventListener("click", () =>
    $("#facetPanel").classList.toggle("is-open"),
  );

  $("#facetBody")?.addEventListener("click", (e) => {
    if (!e.target.closest("#facetClear")) return;
    state.facets.clear();
    applyFilters();
  });

  // 播放清單
  $("#playlist").addEventListener("click", (e) => {
    const item = e.target.closest("[data-play]");
    if (item) playAt(+item.dataset.play);
  });

  $("#playerInfo").addEventListener("click", (e) => {
    const step = e.target.closest("[data-step]");
    if (step) return playAt(state.playing + +step.dataset.step);

    const mark = e.target.closest("[data-mark-unit]");
    if (mark) {
      toggleDone(mark.dataset.markUnit);
      refreshPlaylist();
      return;
    }

    const wide = e.target.closest("[data-toggle-list]");
    if (wide) {
      const on = $(".Player").classList.toggle("is-wide");
      save(STORE.wide, on);
      $("[data-list-label]").textContent = on ? t("listShow", "顯示清單") : t("listHide", "收起清單");
      requestAnimationFrame(fitFrame);
      return;
    }

    const disc = e.target.closest("[data-toggle-discuss]");
    if (disc) {
      const panel = $("#discussPanel");
      panel.hidden = !panel.hidden;
      if (!panel.hidden) {
        discuss.mount(state.playlist[state.playing]);
        panel.scrollIntoView({ block: "nearest" });
      } else {
        discuss.close();
      }
      requestAnimationFrame(fitFrame);
      return;
    }

    const goto = e.target.closest("[data-goto-unit]");
    if (goto) {
      e.preventDefault();
      setTab("course");
      const el = $(`[data-unit="${CSS.escape(goto.dataset.gotoUnit)}"]`);
      el?.classList.add("is-open");
      el?.closest(".Chapter")?.classList.add("is-open");
      el?.scrollIntoView({ block: "center" });
    }
  });

  let plDebounce;
  $("#playlistSearch").addEventListener("input", (e) => {
    state.playlistQuery = e.target.value;
    clearTimeout(plDebounce);
    plDebounce = setTimeout(refreshPlaylist, 120);
  });

  $("#playlistOnlyTodo").addEventListener("click", (e) => {
    state.onlyTodo = !state.onlyTodo;
    e.currentTarget.classList.toggle("is-active", state.onlyTodo);
    refreshPlaylist();
  });

  // 課程內容裡點影片 → 切到上課模式站內播放，而不是跳去 YouTube。
  // 按住 ⌘/Ctrl/Shift 或中鍵時尊重瀏覽器原本行為（開新分頁）。
  $("#chapters").addEventListener("click", (e) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    const link = e.target.closest('a[href*="youtube.com"], a[href*="youtu.be"]');
    if (!link) return;
    const i = urlIndex.get(link.href);
    if (i == null) return; // 不在播放清單裡就讓它正常開連結
    e.preventDefault();
    setTab("player");
    playAt(i);
  });

  // 主課語言切換
  $("#chapters").addEventListener("click", (e) => {
    const langBtn = e.target.closest("[data-lesson]");
    if (!langBtn) return;
    e.preventDefault();
    e.stopPropagation();
    const box = langBtn.closest(".LessonBox");
    const i = langBtn.dataset.lesson;
    $$(".LessonBox__lang", box).forEach((b) => {
      const on = b === langBtn;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", String(on));
    });
    $$("[data-lesson-pane]", box).forEach((p) => {
      p.hidden = p.dataset.lessonPane !== i;
    });
  });

  // 展開／收合 + 完成標記，統一走事件委派
  $("#chapters").addEventListener("click", (e) => {
    const check = e.target.closest('[data-action="toggle-done"]');
    if (check) {
      e.stopPropagation();
      toggleDone(check.closest(".Unit").dataset.unit);
      return;
    }

    const toggle = e.target.closest("[data-toggle]");
    if (!toggle) return;

    const kind = toggle.dataset.toggle;
    const host =
      kind === "chapter"
        ? toggle.closest(".Chapter")
        : kind === "unit"
          ? toggle.closest(".Unit")
          : toggle.closest(".Evidence"); // evidence 與 drillev 共用 .Evidence 外框
    host.classList.toggle("is-open");
  });

  // 完成標記的鍵盤操作
  $("#chapters").addEventListener("keydown", (e) => {
    if (e.key !== " " && e.key !== "Enter") return;
    const check = e.target.closest('[data-action="toggle-done"]');
    if (!check) return;
    e.preventDefault();
    e.stopPropagation();
    toggleDone(check.closest(".Unit").dataset.unit);
  });

  // 搜尋
  const searchInput = $("#search");
  let debounce;
  searchInput.addEventListener("input", () => {
    state.query = searchInput.value;
    $("#searchBox").classList.toggle("has-value", !!state.query);
    clearTimeout(debounce);
    debounce = setTimeout(applyFilters, 120);
  });

  $("#searchClear").addEventListener("click", () => {
    searchInput.value = "";
    state.query = "";
    $("#searchBox").classList.remove("has-value");
    applyFilters();
    searchInput.focus();
  });

  // "/" 聚焦搜尋
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) {
      e.preventDefault();
      searchInput.focus();
    }
    if (e.key === "Escape" && document.activeElement === searchInput) {
      searchInput.blur();
    }
  });

  // 類型篩選
  $$(".FilterBar__btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".FilterBar__btn").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.filter = btn.dataset.filter;
      applyFilters();
    });
  });

  // 全部展開／收合
  $("#expandAll").addEventListener("click", () => {
    const anyClosed = $$(".Chapter").some((c) => !c.classList.contains("is-open"));
    $$(".Chapter").forEach((c) => c.classList.toggle("is-open", anyClosed));
    save(STORE.open, anyClosed);
  });

  // 重設進度
  $("#resetProgress").addEventListener("click", () => {
    if (!state.done.size) return;
    if (!confirm(t("confirmReset", "確定要清除完成紀錄嗎？") + ` (${state.done.size})`)) return;
    state.done.clear();
    save(STORE.done, []);
    $$(".Unit").forEach((u) => {
      u.classList.remove("is-done");
      $(".Unit__check", u)?.setAttribute("aria-checked", "false");
    });
    renderProgress();
    renderNav();
    updateChapterMeta();
  });

  // 主題
  $("#themeToggle").addEventListener("click", () => {
    const current =
      document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    save(STORE.theme, next);
    syncThemeIcon();
    discuss.syncTheme();
  });

  // 側欄高亮：每次都從所有章節的實際位置重算，不依賴 observer 的事件順序。
  //
  // 舊版對每個 isIntersecting 的 entry 直接 toggle，有兩個問題：
  //   1. 兩個章節同時落在觀察帶內時，最後被迭代到的那個贏，而順序是不保證的；
  //      只要兩者都持續 intersecting 就不會再有 callback，高亮從此卡住。
  //   2. 點側欄連結只有原生錨點跳轉，若跳轉後 intersecting 的集合沒變，
  //      callback 根本不觸發，高亮完全不動。
  // 章節愈少、愈長，這兩個問題愈明顯。
  const NAV_LINE = 96; // 判定線：視窗頂端往下這麼多 px，約略是 header 下緣

  const canScroll = () => document.documentElement.scrollHeight > window.innerHeight + 4;

  function activeChapterCode() {
    const chapters = $$(".Chapter");
    if (!chapters.length) return null;
    let current = chapters[0].dataset.chapter;
    for (const c of chapters) {
      const { top, bottom } = c.getBoundingClientRect();
      // 已越過判定線且尚未捲出去的那一章就是當前章節
      if (top <= NAV_LINE && bottom > NAV_LINE) return c.dataset.chapter;
      if (top <= NAV_LINE) current = c.dataset.chapter;
    }
    // 捲到最底要把最後一章點亮，否則它永遠亮不起來
    if (canScroll() && window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
      return chapters[chapters.length - 1].dataset.chapter;
    }
    return current;
  }

  function setNavActive(code) {
    if (!code) return;
    $$("[data-nav]").forEach((a) => a.classList.toggle("is-active", a.dataset.nav === code));
  }

  // 使用者剛點的章節。捲動位置還沒落定前不能被 scroll-spy 蓋掉，
  // 而且章節全部收合、整頁不能捲的時候，永遠以使用者的點選為準——
  // 那種情況下四章同時可見，scroll-spy 本來就分辨不出「現在在哪一章」。
  let picked = null;
  let pickedUntil = 0;

  let navTick = 0;
  function syncNavHighlight() {
    if (navTick) return;
    navTick = requestAnimationFrame(() => {
      navTick = 0;
      if (picked && (performance.now() < pickedUntil || !canScroll())) {
        return setNavActive(picked);
      }
      picked = null;
      setNavActive(activeChapterCode());
    });
  }

  function pickChapter(code) {
    if (!code) return;
    picked = code;
    pickedUntil = performance.now() + 700; // 等錨點捲動落定
    setNavActive(code);
  }

  $("#nav").addEventListener("click", (e) => {
    pickChapter(e.target.closest("[data-nav]")?.dataset.nav);
  });
  // 直接開 /#CH3 這種網址進來也要對
  addEventListener("hashchange", () => pickChapter(location.hash.slice(1) || null));
  if (location.hash) pickChapter(location.hash.slice(1));

  addEventListener("scroll", syncNavHighlight, { passive: true });
  addEventListener("resize", syncNavHighlight, { passive: true });
  // 章節展開／收合會改變高度，捲動位置沒變但當前章節可能已經不同
  $("#chapters").addEventListener("click", () => setTimeout(syncNavHighlight, 0));
  syncNav = syncNavHighlight;
  syncNavHighlight();
}

function syncThemeIcon() {
  const dark =
    (document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  $("#themeToggle svg use").setAttribute("href", dark ? "#i-moon" : "#i-sun");
}

/* --- 啟動 ---------------------------------------------------------------- */

async function init() {
  mountIcons();
  syncThemeIcon();

  let data;
  try {
    const res = await fetch("course.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    $("#chapters").innerHTML = `
      <div class="Blankslate">
        ${icon("triangle-alert", 32)}
        <p class="Blankslate__heading">${rich(t("loadFailed", "課程資料載入失敗"))}</p>
        <p>${esc(err.message)}</p>
      </div>`;
    return;
  }

  state.course = data;

  // localStorage 的命名空間要等這裡才決定得了：前綴取自 site.project，
  // 而 site.project 在 course.json 裡。搬遷必須排在第一次 load() 之前，
  // 否則升級後的第一次載入會讀到空的進度、然後被存回去覆蓋掉舊資料。
  migrateLegacy(data.config);
  STORE = { ...keysFor(data.config), theme: THEME_KEY };

  state.done = new Set(load(STORE.done, []));

  setConfig(data.config);
  renderFilterBar(data.config);
  setLanguages(data.config?.languages);
  discuss.setDiscussions(data.config?.discussions);
  applyChrome(data);
  renderHits(data.config); // 不 await，取數慢不該擋住畫面
  setDrillEvidence(data.drillEvidence);

  // paywall 要在畫任何章節之前決定好，不然會先閃一下未鎖的樣子。
  // demo 版 ready() 不需要等，但真 paywall 會在這裡問伺服器。
  if (paywall.init(data.config, { onChange: onPaywallChange })) {
    await paywall.ready();
    setAccess(paywall.canAccess);
  }

  renderChapters();

  const stanceEl = $("#view-stance");
  if (data.stance?.length) {
    stanceEl.innerHTML = renderStance(data.stance);
    $("#tabStanceCount").textContent = data.stance.length;
  } else {
    stanceEl.remove();
    $('.TabNav__item[data-tab="stance"]')?.remove();
  }

  $("#tabCourseCount").textContent = data.meta.units;

  state.playlist = buildPlaylist(data);
  state.playlist.forEach((it, i) => urlIndex.set(it.url, i));
  state.playing = load(STORE.playing, -1);

  $("#landingBody").innerHTML = renderHome(data);
  renderStats();
  renderNav();
  renderFacetPanel(data);
  renderProgress();
  bindEvents();
  watchFrame();
  initResizer(load(STORE.listW, 0), (w) => save(STORE.listW, w));
  bindKeys({
    next: () => {
      if (state.tab !== "player") setTab("player");
      playAt(state.playing + 1);
    },
    prev: () => {
      if (state.tab !== "player") setTab("player");
      playAt(Math.max(0, state.playing - 1));
    },
    isPlayerTab: () => state.tab === "player",
  });
  applyFilters();

  // ?tab=player&play=12 可直接開到指定分頁與影片，也方便分享連結
  const params = new URLSearchParams(location.search);
  const wanted = params.get("tab");
  setTab(
    ["home", "course", "player", "stance"].includes(wanted)
      ? wanted
      : load(STORE.tab, "home"),
  );

  const deepPlay = Number(params.get("play"));
  if (state.tab === "player" && Number.isInteger(deepPlay) && state.playlist[deepPlay]) {
    state.playing = deepPlay;
  }
  // 還原上次看到哪，但不自動播放，回來時先看到資訊就好。
  // 上次看的那支後來被鎖住（清掉訂單）就別還原，不然一進站就跳 paywall
  const resume = state.playlist[state.playing];
  if (state.tab === "player" && resume && paywall.canAccess(resume.chCode)) {
    playAt(state.playing);
  }

  // 首次造訪展開觀念篇第一章，讓畫面不是一片收合
  if (load(STORE.open, null) === null) {
    $('[data-chapter="CH0"]')?.classList.add("is-open");
  }

  // 深連結：#ch5-u1 直接展開該單元
  if (location.hash) {
    const target = $(CSS.escape(location.hash.slice(1)) ? location.hash : "");
    if (target?.classList.contains("Unit")) {
      target.classList.add("is-open");
      target.closest(".Chapter")?.classList.add("is-open");
      target.scrollIntoView({ block: "center" });
    } else if (target?.classList.contains("Chapter")) {
      target.classList.add("is-open");
    }
  }
}

init();

/** 篩選列的按鈕依設定檔的 kinds 生成。
    寫死在 index.html 裡的按鈕換主題不會跟著變，而且不會有任何錯誤訊息。

    「全部」那一顆以前是寫死的字串——就在這個函式裡，緊鄰著上面那句註解。
    修好了類型按鈕，卻在同一段程式碼裡留下一個換語言不會變的中文字。
    gym-course 的 v1 設定檔本來有 ui.filterAll 這個欄位，v2 把它弄丟了。 */
function renderFilterBar(cfg) {
  const group = $(".FilterBar__group");
  if (!group) return;
  group.setAttribute("aria-label", text(cfg?.ui?.kindFilterLabel || "類型篩選"));
  group.innerHTML =
    '<button class="FilterBar__btn is-active" data-filter="all" type="button">' +
    `${rich(cfg?.ui?.filterAllLabel || "全部")}</button>` +
    (cfg?.kinds || [])
      .map(
        (k) =>
          `<button class="FilterBar__btn" data-filter="${esc(k.id)}" type="button">` +
          `<span class="Drill__marker Drill__marker--${esc(k.id)}"></span>${rich(k.label)}</button>`,
      )
      .join("");
}
