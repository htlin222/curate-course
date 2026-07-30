# curate-course

把 YouTube 上散落的好內容，變成一門**結構完整、連結全數驗證、來源可查**的課程網站。

主題無關。附的範例是一門體態矯正課（371 個單元、406 支影片、423 篇 PubMed 引用），
但框架本身不認識「體態」——換成吉他、統計、烘焙、電銲都一樣跑。

**線上範例**：<https://body-course.pages.dev>

---

## 為什麼不是又一個播放清單

播放清單解決「收藏」，這個框架解決另外三件事：

**一、結構。** 章節 → 單元 → 項目三層，配額寫進設定檔，數量不對就建置失敗。
不會出現「這章塞了 40 支、那章只有 3 支」的失衡。

**二、連結真的活著。** 幾百個格子最大的風險是連結是捏造的。所以有兩層關卡：
`make audit` 離線把設定檔、配額、影片長度、實證欄位全查一遍（確定性，不打網路）；
`make verify` 再對每個 YouTube 連結重打 oEmbed、對每個 PMID 重打 PubMed API。
**不信任任何上游宣稱**，包括 AI agent 自稱驗證過的。

**三、可查證的深度。** 每個單元可以掛證據強度與原始文獻。範例課程的 24 個主題全部經
OpenEvidence 查證，其中 9 個被判為 `contested`——結果照實寫進網站，包含對課程自己不利的部分。

---

## 快速開始

