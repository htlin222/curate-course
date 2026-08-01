// 前端與主題脫鉤的防回歸測試。零依賴、不需要瀏覽器：node --test tests/
//
// 這裡測的都是「不會報錯、只會默默講上一個主題的話」那一類問題：
// 換主題時沒人會發現，但每一個看原始碼的人都會被誤導。
// 修好一次不夠，要讓它不能再壞回去，所以這些規則寫成測試而不是註解。
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { THEME_KEY, STATE_KEYS, prefixOf, keysFor, migrateLegacy } from "../src/web/js/store.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const WEB = path.join(ROOT, "src", "web");

const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

/** src/web 底下所有人寫的原始碼。icons.js 是產生出來的，不算。 */
function webSources() {
  const files = [path.join(WEB, "index.html")];
  for (const dir of ["js", "css"]) {
    for (const name of fs.readdirSync(path.join(WEB, dir))) {
      if (name === "icons.js") continue;
      files.push(path.join(WEB, dir, name));
    }
  }
  return files.map((f) => [path.relative(ROOT, f), fs.readFileSync(f, "utf8")]);
}

/* --- #34 / #14：主題詞彙不得出現在框架程式裡 ------------------------------ */

// 這門課碰巧是體態課，所以拿它自己的詞彙當試紙：框架的任何一個檔案裡
// 出現這些字，就代表某個泛用功能又被用主題的名字命名了。
// 換主題的人照 quality.md 去 grep 舊主題字樣時，這裡命中就是假警報的來源。
const TOPIC_WORDS = [
  "muscle",
  "Muscle",
  "肌群",
  "肌肉",
  "體態",
  "姿勢",
  "駝背",
  "圓肩",
  "骨盆",
  "頸椎",
  "posture",
];

test("#34 框架的前端原始碼裡沒有任何主題名詞", () => {
  const hits = [];
  for (const [rel, text] of webSources()) {
    text.split("\n").forEach((line, i) => {
      for (const word of TOPIC_WORDS) {
        if (line.includes(word)) hits.push(`${rel}:${i + 1} 出現「${word}」`);
      }
    });
  }
  assert.deepEqual(
    hits,
    [],
    `泛用功能不該用主題的名字命名（分面就叫 facet）：\n${hits.join("\n")}`,
  );
});

test("#34 分面篩選的 DOM 契約用 facet，不用任何主題名詞", () => {
  const html = read("src/web/index.html");
  for (const id of ["facetPanel", "facetToggle", "facetCount", "facetBody"]) {
    assert.match(html, new RegExp(`id="${id}"`), `index.html 少了 #${id}`);
  }
  // 側欄 chip 與項目內的標籤共用同一組屬性，改名時很容易只改一邊
  const filters = read("src/web/js/filters.js");
  const render = read("src/web/js/render.js");
  const app = read("src/web/js/app.js");
  assert.match(filters, /data-facet=/);
  assert.match(render, /data-facet=/);
  assert.match(app, /\[data-facet\]/);
});

/* --- #14：localStorage 前綴要跟著 site.project ---------------------------- */

const cfg = (project, extra = {}) => ({ site: { project, ...extra } });

test("#14 前端原始碼沒有寫死任何 localStorage 前綴", () => {
  const hits = [];
  for (const [rel, text] of webSources()) {
    if (rel.endsWith("store.js")) continue; // 前綴的定義本來就住在這裡
    // "xx:done" 這種字面值就是寫死的前綴；模板字串 `${p}:done` 不會命中
    const m = text.match(/"[a-zA-Z0-9-]+:(done|open|tab|playing|wide|listW|cart|order)"/g);
    if (m) hits.push(`${rel}: ${m.join("、")}`);
  }
  assert.deepEqual(hits, [], `課程狀態的鍵名必須由 store.js 依 site.project 產生：\n${hits.join("\n")}`);
});

