# 可查證的深度

這是策展課程跟隨手收藏清單的差別。兩個層級，都可以只做一個或都不做。

## 單元層級

每個主題的整體證據強度、常見迷思、就醫警訊。體態課用 OpenEvidence 查了 24 個問題，
結果寫進 `course/data/oe-*.json`：

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
數十個類別（`course/taxonomy/drills.py` 的 `classify()`），再為每個類別找文獻，
寫進 `course/data/drill-evidence-*.json`：

```json
{ "categories": [{
  "id": "foam-roll", "name": "類別名稱", "evidence_grade": "contested",
  "summary": "2–4 句：實際效果與限制",
  "citations": [{ "pmid": "31473878", "title": "", "journal": "", "year": 2019,
                  "design": "meta-analysis", "takeaway": "關鍵發現，含效果量更好" }]
}]}
```

## PMID 怎麼取

一律用 PubMed E-utilities，**不可自行填寫標題**：

```bash
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&term=<查詢>"
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=<PMIDs>"
```

`make verify` 會重打一次 esummary，比對每筆宣稱的標題與 PMID 對不對得上。
`make audit` 只查格式（純數字、6–9 位）與每類的篇數下限——真偽只有打 API 才算數。
`python3 src/build/verify_refs.py --fix` 可以直接用 API 回傳值覆寫 title/journal/year。

## 誠實比好看重要

如果查證結果顯示這個主題的主流說法證據薄弱，如實寫出來並標成 `contested`。
一門承認自己限制的課，比一門承諾一切的課可信得多——這也是這個框架把 `grades`
做成一等公民、把立場聲明放在首頁的原因。
