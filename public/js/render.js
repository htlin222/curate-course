// render.js — 把 course.json 的資料轉成 DOM 字串
import { icon } from "./icons.js";

/** HTML 逸出，資料雖為自產仍一律過濾 */
export const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

export const KIND = {
  release: { label: "放鬆", dot: "🔵", icon: "circle-dot" },
  stretch: { label: "拉伸", dot: "🟢", icon: "move-vertical" },
  train: { label: "訓練", dot: "🔴", icon: "dumbbell" },
};

const GRADE = {
  strong: { label: "證據充分", cls: "Label--stretch" },
  moderate: { label: "證據中等", cls: "Label--accent" },
  limited: { label: "證據有限", cls: "Label--attention" },
  contested: { label: "證據互斥", cls: "Label--danger" },
};

/* --- 影片 ---------------------------------------------------------------- */

/** 觀看數縮寫：1038712 -> 104 萬 */
function views(n) {
  if (!n) return "";
  if (n >= 1e8) return `${(n / 1e8).toFixed(1)} 億次`;
  if (n >= 1e4) return `${Math.round(n / 1e4)} 萬次`;
  return `${n.toLocaleString("en-US")} 次`;
}

/** 播放鈕：主課與跟練共用同一個元件，只差尺寸 */
function playBtn(sm = false, disabled = false) {
  const cls = `PlayBtn${sm ? " PlayBtn--sm" : ""}${disabled ? " PlayBtn--disabled" : ""}`;
  return `<span class="${cls}">${icon(disabled ? "inbox" : "play", sm ? 14 : 16)}</span>`;
}

function videoCard(v) {
  if (!v || !v.url) {
    return `
      <div class="VideoCard VideoCard--missing">
        <span class="VideoCard__badge">${icon("book-open", 16)}</span>
        <span class="VideoCard__main">
          <span class="VideoCard__title">尚未找到合格影片</span>
          <span class="VideoCard__meta">${esc(v?.note || "這個主題在 YouTube 上沒有品質足夠的示範")}</span>
        </span>
        ${playBtn(false, true)}
      </div>`;
  }

  return `
    <a class="VideoCard" href="${esc(v.url)}" target="_blank" rel="noopener">
      <span class="VideoCard__badge">${icon("book-open", 16)}</span>
      <span class="VideoCard__main">
        <span class="VideoCard__title">${esc(v.title)}</span>
        <span class="VideoCard__meta">
          <span>${esc(v.channel)}</span>
          ${v.duration ? `<span>· ${esc(v.duration)}</span>` : ""}
          ${v.views ? `<span>· ${views(v.views)}</span>` : ""}
        </span>
        ${v.why ? `<span class="VideoCard__why">${esc(v.why)}</span>` : ""}
      </span>
      ${playBtn()}
    </a>`;
}

const LANG_LABEL = { zh: "繁中", en: "English", ja: "日本語" };

/** 主課可能有多個語言版本，用小分頁切換 */
function lessonBox(u) {
  const lessons = (u.lessons || (u.lesson ? [u.lesson] : [])).filter(Boolean);
  if (!lessons.length) return videoCard(null);
  if (lessons.length === 1) return videoCard(lessons[0]);

  return `
    <div class="LessonBox">
      <div class="LessonBox__langs" role="tablist" aria-label="主課語言">
        ${lessons
          .map(
            (l, i) => `
          <button class="LessonBox__lang${i === 0 ? " is-active" : ""}" type="button"
                  role="tab" aria-selected="${i === 0}" data-lesson="${i}">
            ${esc(LANG_LABEL[l.lang] || l.lang || "其他")}
          </button>`,
          )
          .join("")}
      </div>
      ${lessons
        .map(
          (l, i) =>
            `<div class="LessonBox__pane" data-lesson-pane="${i}"${i ? " hidden" : ""}>${videoCard(l)}</div>`,
        )
        .join("")}
    </div>`;
}

