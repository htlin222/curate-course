// 文案契約的防回歸測試。零依賴、不需要瀏覽器：node --test tests/
//
// 契約只有一句：**設定檔的文案先逸出，然後只認得 `**粗體**`**。
// 這裡守的是三件會靜靜壞掉的事：
//   1. 同一份契約有兩套實作（建置期 seo.py／執行期 copy.js）而且行為不一樣（#18、#20）
//   2. 文案佔位符的定義散在三個檔案，同一個 token 指到不同的數字（#18）
//   3. index.html 需要的設定欄位沒有出現在 schema 裡，只能從 build 的警告反推（#15、#28）
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { esc, plain, rich, text, fillTokens, TOKEN_FIELDS } from "../src/web/js/copy.js";

const repo = (name) => fileURLToPath(new URL(`../${name}`, import.meta.url));
const read = (name) => readFileSync(repo(name), "utf8");

/* --- 逸出與受限標記 -------------------------------------------------------- */

describe("文案契約", () => {
  test("#20 逸出蓋掉全部五個危險字元，屬性不可能被切斷", () => {
    assert.equal(esc(`&<>"'`), "&amp;&lt;&gt;&quot;&#x27;");
    // 這一顆就是「seo.py 完全不逸出」的病徵：一個雙引號切斷 placeholder="…"
    assert.equal(plain('說 "你好"'), "說 &quot;你好&quot;");
    assert.ok(!plain('a" onerror="x').includes('"'));
  });

  test("#20 rich() 只認得 **粗體**，HTML 標籤一律變成字面文字", () => {
    assert.equal(rich("**重點**"), "<strong>重點</strong>");
    assert.equal(rich("<strong>假的</strong>"), "&lt;strong&gt;假的&lt;/strong&gt;");
    // 標記跑在逸出之後，所以標記本身不可能夾帶標籤
    assert.equal(rich("**<img src=x>**"), "<strong>&lt;img src=x&gt;</strong>");
    // 落單的 ** 就是字面的星號，不會吃掉後面整段
    assert.equal(rich("2 ** 3"), "2 ** 3");
  });

  test("#20 屬性與純文字 sink 優雅退化成沒有記號的文字", () => {
    assert.equal(plain("**重點**"), "重點");
    assert.equal(text("**重點**"), "重點");
    // text() 給的是 DOM 的純文字 sink，再逸出一次使用者就會看到 &amp;
    assert.equal(text("A & B"), "A & B");
    assert.equal(plain("A & B"), "A &amp; B");
  });

  test("空值不會變成 undefined／null 印在畫面上", () => {
    for (const fn of [esc, plain, rich, text]) {
      assert.equal(fn(undefined), "");
      assert.equal(fn(null), "");
    }
  });
});

/* --- 佔位符：一份定義，三個檔案必須一致 ------------------------------------ */

/** 從 seo.py / audit.py / copy.js 各自的原始碼取出它們認得的 token。 */
function tokensFrom(file, pattern) {
  const m = read(file).match(pattern);
  assert.ok(m, `${file} 找不到 token 定義，改名了就要順手改這個測試`);
  return m[1];
}

