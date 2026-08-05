# 設定檔

`$COURSE/course.config.json` 決定站台的一切。程式裡沒有一個字是寫死的——分頁名稱、篩選標籤、
統計欄位、證據分級的顯示文字，全部從這裡讀。

## 關鍵欄位

| 欄位 | 作用 |
|---|---|
| `frameworkVersion` | 這份設定檔寫給哪一版框架（見下一節）。沒填視為 v1，`make audit` 會擋 |
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

## 這份設定檔寫給哪一版框架

課程躺在自己的目錄裡不動，框架靠 `git pull` 前進——兩者是分開演進的，所以設定檔要
自己講清楚它是照哪一版的規則寫的：

```jsonc
"frameworkVersion": "2.0.0",
```

**只有主版號有意義**，次版號與修訂號對不上稽核一個字都不會說。主版號落後就是
`make audit` 的錯誤，訊息會指向 `docs/MIGRATION.md` 裡對應的那一段；`make new-course`
產出的骨架會自動填上當下的版號。

這個欄位存在的理由是**破壞性變更不會是紅色的**。v1 的 `<strong>` 在 v2 變成字面文字，
但設定檔照樣通過 schema、`make build` 照樣成功——沒有版號的話，你只會在上線之後
從頁面上發現。

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

兩個例外，都是因為出口不是 HTML：

- `og.title` / `og.lede`：真正的換行字元會變成 `<br>`。og 是一張 1200×630 的固定畫布，
  斷句位置必須由你決定。
- **`llms` 整個區塊：原樣輸出，不逸出也不展開。** `llms.txt` 是純文字（Markdown 風格），
  沒有任何 HTML sink——逸出只會讓讀者看到字面的 `&amp;`，而 `**粗體**` 在那裡本來就是
  Markdown 自己的粗體語法。這是契約裡唯一一個「不逸出、不展開」的出口，理由是那裡
  根本沒有需要被防的注入面。數字佔位符照樣會填。

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

## `llms.txt`：整份是模板

`llms.txt` 跟 `og.html` 一樣，框架只提供結構（`#` / `##` / `-` / 空行），**一個字都不寫**。
所有句子來自 `llms` 區塊；**沒宣告的欄位就整塊不輸出**（不是輸出空字串留下半截段落）：

| 欄位 | 產出 |
|---|---|
| `summary` | 開頭摘要。課程規模的數字自己寫進來 |
| `stanceTitle` / `stanceIntro` / `stanceItem` / `stanceConclusion` | 立場段。沒有立場資料時整段消失 |
| `chaptersTitle` / `chapterItem` / `unitSeparator` | 章節清單 |
| `disclaimerTitle` / `disclaimer` | 免責段 |
| `footer` | 結尾帶出網址那一行。沒寫就只印裸網址 |

除了上面七個數字 token，這裡另外可以用 `[[值]]`——就是 `og.html` 模板的同一套機制，
只是記號從 `{{…}}` 換成 `[[…]]`：模板住在設定檔裡，而 `make audit` 會把 `{{durationHours}}`
讀成打錯字的數字佔位符 `{durationHours}`。

| 範圍 | 可用的值 |
|---|---|
| 每個欄位 | `[[course]]` `[[url]]` `[[durationHours]]` `[[durationMinutes]]` |
| `stanceItem` | `[[name]]` `[[grade]]` `[[summary]]` `[[summaryShort]]`（前 180 字，刪節號自己加） |
| `chapterItem` | `[[code]]` `[[title]]` `[[units]]` `[[unitCount]]` |

打錯的 `[[值]]` 不會靜靜消失，`make build` 直接掛掉。總長刻意拆成時與分兩個數字，
而不是給一個組好的 `26 小時 3 分`——那個字串裡的「小時」是中文，不該由框架決定。

```jsonc
"llms": {
  "chaptersTitle": "Chapters",
  "chapterItem": "**[[code]] [[title]]**: [[units]]",
  "unitSeparator": ", ",
  "footer": "Full course: [[url]]"
}
```

## 共用設定：`extends`

證據分級、audit 門檻、「個單元」「主課」這類名詞，每門課的值幾乎都一樣。
實測兩門主題完全不同的課，設定檔有 46 個欄位連值都一模一樣。

`extends` 讓課程只寫差異：

```jsonc
{
  "$schema": "../../src/build/course.schema.json",
  "extends": "../../src/build/defaults.json",
  "site": { … },      // 身分一定要自己寫
  "chapters": [ … ]   // 結構一定要自己寫
}
```