/* --- 動作清單 ------------------------------------------------------------ */

function muscleTags(list) {
  return (list || [])
    .map(
      (m) =>
        `<button class="Label Label--neutral Label--muscle" data-muscle="${esc(m)}"
                 type="button" title="篩選涉及 ${esc(m)} 的內容">${esc(m)}</button>`,
    )
    .join("");
}

function drill(d) {
  const inner = `
    <span class="Drill__marker Drill__marker--${esc(d.kind)}"></span>
    <span class="Drill__main">
      <span class="Drill__name">${esc(d.name)}${d.en ? ` <span class="Drill__en">${esc(d.en)}</span>` : ""}</span>
      <span class="Drill__meta">
        ${d.target ? `<span>${esc(d.target)}</span>` : ""}
        ${d.dose ? `<span class="Drill__dose">${esc(d.dose)}</span>` : ""}
        ${d.channel ? `<span>· ${esc(d.channel)}</span>` : ""}
        ${d.duration ? `<span>· ${esc(d.duration)}</span>` : ""}
      </span>
      ${(d.muscles || []).length ? `<span class="Drill__muscles">${muscleTags(d.muscles)}</span>` : ""}
    </span>
    ${playBtn(true, !d.url)}`;

  const attrs = `class="Drill" data-kind="${esc(d.kind)}" data-muscles="${esc((d.muscles || []).join("|"))}"${d.cat ? ` data-cat="${esc(d.cat)}"` : ""}`;

  // 有連結就整列可點，跟主課卡片一致
  return d.url
    ? `<li ${attrs}><a class="Drill__link" href="${esc(d.url)}" target="_blank" rel="noopener" title="${esc(d.title || "觀看示範")}">${inner}</a></li>`
    : `<li ${attrs}><span class="Drill__link" aria-disabled="true" title="尚未找到合格影片">${inner}</span></li>`;
}

function drillGroup(kind, list) {
  if (!list.length) return "";
  const k = KIND[kind];
  return `
    <div class="DrillGroup" data-group="${kind}">
      <h4 class="DrillGroup__title">
        <span class="Drill__marker Drill__marker--${kind}"></span>
        ${k.label}
        <span class="Counter">${list.length}</span>
      </h4>
      <ul class="DrillList">${list.map(drill).join("")}</ul>
    </div>`;
}

/* --- 實證註記 ------------------------------------------------------------ */

function evidence(ev, unitId) {
  if (!ev) return "";
  const g = GRADE[ev.evidence_grade] || GRADE.limited;

  const row = (key, val) =>
    val
      ? `<div class="Evidence__row"><span class="Evidence__key">${key}</span><span>${esc(val)}</span></div>`
      : "";

  const flags = (ev.red_flags || []).length
    ? `<div class="Evidence__row">
         <span class="Evidence__key">就醫警訊</span>
         <span class="Evidence__flags">
           ${ev.red_flags.map((f) => `<span class="Label Label--danger">${esc(f)}</span>`).join("")}
         </span>
       </div>`
    : "";

  const cites = (ev.citations || []).length
    ? `<div class="Evidence__cite">
         ${ev.citations
           .map(
             (c) =>
               `<a href="${esc(c.url)}" target="_blank" rel="noopener" title="${esc(c.title)}">${esc(c.journal || c.title)}${c.year ? ` ${esc(c.year)}` : ""}</a>`,
           )
           .join("")}
       </div>`
    : "";

  return `
    <section class="Evidence" data-evidence="${esc(unitId)}">
      <button class="Evidence__header" type="button" data-toggle="evidence">
        ${icon("microscope", 14)}
        <span>實證強度</span>
        <span class="Label ${g.cls}">${g.label}</span>
        <span class="Evidence__spacer"></span>
        ${ev.url ? `<span class="Label Label--neutral">OpenEvidence</span>` : ""}
        <span class="Evidence__chevron">${icon("chevron-right", 14)}</span>
      </button>
      <div class="Evidence__body">
        ${row("與疼痛關聯", ev.pain_link)}
        ${row("肌群模型", ev.muscle_model)}
        ${row("骨性 vs 可練", ev.structural_vs_modifiable)}
        ${row("介入效果", ev.intervention)}
        ${row("評估信效度", ev.assessment_validity)}
        ${row("摘要", ev.summary)}
        ${flags}
        ${row("課程須誠實告知", ev.caveats)}
        ${cites}
        ${
          ev.url
            ? `<div class="Evidence__cite"><a href="${esc(ev.url)}" target="_blank" rel="noopener">在 OpenEvidence 讀完整回答 ${icon("external-link", 11)}</a></div>`
            : ""
        }
      </div>
    </section>`;
}

