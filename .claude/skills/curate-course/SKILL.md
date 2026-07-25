---
name: curate-course
description: Use when building a curated video course website from YouTube — picking and verifying videos, organising them into chapters/units, attaching evidence or references, and shipping a static site with good SEO. Topic-agnostic; works for anatomy, cooking, guitar, statistics, welding, anything with good YouTube coverage.
---

# 策展一門 YouTube 課程

這個 repo 是一個 **topic-agnostic 的課程策展框架**。你的工作是產出 `course/` 底下的資料，
框架負責建置、驗證、SEO 與部署。`course/` 現成的體態矯正課是範例，換主題時整個換掉即可。

**核心原則：策展不是生成。** 每一條 YouTube 連結、每一篇引用，都必須是真實存在且你驗證過的。
捏造一個看起來合理的 video ID 或 PMID，比留空更糟。

## 全景

```
course/
  course.config.json   ← 站台設定、章節、配額、所有 UI 文案
  data/                ← 你要產出的策展資料
  taxonomy/            ← 選用：主題專屬的詞彙模組
src/                   ← 框架，換主題時不用動
dist/                  ← 建置產物
```

使用者只改 `course/`。改完跑 `make build && make serve`。

## 流程

### 1. 先把課程結構談清楚

不要一開始就找影片。先確定：

- **主題與受眾**——「給誰、解決什麼問題」決定了選片的深度。
- **章節與單元**——列出章節、每章幾個單元、單元名稱。
- **配額**——每個單元要幾支跟練/練習影片。**加權而非平均攤**：常見或複雜的主題給多，
  冷門的給少。把配額寫進 `course.config.json` 的 `chapters[].drills`，建置時會強制檢查。
- **項目類型**——本框架每個單元底下可以掛一串「項目」，用 `kinds` 定義類型。
  體態課用「放鬆／拉伸／訓練」；吉他課可能是「示範／慢速／練習曲」；
  統計課可能是「觀念／推導／實作」。至少一種，通常三種以內。

把總數算出來對一次。體態課的例子：`37 主課 + 334 跟練 = 371 單元`，
每章配額加總必須等於總數，否則建置會失敗。

### 2. 設定檔

複製 `course/course.config.json` 改。關鍵欄位：

| 欄位 | 作用 |
|---|---|
| `site` | 標題、描述、網址、語系、關鍵字 → 直接餵給 SEO |
| `hero` | 首頁大標與說明，可用 `{units}` `{problems}` 佔位 |
| `ui` | **所有介面文案**。分頁名、篩選標籤、統計欄位、實證欄位標題 |
| `kinds` | 項目類型與配色（`tone` 取 accent/success/danger/attention） |
| `grades` | 證據分級（沒有實證維度就留一個或刪掉相關資料） |
| `chapters` | 章節碼、標題、Lucide 圖示、資料來源檔、配額 |
| `nav` | 側欄的章節分組 |
| `taxonomy` | 選用的詞彙模組（見第 5 節） |

圖示名稱去 https://lucide.dev/icons/ 查，然後把用到的加進 `src/build/build_icons.py` 的
`ICONS` 清單並跑 `make icons`。

### 3. 策展影片（最耗時，一定要並行）

一次一章，派並行的 subagent。每個 agent 的指示要包含：

**品質門檻**——寫成明確清單，不要只說「找好的影片」：

- 優先頻道（列出具體名字）：具備專業背景的創作者、機構官方頻道
- 排除：內容農場、標題殺人（「7 天學會 X」）、播放數過低（< 5,000）、已下架
- 長度區間：教學影片 5–20 分鐘、跟練 1–8 分鐘
- 語言：可接受哪些語言，同等品質下的優先順序

**驗證要求（最重要）**：

```bash
# 唯一可靠的程式化驗證方式
curl -s "https://www.youtube.com/oembed?url=<URL編碼的watch網址>&format=json"
# 200 + 標題頻道相符 = 存在且公開；401/404 = 已刪除或設為私人
```

明確告訴 agent：**video ID 一律取自實際的搜尋結果，不可憑記憶拼湊**。
找不到合格影片就把 `url` 設 `null` 並在 `note` 說明——留空比硬塞相關但不對題的更好。

**輸出格式**（寫進 `course/data/<source>.json`）：

```json
{
  "chapter": "CH5",
  "title": "章節標題",
  "units": [{
    "id": "ch5-u1",
    "name": "單元名稱",
    "type": "posture",
    "assessment": "使用者可以自己做的判斷方法",
    "tight": ["面向 A"], "weak": ["面向 B"],
    "lesson": { "title": "", "channel": "", "url": "", "duration": "", "why": "為何選這支" },
    "drills": [{
      "name": "項目名稱", "en": "English name", "kind": "release",
      "target": "目標", "dose": "劑量或建議",
      "title": "", "channel": "", "url": "", "duration": ""
    }]
  }]
}
```

