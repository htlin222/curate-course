// SEO 與社群預覽圖產出物的防回歸測試。零依賴、不需要瀏覽器：node --test tests/
//
// 這裡測的不是「程式碼長怎樣」，而是「build 真的吐出去的數字對不對」——
// JSON-LD 與 og.png 上的數字錯了不會有人抱怨（頁面上完全看不出來），
// 只會一直錯下去，所以要有人在 CI 裡拿 course.json 逐項對帳。
//
// 需要 make build 先跑過（make check 已經把 build 排在 test 前面）。
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { isAbsolute, join } from "node:path";

const dist = (name) => fileURLToPath(new URL(`../dist/${name}`, import.meta.url));
const repo = (name) => fileURLToPath(new URL(`../${name}`, import.meta.url));
const courseDir = process.env.COURSE
  ? isAbsolute(process.env.COURSE)
    ? process.env.COURSE
    : repo(process.env.COURSE)
  : repo("course");

const ready = existsSync(dist("course.json")) && existsSync(dist("index.html"));
const skip = ready ? false : "需要先跑 make build（make check 會自動處理）";

const course = ready ? JSON.parse(readFileSync(dist("course.json"), "utf8")) : null;
const meta = course?.meta ?? {};
const index = ready ? readFileSync(dist("index.html"), "utf8") : "";
// build.py 只把一部分區塊複製進 course.json.config，og 不在其中，所以直接讀設定檔
const config = ready
  ? JSON.parse(readFileSync(join(courseDir, "course.config.json"), "utf8"))
  : {};

/** 從 index.html 抓出注入好的 Course JSON-LD */
function schemaGraph() {
  const m = index.match(
    /<script type="application\/ld\+json" id="schema">(.*?)<\/script>/s,
  );
  assert.ok(m, "index.html 裡找不到注入好的 JSON-LD");
  return JSON.parse(m[1].replaceAll("<\\/", "</"))["@graph"];
}

const node = (type) => schemaGraph().find((n) => n["@type"] === type);

/* --- #37 JSON-LD：numberOfLessons 是「幾堂課」，不是「幾個影片欄位」 --------- */

describe("JSON-LD", { skip }, () => {
  test("numberOfLessons 等於章節單元數，而不是影片欄位總數", () => {
    assert.equal(node("Course").numberOfLessons, meta.lesson_units);
  });

  test("有跟練影片的課，numberOfLessons 絕不能是 meta.units", () => {
    // units = lesson_units + drill_units。餵 units 會讓一門 37 堂的課
    // 對搜尋引擎宣稱有 371 堂——這正是原本的 bug。
    if (!meta.drill_units) return; // 沒有 drills 時兩者本來就相等，不成立
    assert.notEqual(node("Course").numberOfLessons, meta.units);
    assert.ok(
      node("Course").numberOfLessons < meta.units,
      "課數不可能多過影片欄位數",
    );
  });

  test("syllabusSections 的數量等於章節數", () => {
    assert.equal(node("Course").syllabusSections.length, course.chapters.length);
  });

  test("teaches 用的是設定檔的 ui.problemType，不是寫死的型別", () => {
    const type = course.config.ui?.problemType;
    if (!type) {
      assert.ok(
        !("teaches" in node("Course")),
        "沒設定 ui.problemType 就不該宣告 teaches——寧可不宣告，也不要宣告錯的",
      );
      return;
    }
    const expected = course.chapters.flatMap((ch) =>
      ch.units.filter((u) => u.type === type).map((u) => u.name),
    );
    assert.deepEqual(node("Course").teaches, expected);
    assert.equal(expected.length, meta.problem_units);
  });

  test("語言與難度只在設定檔有寫時才宣告", () => {
    const site = course.config.site;
    for (const n of [node("Course"), node("WebSite")]) {
      assert.equal(n.inLanguage, site.locale, "inLanguage 必須等於 site.locale（沒設就不能有）");
    }
    assert.equal(node("Course").hasCourseInstance.inLanguage, site.locale);
    assert.equal(node("Course").educationalLevel, site.educationalLevel);
    // 沒設 ogLocale 就不該有這個標籤，而不是塞一個猜的
    assert.equal(/property="og:locale"/.test(index), Boolean(site.ogLocale));
  });

  test("timeRequired 是 ISO 8601 duration，且對得上課程總長", () => {
    const m = node("Course").timeRequired.match(/^PT(\d+)H(\d+)M$/);
    assert.ok(m, "timeRequired 必須是 PT<h>H<m>M");
    const seconds = Number(m[1]) * 3600 + Number(m[2]) * 60;
    assert.ok(Math.abs(seconds - meta.duration_seconds) < 60);
  });

  test("og:image 與 JSON-LD 的 image 都指到 /og.png", () => {
    assert.match(index, /<meta property="og:image" content="[^"]+\/og\.png" \/>/);
    assert.match(node("Course").image, /\/og\.png$/);
  });
});

/* --- 主題耦合：框架不准知道這門課叫什麼 ------------------------------------ */