/* --- 動作類別的實證 ------------------------------------------------------ */

let DRILL_EV = {};

export function setDrillEvidence(map) {
  DRILL_EV = map || {};
}

function drillEvidence(u) {
  const cats = [...new Set((u.drills || []).map((d) => d.cat).filter(Boolean))]
    .map((id) => DRILL_EV[id])
    .filter((c) => c && c.citations?.length);
  if (!cats.length) return "";

  const totalCites = cats.reduce((n, c) => n + c.citations.length, 0);

  const block = (cat) => {
    const g = GRADE[cat.evidence_grade] || GRADE.limited;
    return `
      <details class="DrillEvCat">
        <summary>
          <span class="DrillEvCat__name">${esc(cat.name)}</span>
          <span class="Label ${g.cls}">${g.label}</span>
          <span class="Counter">${cat.citations.length}</span>
        </summary>
        ${cat.summary ? `<p class="DrillEvCat__summary">${esc(cat.summary)}</p>` : ""}
        <ol class="DrillEvCat__cites">
          ${cat.citations
            .map(
              (c) => `
            <li>
              <a href="https://pubmed.ncbi.nlm.nih.gov/${esc(c.pmid)}/" target="_blank" rel="noopener">${esc(c.title)}</a>
              <span class="DrillEvCat__src">${esc(c.journal || "")}${c.year ? ` ${esc(c.year)}` : ""}${c.design ? ` · ${esc(c.design)}` : ""} · PMID ${esc(c.pmid)}</span>
              ${c.takeaway ? `<span class="DrillEvCat__take">${esc(c.takeaway)}</span>` : ""}
            </li>`,
            )
            .join("")}
        </ol>
      </details>`;
  };

  return `
    <section class="Evidence DrillEv" data-drillev="${esc(u.id)}">
      <button class="Evidence__header" type="button" data-toggle="drillev">
        ${icon("microscope", 14)}
        <span>這些動作的實證</span>
        <span class="Counter">${cats.length} 類 · ${totalCites} 篇</span>
        <span class="Evidence__spacer"></span>
        <span class="Label Label--neutral">PubMed</span>
        <span class="Evidence__chevron">${icon("chevron-right", 14)}</span>
      </button>
      <div class="Evidence__body DrillEv__body">${cats.map(block).join("")}</div>
    </section>`;
}

/* --- 肌群 ---------------------------------------------------------------- */

function muscles(tight, weak) {
  if (!tight?.length && !weak?.length) return "";
  const block = (mod, iconName, title, list) =>
    list?.length
      ? `<div class="MuscleBlock MuscleBlock--${mod}">
           <h4 class="MuscleBlock__title">${icon(iconName, 12)} ${title}</h4>
           <div class="MuscleBlock__list">
             ${list.map((m) => `<span class="Label Label--neutral">${esc(m)}</span>`).join("")}
           </div>
         </div>`
      : "";

  return `
    <div class="MuscleGrid">
      ${block("tight", "flame", "傾向緊繃／過度活躍", tight)}
      ${block("weak", "battery-low", "傾向無力／活化不足", weak)}
    </div>`;
}

/* --- 單元 ---------------------------------------------------------------- */

