# 策展影片

最耗時的一步，一定要並行：一次一章，每個 subagent 給**獨立的輸出路徑與檔名前綴**，
否則會互相覆蓋。

## 工具：yt-dlp，不是瀏覽器

挑片與抓中繼資料**是同一個動作**。`yt-dlp` 的搜尋模式一次就把選片需要的五個欄位全給你，
不需要瀏覽器、不需要 OAuth，headless 與 CI 都跑得動：

```bash
yt-dlp --no-update --flat-playlist \
  --print "%(id)s|%(duration)s|%(view_count)s|%(channel)s|%(title)s" \
  "ytsearch15:alternate nostril breathing tutorial"
```

```
8VwufJrUhic|658.0|1515015|Yoga With Adriene|Yoga Breathing | Alternate Nostril Breathing
Biry04x7rFM|132.0|159892|The Art of Living|How to do Alternate Nostril Breathing | …
gWIt5OoQDv8|389.0|36138|Vinyasa Yoga Ashram|Nadi Shodhana Pranayama: How to Do It, Steps and Benefits
…
```

這五個欄位剛好就是 `video-meta.json` 要的 `{seconds, views, channel, title}`，所以策展 agent
可以**在挑片的同一個動作裡**把中繼資料寫出來。這樣中繼資料保證不是憑記憶寫的——
它跟選片來自同一次 API 回應，`make audit` 的長度誤差（`driftSeconds`）會直接歸零。

### `--print` 的四個坑（每一個都實際踩過）

| 坑 | 怎麼處理 |
|---|---|
| `\t` **不會**變成 tab | `--print` 不解析跳脫序列，輸出的是字面上的反斜線加 t（`od -c` 看得到 `\  t`）。用 `\|` 之類的單一字元當分隔符 |
| **標題本身就含分隔符** | 上面第一筆的標題就有 `\|`。**把 `title` 排在最後一欄**，解析時限制切幾刀（Python `split("\|", 4)`）——前四欄不可能含分隔符 |
| `duration` 不是整數、也不一定有值 | `--flat-playlist` 回的是 `658.0` 這種浮點數，少數影片是 `NA`。一律 `int(float(x))`、`NA` 當 `0`，不要讓字串寫進 JSON |
| id 開頭是 `-` 就不能當參數傳 | `-2Qs85aPKgk` 這種 id 直接放命令列會被當成選項（`error: You must provide at least one URL`）。用 `--batch-file`，或加 `--` 分隔 |

`--flat-playlist` 的秒數與完整 extraction 可能差 1 秒（實測同一支 `658.0` vs `657`），
遠在 `driftSeconds: 30` 之內，不必特別處理。

### 限流的失敗形狀是 exit 0 + 空輸出

**這是這一頁最危險的一條。** 累積幾百次單片查詢之後，yt-dlp 會開始這樣回：

```bash
$ yt-dlp --skip-download --print "%(id)s|%(duration)s" "https://www.youtube.com/watch?v=<id>"
$ echo $?
0                # 成功。而且 stdout 是空的。
```

影片好好的（同一時間 oEmbed 回 200），只是單片 extraction 被限流——`--flat-playlist`
的搜尋在同一時間往往完全正常，休息一陣子單片查詢就自己好了。

任何「用 yt-dlp 逐一複查 ID，沒回東西就當作影片下架」的自製腳本，都會**靜靜地**把活著的
影片標成失效，而且跑得越久、規模越大殺得越多。所以：

- 自製腳本一定要**比對輸入 id 數與輸出行數**。少了就是限流，重跑，不是判死刑
- **影片存不存在只認 oEmbed**（`make verify` 用的就是它，方向是對的；要提醒的是策展階段
  自己寫的那些腳本）

## agent 指示要包含什麼

**品質門檻**——寫成明確清單，不要只說「找好的影片」：

- 優先頻道（列出具體名字）：具備專業背景的創作者、機構官方頻道
- 排除：內容農場、標題殺人（「7 天學會 X」）、播放數過低（< 5,000）、已下架
- 長度區間：教學影片 5–20 分鐘、跟練 1–8 分鐘
- 語言：可接受哪些語言，同等品質下的優先順序

長度與觀看數不必再叫 agent 目測——上面那條 `ytsearch` 指令的第 2、3 欄就是秒數與觀看數，
直接拿去過濾。

**同一組數字要寫進 `course.config.json` 的 `audit` 區塊**。寫在 prompt 裡的門檻沒有人會複查，
寫進設定檔的 `make audit` 每次都查。

**驗證要求（最重要）**：

```bash
# 唯一可靠的程式化驗證方式
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://www.youtube.com/oembed?url=https%3A//www.youtube.com/watch%3Fv%3D<VIDEO_ID>&format=json"
# 200 = 存在、公開、而且允許嵌入
# 401 = 不允許嵌入或已設為私人   404 = 已刪除或網址錯誤
```

