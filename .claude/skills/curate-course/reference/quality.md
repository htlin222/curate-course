# 稽核與驗證

品質是**兩道獨立關卡**，缺一不可：

| | `make audit` | `make verify` |
|---|---|---|
| 打不打網路 | 不打，秒回 | 打 YouTube oEmbed 與 PubMed |
| 回答什麼 | 這批資料**自己內部一致嗎** | 這些連結與 PMID **真的存在嗎** |
| 什麼時候跑 | 每寫完一章就跑 | 交付前、部署前 |

`make verify` **不信任任何上游宣稱**，包括 agent 自稱已驗證過的，交付前一定要 100% 通過。

## `make audit` 查什麼

確定性——同樣的輸入永遠同樣的輸出，所以可以放進迴圈修到乾淨。
錯誤（`✗`）回傳 1 一定要修；警告（`⚠`）要逐條看過再決定是接受還是換片。

| 面向 | 檢查 |
|---|---|
| 設定檔 | **`frameworkVersion` 的主版號對不對得上這份框架**（對不上就指向 `docs/MIGRATION.md`，其餘檢查都是拿新規則量舊設定檔）、schema（欄位拼錯、型別、`tone` 值）、圖示是否已打包、`nav` 是否漏章或指向不存在的章、`taxonomy` 模組能不能 import、`ui.stats` 參照的統計欄位存不存在、文案佔位符會不會被替換 |
| 結構 | 各章配額、單元 id 唯一、`kind`/`type` 是否已定義、同單元項目重名、每單元項目數是否失衡、`evidenceAlias` 指向幽靈單元 |
| 影片 | 中繼資料覆蓋率、不可用狀態、URL 格式、同單元重複、跨單元共用過多、**長度是否落在設定的區間**、宣稱長度與實際的誤差、觀看數低標、留空的格子有沒有寫 `note` |
| 內容深度 | 指定型別的單元有沒有可操作的 `assessment`、主課有沒有 `why`、`evidence_grade` 是否合法、PMID 格式、每個類別的文獻篇數 |
| 選片品質 | **不是「有沒有片」，是「挑得好不好」**（只警告）：某一章的主課長度中位數明顯低於其他章（多半是策展時沿用了動作的長度門檻，把講解型長片濾掉了）、單一頻道佔比過高（搜尋關鍵字換得不夠）|
| 文案風格 | **AI 寫作痕跡**（只警告）：否定式排比、宣傳性最高級、模糊歸因、填充連接詞、三個以上並排的粗體，以及破折號的**密度**。同時掃設定檔文案與資料檔散文（`summary`／`assessment`／`why`／`note`）。只在 `site.locale` 為 `zh-*` 時啟用，改法見 `writing.md` |

## 門檻寫在哪

`course.config.json` 的 `audit` 區塊。沒寫的欄位用 `src/build/audit.py` 的 `DEFAULTS`：

```jsonc
"audit": {
  "duration": {                                  // 影片長度區間，超出只警告
    "lesson": { "min": "4:00", "max": "22:00" },
    "drill":  { "min": "0:30", "max": "10:00" }
  },
  "driftSeconds": 30,          // 宣稱長度與實際中繼資料的容許誤差
  "minViews": 5000,            // 低於此觀看數要人工看一眼
  "metaCoverage": 1,           // video-meta.json 必須覆蓋的比例，未達即錯誤
  "drillsPerUnit": { "min": 5, "max": 18 },      // 抓策展失衡
  "maxSharedVideos": 50,       // 允許跨單元共用的影片支數
  "requireAssessment": ["posture"],              // 這些 unitType 必須寫自我評估
  "minAssessmentChars": 80,
  "minCitations": 2,           // 每個文獻類別至少幾篇
  "allowMissingUrls": 4,       // 容許幾個「誠實留空且有 note」的格子
  "copyStyle": { "maxDashRatio": 0.05 },        // 容許幾成文案欄位用破折號
  "maxChannelShare": 0.25,     // 單一頻道最多佔整門課幾成
  "minChapterLessonRatio": 0.6 // 一章的主課中位長度，最低是全課中位的幾成
}
```

