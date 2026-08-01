---
name: curate-course
description: Use when building a curated video course website from YouTube — picking and verifying videos, organising them into chapters/units, attaching evidence or references, and shipping a static site with good SEO. Topic-agnostic; works for anatomy, cooking, guitar, statistics, welding, anything with good YouTube coverage.
---

# 策展一門 YouTube 課程

這個 repo 是一個 **topic-agnostic 的課程策展框架**。你的工作是產出**一門課的目錄**底下的資料，
框架負責建置、稽核、驗證、SEO 與部署。

框架本身不內含任何一門課。開新課用 `make new-course NAME=<名字>`，它會產生
`courses/<名字>/`——一門零單元但**現在就建得起來**的課，你往裡面填內容即可。
`examples/body/` 是隨框架附的體態矯正課範例，**不要改它**，它在 CI 裡當對照組。

## 鐵則

1. **策展不是生成。** video ID 一律取自實際搜尋結果，PMID 一律取自 PubMed API。
   捏造一個看起來合理的 ID 比留空更糟。
2. **留空要說明。** 找不到合格影片就 `url: null` + `note` 寫清楚查過什麼、為什麼不合格。
3. **不信任任何上游宣稱**，包括自己剛才說已經驗證過的。交付前一定跑 `make audit` 與 `make verify`。
   **能播 ≠ 能嵌入**——yt-dlp 與 innertube 只回答前者，可嵌入與否只有 `make verify` 的
   oEmbed 算數。**影片死活也只認 oEmbed**：yt-dlp 被限流時是 exit 0 + 空輸出，
   拿它判死刑會靜靜殺掉活著的影片（見 `reference/curating.md`）。
4. **誠實比好看重要。** 查證結果對課程不利就照實寫，標成 `contested`。

## 全景

```
courses/<你的課>/       ← 你的工作範圍，以下用 $COURSE 代稱
  course.config.json   ← 站台設定、章節、配額、品質門檻、所有 UI 文案
  data/                ← 你要產出的策展資料
  assets/              ← favicon、og.png、這門課自己的圖示 sprite
  taxonomy/            ← 選用：主題專屬的詞彙模組
examples/body/         ← 範例課，別動
src/                   ← 框架，換主題時不用動
dist/<課程名>/          ← 建置產物，每門課各自獨立
```

**只改 $COURSE 底下的檔案。** 這個 repo 有不只一門課，所以每個指令都要帶 `COURSE=`：

```bash
make new-course NAME=guitar                    # 一次
COURSE=courses/guitar make build audit serve   # 之後每次
```

`COURSE` 沒設而 repo 剛好只有一門課時會自動選它，有兩門以上就會直接報錯要你講清楚。
`make courses` 隨時可以看現在有哪些課。

改到 `src/` 底下任何一個檔案就是踩線了：`tests/decoupling.test.js` 會掃 `src/` 有沒有
出現課程專屬的字串，CI 也會同時建置兩門課。真的非改不可，那是框架的 bug，開 issue。

## 流程

**1. 先把結構談清楚**——不要一開始就找影片。確定主題與受眾、章節與單元、每單元的項目配額
（**加權而非平均攤**：常見或複雜的主題給多）、項目類型（`kinds`，通常 1–3 種）。
把總數算出來對一次：每章配額加總必須等於總數，否則建置直接失敗。

**2. 寫設定檔**——`$COURSE/course.config.json` 決定站台的一切，程式裡不寫死任何文案。
→ 欄位、schema、圖示、tone、詞彙模組：**`reference/config.md`**

**3. 策展影片**（最耗時，一定要並行）——一次一章，派獨立輸出路徑的 subagent。
用 `yt-dlp --flat-playlist` 搜尋，一次就拿到 id／秒數／觀看數／頻道／標題，
挑片與中繼資料出自同一次 API 回應。
→ agent 指示範本、oEmbed 驗證、資料格式、多語言：**`reference/curating.md`**

**4. 補真實中繼資料**——第 3 步沒順手寫出來（或事後換過片）就補跑一次
`yt-dlp --batch-file`，把 `{videoId: {status, seconds, views, channel, title}}` 寫進
`$COURSE/data/video-meta.json`，建置時覆寫長度、頻道與觀看數。
**不要用瀏覽器裡的 innertube**——那是備案，而且它的 `playabilityStatus: OK` 不代表可嵌入。

**5. 加上可查證的深度**（選用但強烈建議）——這是策展課程跟收藏清單的差別。
→ 單元層級與類別層級實證、PubMed 用法：**`reference/evidence.md`**

**6. 稽核與驗證**——兩道獨立關卡，缺一不可。
→ 檢查項目、門檻怎麼調、自我修正迴圈、踩過的坑：**`reference/quality.md`**

**7. 部署**——`make deploy`（Cloudflare Pages）。別忘了 `make og` 換社群預覽圖。

## 指令

全部都要帶 `COURSE=`（repo 裡只有一門課時可以省略）：

```bash
make new-course NAME=x   # 產生 courses/x/ 骨架，產出即可 make build
make courses             # 列出所有課程，以及現在會建哪一門
make build     # 合併資料 → dist/<課程名>/，配額不符會直接失敗
make audit     # 離線稽核：設定檔、配額、影片長度、實證深度（確定性，不打網路）
make verify    # 重驗每個影片連結與每個 PMID（打真實 API）
make serve     # 本機預覽
make icons     # 重新打包 Lucide 圖示（框架一份 + 這門課一份，需要網路）
make og        # 重新產生社群預覽圖
make check     # lint + build + test + audit，提交前跑這個
make deploy    # 部署到 Cloudflare Pages
```

`DIST` 預設 `dist/<課程名>`，所以多門課並存不會互相覆蓋產物。

## 驗收清單

交付前逐項確認：

- [ ] `make build` 通過，配額全數符合
- [ ] `make audit` 零錯誤，剩下的警告每一條都看過並能說明為什麼接受
- [ ] `make verify` 100% 通過，無失效連結、無捏造引用
- [ ] 每個單元都有可操作的 `assessment`（不只是描述問題）
- [ ] 找不到合格影片的格子誠實留空，`note` 寫清楚查過什麼、為什麼不合格
- [ ] 證據分級照實填，不美化
- [ ] 首頁三個數字（單元/影片/去重）互相對得上
- [ ] 手機與寬螢幕都沒有水平溢出
- [ ] `og.png` 已更新成新主題
- [ ] `discussions` 指向**這門課自己的 repo**，且 giscus API 回的是
      `Discussion not found` 而不是 `giscus is not installed`
- [ ] 品牌圖示、篩選籤、項目名詞都跟著設定檔走，沒有留下上一個主題的字樣
      （見 `reference/quality.md` 的「換主題時最容易漏掉的」）
