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
| `yt-dlp` 說影片不存在 | 無 cookie 時會誤報「Sign in to confirm you're not a bot」，不是影片失效 |
| innertube API 回 ERROR | 必須在真實 YouTube 分頁的 context 內呼叫才有效 |
| 改了樣式但線上沒變 | 檢查 `_headers` 的 Cache-Control，沒有 hash 檔名就別設長快取 |
| 並行 agent 互相覆蓋檔案 | 每個 agent 給獨立的輸出路徑與檔名前綴 |
| 數字對不起來 | 單元數、影片欄位數、去重後支數是三個不同的東西，UI 上要講清楚 |
| 章節圖示顯示空白 | 圖示沒加進 `build_icons.py` 的 `ICONS`，或加了沒跑 `make icons` |
| 標籤沒有顏色 | `tone` 只能用 `tokens.css` 裡有 `.Label--<tone>` 的那幾個 |
| 側欄少一整章 | `nav` 分組沒列到那個章節碼——章節存在不代表側欄看得到 |
| 總時長怪怪的 | 多語言版本會灌進「所有欄位合計」，課程時長只算主要版本 |