門檻不合用就改，**但要有理由**——把區間放寬到全部通過等於沒有稽核。
合理的做法是留下警告，並在交付說明裡講清楚為什麼接受。

## 自我修正迴圈

```bash
python3 src/build/audit.py --json     # 機器可讀，直接讀 errors[] 逐條修
python3 src/build/audit.py --strict   # 警告也視為錯誤（要求零瑕疵時用）
COURSE=courses/guitar python3 src/build/audit.py   # 多課程並存
```

`--json` 回傳 `{errors: [{section, message, detail}], warnings: [...], stats: {...}, ok: bool}`。
修完再跑一次，直到 `ok: true`，再進 `make verify`。

## 踩過的坑

| 現象 | 真相 |
|---|---|
| `WebFetch` 打 `youtube.com/watch` 拿不到東西 | 會被 Google 導向 captcha 頁，改用 oEmbed 端點 |
| `yt-dlp` 說影片不存在 | 無 cookie 時會誤報「Sign in to confirm you're not a bot」，不是影片失效。單次搜尋沒事，連抓數百支就會被擋——加 `--cookies-from-browser chrome` 借用登入狀態即可。另有少數影片要 `--ignore-no-formats-error` 才拿得到中繼資料 |
| **`yt-dlp` 什麼都沒說**（exit 0 + 空 stdout） | 被限流的樣子，不是影片下架。同一支影片 oEmbed 照樣回 200，`--flat-playlist` 的搜尋也照樣正常，休息一陣子單片查詢就自己好了。**自製複查腳本一定要比對輸入 id 數與輸出行數**，不要「沒回東西就標成失效」——跑得越久、規模越大，被誤殺的越多 |
| 影片明明能播，網站上卻是死掉的播放器 | 能播 ≠ 能嵌入。yt-dlp 拿得到完整中繼資料、innertube 回 `playabilityStatus: OK`，都不代表允許 iframe 嵌入。**只有 oEmbed（`make verify`）算數**，401 就是不能嵌入，得換片 |
| innertube API 回 ERROR | 必須在真實 YouTube 分頁的 context 內呼叫才有效——但那是備案，中繼資料改用 `yt-dlp --batch-file` 就不必開瀏覽器（見 `curating.md`） |
| `--print "%(id)s\t…"` 解析出 0 筆 | `--print` 不解析跳脫序列，`\t` 輸出的是字面上的反斜線加 t（`od -c` 看得到）。改用 `\|` 當分隔符，並把可能含 `\|` 的 `title` 排在最後一欄 |
| 改了樣式但線上沒變 | 檢查 `_headers` 的 Cache-Control，沒有 hash 檔名就別設長快取 |
| 並行 agent 互相覆蓋檔案 | 每個 agent 給獨立的輸出路徑與檔名前綴，**暫存目錄也要各給一個子目錄**——`q1.txt` 這種通用檔名一定會被別人蓋掉 |
| 數字對不起來 | 單元數、影片欄位數、去重後支數是三個不同的東西，UI 上要講清楚 |
| 章節圖示顯示空白 | 設定檔改了圖示但沒跑 `make icons` 重打包這門課的 sprite |
| 標籤沒有顏色 | `tone` 只能用 `tokens.css` 裡有 `.Label--<tone>` 的那幾個 |
| 側欄少一整章 | `nav` 分組沒列到那個章節碼——章節存在不代表側欄看得到 |
| 總時長怪怪的 | 多語言版本會灌進「所有欄位合計」，課程時長只算主要版本 |
| 分類 patterns 加了肌肉名之後歸類全亂 | `classify()` 會比對 `target` 欄位，那裡放的就是肌肉名——把「臀中肌」當 pattern，所有目標含臀中肌的動作都會掉進臀肌啟動。patterns 只能用**動作名**，改完一定要 diff 前後的歸類結果 |
| PMID 全部驗過了，卻還是有沒驗到的 | `verify_refs.py` 要同時掃 `drill-evidence-*.json` 的 `categories` **與** `oe-*.json` 的 `conditions`。只驗一層等於留了一半的門沒鎖 |


