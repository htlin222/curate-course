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
| 設定檔 | schema（欄位拼錯、型別、`tone` 值）、圖示是否已打包、`nav` 是否漏章或指向不存在的章、`taxonomy` 模組能不能 import、`ui.stats` 參照的統計欄位存不存在、文案佔位符會不會被替換 |
| 結構 | 各章配額、單元 id 唯一、`kind`/`type` 是否已定義、同單元項目重名、每單元項目數是否失衡、`evidenceAlias` 指向幽靈單元 |
| 影片 | 中繼資料覆蓋率、不可用狀態、URL 格式、同單元重複、跨單元共用過多、**長度是否落在設定的區間**、宣稱長度與實際的誤差、觀看數低標、留空的格子有沒有寫 `note` |
| 內容深度 | 指定型別的單元有沒有可操作的 `assessment`、主課有沒有 `why`、`evidence_grade` 是否合法、PMID 格式、每個類別的文獻篇數 |

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
  "allowMissingUrls": 4        // 容許幾個「誠實留空且有 note」的格子
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
| innertube API 回 ERROR | 必須在真實 YouTube 分頁的 context 內呼叫才有效 |
| 改了樣式但線上沒變 | 檢查 `_headers` 的 Cache-Control，沒有 hash 檔名就別設長快取 |
| 並行 agent 互相覆蓋檔案 | 每個 agent 給獨立的輸出路徑與檔名前綴，**暫存目錄也要各給一個子目錄**——`q1.txt` 這種通用檔名一定會被別人蓋掉 |
| 數字對不起來 | 單元數、影片欄位數、去重後支數是三個不同的東西，UI 上要講清楚 |
| 章節圖示顯示空白 | 圖示沒加進 `build_icons.py` 的 `ICONS`，或加了沒跑 `make icons` |
| 標籤沒有顏色 | `tone` 只能用 `tokens.css` 裡有 `.Label--<tone>` 的那幾個 |
| 側欄少一整章 | `nav` 分組沒列到那個章節碼——章節存在不代表側欄看得到 |
| 總時長怪怪的 | 多語言版本會灌進「所有欄位合計」，課程時長只算主要版本 |
| 分類 patterns 加了肌肉名之後歸類全亂 | `classify()` 會比對 `target` 欄位，那裡放的就是肌肉名——把「臀中肌」當 pattern，所有目標含臀中肌的動作都會掉進臀肌啟動。patterns 只能用**動作名**，改完一定要 diff 前後的歸類結果 |
| PMID 全部驗過了，卻還是有沒驗到的 | `verify_refs.py` 要同時掃 `drill-evidence-*.json` 的 `categories` **與** `oe-*.json` 的 `conditions`。只驗一層等於留了一半的門沒鎖 |


## 換主題時最容易漏掉的

這些不會讓 `make audit` 變紅，但會讓網站繼續講上一個主題的事——上線後才被使用者發現。

| 症狀 | 檢查 |
|---|---|
| **留言跑到別的 repo** | `discussions` 的 `repo` / `repoId` / `categoryId` 還是上一個主題的值。換主題一定要在新 repo 開 Discussions 並換掉這三個 |
| 品牌圖示還是舊主題的 | `site.brandIcon` 有進 `course.json` 也被稽核檢查，但**前端要真的去讀它**；`index.html` 裡的圖示只是預設值 |
| 篩選籤寫著上一個主題的類型 | FilterBar 的按鈕若寫死在 `index.html`，換 `kinds` 不會跟著變。要從設定檔產生 |
| `make build` 的類型統計全是 0 | 統計行若寫死 `kinds['release']` 這種 id，換主題就對不到。改成迭代 `CFG["kinds"]` |
| 「支跟練影片」之類的名詞不對題 | 項目名詞要放進 `ui`（例如 `ui.drillNoun`），不要寫死在 JS 裡 |
| `og.png` 還是舊課程 | `src/web/og.html` 是靜態模板，數字與文案都要手動對齊 `make build` 的輸出，再跑 `make og` |

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
