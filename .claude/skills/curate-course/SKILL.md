---
name: curate-course
description: Use when building a curated video course website from YouTube — picking and verifying videos, organising them into chapters/units, attaching evidence or references, and shipping a static site with good SEO. Topic-agnostic; works for anatomy, cooking, guitar, statistics, welding, anything with good YouTube coverage.
---

# 策展一門 YouTube 課程

這個 repo 是一個 **topic-agnostic 的課程策展框架**。你的工作是產出 `course/` 底下的資料，
框架負責建置、稽核、驗證、SEO 與部署。`course/` 現成的體態矯正課是範例，換主題時整個換掉。

## 鐵則

1. **策展不是生成。** video ID 一律取自實際搜尋結果，PMID 一律取自 PubMed API。
   捏造一個看起來合理的 ID 比留空更糟。
2. **留空要說明。** 找不到合格影片就 `url: null` + `note` 寫清楚查過什麼、為什麼不合格。
3. **不信任任何上游宣稱**，包括自己剛才說已經驗證過的。交付前一定跑 `make audit` 與 `make verify`。
4. **誠實比好看重要。** 查證結果對課程不利就照實寫，標成 `contested`。

## 全景

```
course/
  course.config.json   ← 站台設定、章節、配額、品質門檻、所有 UI 文案
  data/                ← 你要產出的策展資料
  taxonomy/            ← 選用：主題專屬的詞彙模組
src/                   ← 框架，換主題時不用動
dist/                  ← 建置產物
```

只改 `course/`。改完 `make build && make audit && make serve`。

## 流程

**1. 先把結構談清楚**——不要一開始就找影片。確定主題與受眾、章節與單元、每單元的項目配額
（**加權而非平均攤**：常見或複雜的主題給多）、項目類型（`kinds`，通常 1–3 種）。
把總數算出來對一次：每章配額加總必須等於總數，否則建置直接失敗。

**2. 寫設定檔**——`course/course.config.json` 決定站台的一切，程式裡不寫死任何文案。
→ 欄位、schema、圖示、tone、詞彙模組：**`reference/config.md`**

**3. 策展影片**（最耗時，一定要並行）——一次一章，派獨立輸出路徑的 subagent。
→ agent 指示範本、oEmbed 驗證、資料格式、多語言：**`reference/curating.md`**

**4. 補真實中繼資料**——策展抄下來的長度常有誤差。在**真實 YouTube 分頁的 context 內**
呼叫 innertube API，把 `{videoId: {status, seconds, views, channel, title}}` 寫進
`course/data/video-meta.json`，建置時覆寫長度、頻道與觀看數。

**5. 加上可查證的深度**（選用但強烈建議）——這是策展課程跟收藏清單的差別。
→ 單元層級與類別層級實證、PubMed 用法：**`reference/evidence.md`**

**6. 稽核與驗證**——兩道獨立關卡，缺一不可。
→ 檢查項目、門檻怎麼調、自我修正迴圈、踩過的坑：**`reference/quality.md`**

**7. 部署**——`make deploy`（Cloudflare Pages）。別忘了 `make og` 換社群預覽圖。

## 指令

```bash
make build     # 合併資料 → dist/，配額不符會直接失敗
make audit     # 離線稽核：設定檔、配額、影片長度、實證深度（確定性，不打網路）
make verify    # 重驗每個影片連結與每個 PMID（打真實 API）
make serve     # 本機預覽
make icons     # 重新打包 Lucide 圖示
make og        # 重新產生社群預覽圖
make check     # lint + build + audit，提交前跑這個
make deploy    # 部署到 Cloudflare Pages
```

多課程並存：`COURSE=courses/guitar DIST=dist-guitar make build`

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