test("#14 兩門課的鍵名不會互相覆蓋", () => {
  const a = keysFor(cfg("gym-course"));
  const b = keysFor(cfg("photography-course"));
  assert.equal(a.done, "gym-course:done");
  assert.equal(b.done, "photography-course:done");
  for (const k of STATE_KEYS) assert.notEqual(a[k], b[k]);
});

test("#14 project 壞掉或沒有時退回一個中性前綴，不要炸掉", () => {
  assert.equal(prefixOf(undefined), "course:");
  assert.equal(prefixOf({ site: {} }), "course:");
  assert.equal(prefixOf({ site: { project: "有中文的名字" } }), "course:");
});

/** node 沒有 localStorage，用最小可用的替身。 */
function fakeStorage(seed = {}) {
  const map = new Map(Object.entries(seed));
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    get size() {
      return map.size;
    },
    dump: () => Object.fromEntries(map),
  };
}

test("#14 有宣告 legacyStorePrefix 時，舊資料會被搬過來（進度不會無聲消失）", () => {
  const store = fakeStorage({ "bc:done": '["u1","u2"]', "bc:tab": '"course"', "bc:theme": '"dark"' });
  const moved = migrateLegacy(cfg("body-course", { legacyStorePrefix: "bc:" }), store);

  assert.equal(store.getItem("body-course:done"), '["u1","u2"]');
  assert.equal(store.getItem("body-course:tab"), '"course"');
  assert.equal(store.getItem(THEME_KEY), '"dark"');
  assert.ok(moved.includes("body-course:done"));
  // 舊鍵刻意保留：退回舊版本時資料還在
  assert.equal(store.getItem("bc:done"), '["u1","u2"]');
});

test("#14 搬遷不會蓋掉新資料，重跑也安全", () => {
  const conf = cfg("body-course", { legacyStorePrefix: "bc:" });
  const store = fakeStorage({ "bc:done": '["old"]', "body-course:done": '["new"]' });
  migrateLegacy(conf, store);
  assert.equal(store.getItem("body-course:done"), '["new"]');
  migrateLegacy(conf, store);
  assert.equal(store.getItem("body-course:done"), '["new"]');
});

test("#14 沒宣告 legacyStorePrefix 的課程不會撿到別門課的資料", () => {
  const store = fakeStorage({ "bc:done": '["u1"]' });
  assert.deepEqual(migrateLegacy(cfg("photography-course"), store), []);
  assert.equal(store.getItem("photography-course:done"), null);
});

test("#14 主題鍵跨課程共用，且 index.html 的首屏腳本讀得到它", () => {
  // 主題是裝置偏好而不是課程狀態，而且 inline script 跑在 course.json 之前，
  // 那時候還不知道 project 是什麼——所以它刻意不帶課程前綴。
  assert.equal(THEME_KEY, "curate:theme");
  const html = read("src/web/index.html");
  assert.ok(html.includes(`"${THEME_KEY}"`), "index.html 的首屏主題腳本沒有讀共用鍵");
});

/* --- #26：index.html 不得夾帶上一門課的預設值 ----------------------------- */

test("#26 index.html 內嵌的 JSON-LD 是空殼", () => {
  const html = read("src/web/index.html");
  const m = html.match(/<script type="application\/ld\+json" id="schema">(.*?)<\/script>/s);
  assert.ok(m, "找不到 seo.py 要注入的 <script id=\"schema\"> 節點");
  assert.deepEqual(
    JSON.parse(m[1]),
    {},
    "預設值一定會被 seo.py 覆寫；留一份舊課程的 schema 只會在注入失敗時上線一份合法但完全錯誤的結構化資料",
  );
});

test("#26 index.html 沒有寫死任何課程規模的數字", () => {
  const html = read("src/web/index.html");
  const counters = [...html.matchAll(/<span class="Counter"[^>]*>([^<]*)<\/span>/g)].map(
    (m) => m[1],
  );
  assert.ok(counters.length > 0);
  for (const c of counters) {
    assert.equal(c.trim(), "0", `Counter 預設值「${c}」是上一門課的數字，應該是 0`);
  }
});

