# 外部資料庫 API — 設計

2026-08-04

> 這是**框架文件**，不屬於任何一門課。談的是「驗證引用與影片時，該打哪些
> 外部資料庫、憑證怎麼管、沒有憑證時怎麼辦」。

## 要解決的問題

`verify_refs.py` 與 `verify_links.py` 是這個框架最後一道關卡：不信任任何上游
宣稱，一律重打真實 API。但這兩支腳本目前都在**匿名**呼叫外部服務，於是有三個
問題疊在一起：

**一、被限速拖慢。** NCBI 無金鑰是 3 req/s，所以 `verify_refs.py` 裡到處是
`time.sleep(0.4)`、三次退避重試、`fetch` 失敗就整批放棄。`make verify` 要跑
30 分鐘，於是它只能排每週——而「每週」的意思是改壞了最多七天才知道。

**二、有一個從沒生效過的設定。** `verify_refs.py` 早就在讀 `CROSSREF_MAILTO`，
但 `.env.example` 沒有這一項、workflow 也沒傳，所以它永遠是
`curate-course@example.com`。Crossref 的 polite pool 從來沒有啟用過。

**三、DOI 那條路的撤稿偵測是空的。** 見下一節——這是實測才發現的，也是這次
改動裡唯一真正補洞的部分。

## 實測：四個資料庫對同一篇撤稿論文的回答

拿 Wakefield 1998（PMID 9500320 / DOI `10.1016/S0140-6736(97)11096-0`，公認
已撤稿）四方對打：

| 來源 | 回答 |
|---|---|
| PubMed esummary | ✅ `pubtype` 含 `Retracted Publication` |
| Europe PMC | ✅ 同上；`commentCorrectionList` 回的是 "Comment in"，**與撤稿無關** |
| Crossref | ❌ `update-to: null`、`relation: {}`，只有 title 前面加了 `RETRACTED:` |
| OpenAlex | ✅ `is_retracted: True` |

兩個結論直接改寫了原本的計畫：

**`verify_refs.py` 的 DOI 撤稿偵測形同虛設。** 那段程式碼（`update-to` 裡找
`type == "retraction"`）對這篇完全沒反應。走 PMID 的 469 筆有 PubMed 擋著，
走 DOI 的 25 筆等於沒有保護。補得起來的只有 OpenAlex 的 `is_retracted`。

**Europe PMC 沒有比 esummary 強。** 原本以為它的 `commentCorrectionList` 能
補 preprint 撤稿，實測那個欄位裝的是評論往來。它降級成單純的 NCBI fallback。

順帶一條零成本規則：Crossref 的 title 以 `RETRACTED:` / `WITHDRAWN:` 開頭時
直接判撤稿。現在這種情況會被報成「標題與識別碼不符」——訊息是對的，但人讀
不出真正的死因，於是會去「修正」標題，把撤稿的證據親手抹掉。

第二個實測結論，關於開放取用：同一個 DOI（`10.1001/jama.2022.22625`），
Unpaywall 回 `is_oa: true` 並給出 PMC 全文連結，OpenAlex 的
`best_oa_location` 卻是 `None`。**OA 狀態只信 Unpaywall**，OpenAlex 只取
`cited_by_count`。

## 六個資料庫的角色

| 資料庫 | 憑證 | 用途 | 缺憑證時 |
|---|---|---|---|
| NCBI E-utilities | `NCBI_API_KEY` | 現有驗證，3 → 10 req/s | 退回 3 req/s，行為不變 |
| Crossref | `CROSSREF_MAILTO` | 現有驗證 + `RETRACTED:` 前綴判撤稿 | 退回共用池（今天的現況） |
| OpenAlex | `OPENALEX_MAILTO` | **`is_retracted` 硬失敗** + `cited_by` 只報告 | 免金鑰即可用，仍然跑 |
| Unpaywall | `UNPAYWALL_EMAIL` | `oa_url` 寫回資料檔 | 整段跳過 |
| Europe PMC | 無 | NCBI 連續失敗時的 fallback | — |
| YouTube Data API | `YOUTUBE_API_KEY` | `embeddable` / `regionRestriction` / `duration` | 退回 oEmbed |