describe("seo.py 沒有寫死這門課的主題", { skip }, () => {
  // seo.py 曾經寫著 .get("problemType", "posture")——正上方的註解甚至已經寫明
  // 「寫死換主題會產出空的 teaches……這種沉默的失敗最難發現」，程式卻沒照做。
  // 這是啟發式檢查：只掃設定檔裡「屬於這門課」的識別字有沒有變成 seo.py 的字串字面值。
  const generic = new Set([
    "name", "title", "url", "type", "units", "label", "description",
    "icon", "image", "summary", "stats", "grades", "kinds", "site", "duration",
  ]);

  /** 去掉註解——那裡面本來就會引用舊值來說明當初錯在哪，不算寫死 */
  function stripComments(src) {
    return src
      .split("\n")
      .map((line) => {
        let quote = null;
        for (let i = 0; i < line.length; i++) {
          const c = line[i];
          if (quote) {
            if (c === "\\") i++;
            else if (c === quote) quote = null;
          } else if (c === '"' || c === "'") quote = c;
          else if (c === "#") return line.slice(0, i);
        }
        return line;
      })
      .join("\n");
  }

  test("設定檔裡的主題識別字不該出現在框架程式碼裡", () => {
    const src = stripComments(readFileSync(repo("src/build/seo.py"), "utf8"));
    const candidates = [
      ...new Set([
        ...Object.keys(config.ui?.unitTypes || {}),
        config.ui?.problemType,
        config.site?.locale,
        config.site?.ogLocale,
        config.site?.educationalLevel,
      ]),
    ].filter((v) => v && v.length >= 4 && !generic.has(v));

    const leaked = candidates.filter((v) =>
      new RegExp(`["']${v.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["']`).test(src),
    );
    assert.deepEqual(
      leaked,
      [],
      `這些值屬於 course/，不該寫進 src/build/seo.py：${leaked.join("、")}`,
    );
  });
});

/* --- #14 llms.txt：框架不准替課程講任何一句話 ------------------------------ */

describe("llms.txt 的每一個字都來自課程", { skip }, () => {
  // llms.txt 以前有一整批寫死的中文句型（「共 X 個單元（X 個影片欄位…）」、
  // 「## 章節」、「## 免責」、條列的「（分級）：摘要…」）。那比 fallback 更糟：
  // fallback 至少還能覆寫，寫死的句型連接縫都沒有，一門英文課的 llms.txt 就會
  // 冒出中文——而且沒有任何檢查會發現，因為檔案本身完全合法。
  //
  // 做法：把「設定檔提供的文案」與「course.json 的資料」逐段從產出物裡刪掉，
  // 剩下的必須只有 ASCII 結構（# > - ** 空行 數字 網址）。
  // 還留著非 ASCII 字元，就代表那個字是框架自己寫的。
  const llms = () => readFileSync(dist("llms.txt"), "utf8");

  /** 模板裡的坑：`[[值]]`（build 算出來的）與 `{數字}`（七個文案佔位符） */
  const PLACEHOLDER = /\[\[\w+\]\]|\{\w+\}/g;

  /** 設定檔的文案：去掉坑之後剩下的字面片段 */
  function copyFragments() {
    const out = [];
    for (const value of Object.values(config.llms || {})) {
      if (typeof value === "string") out.push(...value.split(PLACEHOLDER));
    }
    const site = config.site || {};
    out.push(site.name, site.description, site.url, config.stance?.title);
    return out;
  }

  /** course.json 的資料：章節、單元名、立場條目 */
  function dataFragments() {
    const out = [];
    for (const ch of course.chapters) {
      out.push(ch.code, ch.title, ...ch.units.map((u) => u.name));
    }
    for (const s of course.stance || []) out.push(s.name, s.evidence_grade, s.summary);
    return out;
  }

  /** 把每個片段從文字裡刪光。找不到完整片段時退而求其次刪最長的前綴——
   *  立場摘要在 llms.txt 裡是截短的，那一段仍然是課程自己的字。 */
  function strip(text, fragments) {
    for (const f of [...new Set(fragments)].filter(Boolean).sort((a, b) => b.length - a.length)) {
      if (text.includes(f)) {
        text = text.split(f).join("");
        continue;
      }
      let piece = f;
      while (piece.length > 4 && !text.includes(piece)) piece = piece.slice(0, -1);
      if (piece.length > 4) text = text.split(piece).join("");
    }
    return text;
  }

  test("產出物裡沒有任何設定檔以外的固定句型", () => {
    const rest = strip(llms(), [...copyFragments(), ...dataFragments()]);
    const leaked = [...new Set(rest.match(/[^\x00-\x7F]/g) || [])];
    assert.deepEqual(
      leaked,
      [],
      `這些字元不是來自 course.config.json 也不是來自 course.json，` +
        `就是 seo.py 自己寫的：${leaked.join("")}\n剩下的內容：\n${rest.trim()}`,
    );
  });

  test("設定檔宣告的每個文案欄位都真的出現在產出物裡", () => {
    // 反向檢查：只掃「沒有多餘的字」會漏掉「少了整段」——
    // 把某個欄位讀丟了，llms.txt 只是安靜地短一截。
    const text = llms();
    const missing = Object.entries(config.llms || {})
      .filter(([, v]) => typeof v === "string")
      .map(([k, v]) => [k, v.split(PLACEHOLDER).sort((a, b) => b.length - a.length)[0] || ""])
      .filter(([, frag]) => frag.length > 2 && !text.includes(frag))
      .map(([k]) => k);
    assert.deepEqual(missing, [], "這些 llms.* 欄位設定了卻沒有出現在 llms.txt 裡");
  });

  test("沒有殘留未填的佔位符", () => {
    assert.equal(llms().match(PLACEHOLDER), null);
  });
});

