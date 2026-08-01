# 設定檔

`course/course.config.json` 決定站台的一切。程式裡沒有一個字是寫死的——分頁名稱、篩選標籤、
統計欄位、證據分級的顯示文字，全部從這裡讀。

## 關鍵欄位

| 欄位 | 作用 |
|---|---|
| `site` | 標題、描述、網址、語系、關鍵字 → 直接餵給 SEO 與 JSON-LD |
| `hero` | 首頁大標與說明，可用 `{units}` `{problems}` 等佔位符（見下） |
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
| `landing` / `stance` / `footer` / `llms` | 首頁、立場頁、頁尾、`llms.txt` 的文案。寫法見下一節「文案怎麼寫」 |

## 文案怎麼寫

**一句話：所有文案都會先被逸出，然後只認得 `**粗體**`。**

```jsonc
"disclaimer": "**免責聲明。**本課程為衛教與運動指引，**不構成醫療診斷或治療建議**。"
```

這條規則對每一個文案欄位都成立，不分建置期或執行期，也不分渲染在哪裡：

| 你寫的 | 頁面上看到的 |
|---|---|
| `**重點**` | **重點**（`<strong>`） |
| `<strong>重點</strong>` | 字面的 `<strong>重點</strong>`，而且 `make audit` 會直接報錯 |
| `說 "你好"` | `說 "你好"`——引號不會再切斷 `placeholder="…"` 或 `<meta content="…">` |

短標籤與屬性（`site.title`、`ui.searchPlaceholder`、`ui.playlistSearch`、各種 `title=`）
塞不進 `<strong>`，所以那裡的 `**` 記號會被**拿掉只留文字**，不會讓使用者看到字面的星號。

唯一的額外規則在 `og.title` / `og.lede`：真正的換行字元會變成 `<br>`。og 是一張
1200×630 的固定畫布，斷句位置必須由你決定。

### 為什麼值得記這一條

以前沒有契約，只有一堆呼叫點各自的習慣：同一個 `stance` 物件底下 `intro` 逸出、`outro`
是 raw HTML；`{videos}` 在建置期是去重支數、在前端卻是影片欄位數；`site.title` 裡一個雙引號
就會產生壞掉的 `<meta>`，而 build、audit、測試全部照樣通過。現在這三件事分別由
`tests/copy-contract.test.js` 與 `make audit` 的「文案」區段擋住。

實作在 `src/web/js/copy.js`（執行期）與 `src/build/seo.py`（建置期首屏注入），
兩份有測試逐字比對。

### 數字佔位符

文案裡可以放這七個 token，build 時換成真的數字：

| token | 意思 |
|---|---|
| `{units}` | 影片欄位合計（主課 + 項目） |
| `{lessonUnits}` | 章節單元數 |
| `{drillUnits}` | 項目數 |
| `{slots}` | 影片欄位總數（含多語言版本） |
| `{videos}` | 去重後的實際影片支數 |
| `{problems}` | `ui.problemType` 那一類的單元數 |
| `{evidence}` | 單元層級的查核則數 |

七個在建置期與執行期指向同一個 meta 欄位。打錯字（`{unit}`）不會被靜靜吞掉：
原樣保留，然後 `make audit` 報錯。

## Schema

欄位結構定義在 `src/build/course.schema.json`。設定檔頂端的 `$schema` 讓編輯器自動完成，
`make audit` 也會拿它擋錯：欄位拼錯（`units` 打成 `unit`）、型別不對、`tone` 用了不存在的值。

`ui` / `footer` / `stance` / `llms` / `landing` 都是 `additionalProperties: false`：
**沒宣告的欄位一律報錯**。反過來說，schema 裡有的就是前端真的會讀的全部——
不必再從 build 的「未解析 `{{ui.x}}`」警告去反推還有哪些欄位存在。
`index.html` 用到的 `{{a.b}}` 少填一個，`make audit` 就是紅的（以前只會印一行警告，
然後把字面的 `{{ui.progressLabel}}` 送上線）。

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
