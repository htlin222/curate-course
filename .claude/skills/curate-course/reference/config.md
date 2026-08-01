# 設定檔

`course/course.config.json` 決定站台的一切。程式裡沒有一個字是寫死的——分頁名稱、篩選標籤、
統計欄位、證據分級的顯示文字，全部從這裡讀。

## 關鍵欄位

| 欄位 | 作用 |
|---|---|
| `site` | 標題、描述、網址、語系、關鍵字 → 直接餵給 SEO 與 JSON-LD |
| `hero` | 首頁大標與說明，可用 `{units}` `{problems}` 佔位 |
| `ui` | **所有介面文案**。分頁名、篩選標籤、統計欄位、實證欄位標題、單元型別，以及**所有主題名詞**（`unitNoun`／`lessonNoun`／`drillNoun`／`evidenceSource` 等，見 `quality.md`）|
| `kinds` | 項目類型與配色（`id` / `label` / `tone`），至少一種 |
| `grades` | 證據分級（沒有實證維度就整組刪掉） |
| `chapters` | 章節碼、標題、Lucide 圖示、資料來源檔、配額 |
| `nav` | 側欄的章節分組。**必須不多不少涵蓋所有章節** |
| `evidenceAlias` | unit id → 實證資料的 key，用在共用同一份查核的單元 |
| `taxonomy` | 選用的詞彙模組（見下） |
| `audit` | **品質門檻** → `make audit` 照這裡檢查（見 `quality.md`） |
| `counter` | 選用：header 的累計瀏覽次數徽章（Pages Function + D1）。整組拿掉就不顯示，也完全不打 API |
| `discussions` | 選用：giscus 設定，每支影片一串 GitHub Discussions。整組拿掉就沒有討論面板。**換主題必換 `repo`/`repoId`/`categoryId`**，否則留言會靜靜掉到上一個主題的 repo |
| `landing` / `stance` / `footer` / `llms` | 首頁、立場頁、頁尾、`llms.txt` 的文案。**哪些欄位吃 HTML 見下一節**——預設全部是純文字 |

## 哪些文案欄位吃 HTML

**預設答案是「不吃」。** 絕大多數文案欄位都會被 `esc()` 逸出，寫 `<strong>` 只會在頁面上
印出字面的 `<strong>`。只有下面這幾個是例外，而且不是每一個都是刻意設計的。

### 可以放心寫 HTML 的（三個，建置期與執行期行為一致）

| 欄位 | 出現在 |
|---|---|
| `hero.lede` | 首頁大標下方的說明段 |
| `footer.disclaimer` | 頁尾那一行免責 |
| `stance.outro` | 立場頁最下面的結語 |

**`stance.intro` 不在這裡。** 同一個 `stance` 物件底下，`intro` 走 `esc()`、`outro` 走 raw
（`src/web/js/render.js` 的 `renderStance`），相鄰兩行的處理方式相反。範例課剛好只在 `outro`
用了 `<strong>`，所以這個不對稱一直沒被撞到——換主題時很自然會假設「立場區塊的長文都吃 HTML」，
然後在 `intro` 看到字面的 `<strong>`。

### 沒有逸出，但**別當成功能用**的

這些欄位在某些呼叫點是 raw，在另一些呼叫點卻是逸出的——是呼叫點漏了 `esc()`，不是設計：

| 欄位 | 不一致在哪 |
|---|---|
| `kinds[].label` | 項目分組標題是 raw；篩選列（`app.js`）與播放清單（`player.js`）是逸出的 |
| `grades[].label` | 所有分級標籤都是 raw |
| `ui.tightLabel` / `ui.weakLabel` | 兩欄對照的小標是 raw |
| `ui.unitNoun` / `lessonNoun` / `drillNoun` / `drillNounShort` | 統計行與章節列是 raw，篩選計數是純文字 |
| `nav[].title` | 側欄分組標題是 raw |

在這些欄位寫 HTML，換一個渲染位置就會露餡。當成純文字用。

### 建置期是 raw，執行期會被改成逸出的（最容易誤判）

