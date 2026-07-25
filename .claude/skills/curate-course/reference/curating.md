# 策展影片

最耗時的一步，一定要並行：一次一章，每個 subagent 給**獨立的輸出路徑與檔名前綴**，
否則會互相覆蓋。

## agent 指示要包含什麼

**品質門檻**——寫成明確清單，不要只說「找好的影片」：

- 優先頻道（列出具體名字）：具備專業背景的創作者、機構官方頻道
- 排除：內容農場、標題殺人（「7 天學會 X」）、播放數過低（< 5,000）、已下架
- 長度區間：教學影片 5–20 分鐘、跟練 1–8 分鐘
- 語言：可接受哪些語言，同等品質下的優先順序

**同一組數字要寫進 `course.config.json` 的 `audit` 區塊**。寫在 prompt 裡的門檻沒有人會複查，
寫進設定檔的 `make audit` 每次都查。

**驗證要求（最重要）**：

```bash
# 唯一可靠的程式化驗證方式
curl -s "https://www.youtube.com/oembed?url=<URL編碼的watch網址>&format=json"
# 200 + 標題頻道相符 = 存在且公開；401/404 = 已刪除或設為私人
```

明確告訴 agent：**video ID 一律取自實際的搜尋結果，不可憑記憶拼湊**。
找不到合格影片就把 `url` 設 `null` 並在 `note` 寫清楚查過什麼、為什麼都不合格——
留空比硬塞相關但不對題的更好，但**留空而沒有 `note` 會被 `make audit` 判為錯誤**。

## 輸出格式

寫進 `course/data/<source>.json`：

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

- `type` 對應 `ui.unitTypes`，`kind` 對應 `kinds[].id`——用了沒定義的值會被稽核擋下。
- `tight` / `weak` 是選用的兩欄對照（體態課放緊繃/無力肌群，其他主題可放
  「常見錯誤/該練的能力」，或整個不用）。
- `assessment` 要是**讀者可以自己做的判斷方法**，不是問題描述。
- 一個檔可以放多章：`{"chapters": [{"chapter": "CH1", "units": […]}, …]}`。

## 多語言

同一個單元想提供第二語言版本，另外寫進 `course/data/alt-lessons-<lang>.json`：

```json
{ "lessons": [{ "unit": "ch5-u1", "lang": "en", "title": "", "channel": "", "url": "", "why": "" }] }
```

替代版本會被驗證與補中繼資料，但**不計入課程總時長**（同一堂課不重複算）。

## 中繼資料

策展 agent 抄下來的長度常有 ±30 秒誤差。抓一次真的：在**真實 YouTube 分頁的 context 內**
呼叫 innertube API（直連會被擋），把結果寫進 `course/data/video-meta.json`：

```json
{ "IasNstQF6z8": { "status": "OK", "seconds": 520, "views": 20119,
                   "channel": "頻道名", "title": "影片標題" } }
```

建置時會用它覆寫長度、頻道與觀看數，總時長才會準；`make audit` 也靠它查長度區間與觀看數。