## 換主題時最容易漏掉的

**大部分已經有稽核在擋了。** `make audit` 的「主題耦合」區段會抓兩件事：前端有沒有寫死
項目類型 id、`ui.problemType` 對不對得到單元；「文案」區段再抓三件：佔位符有沒有打錯字、
`index.html` 需要的文案欄位有沒有漏填、文案裡有沒有寫 HTML 標籤。這幾種 bug 的共同
特徵是**不會報錯**——類型 id 寫死在前端，換主題後項目全部不顯示但主控台一片安靜；
`teaches` 找不到單元就產出空陣列，JSON-LD 依然合法。沉默的失敗最貴。

### 主題詞彙一律走設定檔

程式裡不該出現任何主題名詞。`ui` 底下這幾個欄位就是為此存在的：

| 欄位 | 用在哪 | 體態課的值 |
|---|---|---|
| `unitNoun` / `lessonNoun` / `drillNoun` / `drillNounShort` | 統計行、章節卡片、篩選計數 | 個單元／堂主課／支跟練影片／支跟練 |
| `kindFilterLabel` | 篩選列的無障礙標籤 | 動作類型篩選 |
| `missingTitle` / `missingHint` | 找不到合格影片時的卡片 | 尚未找到合格影片／… |
| `lessonLangLabel` / `watchLabel` / `facetFilterHint` | 語言分頁、項目連結、分面標籤的 title | — |
| `evidenceSource` / `evidenceSourceLink` | 實證查核的來源名稱與連結文字 | OpenEvidence／在 OpenEvidence 讀完整回答 |

全部有預設值，不填不會壞，但會講出上一個主題的話。

### 文案佔位符有七個，別只用 {units}

`{units}` 是**所有影片欄位合計**（主課 + 項目），不是章節單元數。體態課刻意把 371 個
欄位統稱為「單元」，所以那裡沒問題；但塔羅課有 62 個單元、368 個欄位，寫
「{units} 個單元」就會印出「368 個單元」——數字沒錯，話講錯了。

| 佔位符 | 意義 |
|---|---|
| `{units}` | 影片欄位合計（主課 + 項目） |
| `{lessonUnits}` / `{drillUnits}` | 章節單元數／項目數 |
| `{slots}` / `{videos}` | 影片欄位數／去重後實際支數 |
| `{problems}` / `{evidence}` | 主題單元數／實證查核則數 |

打錯字會被稽核擋下，不會原樣印到頁面上。建置期（`seo.py`）與執行期（`copy.js`）用的是
同一份對應表，同一個 token 在首屏與前端一定得到同一個數字。

### 文案不吃 HTML，只吃 `**粗體**`

所有文案欄位一律先逸出，唯一認得的標記是 `**粗體**`；寫 `<strong>` 會被稽核擋下來。
細節見 `config.md` 的「文案怎麼寫」。

### 剩下這些還是要自己看

這些不會讓 `make audit` 變紅，但會讓網站繼續講上一個主題的事——上線後才被使用者發現。