`index.html` 裡的 `{{a.b}}` 由 `src/build/seo.py` 的 `render_template()` 直接字串替換，
**完全不逸出**。但 `src/web/js/app.js` 的 `applyChrome()` 在 JS 跑完後又會把其中大部分
重寫一次，這次過 `esc()`：

| 欄位 | 首屏（建置期注入） | JS 跑完之後 |
|---|---|---|
| `site.name`、`hero.eyebrow`、`hero.heading`、`footer.credits`、`ui.progressLabel`、`ui.facetLabel`、`ui.tabs.*` | raw HTML | 逸出成字面文字 |
| `site.title` | raw，進 `<title>` 與 `<meta content="…">` | `document.title` 改成純文字 |
| `ui.searchPlaceholder` | raw，進 `placeholder="…"` | `setAttribute` 改成純文字 |
| `ui.playlistSearch` | raw，進 `placeholder="…"`，**沒有執行期覆寫** | 不變 |

在這些欄位寫 `<strong>`，畫面會先粗體再變回字面文字——看起來像閃爍，很難查。
更實際的風險是**雙引號**：`site.title` 或 `ui.searchPlaceholder` 裡的 `"` 會直接切斷
`<meta content="…">` 與 `placeholder="…"` 的屬性。這幾個欄位連 `"` 都別寫。

### 一句話結論

**除了 `hero.lede`、`footer.disclaimer`、`stance.outro`，所有文案欄位一律當純文字寫。**
需要強調就換句話說，或改用標點；`llms.*` 是純文字檔的內容，本來就不涉及 HTML。

## Schema

欄位結構定義在 `src/build/course.schema.json`。設定檔頂端的 `$schema` 讓編輯器自動完成，
`make audit` 也會拿它擋錯：欄位拼錯（`units` 打成 `unit`）、型別不對、`tone` 用了不存在的值。

```jsonc
{
  "$schema": "../src/build/course.schema.json",
  "site":  { "project": "guitar-course", "name": "…", "url": "https://…" },
  "kinds": [
    { "id": "demo",     "label": "示範",   "tone": "accent"  },
    { "id": "slow",     "label": "慢速",   "tone": "success" },
    { "id": "practice", "label": "練習曲", "tone": "danger"  }
  ],
  "chapters": [
    { "code": "CH1", "title": "…", "icon": "guitar", "source": "ch1",
      "units": 4, "drills": 20 }   // 配額：建置時強制檢查
  ]
}
```

## 圖示

名稱去 <https://lucide.dev/icons/> 查，把用到的加進 `src/build/build_icons.py` 的 `ICONS`
再跑 `make icons`。網站不吃任何外部請求，圖示在建置時就打包成內嵌 sprite——
**沒打包的圖示線上會是空白**，`make audit` 會先抓到。

config 裡會用到圖示的地方：`site.brandIcon`、`chapters[].icon`、`ui.stats[].icon`、
`landing.steps[].icon`。

## tone

`kinds` 與 `grades` 的 `tone` 只是指向設計語彙，跟主題無關。可用值等於 `src/web/css/tokens.css`
裡有 `.Label--<tone>` 定義的那幾個：`accent` / `success` / `attention` / `danger` / `done` /
`neutral`。用了沒定義的值，標籤會變成沒有顏色的灰底，`make audit` 會擋。

## 詞彙模組（選用）

`course/taxonomy/` 放兩個可選模組，在 config 的 `taxonomy` 指定 import 路徑：

- **`facets`**——提供 `extract(*texts) -> [str]`、`GROUPS`、`GROUP_OF`。
  用來做側欄的分面篩選。體態課是肌群；烹飪課可能是食材或技法；程式課可能是語言特性。
  重點是**正規化同義詞**（「背闊肌」與「闊背肌」是同一個）。
- **`categories`**——提供 `classify(item) -> id | None`、`NAMES`、`KINDS`。
  把項目歸類，讓文獻可以掛在類別上（見 `evidence.md`）。

兩個都可以不要，config 拿掉 `taxonomy` 即可，篩選面板會自動消失。