/* --- #31 og.html：圖上每一個數字都要跟 course.json 對得起來 ----------------- */

describe("og.html", { skip: skip || (existsSync(dist("og.html")) ? false : "沒有 dist/og.html") }, () => {
  const og = () => readFileSync(dist("og.html"), "utf8");

  /** 由 course.json 重算各證據分級的單元數——og 圖上的 chip 數字唯一的真相 */
  function gradeCounts() {
    const counts = {};
    for (const ch of course.chapters) {
      for (const u of ch.units) {
        const g = u.evidence?.evidence_grade;
        if (g) counts[g] = (counts[g] || 0) + 1;
      }
    }
    return counts;
  }

  /** 抓出 <span class="chip …">標籤 <i>數字</i></span> */
  function chips() {
    return [...og().matchAll(/<span class="chip [^"]*">(.*?)\s*<i>(\d+)<\/i><\/span>/g)].map(
      (m) => ({ label: m[1], count: Number(m[2]) }),
    );
  }

  test("模板沒有殘留未填的佔位符", () => {
    assert.equal(og().match(/\{\{\w+\}\}/g), null);
  });

  test("每個證據分級的計數都等於重新統計的結果", () => {
    const counts = gradeCounts();
    const grades = course.config.grades || [];
    assert.equal(chips().length, grades.length, "chip 數量要等於設定檔的分級數");
    for (const [i, g] of grades.entries()) {
      assert.equal(chips()[i].label, g.label, `第 ${i + 1} 個 chip 的標籤`);
      assert.equal(chips()[i].count, counts[g.id] || 0, `「${g.label}」的計數`);
    }
  });

  test("分級計數合計等於實證查核題數（改了標籤忘了改數字會在這裡爆）", () => {
    const total = chips().reduce((sum, c) => sum + c.count, 0);
    assert.equal(total, meta.evidence_checked);
  });

  test("統計數字全部取自 meta，沒有人工寫死", () => {
    const stats = [...og().matchAll(/<div class="stat"><b>(.*?)<\/b><span>(.*?)<\/span>/g)];
    assert.ok(stats.length > 0, "og.html 應該要有統計數字");
    const configured = config.og?.stats || config.ui?.stats?.slice(0, 4) || [];
    assert.equal(stats.length, configured.length);
    for (const [i, s] of configured.entries()) {
      const expected =
        s.field === "duration_hours"
          ? `${Math.round(meta.duration_seconds / 3600)} 小時`
          : String(meta[s.field]);
      assert.equal(stats[i][2], s.label, `第 ${i + 1} 個統計的標籤`);
      assert.equal(stats[i][1], expected, `第 ${i + 1} 個統計（${s.field}）的數字`);
    }
  });

  test("品牌名與頁尾網域來自設定檔", () => {
    const site = course.config.site;
    assert.match(og(), new RegExp(`</svg>${site.name}</div>`));
    assert.ok(
      og().includes(site.url.replace(/^https?:\/\//, "").replace(/\/$/, "")),
      "頁尾應該印出 site.url 的網域",
    );
  });

  test("品牌圖示是從 sprite 取的，不是內嵌寫死的 path", () => {
    const icon = course.config.site?.brandIcon;
    if (!icon) return;
    const sprite = readFileSync(repo("src/web/js/icons.js"), "utf8");
    const m = sprite.match(new RegExp(`<symbol id=\\\\"i-${icon}\\\\"[^>]*>(.*?)</symbol>`, "s"));
    assert.ok(m, `icons.js 裡沒有 i-${icon}，make icons 沒跑過`);
    // sprite 是 JSON 字串，路徑裡的 " 被跳脫過，還原後才能比對
    assert.ok(og().includes(m[1].replaceAll('\\"', '"')), "og.html 的品牌圖示要跟 sprite 一致");
  });
});

/* --- #11 og.png：只能經由進版控的 course/assets/ 進 dist ------------------- */

describe("og.png 的位置", { skip }, () => {
  test("dist/og.png 存在就代表 course/assets/og.png 也要在（否則重新 clone 就 404）", () => {
    if (!existsSync(dist("og.png"))) return; // 還沒跑過 make og
    const tracked = join(courseDir, "assets", "og.png");
    assert.ok(
      existsSync(tracked),
      "dist/ 有 og.png 但 course/assets/ 沒有：這張圖不會進版控，重新 clone 後 /og.png 是 404",
    );
    assert.deepEqual(
      readFileSync(dist("og.png")),
      readFileSync(tracked),
      "dist/og.png 與版控中的那一份內容不同，代表有人繞過 make og 直接寫進 dist",
    );
  });
});