describe("文案佔位符", () => {
  test("#18 seo.py 與 copy.js 的 token → meta 欄位對應逐項相同", () => {
    const body = tokensFrom("src/build/seo.py", /TOKEN_FIELDS = \{([\s\S]*?)\n\}/);
    const py = Object.fromEntries(
      [...body.matchAll(/"(\w+)":\s*"(\w+)"/g)].map((m) => [m[1], m[2]]),
    );
    // 光比對 token 名稱不夠：以前兩邊都認得 {videos}，但一個指向 video_unique、
    // 另一個指向 video_slots，同一份設定檔在首屏與前端得到兩個數字。
    assert.deepEqual(py, TOKEN_FIELDS);
  });

  test("#18 audit.py 擋的 token 清單與實作一致", () => {
    const body = tokensFrom("src/build/audit.py", /COPY_TOKENS = \(([\s\S]*?)\)/);
    const known = [...body.matchAll(/"(\w+)"/g)].map((m) => m[1]);
    assert.deepEqual(known.slice().sort(), Object.keys(TOKEN_FIELDS).sort());
  });

  test("#18 未知的 token 原樣保留，才有東西給 audit 抓", () => {
    const meta = { units: 371, video_unique: 344, video_slots: 406 };
    assert.equal(fillTokens("{units} 個單元", meta), "371 個單元");
    assert.equal(fillTokens("{videos} 支影片", meta), "344 支影片");
    assert.equal(fillTokens("{slots} 個欄位", meta), "406 個欄位");
    assert.equal(fillTokens("{unit} 打錯了", meta), "{unit} 打錯了");
  });

  test("#18 前端不得再有自己那套只認兩個 token 的 replace()", () => {
    // ui.facetFilterHint 的 {name} 由前端填入分面名稱，不是課程規模的數字，不算。
    const src = read("src/web/js/render.js").replaceAll('.replace("{name}", f)', "");
    assert.ok(
      !/\.replace\(\s*"\{\w+\}"/.test(src),
      "render.js 又出現手寫的 {token} replace()，佔位符必須走 copy.js 的 fillTokens()",
    );
  });
});

/* --- schema 必須涵蓋首屏真的會讀的欄位 ------------------------------------- */

describe("設定欄位的宣告", () => {
  const schema = JSON.parse(read("src/build/course.schema.json"));

  /** 依 "a.b.c" 走訪 schema 的 properties */
  function declared(dotted) {
    let node = schema;
    for (const part of dotted.split(".")) {
      const props = node.properties || {};
      if (!props[part]) {
        // tabs 之類的自由鍵用 additionalProperties 描述
        if (typeof node.additionalProperties === "object") {
          node = node.additionalProperties;
          continue;
        }
        return false;
      }
      node = props[part];
    }
    return true;
  }

  test("#15/#28 index.html 的每個 {{a.b}} 都在 schema 裡宣告過", () => {
    const tokens = [...new Set(read("src/web/index.html").match(/\{\{[\w.]+\}\}/g) || [])];
    assert.ok(tokens.length > 0, "index.html 一個文案佔位符都沒有？");
    const missing = tokens.filter((t) => !declared(t.slice(2, -2)));
    assert.deepEqual(
      missing,
      [],
      "這些欄位換主題時只能從 build 的「未解析」警告反推，補進 course.schema.json",
    );
  });

  test("#15 前端讀得到的 ui.* 欄位都在 schema 裡宣告過", () => {
    const ui = schema.properties.ui.properties;
    const used = new Set();
    for (const f of ["app.js", "render.js", "player.js", "filters.js", "discuss.js"]) {
      for (const m of read(`src/web/js/${f}`).matchAll(/\bUI\.([a-zA-Z]\w*)/g)) used.add(m[1]);
      for (const m of read(`src/web/js/${f}`).matchAll(/\bui\?\.([a-zA-Z]\w*)/g)) used.add(m[1]);
    }
    const missing = [...used].filter((k) => !(k in ui)).sort();
    assert.deepEqual(missing, [], "前端會讀但 schema 沒宣告的 ui 欄位");
  });

  test("#15 ui 與 footer 拼錯欄位會被擋（additionalProperties: false）", () => {
    for (const key of ["ui", "footer", "stance", "llms", "landing"]) {
      assert.equal(
        schema.properties[key].additionalProperties,
        false,
        `${key} 沒有關掉額外欄位，拼錯只會靜靜地退回預設值`,
      );
    }
  });
});

/* --- 兩份實作必須給出同一個字串 -------------------------------------------- */

// 這是整組測試裡唯一會開子行程的一顆。找不到 python3 就跳過，不要讓 node --test 掛掉。
const SAMPLES = [
  "純文字",
  "**粗體**",
  "前 **中** 後",
  '雙引號 " 與單引號 \'',
  "<strong>假的</strong> & 符號",
  "2 ** 3 沒有配對",
  "跨行\n第二行",
];

const PY = `
import json, sys
sys.path.insert(0, "src/build")
import seo
cases = json.loads(sys.argv[1])
print(json.dumps({
    "esc": [seo.esc(c) for c in cases],
    "rich": [seo.rich(c) for c in cases],
    "plain": [seo.plain(c) for c in cases],
}, ensure_ascii=False))
`;

const py = existsSync(repo("src/build/seo.py"))
  ? spawnSync("python3", ["-c", PY, JSON.stringify(SAMPLES)], {
      cwd: repo("."),
      encoding: "utf8",
    })
  : { status: 1 };

test("#20 建置期（seo.py）與執行期（copy.js）逐字相同", { skip: py.status === 0 ? false : "沒有可用的 python3" }, () => {
  const got = JSON.parse(py.stdout);
  assert.deepEqual(got.esc, SAMPLES.map(esc));
  assert.deepEqual(got.rich, SAMPLES.map(rich));
  assert.deepEqual(got.plain, SAMPLES.map(plain));
});
