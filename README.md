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

**二、連結真的活著。** 幾百個格子最大的風險是連結是捏造的。所以有兩道獨立關卡：
`verify_links.py` 對每個 YouTube 連結重打 oEmbed、`verify_refs.py` 對每個 PMID 重打
PubMed API。**不信任任何上游宣稱**，包括 AI agent 自稱驗證過的。

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

### 3. 建置

```bash
make build && make serve
```

配額不符、URL 格式錯誤、同單元重複影片都會被擋下來。

---

## 讓 AI 幫你策展

repo 內附 `.claude/skills/curate-course/SKILL.md`。在 Claude Code 裡開這個專案，
直接說「幫我用這個框架做一門 X 的課程」，agent 會照著 skill 走完整流程：
談結構 → 定配額 → 並行策展 → 驗證連結 → 補中繼資料 → 加引用 → 建置部署。

Skill 裡寫死了幾條不可退讓的規則，最重要的是：**video ID 必須取自實際搜尋結果，
不可憑記憶拼湊；找不到合格影片就留空並說明原因。**

---

## 指令

```
make build     course/ → dist/，含配額驗證與 SEO 產出
make verify    重驗每個影片連結與每個 PMID（打真實 API）
make serve     本機預覽
make icons     重新下載 Lucide 圖示並打包成內嵌 sprite
make og        重新產生社群預覽圖
make lint      ruff 檢查
make check     lint + build，提交前跑這個
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

**SEO**：`Course` JSON-LD（含 syllabus 與 citation）、OG/Twitter 卡、sitemap、
robots、`llms.txt`。文案在建置時就注入 HTML，不等 JS 執行，首屏就有真實內容。

**零外部請求**：Primer 設計語彙用 CSS 變數自行實作，Lucide 圖示打包成內嵌 sprite。
只有你按下播放時才會連到 YouTube。

---

## 架構

```
src/
  build/
    build.py          合併、配額驗證、中繼資料套用
    seo.py            JSON-LD / sitemap / robots / llms.txt / 模板注入
    build_icons.py    Lucide sprite 打包
    verify_links.py   YouTube oEmbed 驗證
    verify_refs.py    PubMed 引用驗證
  web/
    index.html        模板，{{token}} 於建置時替換
    css/  js/         前端
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
| 驗證 | 連結 100% 有效、PMID 100% 存在且標題相符 |

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