需要 [uv](https://docs.astral.sh/uv/)。建置腳本只用 Python 標準庫，沒有執行期相依。

```bash
git clone https://github.com/<you>/curate-course.git
cd curate-course

make build     # course/ → dist/
make serve     # http://localhost:8899
```

看到的是範例的體態課。接著換成你的主題。

---

## 換成你的主題

**你只需要動 `course/`**，其他都是框架。

```
course/
├── course.config.json   站台設定、章節、配額、所有 UI 文案
├── data/                策展資料（影片、實證、中繼資料）
└── taxonomy/            選用：主題專屬的詞彙模組
```

### 1. 設定

`course.config.json` 裡沒有一個字是寫死在程式裡的——分頁名稱、篩選標籤、
統計欄位、證據分級的顯示文字，全部從這裡讀。

```jsonc
{
  "site":  { "name": "…", "title": "…", "url": "https://…" },
  "kinds": [                       // 每個單元底下的項目分幾類
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

### 2. 資料

`course/data/<source>.json`，一章一檔：

```jsonc
{
  "chapter": "CH1",
  "units": [{
    "id": "ch1-u1",
    "name": "單元名稱",
    "assessment": "讀者可以自己做的判斷方法",
    "lesson": { "title": "…", "channel": "…", "url": "https://youtube.com/watch?v=…",
                "why": "為何選這支" },
    "drills": [{ "name": "…", "kind": "demo", "url": "…", "dose": "…" }]
  }]
}
```

### 3. 建置與稽核

```bash
make build && make audit && make serve
```

配額不符、URL 格式錯誤、同單元重複影片會讓建置直接失敗。
`make audit` 再往下查一層——而且**不打網路**，同樣的輸入永遠得到同樣的報告：

```
設定檔    schema 拼字與型別、圖示有沒有打包、nav 有沒有漏章、佔位符會不會被替換
結構      各章配額、id 唯一、kind/type 是否已定義、每單元項目數是否失衡
影片      中繼資料覆蓋率、長度是否落在設定區間、宣稱長度與實際的誤差、觀看數低標、
          留空的格子有沒有寫清楚原因
內容深度  自我評估夠不夠具體、evidence_grade 是否合法、PMID 格式、每類文獻篇數
```

門檻寫在 `course.config.json` 的 `audit` 區塊（影片長度區間、最低觀看數、每單元項目數
上下限…），不是寫死在程式裡。`--json` 給 agent 讀、`--strict` 讓警告也變成錯誤。

---

## 讓 AI 幫你策展

repo 內附一個 Claude Code skill。在 Claude Code 裡開這個專案，輸入：

```
/curate-course 幫我用這個框架做一門古典吉他入門課
```

或直接用自己的話說「幫我用這個框架做一門 X 的課程」，agent 會照著 skill 走完整流程：
談結構 → 定配額 → 並行策展 → 驗證連結 → 補中繼資料 → 加引用 → 稽核 → 建置部署。

Skill 本身採漸進揭露，主檔只有流程骨架，細節按需載入：

```
.claude/skills/curate-course/
  SKILL.md              鐵則、七步流程、驗收清單
  reference/config.md   設定檔欄位、schema、圖示、tone、詞彙模組
  reference/curating.md 策展 agent 指示範本、oEmbed 驗證、資料格式、多語言
  reference/evidence.md 單元／類別兩層實證、PubMed E-utilities 用法
  reference/quality.md  audit 與 verify 的分工、門檻怎麼調、踩過的坑
```

裡頭寫死了幾條不可退讓的規則，最重要的是：**video ID 必須取自實際搜尋結果，
不可憑記憶拼湊；找不到合格影片就留空並在 `note` 說明原因**——留空而不說明會被稽核擋下。

---

## 指令

```
make build     course/ → dist/，含配額驗證與 SEO 產出
make audit     離線稽核設定檔、配額、影片長度與實證深度（不打網路，可放 CI）
make test      前端純邏輯的單元測試（node:test，零依賴、不需要瀏覽器）
make e2e       paywall 端對端流程並截圖（Playwright，需要 Chrome）
make verify    重驗每個影片連結與每個 PMID（打真實 API）
make serve     本機預覽
make icons     重新下載 Lucide 圖示並打包成內嵌 sprite
make og        重新產生社群預覽圖
make lint      ruff 檢查
make check     lint + test + build + audit，提交前跑這個
make deploy    部署到 Cloudflare Pages
```

多課程並存：`COURSE=courses/guitar DIST=dist-guitar make build`

---

## 網站有什麼

四個檢視：

- **首頁** — 用法三步驟、立場摘要、章節總覽
- **課程內容** — 章節樹、自我評估、分面標籤、項目清單、證據註記
- **上課模式** — 左側嵌入播放（走 `youtube-nocookie.com`）、右側播放清單，
  滿版高度、欄寬可拖曳、`?tab=player&play=12` 深連結
- **立場** — 課程對自身限制的說明與原始文獻

外加：分面篩選、全文搜尋、localStorage 進度追蹤、深淺色主題、
YouTube IFrame API 快捷鍵（按 `?` 看清單）。

**每支影片一串討論**：上課模式的動作列有「討論」按鈕，用
[giscus](https://giscus.app) 把留言存進 repo 的 GitHub Discussions，
`data-term` 綁 video id，所以同一支影片在不同單元共用同一串。
啟用方式：到 <https://github.com/apps/giscus> 安裝到你的 repo，
再把 `repoId` / `categoryId` 填進 `course.config.json` 的 `discussions`。
面板只在點開時才載入 giscus，不影響首屏。

**選用的 0 元 paywall**：`course.config.json` 加 `paywall` 區塊，就會多出「加入購物車 →
0 元結帳 → 解鎖」的流程：前幾章免費試看，其餘章節顯示鎖頭、點下去彈出結帳，
結完帳全部解鎖。金額真的是 0，被劃掉的原價是虛構的，介面上有一行字直接講明。
拿掉那個區塊就完全回到全站開放。設計與接真金流要補的東西見
[docs/PAYWALL.md](docs/PAYWALL.md)。

**SEO**：`Course` JSON-LD（含 syllabus 與 citation）、OG/Twitter 卡、sitemap、
robots、`llms.txt`。文案在建置時就注入 HTML，不等 JS 執行，首屏就有真實內容。

**首屏零外部請求**：Primer 設計語彙用 CSS 變數自行實作，Lucide 圖示打包成內嵌 sprite。
只有按下播放時才連 YouTube、點開討論時才連 giscus。

---

## 架構

```
src/
  build/
    build.py          合併、配額驗證、中繼資料套用
    seo.py            JSON-LD / sitemap / robots / llms.txt / 模板注入
    build_icons.py    Lucide sprite 打包
    audit.py          離線品質稽核（設定檔／配額／長度／實證）
    course.schema.json  設定檔結構，編輯器自動完成 + 稽核擋拼字
    verify_links.py   YouTube oEmbed 驗證
    verify_refs.py    PubMed 引用驗證
  web/
    index.html        模板，{{token}} 於建置時替換
    css/  js/         前端
    js/paywall-core.js  0 元 paywall 的純邏輯，被 node --test 直接載入
tests/
  paywall-core.test.js  單元測試（零依賴）
  e2e-paywall.cjs       Playwright 端對端 + 截圖
docs/PAYWALL.md       paywall 設計與接真金流的待辦
course/               ← 你的課程
dist/                 ← 建置產物（gitignored）
```

框架不 import 任何主題詞彙。`course/taxonomy/` 是可插拔的：
提供 `extract()` 就有分面篩選，提供 `classify()` 就能把引用掛在類別上，
兩個都不給也能跑。

---

## 範例課程：體態矯正

`course/` 現成的內容。做它的過程順便驗證了框架的每個環節：

| | |
|---|---|
| 單元 | 371（37 堂主課 + 334 支跟練） |
| 影片 | 406 個欄位、344 支不重複、26 小時 3 分 |
| 多語言 | 35 個單元有繁中／英文兩版 |
| 證據查核 | 24 個主題 + 3 個核心觀念（OpenEvidence） |
| 文獻 | 55 個動作類別、423 篇 PubMed 引用 |
| 驗證 | 稽核零錯誤、連結 100% 有效、PMID 100% 存在且標題相符 |

查證結果沒有很好看，而這正是重點：

- 靜態體態與疼痛的**因果關係沒有共識**（Swain 2020 涵蓋 41 篇系統性回顧的傘狀回顧）
- Janda 交叉症候群**沒有任何評分者間信度資料**，也沒有 EMG／影像研究能重現
- 矯正運動有效，**但不是因為它把體態調正了**——沒有中介分析支持，
  頭對頭試驗中也不優於一般運動

這些全部寫在網站上，`contested` 標籤直接顯示在單元標題列。

---

## 授權

程式碼採 MIT，見 [LICENSE](LICENSE)。

**影片著作權屬原 YouTube 頻道**，本專案只存連結與公開中繼資料，不重製也不代管。
Lucide 圖示為 ISC。範例課程的內容為衛教與運動指引，不構成醫療建議。
