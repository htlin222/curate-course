// /curate-chapter 的確定性稽核。零依賴、不需要瀏覽器：node --test tests/
//
// 這 60 行決定一次策展要不要落地，是整份工作流程唯一的品質關卡——而它一直
// 沒有測試。實測在裡面找到三個 bug（unitId 由 agent 猜、單元身分完全沒查、
// 同單元重複沒擋），全部是靠實際跑十幾分鐘跑出來的，不是靠測試。
//
// 測法：把 curate-chapter.js 裡 <audit-core> 與 </audit-core> 之間的原始碼
// **原地抽出來執行**，不另外抄一份。抄一份的話兩邊會各自演化，而這個 repo
// 已經有 copy.js / seo.py 那組雙實作要維護了，不需要第二組。
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

import { repo } from "./_paths.js";

const WORKFLOW = repo(".claude", "workflows", "curate-chapter.js");

/** 從工作流程原始碼裡取出稽核核心並求值。哨兵不見了就直接失敗——
    那代表有人重構掉了這段，而測試還在假裝守著它。 */
function loadAuditCore() {
  const src = fs.readFileSync(WORKFLOW, "utf8");
  const open = src.indexOf("// <audit-core>");
  const close = src.indexOf("// </audit-core>");
  assert.ok(open !== -1 && close > open, "curate-chapter.js 裡找不到 <audit-core> 哨兵");
  const region = src.slice(open, close);
  assert.match(region, /function auditCuration\(/, "<audit-core> 裡沒有 auditCuration");
  return new Function(`${region}; return auditCuration`)();
}

const auditCuration = loadAuditCore();

test("稽核核心的內部變數沒有洩漏到函式外面被使用", () => {
  // 實測踩到：把這段算術抽成純函式之後，外面一行 log 還在用 okIds.size。
  // 整章跑完（搜尋、驗證、潤稿、寫檔全部做完）才在最後一行炸掉。
  //
  // 這種錯 `new Function(src)` 的語法檢查抓不到——未定義變數是執行期才炸的。
  // 所以改用結構性的規則：<audit-core> 裡 const/let 宣告的名字，區塊外面不准出現。
  // 要用就走 auditCuration 回傳的 report / blocking / summary。
  const src = fs.readFileSync(WORKFLOW, "utf8");
  const open = src.indexOf("// <audit-core>");
  const close = src.indexOf("// </audit-core>");
  const core = src.slice(open, close);
  const outside = src.slice(0, open) + src.slice(close);

  // 註解與字串字面值裡出現變數名不算「用到」——'drills' 這種寫在 schema 或
  // 提示文字裡的字會製造一堆假警報。但模板字面值的 ${…} 要留著：實際踩到的
  // 那個 bug（${okIds.size}）就在裡面。
  const codeOnly = (s) =>
    s
      .replace(/\/\/[^\n]*/g, "")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/`(?:\\.|[^`\\])*`/g, (lit) =>
        [...lit.matchAll(/\$\{([\s\S]*?)\}/g)].map((m) => m[1]).join(";"),
      )
      .replace(/'(?:\\.|[^'\\])*'/g, "''")
      .replace(/"(?:\\.|[^"\\])*"/g, '""');

  /** const/let 宣告的名字，含解構（const { report, blocking } = …）。 */
  const names = (s) => {
    const out = [...s.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)/g)].map((m) => m[1]);
    for (const m of s.matchAll(/\b(?:const|let|var)\s*[{[]([^}\]]*)[}\]]\s*=/g)) {
      out.push(
        ...m[1]
          .split(",")
          .map((x) => x.split(":").pop().trim())
          .filter(Boolean),
      );
    }
    return out;
  };

  const code = codeOnly(outside);
  const declaredOutside = new Set(names(code));

  const suspects = names(codeOnly(core)).filter(
    (n) =>
      n !== "auditCuration" &&
      n.length >= 4 && // 迴圈變數 r / v / s 各自為政，不是洩漏
      !declaredOutside.has(n), // 外面自己也宣告過的是同名不同物
  );

  // 只認「裸識別字」：前面不是 `.`（屬性存取）、後面不是 `:`（物件鍵）。
  const leaked = suspects.filter((name) =>
    new RegExp(`(?<![.\\w$])${name}\\b(?!\\s*:)`).test(code),
  );

  assert.deepEqual(
    leaked,
    [],
    `這些是 <audit-core> 的內部變數，外面不該用：${leaked.join("、")}。改用 report.*`,
  );
});

/** 造一筆「單元已策展完成」的資料。預設是全部合格的樣子，測試只覆寫要壞的部分。 */
function unitRow(id, { drills = 1, lessonId = `${id}-L`, drillIds = null, results = null } = {}) {
  const ids = drillIds || Array.from({ length: drills }, (_, i) => `${id}-d${i}`);
  const search = {
    lesson: { videoId: lessonId, views: 10000, why: "因為" },
    drills: ids.map((v, i) => ({ name: `動作${i}`, videoId: v, views: 10000 })),
    searchLog: [`${id} 查了一次`],
  };
  return {
    unitId: id,
    results: results || [lessonId, ...ids].map((v) => ({ videoId: v, httpStatus: 200, ok: true })),
    _search: search,
  };
}

const plan = (ids) => ids.map((id) => ({ id, name: `單元 ${id}` }));

const run = (units, rows, over = {}) =>
  auditCuration({
    chapter: "CH10",
    units,
    rows,
    wantUnits: units.length,
    wantDrills: rows.reduce((n, r) => n + (r._search?.drills?.length || 0), 0),
    minViews: 5000,
    ...over,
  });

test("一切正常時不擋，配額算得出來", () => {
  const rows = [unitRow("u1", { drills: 3 }), unitRow("u2", { drills: 2 })];
  const { report, blocking } = run(plan(["u1", "u2"]), rows);

  assert.equal(blocking, false);
  assert.equal(report.units.got, 2);
  assert.equal(report.drills.got, 5);
  assert.equal(report.lessons, 2);
  assert.equal(report.verified, 7); // 2 主課 + 5 動作
  assert.deepEqual(report.dead, []);
});

test("動作數與配額不符就擋——湊不齊不能默默落地", () => {
  const rows = [unitRow("u1", { drills: 3 })];
  const { report, blocking } = run(plan(["u1"]), rows, { wantDrills: 5 });

  assert.equal(blocking, true);
  assert.equal(report.drills.ok, false);
  assert.equal(report.drills.got, 3);
  assert.equal(report.drills.want, 5);
});

test("oEmbed 沒過就擋，並記下 HTTP 狀態", () => {
  const rows = [unitRow("u1", { drills: 1 })];
  rows[0].results[1] = { videoId: "u1-d0", httpStatus: 401, ok: false };
  const { report, blocking } = run(plan(["u1"]), rows);

  assert.equal(blocking, true);
  assert.equal(report.dead.length, 1);
  assert.match(report.dead[0], /u1-d0 · HTTP 401/);
  assert.equal(report.verified, 1); // 只剩主課
});

test("200 但頻道對不上是「指錯片」，不是「失效」", () => {
  // 實測踩到：報告印出「dead · HTTP 200」，讀不通，而且會讓人跑去查連結是不是
  // 掛了——真正的問題是策展資料指到了別支影片。
  const rows = [unitRow("u1", { drills: 1 })];
  rows[0].results[1] = {
    videoId: "u1-d0",
    httpStatus: 200,
    ok: false,
    mismatch: "頻道是 B 頻道，策展寫的是 A 頻道",
  };
  const { report, blocking } = run(plan(["u1"]), rows);

  assert.equal(blocking, true, "指錯片一樣要擋");
  assert.deepEqual(report.dead, [], "200 不該出現在 dead 裡");
  assert.equal(report.wrongVideo.length, 1);
  assert.match(report.wrongVideo[0], /B 頻道/);
});

test("標題不同但 ok=true：只記進 mismatch，不擋", () => {
  // YouTube 有多語言與 A/B 標題，同一支片不同時間回不同標題。以前 ok 的定義是
  // 「200 且標題與頻道相符」，而同一份 prompt 又說「標題不符時以 oEmbed 為準」——
  // 兩句話矛盾，結果一支完全合格的影片擋掉整章寫檔。
  const rows = [unitRow("u1", { drills: 1 })];
  rows[0].results[1] = {
    videoId: "u1-d0",
    httpStatus: 200,
    ok: true,
    oembedTitle: "中文標題",
    mismatch: "策展記的是英文標題，oEmbed 回中文",
  };
  const { report, blocking } = run(plan(["u1"]), rows);

  assert.equal(blocking, false, "標題差異不該擋");
  assert.deepEqual(report.dead, []);
  assert.deepEqual(report.wrongVideo, []);
  assert.equal(report.mismatched.length, 1);
  assert.equal(report.verified, 2, "標題不同的影片仍然算驗證通過");
});

/* --- 這三條對應實測撞到的 bug，是防回歸而不是假想 ---------------------- */

test("unitId 不在規劃清單裡就擋（實測全部變成 \"unknown\"）", () => {
  const rows = [unitRow("unknown", { drills: 1 })];
  const { report, blocking } = run(plan(["u1"]), rows, { wantUnits: 1 });

  assert.equal(blocking, true);
  assert.deepEqual(report.unknownUnitIds, ["unknown"]);
});

test("兩個單元拿到同一個 id 就擋", () => {
  const rows = [unitRow("u1", { drills: 1 }), unitRow("u1", { drills: 1, lessonId: "L2" })];
  const { report, blocking } = run(plan(["u1", "u2"]), rows, { wantUnits: 2 });

  assert.equal(blocking, true);
  assert.deepEqual(report.duplicateUnitIds, ["u1"]);
});

test("規劃裡沒有名字的單元就擋（寫出去 name 會是 null）", () => {
  const rows = [unitRow("u1", { drills: 1 })];
  const { report, blocking } = run([{ id: "u1" }], rows);

  assert.equal(blocking, true);
  assert.deepEqual(report.unitsWithoutName, ["u1"]);
});

test("同單元重複要擋，跨單元共用只報——make audit 對這兩者態度相反", () => {
  const within = [unitRow("u1", { drillIds: ["X", "X"] })];
  const a = run(plan(["u1"]), within);
  assert.equal(a.blocking, true, "同單元重複必須擋");
  assert.equal(a.report.duplicatesWithinUnit.length, 1);
  assert.match(a.report.duplicatesWithinUnit[0], /X 在 u1/);
  assert.deepEqual(a.report.duplicatesAcrossUnits, [], "同單元重複不該混進跨單元");

  const across = [unitRow("u1", { drillIds: ["S"] }), unitRow("u2", { drillIds: ["S"] })];
  const b = run(plan(["u1", "u2"]), across);
  assert.equal(b.blocking, false, "跨單元共用是規格允許的重疊，不該擋");
  assert.equal(b.report.duplicatesAcrossUnits.length, 1);
  assert.deepEqual(b.report.duplicatesWithinUnit, []);
});

/* --- 留空的規矩：留空可以，留空不說明不行 ------------------------------ */

test("留空但寫了 note 不擋；沒寫 note 就擋", () => {
  const withNote = [unitRow("u1", { drills: 0 })];
  withNote[0]._search.drills = [{ name: "找不到", videoId: null, note: "查過 A、B，都低於門檻" }];
  const a = run(plan(["u1"]), withNote, { wantDrills: 1 });
  assert.equal(a.blocking, false);
  assert.equal(a.report.blanks.length, 1);
  assert.deepEqual(a.report.blanksWithoutNote, []);

  const noNote = [unitRow("u1", { drills: 0 })];
  noNote[0]._search.drills = [{ name: "找不到", videoId: null }];
  const b = run(plan(["u1"]), noNote, { wantDrills: 1 });
  assert.equal(b.blocking, true);
  assert.equal(b.report.blanksWithoutNote.length, 1);
});

/* --- 只提醒、不擋的那幾類：別讓十幾分鐘的策展整批作廢 ------------------ */

test("觀看數偏低只報不擋", () => {
  const rows = [unitRow("u1", { drills: 1 })];
  rows[0]._search.drills[0].views = 12;
  const { report, blocking } = run(plan(["u1"]), rows);

  assert.equal(blocking, false);
  assert.equal(report.belowMinViews.length, 1);
  assert.match(report.belowMinViews[0], /12 次觀看/);
});

test("標題與 oEmbed 不符只報不擋（YouTube 會做標題 A/B 測試）", () => {
  const rows = [unitRow("u1", { drills: 1 })];
  rows[0].results[0].mismatch = "標題不同";
  const { report, blocking } = run(plan(["u1"]), rows);

  assert.equal(blocking, false);
  assert.equal(report.mismatched.length, 1);
});

test("searchLog 逐條帶上 unitId，是可稽核的軌跡", () => {
  const rows = [unitRow("u1", { drills: 1 }), unitRow("u2", { drills: 1 })];
  const { report } = run(plan(["u1", "u2"]), rows);

  assert.equal(report.searchLog.length, 2);
  assert.match(report.searchLog[0], /^u1 · /);
});

test("summary 是一行摘要，數字對得上 report", () => {
  const rows = [unitRow("u1", { drills: 3 })];
  const { report, summary } = run(plan(["u1"]), rows);

  assert.match(summary, new RegExp(`單元 ${report.units.got}/${report.units.want}`));
  assert.match(summary, new RegExp(`動作 ${report.drills.got}/${report.drills.want}`));
});

test("沒有任何單元回來時擋下，不會寫出一份空章節", () => {
  const { blocking, report } = run(plan(["u1", "u2"]), [], { wantUnits: 2, wantDrills: 4 });

  assert.equal(blocking, true);
  assert.equal(report.units.got, 0);
});