`type` 對應 `ui.unitTypes`；`kind` 對應 `kinds[].id`；`tight`/`weak` 是選用的兩欄對照
（體態課用來放緊繃/無力肌群，其他主題可放「常見錯誤/該練的能力」，或整個不用）。

**多語言**：同一個單元想提供第二語言版本，另外寫進 `course/data/alt-lessons-<lang>.json`：

```json
{ "lessons": [{ "unit": "ch5-u1", "lang": "en", "title": "", "channel": "", "url": "", "why": "" }] }
```

### 4. 補上真實的中繼資料

策展 agent 抄下來的長度常有 ±30 秒誤差。抓一次真的：

在**真實 YouTube 分頁的 context 內**呼叫 innertube API（直連會被擋），把
`{videoId: {status, seconds, views, channel, title}}` 寫進 `course/data/video-meta.json`。
建置時會用它覆寫長度、頻道與觀看數，總時長才會準。

### 5. 加上可查證的深度（選用但強烈建議）

這是策展課程跟隨手收藏清單的差別。兩個層級：

**單元層級**——每個主題的整體證據強度、常見迷思、警訊。體態課用 OpenEvidence 查了
24 個問題，結果寫進 `course/data/oe-*.json`，含 `evidence_grade` 與引用。

**類別層級**——個別項目通常沒有專屬文獻（「臀橋」沒有自己的 RCT，「臀肌訓練」才有）。
先把項目歸納成數十個類別（`course/taxonomy/drills.py` 的作法），再為每個類別找文獻，
寫進 `course/data/drill-evidence-*.json`：

```json
{ "categories": [{
  "id": "foam-roll", "name": "類別名稱", "evidence_grade": "contested",
  "summary": "繁中 2–4 句：實際效果與限制",
  "citations": [{ "pmid": "31473878", "title": "", "journal": "", "year": 2019,
                  "design": "meta-analysis", "takeaway": "關鍵發現，含效果量更好" }]
}]}
```

PMID 一律用 PubMed E-utilities 取得，不可自行填寫標題：

```bash
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&term=<查詢>"
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=<PMIDs>"
```

**誠實比好看重要。** 如果查證結果顯示這個主題的主流說法證據薄弱，如實寫出來並標成
`contested`。一門承認自己限制的課，比一門承諾一切的課可信得多——這也是這個框架
把 `grades` 做成一等公民的原因。

### 6. 詞彙模組（選用）

`course/taxonomy/` 放兩個可選模組，在 config 的 `taxonomy` 指定：

- **`facets`**——提供 `extract(*texts) -> [str]`、`GROUPS`、`GROUP_OF`。
  用來做側欄的分面篩選。體態課是肌群；烹飪課可能是食材或技法；程式課可能是語言特性。
  重點是**正規化同義詞**（「背闊肌」與「闊背肌」是同一個）。
- **`categories`**——提供 `classify(item) -> id | None`、`NAMES`、`KINDS`。
  把項目歸類，讓文獻可以掛在類別上。

兩個都可以不要，config 拿掉 `taxonomy` 即可，篩選面板會自動消失。

### 7. 建置、驗證、部署

```bash
make build     # 合併資料 → dist/，配額不符會直接失敗
make verify    # 重驗每個影片連結與每個 PMID（打真實 API）
make serve     # 本機預覽
make og        # 重新產生社群預覽圖（改 src/web/og.html 的文案）
make deploy    # 部署到 Cloudflare Pages
```

`make verify` 是最後一道關卡，**不信任任何上游宣稱**，包括 agent 自稱已驗證過的。
交付前一定要跑，並確認 100% 通過。

## 踩過的坑

| 現象 | 真相 |
|---|---|
| `WebFetch` 打 `youtube.com/watch` 拿不到東西 | 會被 Google 導向 captcha 頁，改用 oEmbed 端點 |
| `yt-dlp` 說影片不存在 | 無 cookie 時會誤報「Sign in to confirm you're not a bot」，不是影片失效 |
| innertube API 回 ERROR | 必須在真實 YouTube 分頁的 context 內呼叫才有效 |
| 改了樣式但線上沒變 | 檢查 `_headers` 的 Cache-Control，沒有 hash 檔名就別設長快取 |
| 並行 agent 互相覆蓋檔案 | 每個 agent 給獨立的輸出路徑與檔名前綴 |
| 數字對不起來 | 單元數、影片欄位數、去重後支數是三個不同的東西，UI 上要講清楚 |

## 驗收清單

交付前逐項確認：

- [ ] `make build` 通過，配額全數符合
- [ ] `make verify` 100% 通過，無失效連結、無捏造引用
- [ ] 每個單元都有可操作的 `assessment`（不只是描述問題）
- [ ] 找不到合格影片的格子誠實留空，`note` 說明原因
- [ ] 證據分級照實填，不美化
- [ ] 首頁三個數字（單元/影片/去重）互相對得上
- [ ] 手機與寬螢幕都沒有水平溢出
- [ ] `og.png` 已更新成新主題