export function renderUnit(u, done) {
  const counts = { release: 0, stretch: 0, train: 0 };
  (u.drills || []).forEach((d) => {
    if (counts[d.kind] != null) counts[d.kind]++;
  });
  const total = (u.drills || []).length;

  const badges = [
    u.type === "posture"
      ? `<span class="Label Label--neutral">體態問題</span>`
      : u.type === "foundation"
        ? `<span class="Label Label--accent">基礎</span>`
        : u.type === "guide"
          ? `<span class="Label Label--neutral">說明</span>`
          : `<span class="Label Label--neutral">觀念</span>`,
    total ? `<span class="Label Label--neutral">${icon("layers", 11)} ${total}</span>` : "",
    // 實證強度直接標在標題列。contested 的單元不該要展開才看得到
    u.evidence?.evidence_grade
      ? `<span class="Label ${(GRADE[u.evidence.evidence_grade] || GRADE.limited).cls}"
               title="OpenEvidence 查證結果">${icon("microscope", 11)} ${(GRADE[u.evidence.evidence_grade] || GRADE.limited).label}</span>`
      : "",
  ].join("");

  const groups = ["release", "stretch", "train"]
    .map((k) => drillGroup(k, (u.drills || []).filter((d) => d.kind === k)))
    .join("");

  // 單元自身的肌群 + 底下所有動作的肌群，供側欄篩選比對
  const allMuscles = [
    ...new Set([...(u.muscles || []), ...(u.drills || []).flatMap((d) => d.muscles || [])]),
  ];

  return `
    <article class="Unit${done ? " is-done" : ""}" id="${esc(u.id)}" data-unit="${esc(u.id)}"
             data-muscles="${esc(allMuscles.join("|"))}">
      <button class="Unit__header" type="button" data-toggle="unit">
        <span class="Unit__check" data-action="toggle-done" role="checkbox"
              aria-checked="${done}" tabindex="0" title="標記為完成">${icon("check", 12)}</span>
        <span class="Unit__main">
          <span class="Unit__title">${esc(u.name)} ${badges}</span>
          ${u.summary ? `<span class="Unit__summary">${esc(u.summary)}</span>` : ""}
        </span>
        <span class="Unit__chevron">${icon("chevron-right", 16)}</span>
      </button>

      <div class="Unit__body">
        ${lessonBox(u)}
        ${
          u.assessment
            ? `<div class="Assessment">
                 <span class="Assessment__icon">${icon("clipboard-check", 16)}</span>
                 <span><span class="Assessment__label">怎麼自己評估</span>${esc(u.assessment)}</span>
               </div>`
            : ""
        }
        ${muscles(u.tight, u.weak)}
        ${evidence(u.evidence, u.id)}
        ${groups}
        ${drillEvidence(u)}
      </div>
    </article>`;
}

/* --- 立場聲明 ------------------------------------------------------------ */

// 從 OpenEvidence 的完整回答提煉出的一句話結論
const VERDICT = {
  "concept-1": "體態偏差與疼痛確實相關，但因果關係在文獻中沒有共識。",
  "concept-2": "交叉症候群是好用的記憶架構，不是已驗證的診斷。",
  "concept-3": "矯正運動有效，但不是因為它把體態「調正」了。",
};