路徑相對於課程目錄，`make new-course` 產出的骨架已經填好。**沒寫就完全不繼承**，
既有課程的行為一個字都不會變。

### 合併規則只有兩條

| 型別 | 行為 |
|---|---|
| 物件 | 遞迴合併，課程只覆蓋自己提到的 key |
| 其他（**包含陣列**） | 課程的值整個取代 |

陣列刻意不逐元素合併。`grades` 與 `kinds` 是「一整組」而不是一堆獨立項目：
課程把四級改成三級時，逐元素合併會留下第四級的殘骸，而設定檔上完全看不出來。

繼承只支援一層。巢狀繼承會讓「這個欄位到底從哪來」要翻三個檔案才答得出來，
而設定檔的價值就在於一眼看得出生效值。`extends` 指到不存在的檔案、或基底檔案
自己也有 `extends`，都會直接報錯，不會靜靜當作沒有繼承。

### `defaults.json` 裡有什麼、沒有什麼

有的是**跨主題、跨領域都成立**的：四個證據分級、`audit` 的長度與觀看數門檻、
`ui` 的中性名詞、`llms` 的段落標題。

刻意不放的三類，每一類都是因為「繼承了會靜靜出錯」：

| 沒放 | 理由 |
|---|---|
| `site` | 課程的身分。`locale` 尤其危險：英文課忘了覆蓋就會得到 `lang="zh-Hant"`，而且會誤觸只對中文有效的 `copyStyle` 檢查 |
| `evidence.designTiers` | 證據階梯因領域而異。生醫的「統合分析 > RCT > 佇列」套到行為科學是錯的，兩套混在一起會得到一組無意義的層級 |
| `chapters` / `kinds` / `frameworkVersion` | 本來就是每門課自己的結構與宣告 |

### 載入點只有一個

`coursepath.load_config()`。`build`、`audit`、`seo`、`build_icons`、`setup_counter`
全部走它。以前每支腳本各自 `json.loads(COURSE / "course.config.json")`，
只要合併規則出現在其中一處而不在另一處，就會變成「build 過了但 og 圖少一段」——
那種不一致沒有任何錯誤訊息。`tests/config-extends.test.js` 用子行程去問真正
生效的那一份，而不是在測試裡照抄一份規則。

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

名稱去 <https://lucide.dev/icons/> 查，**直接寫進設定檔就好**，然後跑 `make icons`。
要打包哪些圖示是從設定檔推導出來的（任何叫 `icon` 或 `xxxIcon` 的欄位），
不必去編輯框架的任何檔案。網站不吃任何外部請求，圖示在建置時就打包成內嵌 sprite——
**沒打包的圖示線上會是空白**，`make audit` 會先抓到。

config 裡會用到圖示的地方：`site.brandIcon`、`chapters[].icon`、`ui.stats[].icon`、
`landing.steps[].icon`。設定檔以外的地方（`$COURSE/assets/` 裡的自訂樣板）也想用圖示時，
用頂層的 `icons` 陣列當逃生門。

sprite 分兩份：`src/web/js/icons.js` 只裝框架介面自己用的圖示，內容與課程無關；
這門課的圖示產在 `$COURSE/assets/js/icons.js`，建置時覆蓋掉框架那一份。
所以兩門課並存時，`make icons` 不會把另一門課的圖示洗掉。

## tone

`kinds` 與 `grades` 的 `tone` 只是指向設計語彙，跟主題無關。可用值等於 `src/web/css/tokens.css`
裡有 `.Label--<tone>` 定義的那幾個：`accent` / `success` / `attention` / `danger` / `done` /
`neutral`。用了沒定義的值，標籤會變成沒有顏色的灰底，`make audit` 會擋。

## 詞彙模組（選用）

`$COURSE/taxonomy/` 放兩個可選模組，在 config 的 `taxonomy` 指定 import 路徑：

- **`facets`**——提供 `extract(*texts) -> [str]`、`GROUPS`、`GROUP_OF`。
  用來做側欄的分面篩選。體態課是肌群；烹飪課可能是食材或技法；程式課可能是語言特性。
  重點是**正規化同義詞**（「背闊肌」與「闊背肌」是同一個）。
- **`categories`**——提供 `classify(item) -> id | None`、`NAMES`、`KINDS`。
  把項目歸類，讓文獻可以掛在類別上（見 `evidence.md`）。

兩個都可以不要，config 拿掉 `taxonomy` 即可，篩選面板會自動消失。