test("#26 首屏寫死的預設值都有對應的設定檔覆寫路徑", () => {
  const app = read("src/web/js/app.js");
  // brandIcon / favicon / 分面圖示：三個都必須在 applyChrome() 裡從設定檔重畫，
  // 否則換主題後它們會活下來，而且不會有任何錯誤訊息
  assert.match(app, /site\.brandIcon/);
  assert.match(app, /applyFavicon\(/);
  assert.match(app, /ui\?\.facetIcon/);
});

/* --- #38：新增章節圖示不必改框架檔案 -------------------------------------- */

/** build_icons.py 模組層級的 FRAMEWORK_ICONS。 */
function frameworkIcons() {
  const py = read("src/build/build_icons.py");
  const block = py.match(/FRAMEWORK_ICONS = \[(.*?)\n\]/s);
  assert.ok(block, "build_icons.py 找不到 FRAMEWORK_ICONS");
  return [...block[1].matchAll(/"([a-z0-9-]+)"/g)].map((m) => m[1]);
}

/** src/web 裡寫死的圖示名：icon("x", …) 與 <use href="#i-x">。 */
function iconsUsedInCode() {
  const used = new Set();
  for (const [rel, text] of webSources()) {
    if (rel.endsWith(".css")) continue;
    // icon("play", 16) 與 icon(ch.icon || "circle-dot", 16) 都要算
    for (const call of text.matchAll(/icon\(([^)]*)\)/g)) {
      for (const m of call[1].matchAll(/"([a-z0-9-]+)"/g)) used.add(m[1]);
    }
    for (const m of text.matchAll(/#i-([a-z0-9-]+)/g)) used.add(m[1]);
    // block("tight", "flame", …) 這種把名字當一般參數傳的寫法
    for (const m of text.matchAll(/block\("[a-z-]+", "([a-z0-9-]+)"/g)) used.add(m[1]);
  }
  return used;
}

test("#38 框架用到的圖示都在 FRAMEWORK_ICONS 裡（漏了線上會是空白方塊）", () => {
  const packaged = new Set(frameworkIcons());
  const missing = [...iconsUsedInCode()].filter((n) => !packaged.has(n)).sort();
  assert.deepEqual(missing, []);
});

test("#38 FRAMEWORK_ICONS 裡沒有課程專屬的圖示", () => {
  // 反向檢查：清單裡每個名字都要真的被框架的程式用到。
  // 否則就是又有人為了某一門課的章節，把圖示加進了框架檔案——
  // 那正是 #38 說的「稽核逼你違反只改 course/ 的承諾」。
  const used = iconsUsedInCode();
  const orphan = frameworkIcons().filter((n) => !used.has(n));
  assert.deepEqual(
    orphan,
    [],
    "章節圖示請寫在 course/course.config.json，build_icons.py 會自動掃出來",
  );
});

test("#38 課程設定檔裡的圖示不必列進框架清單就會被打包", () => {
  const config = JSON.parse(read("course/course.config.json"));
  const framework = new Set(frameworkIcons());
  const sprite = new Set(
    JSON.parse(read("src/web/js/icons.js").match(/ICON_NAMES = (\[.*?\]);/s)[1]),
  );

  const fromConfig = new Set();
  const walk = (node) => {
    if (Array.isArray(node)) return node.forEach(walk);
    if (node && typeof node === "object") {
      for (const [k, v] of Object.entries(node)) {
        if (typeof v === "string" && (k === "icon" || k.endsWith("Icon"))) fromConfig.add(v);
        else walk(v);
      }
    }
  };
  walk(config);

  const courseOnly = [...fromConfig].filter((n) => !framework.has(n));
  assert.ok(courseOnly.length > 0, "這門課應該有自己的章節圖示，測試才有意義");
  for (const name of courseOnly) {
    assert.ok(sprite.has(name), `${name} 只寫在 course.config.json 裡，卻沒有被打包進 sprite`);
  }
});