export function renderStance(stance) {
  if (!stance?.length) return "";

  const card = (s, i) => {
    const g = GRADE[s.evidence_grade] || GRADE.limited;
    const findings = (s.key_findings || []).length
      ? `<details>
           <summary>看完整實證（${s.key_findings.length} 項發現）</summary>
           <ul class="StanceCard__findings">
             ${s.key_findings.map((f) => `<li>${esc(f)}</li>`).join("")}
           </ul>
           ${s.caveats ? `<ul class="StanceCard__findings"><li>${esc(s.caveats)}</li></ul>` : ""}
         </details>`
      : "";

    const cites = (s.citations || []).length
      ? `<div class="StanceCard__cites">
           ${s.citations
             .map(
               (c) =>
                 `<a href="${esc(c.url)}" target="_blank" rel="noopener" title="${esc(c.title)}">${esc(c.journal || c.title)}${c.year ? ` ${esc(c.year)}` : ""}</a>`,
             )
             .join("")}
         </div>`
      : "";

    return `
      <article class="StanceCard">
        <header class="StanceCard__head">
          <span class="StanceCard__n">${i + 1}</span>
          <span class="StanceCard__name">${esc(s.name)}</span>
          <span class="Label ${g.cls}">${g.label}</span>
        </header>
        <div class="StanceCard__body">
          <p class="StanceCard__verdict">${esc(VERDICT[s.unit] || "")}</p>
          <p class="StanceCard__summary">${esc(s.summary)}</p>
          ${findings}
        </div>
        <footer class="StanceCard__foot">
          ${cites}
          ${
            s.url
              ? `<div class="StanceCard__cites" style="margin-top:6px">
                   <a href="${esc(s.url)}" target="_blank" rel="noopener">在 OpenEvidence 讀完整回答 ${icon("external-link", 10)}</a>
                 </div>`
              : ""
          }
        </footer>
      </article>`;
  };

  return `
    <div class="StancePage__intro">
      <h2>${icon("microscope", 22)} 這門課的立場</h2>
      <p>
        在做這門課之前，我們先把三個最根本的問題丟給 OpenEvidence 查證：
        體態真的會導致疼痛嗎？Janda 的交叉症候群是真的嗎？矯正運動到底有多有效？
        答案沒有想像中好聽——但把它講清楚，比賣一個承諾誠實得多。
        以下每一條結論都附原始文獻連結，你可以自己去查。
      </p>
    </div>
    <div class="StancePage__grid">${stance.map(card).join("")}</div>
    <div class="StancePage__outro">
      <strong>所以這門課的定位是什麼？</strong>
      運動的效益來自肌力、負荷耐受度、神經生理止痛與心理社會因素，
      <strong>而不是生物力學上把體態「調正」</strong>。體態數值的改善是伴隨現象，不是療效機轉；
      也沒有證據顯示精心設計的矯正課表比一般運動更有效。
      這不代表別練——而是別把它當成治病，把它當成一套讓身體更耐操、動起來更舒服的訓練。
      真正需要診斷與治療的狀況，請去看醫師或物理治療師。
    </div>`;
}

/* --- 章節 ---------------------------------------------------------------- */

export function renderChapter(ch, doneSet) {
  const doneCount = ch.units.filter((u) => doneSet.has(u.id)).length;
  const pct = ch.units.length ? Math.round((doneCount / ch.units.length) * 100) : 0;
  const drillTotal = ch.units.reduce((n, u) => n + (u.drills?.length || 0), 0);

  return `
    <section class="Chapter" id="${esc(ch.code)}" data-chapter="${esc(ch.code)}">
      <button class="Chapter__header" type="button" data-toggle="chapter">
        <span class="Chapter__num">${icon(ch.icon || "circle-dot", 18)}</span>
        <span class="Chapter__titles">
          <span class="Chapter__title">
            <span class="Chapter__code">${esc(ch.code)}</span>
            ${esc(ch.title)}
          </span>
          <span class="Chapter__meta">
            ${ch.units.length} 個單元${drillTotal ? ` · ${drillTotal} 支跟練影片` : ""}
            ${doneCount ? ` · 已完成 ${doneCount}` : ""}
          </span>
        </span>
        <span class="Chapter__progress">
          <span class="ProgressBar ProgressBar--thin">
            <span class="ProgressBar__fill" style="width:${pct}%"></span>
          </span>
        </span>
        <span class="Chapter__chevron">${icon("chevron-right", 16)}</span>
      </button>
      <div class="Chapter__body">
        ${ch.units.map((u) => renderUnit(u, doneSet.has(u.id))).join("")}
      </div>
    </section>`;
}

