// 設定檔繼承（course.config.json 的 extends）。零依賴：node --test tests/
//
// 合併規則住在 coursepath.py，這裡刻意用子行程去問真正生效的那一份，而不是
// 在 JS 裡照抄一份規則——兩份實作遲早分岔，而分岔的症狀是「build 過了但
// audit 看到另一份設定」，沒有任何錯誤訊息。
//
// 這裡釘住的是三條契約：
//   1. 物件遞迴合併，陣列整組覆蓋（grades/kinds 是一整組，不是一堆獨立項目）
//   2. 合併結果不含 extends 本身（schema 驗證與產出物看到的是實際生效值）
//   3. 指向不存在的檔案、巢狀繼承，都要明確報錯而不是靜靜當作沒繼承
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { repo, readJSON, loadConfig } from "./_paths.js";

const CONFIG_NAME = "course.config.json";

/** 回傳 stderr；期待 load_config 失敗時用。 */
function loadConfigError(dir) {
  try {
    loadConfig(dir);
    return null;
  } catch (e) {
    return String(e.stderr || e.message);
  }
}

function courseWith(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "curate-extends-"));
  for (const [name, body] of Object.entries(files)) {
    fs.writeFileSync(path.join(dir, name), JSON.stringify(body), "utf8");
  }
  return dir;
}

test("框架附的 defaults.json 是合法 JSON，且不含課程身分欄位", () => {
  const defaults = readJSON(repo("src", "build", "defaults.json"));
  assert.ok(defaults && typeof defaults === "object", "defaults.json 應該是物件");

  // site 是每門課的身分（網址、語系、專案名），繼承它等於讓新課靜靜掛著別人的
  // 身分。locale 尤其危險：英文課忘了覆蓋就會得到 lang="zh-Hant"，而且會誤觸
  // 只對中文有效的 copyStyle 檢查。
  assert.ok(!("site" in defaults), "site 不該進 defaults");
  assert.ok(!("chapters" in defaults), "chapters 不該進 defaults");
  assert.ok(!("frameworkVersion" in defaults), "frameworkVersion 該由課程自己宣告");

  // 證據階梯因領域而異（生醫的「統合分析 > RCT」套到行為科學是錯的），
  // 混進 defaults 會讓兩套階梯合併成一組無意義的層級。
  assert.ok(
    !defaults.evidence || !("designTiers" in defaults.evidence),
    "evidence.designTiers 因領域而異，不該進 defaults",
  );
});

test("沒寫 extends 的課程完全不繼承", () => {
  const dir = courseWith({ [CONFIG_NAME]: { site: { name: "x" } } });
  const cfg = loadConfig(dir);
  assert.deepEqual(cfg, { site: { name: "x" } }, "沒有 extends 就該原樣回傳");
});

test("物件遞迴合併，陣列整組覆蓋", () => {
  const dir = courseWith({
    "base.json": {
      audit: { minViews: 5000, driftSeconds: 30 },
      grades: [{ id: "strong" }, { id: "moderate" }],
    },
    [CONFIG_NAME]: { extends: "base.json", audit: { minViews: 1 }, grades: [{ id: "only" }] },
  });
  const cfg = loadConfig(dir);

  assert.deepEqual(cfg.audit, { minViews: 1, driftSeconds: 30 }, "物件該遞迴合併");
  assert.deepEqual(cfg.grades, [{ id: "only" }], "陣列該整組覆蓋，不留上一組的殘骸");
});

test("合併結果不含 extends 本身", () => {
  const dir = courseWith({
    "base.json": { ui: { unitNoun: "個單元" } },
    [CONFIG_NAME]: { extends: "base.json" },
  });
  assert.ok(!("extends" in loadConfig(dir)), "extends 該在合併後被移除");
});

test("extends 指向不存在的檔案會報錯", () => {
  const dir = courseWith({ [CONFIG_NAME]: { extends: "nope.json" } });
  const err = loadConfigError(dir);
  assert.ok(err, "應該要失敗，而不是靜靜當作沒有繼承");
  assert.match(err, /nope\.json/, "訊息要指出是哪一個路徑找不到");
});

test("巢狀繼承被擋下", () => {
  const dir = courseWith({
    "mid.json": { extends: "base.json" },
    "base.json": { ui: {} },
    [CONFIG_NAME]: { extends: "mid.json" },
  });
  const err = loadConfigError(dir);
  assert.ok(err, "巢狀繼承應該要失敗");
  assert.match(err, /一層/, "訊息要說明只支援一層");
});

test("repo 裡每一份 extends 都指得到檔案", () => {
  const groups = ["courses", "examples"];
  for (const group of groups) {
    const base = repo(group);
    if (!fs.existsSync(base)) continue;
    for (const name of fs.readdirSync(base)) {
      const cfgPath = path.join(base, name, CONFIG_NAME);
      if (!fs.existsSync(cfgPath)) continue;
      const ref = readJSON(cfgPath)?.extends;
      if (!ref) continue;
      const target = path.resolve(path.join(base, name), ref);
      assert.ok(
        fs.existsSync(target),
        `${group}/${name} 的 extends 指向 ${ref}，但那個檔案不存在`,
      );
    }
  }
});