全部六個都免費。`CROSSREF_MAILTO`、`OPENALEX_MAILTO`、`UNPAYWALL_EMAIL` 三個
其實只要一個能收信的位址，不需要註冊流程；`NCBI_API_KEY` 與 `YOUTUBE_API_KEY`
要走各自的後台。逐步流程寫在 `.env.example`，不在這裡重複。

## 鐵律：缺憑證只降級，永不硬失敗

GitHub Actions 在 **fork 來的 PR** 上拿不到 repository secrets。如果任何一支
腳本在缺憑證時 exit 1，外部貢獻者的 PR 會一律紅掉，而且錯誤訊息會指向一個
他們根本無權取得的東西。

所以每一個外部來源都必須有兩條路徑：有憑證走快的，沒憑證走今天已經在跑的那條。
`make verify` 沒有憑證時的行為，必須跟這次改動之前**逐字元相同**。

這條鐵律也順帶回答了「那 Unpaywall 呢？」——它沒有降級路徑可走（今天根本沒有
OA 連結這件事），所以缺 `UNPAYWALL_EMAIL` 時整段跳過，不報錯、不警告。

## 資料的保鮮期決定它寫不寫回資料檔

`verify_refs.py --fix` 現有的模式是打 API 然後覆寫回 `course/data/*.json`：
`design` 就是這樣從「策展 agent 手寫的宣稱」變成「PubMed 標的可覆核事實」。

新資料要不要走同一條路，看它會不會過期：

- **`oa_url` 寫回。** 一篇論文的開放取用狀態幾乎不倒退，寫進資料檔是淨賺——
  學習者點得到免費全文，而不是撞上付費牆。
- **`cited_by` 只印在 `make verify` 的輸出裡，不寫回。** 被引用次數三個月就
  變了。寫進 repo 等於種一個會慢慢變錯、又沒有任何檢查會抓到的數字——這跟
  當初手寫 `design` 是同一類問題，只是錯誤來自時間而不是人。
- **`duration` 只核對，不寫回。** 它拿 YouTube 回報的真實長度去對資料檔裡
  宣稱的長度。`make audit` 早就在稽核影片長度，但那是拿資料檔裡的數字自己跟
  自己比——被比的那個數字從來沒有被驗證過。

## 影片：YouTube Data API 取代 oEmbed

`verify_links.py` 現在打 oEmbed 看 HTTP 狀態碼，靠 401/403/404 反推死因。
它的註解自己承認兩件事：401 有兩種處置完全不同的成因（設為私人 vs 禁止嵌入）
分不出來，以及 oEmbed 回 200 並不保證允許嵌入，要另外跑 `yt-dlp` 才知道。

`videos.list?part=status,contentDetails` 一次回 `uploadStatus`、
`privacyStatus`、`embeddable`、`regionRestriction`、`duration`，歧義當場消失。
配額上，一次查 50 支 id 算 1 unit，344 支影片只花 7 units，日配額 10000。

順帶一提請求數：344 次併發 HTTP 變成 7 次批次。

## 不做的事

- **不動 `audit.py`。** 它是離線且確定性的，`make check` 每個 PR 都要跑。
  把網路呼叫放進去等於讓 CI 隨外部服務的心情變紅。實證來源的驗證屬於
  `make verify` 那一層。
- **不加 Semantic Scholar。** 它能給的（引用數、tldr）與 OpenAlex 重疊，
  多一把金鑰換不到新的檢查能力。
- **不碰 `course.schema.json`。** 它驗的是 `course.config.json`，本來就不含
  citations；`build.py` 也不碰 citations（整包透傳）。`oa_url` 只需要動
  資料檔與 `render.js`。
