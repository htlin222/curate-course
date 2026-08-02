// 前端不得寫死使用者看得到的文字。零依賴：node --test tests/
//
// 這個框架宣稱主題無關，`site.locale` 也是設定檔欄位——但實測前端有四十幾個
// 寫死的中文字串完全沒有設定檔路徑：鍵盤快捷鍵整張表、paywall 的「稱呼」
// 「付款方式」「信用卡」、「顯示清單」、「億次／萬次」、「課程資料載入失敗」。
// 換句話說，這個框架做不了非中文的課，而且不會有任何錯誤訊息——網站會正常
// 建置、正常上線，然後對著英文讀者說中文。
//
// 契約：使用者看得到的字，一律要有設定檔路徑。寫成 `UI.x || "中文"` 的形式——
// 中文留著當預設值（不填也能跑），但填了就要生效。
//
// 這條規則抓的是「沒有 || 退路的字面中文」，不是「有中文預設值」。
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { ROOT } from "./_paths.js";

const WEB = path.join(ROOT, "src", "web");
const CJK = /[\u4e00-\u9fff]/;

/** 這些檔案不是使用者介面，或裡面的中文是給開發者看的。 */
const SKIP_FILES = new Set(["icons.js", "copy.js", "paywall-core.js"]);

/** 有設定檔路徑的呼叫形式。命中其中一種就算「可覆寫」。 */
const HAS_CONFIG_PATH = [
  /\b(?:UI|CFG|PW)\b\s*[.?]/, // UI.unitNoun || "個單元"
  /\b(?:cfg|config|c)\s*\??\.\s*(?:ui|site|footer|hero|landing|stance|paywall|languages)\b/,
  /\bT\s*\(/, // paywall 的 T("gateTitle", "…")
  /\bpwT\s*\(/, // render.js 的 pwT("lockedLabel", "…")
  /\bt\(/, // t("listShow", "顯示清單")。\b 讓 parseInt( / format( 不會誤判
];

/** 把註解換成等長的空白——整檔處理，因為區塊註解與模板字串都會跨行。
    逐行處理會把跨行的東西切斷，然後把註解裡的字當成介面文字報上來。
    （第一版就是這樣，67 筆裡有一堆是註解與被切一半的 HTML。） */
function stripComments(src) {
  let out = "";
  let i = 0;
  const keep = (s) => (out += s.replace(/[^\n]/g, " "));
  while (i < src.length) {
    const two = src.slice(i, i + 2);
    if (two === "//") {
      const end = src.indexOf("\n", i);
      keep(src.slice(i, end === -1 ? src.length : end));
      i = end === -1 ? src.length : end;
    } else if (two === "/*") {
      const end = src.indexOf("*/", i + 2);
      keep(src.slice(i, end === -1 ? src.length : end + 2));
      i = end === -1 ? src.length : end + 2;
    } else if (two === "*/") {
      keep(two);
      i += 2;
    } else {
      out += src[i];
      i += 1;
    }
  }
  return out;
}

/** 整檔掃出字面文字，回傳 [{line, text, context}]。context 是該字面所在的整段
    運算式（往前後各抓幾行），用來判斷有沒有設定檔路徑——因為模板字串常常跨行，
    `UI.x || "預設"` 的 UI.x 可能在三行之前。 */
function literalsOf(src) {
  const clean = stripComments(src);
  const lineOf = (idx) => clean.slice(0, idx).split("\n").length;
  const lines = clean.split("\n");
  const hits = [];
  const push = (idx, text) => {
    if (!CJK.test(text)) return;
    const n = lineOf(idx);
    hits.push({
      line: n,
      text,
      // 前後三行當上下文：跨行的模板字串與 || 退路都在這個範圍內
      context: lines.slice(Math.max(0, n - 4), n + 3).join("\n"),
    });
  };
  for (const m of clean.matchAll(/"([^"\\\n]*(?:\\.[^"\\\n]*)*)"|'([^'\\\n]*(?:\\.[^'\\\n]*)*)'/g)) {
    push(m.index, m[1] ?? m[2]);
  }
  for (const m of clean.matchAll(/`([^`\\]*(?:\\.[^`\\]*)*)`/g)) {
    // 模板字串：只看字面片段，${…} 裡是程式碼
    for (const part of m[1].split(/\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/)) {
      push(m.index, part);
    }
  }
  return hits;
}

function offenders() {
  const found = [];
  for (const name of fs.readdirSync(path.join(WEB, "js")).sort()) {
    if (!name.endsWith(".js") || SKIP_FILES.has(name)) continue;
    const src = fs.readFileSync(path.join(WEB, "js", name), "utf8");
    for (const h of literalsOf(src)) {
      if (HAS_CONFIG_PATH.some((re) => re.test(h.context))) continue;
      found.push(`${name}:${h.line}  「${h.text.trim().slice(0, 28)}」`);
    }
  }
  return [...new Set(found)];
}

test("前端沒有寫死、無法從設定檔覆寫的中文字串", () => {
  const bad = offenders();
  assert.deepEqual(
    bad,
    [],
    `這些字使用者看得到，但換一個語言的課程沒辦法改：\n  ${bad.join("\n  ")}\n\n` +
      `改法：加一個 ui.* 欄位（記得同步 course.schema.json），寫成 UI.欄位 || "原本的中文"。`,
  );
});

// index.html 還有 17 處寫死的中文（aria-label、blankslate、按鈕 title）。
//
// 刻意留在下一輪，因為它需要的是**另一套機制**而不是同一招：首屏是建置期由
// seo.py 注入 `{{a.b}}` 的，而 audit 會擋「index.html 用到但設定檔沒有的欄位」
// ——直接加 17 個 {{ui.text.*}} 佔位符，等於逼每一門課都必須填滿那 17 格，
// 否則 build 就紅。正確做法是讓 seo.py 也帶一份預設值表（跟 JS 的 fallback
// 對齊，再用測試釘住兩者一致，就像 copy.js ↔ seo.py 那組）。
//
// 標成 skip 而不是刪掉：讓它留在測試輸出裡，不要變成沒有人記得的 TODO。
test("index.html 沒有寫死的中文（首屏走 {{a.b}} 注入）", { skip: "待做：seo.py 需要一份與 JS fallback 對齊的預設值表" }, () => {
  let html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
  // HTML 註解會跨行，整檔換成等長空白才不會把註解裡的說明當成介面文字
  html = html.replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, " "));
  // <script> 裡是 JS，用同一套規則處理它的註解
  html = html.replace(/<script\b[^>]*>([\s\S]*?)<\/script>/g, (m, body) =>
    m.replace(body, stripComments(body)),
  );
  const bad = [];
  html.split("\n").forEach((line, i) => {
    const code = line.replace(/\{\{[\w.]+\}\}/g, "");
    if (CJK.test(code)) bad.push(`index.html:${i + 1}  ${code.trim().slice(0, 60)}`);
  });
  assert.deepEqual(bad, [], `首屏的字要走 {{a.b}} 從設定檔注入：\n  ${bad.join("\n  ")}`);
});