| 症狀 | 檢查 |
|---|---|
| **留言跑到別的 repo** | `discussions` 的 `repo` / `repoId` / `categoryId` 還是上一個主題的值。換主題一定要在新 repo 開 Discussions 並換掉這三個 |
| 品牌圖示還是舊主題的 | `site.brandIcon` 有進 `course.json` 也被稽核檢查，但**前端要真的去讀它**；`index.html` 裡的圖示只是預設值 |
| 篩選籤寫著上一個主題的類型 | FilterBar 的按鈕若寫死在 `index.html`，換 `kinds` 不會跟著變。要從設定檔產生 |
| `make build` 的類型統計全是 0 | 統計行若寫死 `kinds['release']` 這種 id，換主題就對不到。改成迭代 `CFG["kinds"]` |
| 「支跟練影片」之類的名詞不對題 | 項目名詞要放進 `ui`（例如 `ui.drillNoun`），不要寫死在 JS 裡 |
| `og.png` 還是舊課程 | 模板本身已經不用管了——`make build` 會把統計與分級注入 `dist/og.html`，少填一個佔位符就直接讓 build 掛掉。會留下的是 **`assets/og.png` 這個提交進 repo 的截圖檔**：數字變了沒人會提醒你，換主題或改完統計要重跑 `make og` 再 `git add` |
| `LICENSE` 掛著別人的名字 | `Copyright (c) 2026 curate-course contributors` 是框架的，clone 下來要換成自己的。免責聲明框架只給通用句，主題專屬的那句寫在 `course.config.json` 的 `footer.disclaimer` 與 `llms.disclaimer` |
| `docs/plans/` 留著範例課程的設計文件 | `2026-07-25-example-course-design.md` 記的是 `examples/body/` 的規劃，不是你的課的。要嘛刪掉，要嘛換成自己的 |

### giscus 到底接上了沒

肉眼看討論面板分不出「還沒人留言」和「App 沒授權」，用 API 問：

```bash
curl -s "https://giscus.app/api/discussions?repo=<url編碼的owner%2Frepo>&term=t&category=General&strict=false&number=0&first=1"
```

- `{"error":"Discussion not found"}` → **正常**，只是還沒人留言（第一則留言時才建立討論串）
- `{"error":"giscus is not installed on this repository"}` → App 還沒授權到這個 repo，
  去 <https://github.com/apps/giscus/installations/new> 加上去

取 `repoId` / `categoryId` 不必開 giscus.app，用 GitHub API 更快：

```bash
gh api -X PATCH repos/<owner>/<repo> -F has_discussions=true
gh api graphql -f query='{ repository(owner:"<owner>", name:"<repo>") {
  id  discussionCategories(first:20){ nodes { id name } } } }'
```


## 瀏覽次數徽章（選用）

設定檔加上 `counter` 就會在 header 顯示累計瀏覽次數，拿掉就整個消失。

```bash
make counter   # 建 D1 資料庫 → 建表 → 寫出 wrangler.jsonc（冪等，可重跑）
make deploy
```

`make counter` 冪等：重跑會沿用既有資料庫，不會把數字歸零。
產生的 `wrangler.jsonc` 含每門課自己的 `database_id`，已被 gitignore。

### 為什麼是 D1，不是 KV 或 Durable Object

這三個都能存一個數字，但只有 D1 適合：

| | 免費額度 | 為什麼不選 |
|---|---|---|
| **KV** | 1,000 寫入/日 | 而且**同一個 key 每秒最多寫 1 次**，訪客一多就撞 429。計數器是最不適合 KV 的用法 |
| **Durable Object** | 有免費方案 | 計數器的教科書解，但 **Pages 專案不能自己託管 DO class**，必須另外部署一個 Worker 再綁定——對「clone 下來就能跑」來說設定成本太高 |
| **D1** ✅ | 100,000 列寫入/日 | 直接綁 Pages Functions，全程 CLI 建得完 |
| Web Analytics | 免費 | 只能看儀表板，**沒有公開讀取 API**，餵不了頁面上的數字 |

遞增用單一語句 `INSERT … ON CONFLICT DO UPDATE SET n = n + 1 RETURNING n`，
不需要交易，也沒有 read-modify-write 的競態。

### 這個數字誠實嗎

- 數的是**累計頁面瀏覽**，不是不重複訪客。重整一次就多一次
- 伺服器端擋掉常見爬蟲 UA（回 `counted: false`），但擋不完
- 沒有 cookie、沒有指紋、不碰任何個人資料

`title` 欄位就是拿來把上面這幾點講給讀者聽的，別寫成「訪客人數」。

### 壞掉時會怎樣

沒綁 D1、本機預覽、API 掛掉，`/api/hits` 一律回 503，前端讓徽章維持隱藏。
**寧可沒有這個功能，也不要在 header 留一個壞掉的空殼。** `_headers` 對 `/api/*`
設 `no-store`，否則數字會被邊緣快取凍住。
