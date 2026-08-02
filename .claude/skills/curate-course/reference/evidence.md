# 可查證的深度

這是策展課程跟隨手收藏清單的差別。兩個層級，都可以只做一個或都不做。

**整個不做也是合法的。** 語言、樂器、軟體操作這類技能課，主張多半不是可實證的經驗命題，
硬掛文獻只會生出湊數的引用。這時候把 `course.config.json` 的 `grades` 整組拿掉即可——
稽核會據此判斷「這門課沒有實證維度」，不再提示缺實證。連帶把 `stance`、`evidenceAlias`、
`ui.evidenceRows` 與 `ui.stats` 裡的 `evidence_checked` 一起移除，網站就完全不會出現實證欄位。

## 單元層級

每個主題的整體證據強度、常見迷思、就醫警訊。體態課用 OpenEvidence 查了 24 個問題，
結果寫進 `$COURSE/data/oe-*.json`：

```json
{ "conditions": [{
  "unit": "ch5-u1",
  "name": "主題名稱",
  "evidence_grade": "contested",
  "summary": "…",
  "pain_link": "…", "intervention": "…", "assessment_validity": "…",
  "red_flags": ["…"],
  "caveats": "課程須誠實告知的部分",
  "citations": [{ "pmid": "…", "title": "…", "url": "…", "year": 2020 }]
}]}
```

顯示哪些欄位、標題叫什麼，由 config 的 `ui.evidenceRows` 決定；`evidence_grade` 必須是
`grades[].id` 之一。不屬於任何章節的 `concept-*` 會被抽出來當首頁的立場聲明。

## 類別層級

個別項目通常沒有專屬文獻（「臀橋」沒有自己的 RCT，「臀肌訓練」才有）。先把項目歸納成
數十個類別（`$COURSE/taxonomy/drills.py` 的 `classify()`），再為每個類別找文獻，
寫進 `$COURSE/data/drill-evidence-*.json`：

```json
{ "categories": [{
  "id": "foam-roll", "name": "類別名稱", "evidence_grade": "contested",
  "summary": "2–4 句：實際效果與限制",
  "citations": [{ "pmid": "31473878", "title": "", "journal": "", "year": 2019,
                  "design": "meta-analysis", "takeaway": "關鍵發現，含效果量更好" }]
}]}
```

## 證據分級要撐得住底下的引用

`evidence_grade` 本來是純粹的宣稱：說 `strong` 就是 `strong`，掛三篇敘述性回顧也沒人管。
在 `course.config.json` 加上 `evidence` 區塊，它就變成可驗證的：

```jsonc
"evidence": {
  // 這門課的證據階梯。名稱由你定，數字越小越強。
  "designTiers": { "meta-analysis": 1, "systematic review": 1, "RCT": 2,
                   "cohort": 3, "cross-sectional": 4, "narrative review": 5 },
  // 每個分級最低要有一篇第幾層以上的設計撐著。對不上是**錯誤**。
  "gradeRequires": { "strong": 1, "moderate": 2 },
  // 高分級的最新一篇引用最多可以多舊（年）。只警告。
  "maxAgeYears": { "strong": 12, "moderate": 18 },
  // 這些分級必須寫出爭議在哪（caveats 或 summary 擇一）
  "requireCaveats": ["contested"], "minCaveatChars": 40
}
```

**框架不預設任何一套階梯，整組不寫就整組不檢查**（但稽核會明講「沒檢查」，
不會靜靜通過）。理由見下一節。

`design` 不必手寫：`make verify ARGS=--fix` 會用 **PubMed 自己標的 publication type**
覆蓋掉手寫的值。階梯的底層因此從「agent 的宣稱」變成「可覆核的事實」。

## 非生醫主題怎麼定階梯

生醫的「統合分析 > RCT > 佇列」套到別的領域是錯的。幾個起點：

| 領域 | 階梯（1 最強） |
|---|---|
| 生醫、運動科學、復健 | 統合分析／系統性回顧 → RCT → 佇列／病例對照 → 橫斷 → 敘述性回顧 |
| 行為科學、生產力、學習方法 | 統合分析 → 隨機田野實驗 → 實驗室實驗 → 長期追蹤問卷 → 橫斷問卷 → 個案 → 專家意見 |
| 工程、軟體實務 | 系統性回顧 → 受控實驗 → 大規模觀測研究 → 案例研究 → 經驗報告 |
| 技藝、樂器、語言 | 多半**不要用這一層**。把 `grades` 整組拿掉比硬掛文獻誠實 |

