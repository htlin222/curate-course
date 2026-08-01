// filters.js — 搜尋、項目類型、分面篩選
import { icon } from "./icons.js";
import { esc, UI } from "./render.js";
import { rich, text } from "./copy.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* --- 分面面板 ------------------------------------------------------------ */

export function renderFacetPanel(course) {
  const list = course.facets || [];
  if (!list.length) {
    $("#facetPanel")?.remove();
    return;
  }

  const byGroup = new Map();
  for (const f of list) {
    if (!byGroup.has(f.group)) byGroup.set(f.group, []);
    byGroup.get(f.group).push(f);
  }

  $("#facetCount").textContent = list.length;
  $("#facetBody").innerHTML =
    [...byGroup]
      .map(
        ([group, items]) => `
        <div class="FacetGroup__title">${esc(group)}</div>
        <div class="FacetChips">
          ${items
            .map(
              (f) => `
            <button class="FacetChip" type="button" data-facet="${esc(f.name)}">
              ${esc(f.name)}<span class="FacetChip__n">${f.count}</span>
            </button>`,
            )
            .join("")}
        </div>`,
      )
      .join("") +
    `<button class="btn FacetPanel__clear" id="facetClear" type="button">
       ${icon("rotate-ccw", 12)} ${rich(UI.facetClear || "")}
     </button>`;
}

/** 同步所有分面按鈕（側欄 chip + 項目內的標籤）的選取狀態 */
export function syncFacetChips(selected) {
  $$("[data-facet]").forEach((el) =>
    el.classList.toggle("is-active", selected.has(el.dataset.facet)),
  );
  const panel = $("#facetPanel");
  if (panel && selected.size) panel.classList.add("is-open");
}

/* --- 主篩選 -------------------------------------------------------------- */

/**
 * 依 state 顯示／隱藏章節、單元與項目。
 * state: { query, filter, facets:Set }
 */
export function applyFilters(state, course) {
  const q = state.query.trim().toLowerCase();
  const sel = state.facets;
  let visibleUnits = 0;
  let visibleDrills = 0;

  $$(".Chapter").forEach((chEl) => {
    let chapterHasMatch = false;

    $$(".Unit", chEl).forEach((unitEl) => {
      const unitFacets = (unitEl.dataset.facets || "").split("|").filter(Boolean);
      const facetOk = !sel.size || unitFacets.some((f) => sel.has(f));
      const textOk = !q || unitEl.textContent.toLowerCase().includes(q);
      const match = facetOk && textOk;

      unitEl.hidden = !match;
      if (!match) return;

      chapterHasMatch = true;
      visibleUnits++;

      // 項目層級：類型 + 分面兩個維度
      $$(".Drill", unitEl).forEach((d) => {
        const kindOk = state.filter === "all" || d.dataset.kind === state.filter;
        const df = (d.dataset.facets || "").split("|").filter(Boolean);
        const fOk = !sel.size || df.some((f) => sel.has(f));
        d.hidden = !(kindOk && fOk);
        if (kindOk && fOk) visibleDrills++;
      });

      // 整組項目都被篩掉就把標題也收起來
      $$(".DrillGroup", unitEl).forEach((g) => {
        const anyVisible = $$(".Drill", g).some((d) => !d.hidden);
        g.hidden = !anyVisible;
      });
    });

    chEl.hidden = !chapterHasMatch;
    if ((q || sel.size) && chapterHasMatch) chEl.classList.add("is-open");
  });

  const totalDrills = course.meta.drill_units;
  const parts = [];
  if (q) parts.push(`「${state.query.trim()}」`);
  if (sel.size) parts.push(`${text(UI.facetPrefix || "")}：${[...sel].join("、")}`);

  // paywall 鎖住的章節不渲染動作，所以分母對不上時要講清楚為什麼
  const locked = state.lockedNote ? ` · ${state.lockedNote}` : "";

  $("#filterCount").textContent = parts.length
    ? `${visibleUnits} ${text(UI.unitNoun || "個單元")} · ${visibleDrills} ${text(UI.drillNoun || "支跟練影片")}符合 ${parts.join(" + ")}`
    : `顯示 ${visibleDrills} / ${totalDrills} ${text(UI.drillNoun || "支跟練影片")}${locked}`;

  toggleBlankslate(visibleUnits);
  return { visibleUnits, visibleDrills };
}

function toggleBlankslate(visibleUnits) {
  const host = $("#chapters");
  const existing = $("#filterBlank");
  if (visibleUnits === 0 && !existing) {
    host.insertAdjacentHTML(
      "beforeend",
      `<div class="Blankslate" id="filterBlank">
         ${icon("inbox", 32)}
         <p class="Blankslate__heading">${rich(UI.emptyTitle || "")}</p>
         <p>${rich(UI.emptyHint || "")}</p>
       </div>`,
    );
  } else if (visibleUnits > 0 && existing) {
    existing.remove();
  }
}