/* --- 首頁 ---------------------------------------------------------------- */

const STEPS = [
  ["clipboard-check", "先評估", "每個體態問題都附可以自己做的測試——靠牆、躺下、拍張側面照就能判斷。不確定自己屬於哪一型，就別急著跟著練。"],
  ["dumbbell", "再跟著練", "每個問題配 9–18 支跟練影片，分成放鬆、拉伸、訓練三類，依久坐族的盛行率加權分配，不是平均攤。"],
  ["microscope", "順便查證", "每個單元標了實證強度，動作類別附 PubMed 文獻。結果不好看的也照寫——這是這門課跟其他體態課最大的差別。"],
];

export function renderHome(course) {
  const { meta, chapters, stance } = course;

  const steps = STEPS.map(
    ([ic, title, body], i) => `
    <div class="Step">
      <span class="Step__n">${icon(ic, 18)}</span>
      <div>
        <h3 class="Step__title">${i + 1}. ${esc(title)}</h3>
        <p class="Step__body">${esc(body)}</p>
      </div>
    </div>`,
  ).join("");

  const stanceCards = (stance || []).map((s) => {
    const g = GRADE[s.evidence_grade] || GRADE.limited;
    return `
      <div class="LandingStance">
        <div class="LandingStance__head">
          <span class="Label ${g.cls}">${g.label}</span>
          <strong>${esc(s.name)}</strong>
        </div>
        <p>${esc(VERDICT[s.unit] || "")}</p>
      </div>`;
  }).join("");

  const chapterCards = chapters.map((ch) => {
    const drills = ch.units.reduce((n, u) => n + (u.drills?.length || 0), 0);
    return `
      <button class="ChapterCard" type="button" data-goto-chapter="${esc(ch.code)}">
        <span class="ChapterCard__icon">${icon(ch.icon || "circle-dot", 18)}</span>
        <span class="ChapterCard__main">
          <span class="ChapterCard__title"><span class="Chapter__code">${esc(ch.code)}</span> ${esc(ch.title)}</span>
          <span class="ChapterCard__meta">${ch.units.length} 單元${drills ? ` · ${drills} 支跟練` : ""}</span>
          <span class="ChapterCard__units">${ch.units.map((u) => esc(u.name)).join("、")}</span>
        </span>
      </button>`;
  }).join("");

  return `
    <section class="Landing__section">
      <h2 class="Landing__h2">${icon("book-open", 20)} 怎麼用這門課</h2>
      <div class="Steps">${steps}</div>
    </section>

    <section class="Landing__section">
      <h2 class="Landing__h2">${icon("microscope", 20)} 開始之前，先知道這件事</h2>
      <p class="Landing__lede">
        我們把三個最根本的問題丟給 OpenEvidence 查證，答案沒有想像中好聽。
        與其讓你練完才發現，不如一開始就講清楚。
      </p>
      <div class="Landing__stance">${stanceCards}</div>
      <button class="btn" type="button" data-tab-link="stance">
        讀完整實證與原始文獻 ${icon("chevron-right", 14)}
      </button>
    </section>

    <section class="Landing__section">
      <h2 class="Landing__h2">${icon("layers", 20)} 十二個章節，從頭到腳</h2>
      <div class="ChapterGrid">${chapterCards}</div>
    </section>

    <section class="Landing__cta">
      <div>
        <h2 class="Landing__h2">準備好就開始</h2>
        <p class="Landing__lede">
          ${meta.units} 個單元、${meta.video_slots} 支影片，全部免費。
          進度存在你自己的瀏覽器裡，沒有帳號、沒有後端。
        </p>
      </div>
      <div class="Landing__ctaBtns">
        <button class="btn btn-primary" type="button" data-tab-link="player">
          ${icon("play", 14)} 進入上課模式
        </button>
        <button class="btn" type="button" data-tab-link="course">
          ${icon("layers", 14)} 瀏覽課程內容
        </button>
      </div>
    </section>`;
}