兩個原則：

1. **階梯要反映該領域真實的證據生態。** 生產力研究裡「隨機田野實驗」已經是天花板，
   要求統合分析等於要求一個不存在的東西，結果是逼出捏造的引用。
2. **「專家意見」在某些領域是合理的最高層**（例如尚無實證傳統的手藝），
   但那時候就不該用 `strong` 這種字眼。分級的名字也要跟著領域走。

## 識別碼怎麼取：先確認你的主題在哪個資料庫

**PubMed 只收生醫。** 邏輯學、論證理論、倫理學、科學哲學的期刊幾乎完全不在裡面——
`Informal Logic`、`Argumentation`、`Synthese`、`Ethics`、`Philosophy of Science` 查了都是空的。
在這些主題硬要 PMID，只會逼出捏造的引用。

| 主題 | 用什麼 | 識別碼 |
|---|---|---|
| 生醫、運動科學、復健、營養 | PubMed E-utilities | PMID |
| 邏輯、論證、倫理、哲學、人文社科 | Crossref | DOI |

選 DOI 不只是「PubMed 沒有所以退而求其次」：**DOI 是 Humanities Source (EBSCO) 這類
全文資料庫共用的識別碼**，所以同一筆引用既能在 Crossref 公開驗證（任何人都查得到，
不需要訂閱），又能讓有機構訂閱的讀者直接在 EBSCO 開全文。PMID 做不到後者。

### PMID 怎麼取

一律用 PubMed E-utilities，**不可自行填寫標題**：

```bash
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&term=<查詢>"
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=<PMIDs>"
```

`make verify` 會重打一次 esummary，比對每筆宣稱的標題與 PMID 對不對得上。
`make audit` 只查格式（純數字、6–9 位）與每類的篇數下限——真偽只有打 API 才算數。
`python3 src/build/verify_refs.py --fix` 可以直接用 API 回傳值覆寫 title/journal/year。

### DOI 怎麼取

Crossref 不需要金鑰，但**請在 User-Agent 帶上聯絡信箱**（`mailto:`），
那是它們的 polite pool，沒帶會被降速：

```bash
UA='curate-course/1.0 (mailto:you@example.com)'

# 搜尋
curl -s -A "$UA" "https://api.crossref.org/works?rows=5&select=DOI,title,container-title,issued,type&query.bibliographic=<查詢>"

# 逐筆反查（等同 esummary 的角色）
curl -s -A "$UA" "https://api.crossref.org/works/10.22329/il.v37i1.4696"
```

回傳的 `message.title[0]` / `message.container-title[0]` / `message.issued.date-parts[0][0]`
分別對應 title / journal / year，一律用 API 回傳值填，不可自己打。

citation 寫 `doi` 而不是 `pmid`，`url` 用 `https://doi.org/<DOI>`：

```json
{ "doi": "10.22329/il.v37i1.4696", "title": "API 回傳的標題",
  "journal": "Informal Logic", "year": 2017,
  "url": "https://doi.org/10.22329/il.v37i1.4696",
  "design": "conceptual-analysis", "takeaway": "…" }
```

人文主題的 `design` 值也要換一組，`meta-analysis` / `rct` 在這裡沒有意義：
`conceptual-analysis` / `formal-proof` / `case-study` / `corpus-study` /
`experimental-philosophy` / `systematic-review`。

> `verify_refs.py` 兩種識別碼都驗：`pmid` 打 PubMed esummary、`doi` 打 Crossref，
> 一筆一筆比對回傳的標題。`--fix` 會用 API 回傳值覆寫 title/journal/year。

## 誠實比好看重要

如果查證結果顯示這個主題的主流說法證據薄弱，如實寫出來並標成 `contested`。
一門承認自己限制的課，比一門承諾一切的課可信得多——這也是這個框架把 `grades`
做成一等公民、把立場聲明放在首頁的原因。