**能播 ≠ 能嵌入。** 上課模式整個是 `youtube-nocookie.com` 的 iframe，不允許嵌入的影片在
網站上就是一塊死掉的播放器。而 yt-dlp 與 innertube 都只回答「這支影片能不能播」：

```bash
$ yt-dlp --skip-download --print "%(id)s|%(duration)s|%(channel)s" "3n4oD9jSlxU"
3n4oD9jSlxU|441|Daniel Sih          # 中繼資料一應俱全，看起來完全正常

$ curl -s -o /dev/null -w "%{http_code}\n" \
    "https://www.youtube.com/oembed?url=https%3A//www.youtube.com/watch%3Fv%3D3n4oD9jSlxU&format=json"
401                                  # 但它不允許嵌入
```

innertube 也一樣：它的 `playabilityStatus: OK` 只回答「這支影片能不能播」，不回答
「能不能在你的網站上嵌入」。曾經有一批 180 支全部回 `OK`、`videoDetails` 也都拿得到，
`make verify` 照樣擋下其中一支。

所以：**可嵌入與否只有 `verify_links.py` 的 oEmbed 檢查算數**，補完中繼資料不能跳過
`make verify`。

明確告訴 agent：**video ID 一律取自實際的搜尋結果，不可憑記憶拼湊**。
找不到合格影片就把 `url` 設 `null` 並在 `note` 寫清楚查過什麼、為什麼都不合格——
留空比硬塞相關但不對題的更好，但**留空而沒有 `note` 會被 `make audit` 判為錯誤**。

## 輸出格式

寫進 `$COURSE/data/<source>.json`：

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

同一個單元想提供第二語言版本，另外寫進 `$COURSE/data/alt-lessons-<lang>.json`：

```json
{ "lessons": [{ "unit": "ch5-u1", "lang": "en", "title": "", "channel": "", "url": "", "why": "" }] }
```

替代版本會被驗證與補中繼資料，但**不計入課程總時長**（同一堂課不重複算）。

## 中繼資料

策展階段沒有順手寫出中繼資料（或事後換過片）的話，用 `--batch-file` 一次補齊全部。
不需要瀏覽器、不需要 innertube，一個指令跑完數百支：

```bash
# 1. 從策展資料撈出所有 video id
python3 - "$COURSE/data" > ids.txt <<'PY'
import glob, re, sys
ids = set()
for f in glob.glob(f"{sys.argv[1]}/*.json"):
    ids |= set(re.findall(r"[?&]v=([\w-]{11})", open(f).read()))
print("\n".join(sorted(ids)))
PY

# 2. 一個指令抓完（batch-file 吃裸 id，不必是完整網址）
yt-dlp --no-update --cookies-from-browser chrome --ignore-no-formats-error \
  --skip-download --batch-file ids.txt \
  --print "%(id)s|%(duration)s|%(view_count)s|%(channel)s|%(title)s" > meta.txt

# 3. 轉成 video-meta.json
python3 - meta.txt "$COURSE/data/video-meta.json" <<'PY'
import json, sys
num = lambda s: int(float(s)) if s.replace(".", "", 1).isdigit() else 0
out = {}
for line in open(sys.argv[1]):
    if not line.strip():
        continue
    vid, dur, views, channel, title = line.rstrip("\n").split("|", 4)
    out[vid] = {"status": "OK", "seconds": num(dur), "views": num(views),
                "channel": channel, "title": title}
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print(f"{len(out)} 支寫入 {sys.argv[2]}")
PY
```

兩個旗標都不是裝飾：

- `--cookies-from-browser chrome`：**連抓數百支一定要加**，否則會收到
  「Sign in to confirm you're not a bot」，看起來像影片失效，其實是被擋
- `--ignore-no-formats-error`：少數影片沒有可下載的 format，加了才拿得到中繼資料

產出的 schema 直接對得上：

| yt-dlp | `video-meta.json` |
|---|---|
| `id` | key |
| `duration` | `seconds` |
| `view_count` | `views` |
| `channel` | `channel` |
| `title` | `title` |

```json
{ "IasNstQF6z8": { "status": "OK", "seconds": 520, "views": 20119,
                   "channel": "頻道名", "title": "影片標題" } }
```

建置時會用它覆寫長度、頻道與觀看數，總時長才會準；`make audit` 也靠它查長度區間與觀看數。

這一步順帶是一次粗篩：**輸出行數少於輸入 id 數就要查**。但記得上面那條——少掉的可能是
限流不是下架，最終判定交給 `make verify` 的 oEmbed。

### 備案：innertube

yt-dlp 真的用不了（沒裝、被整個擋掉）時，可以在**真實 YouTube 分頁的 context 內**呼叫
innertube API（直連會被擋）。這是備案，不是主流程：它需要一個真的瀏覽器、一個真的分頁、
在該分頁 context 裡跑 JS，是整條流程裡最脆弱的一步。而且它回的 `playabilityStatus: OK`
只代表可播，不代表可嵌入（見上面的 oEmbed 段落）。
