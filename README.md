# 體態矯正課程

一門從頭到腳的體態自學課程網站。十二個章節、371 個單元，涵蓋頸椎到足踝的
24 個常見體態問題。每個問題給三件事：**怎麼自己評估**、**該練什麼**、
以及**這套說法在醫學文獻裡站不站得住腳**。

## 這門課和別的體態課差在哪

差在第三件事。

課程裡的 24 個體態問題加上 3 個核心觀念，全部丟給 OpenEvidence 查證過，
結果原封不動寫進網站，包括對課程自己不利的部分：

| 分級 | 題數 | 意思 |
|---|---|---|
| 證據充分 strong | 2 | 有硬證據支持 |
| 證據中等 moderate | 8 | 有關聯，方法學有限制 |
| 證據有限 limited | 8 | 主要是臨床經驗與理論模型 |
| 證據互斥 contested | 9 | 文獻結論與坊間說法相衝突 |

被判為 contested 的包括圓肩、骨盆前傾、腰椎過度前拱、X 型腿、假胯寬、
肱骨前移、股骨前移——也就是體態課最愛賣的那幾個題目。

三個核心觀念的查證結果（首頁「這門課的立場」）：

1. **靜態體態與疼痛的因果關係沒有共識**。Swain 2020 涵蓋 41 篇系統性回顧的
   傘狀回顧明確結論如此。腰痛相關的甚至是前凸「減少」而非過大，與坊間教法方向相反。
2. **Janda 交叉症候群沒有被驗證**。沒有 EMG／影像研究能重現他描述的緊繃-無力配對，
   沒有 ICD 碼、沒有診斷準則、沒有任何評分者間信度資料。
3. **矯正運動有效，但不是因為它把體態調正了**。對線確實會變（顱椎角 8 週 6–7°），
   但沒有任何中介分析證明對線改變導致止痛；頭對頭試驗中矯正運動不優於一般運動。

結論不是「別練」，而是：運動的價值在肌力、負荷耐受度與不適感改善，
體態數值的變化是伴隨現象，不是療效機轉。

## 結構

| Part | 內容 | 單元 |
|---|---|---|
| Part 1 | CH0–CH11 主課教學影片 | 37 |
| Part 2 | 跟練影片（🔵放鬆／🟢拉伸／🔴訓練） | 334 |

跟練影片依久坐族盛行率與涉及肌群數加權分配，不是平均攤。
頭前伸、駝背、圓肩、骨盆前傾各 17–18 支；軍人頸、胸椎過直、垂肩、上X下O 各 9 支。

37 堂主課中有 **35 堂備有繁中／英文兩個版本**可切換（連同替代版本共 406 支影片連結）。
剩下兩堂是「假胯寬」與「股骨前移」——前者英文沒有對應診斷、後者繁中沒有合格內容，
留空而不硬湊。

## 四個檢視

- **首頁**（點 header 的品牌）— 三步驟用法、立場摘要、十二章總覽、開始的入口。
- **課程內容** — 章節樹、自我評估、肌群標籤、跟練清單、實證註記。
  點任何影片會切到上課模式站內播放（⌘/Ctrl+click 仍照常開新分頁）。
- **上課模式** — 左側嵌入播放（走 `youtube-nocookie.com`），右側 406 支播放清單。
  滿版高度、欄寬可用握把拖曳、可搜尋、可只看未完成，支援 `?tab=player&play=12` 深連結。
- **這門課的立場** — 三題核心觀念的完整查證結果與原始文獻。

側欄可**依肌群篩選**：58 個標準化肌群依部位分組，點下去就篩出所有涉及該肌群的單元與動作。
動作內的肌群標籤也可直接點。

**鍵盤快捷鍵**（按 `?` 叫出說明）：iframe 跨域，所以播放控制走 YouTube IFrame Player API
的 `postMessage`——`Space`/`K` 播放暫停、`J`/`L` ±10 秒、`M` 靜音、`F` 全螢幕、
`0–9` 跳段、`Shift+N`/`Shift+P` 切換課程影片。

## 動作類別的 PubMed 文獻

334 支跟練影片歸納成 **55 個動作類別**（單一動作沒有專屬文獻，「臀橋」沒有自己的 RCT，
有的是「臀肌活化訓練」的文獻）。每個類別配 5–8 篇 PubMed 文獻，共 **423 篇**，
以單元層級的折疊區塊呈現。

同樣照實寫：`ball-release`（按摩球放鬆）、`trigger-point`（激痛點）、`tva-activation`
（腹橫肌啟動）都被標為 **contested**。

## 開發

Python 環境用 [uv](https://docs.astral.sh/uv/) 管理；建置腳本只用標準庫，
沒有執行期相依，`uv run` 會自動處理虛擬環境。

```bash
make            # 列出所有指令
make build      # data/*.json → public/course.json（含配額驗證 + SEO 產出）
make serve      # 本機預覽 http://localhost:8899
make verify     # 重驗所有影片連結與 PubMed 引用（打真實 API）
make icons      # 重新下載 Lucide 圖示並打包
make og         # 重新產生社群預覽圖
make lint       # ruff 檢查
make check      # lint + build，提交前跑這個
make deploy     # 建置後部署到 Cloudflare Pages
```

`build.py` 會擋下配額不符的建置，並自動：套用 YouTube 實際 metadata（時長／頻道／觀看數）、
正規化肌群、分類動作、合併文獻、注入 JSON-LD。

### 兩個獨立的查核關卡

不信任任何上游宣稱（包含 agent 自稱已驗證），兩支腳本都重打原始 API：

- `verify_links.py` — YouTube oEmbed。被刪除／私人／不可嵌入的影片會被抓出來，
  `--prune` 可自動標記為待補。
- `verify_refs.py` — PubMed esummary。捏造的 PMID 或對不上的標題會被退回，
  `--fix` 可用 API 回傳值覆寫。

目前狀態：**344 個影片連結 100% 有效**、**365 個 PMID 100% 存在且標題相符**，
且無任何一篇引用是被撤稿的研究。

> 三個踩過的坑：`WebFetch` 直接打 `youtube.com/watch` 會被 Google 擋成 captcha；
> 無 cookie 的 `yt-dlp` 會誤報影片失效（實測有一支被誤殺的其實正常）；
> innertube API 直連會回 ERROR，必須在真實 YouTube 頁面 context 內呼叫才拿得到 metadata。

## 檔案

```
pyproject.toml       uv 專案設定與 ruff 規則
Makefile             所有常用指令
build.py             合併、配額驗證、metadata 套用
muscles.py           肌群名稱正規化與部位分組
drills.py            動作類別定義與比對規則
seo.py               JSON-LD / sitemap / robots / llms.txt
build_icons.py       Lucide sprite 打包
verify_links.py      影片連結存活驗證
verify_refs.py       PubMed 引用真實性驗證
data/
  ch*.json           各章影片與動作資料
  alt-lessons-*.json 主課的其他語言版本
  oe-*.json          OpenEvidence 查證結果（24 個體態問題 + 3 個核心觀念）
  drill-evidence-*.json  動作類別的 PubMed 文獻
  video-meta.json    YouTube 實際 metadata（時長／頻道／觀看數）
public/
  index.html
  course.json        建置產物
  og.png             社群預覽圖（由 tools/og.html 以 headless Chrome 產生）
  css/               tokens / layout / course / evidence / stance / tabs / player / landing
  js/
    icons.js         Lucide sprite（建置時內嵌，零外部請求）
    render.js        資料 → DOM（含首頁與立場頁）
    filters.js       搜尋、類型、肌群篩選
    player.js        上課模式：播放清單、嵌入播放、欄寬拖曳
    keys.js          YouTube IFrame API 快捷鍵
    app.js           載入、分頁、互動、進度追蹤
docs/
  VIDEO_SPEC.md      影片策展規格（品質門檻與驗證要求）
```

## 設計

視覺語彙取自 [Primer](https://primer.style/)，用 CSS 變數自行實作而非引入套件，
所以沒有任何外部請求。深淺色主題都支援，跟隨系統偏好、可手動覆寫。
圖示為 [Lucide](https://lucide.dev/icons/)（ISC），建置時打包成 SVG sprite 內嵌。

進度追蹤存在 localStorage，不上傳任何資料，沒有帳號、沒有後端。

## 免責

本課程為衛教與運動指引，**不構成醫療診斷或治療建議**。持續疼痛、麻木、無力、
外傷史，或體態不對稱短期內明顯惡化，請先看醫師或物理治療師。

實證註記反映查詢當下的文獻狀態，不等於臨床指引。影片版權歸原 YouTube 頻道所有，
本站僅提供連結。

## 授權

程式碼採 MIT，見 [LICENSE](LICENSE)。**影片著作權屬原 YouTube 頻道**，本專案只存
連結與公開中繼資料，不重製也不代管。Lucide 圖示為 ISC，PubMed 與 OpenEvidence
引用的文獻著作權屬各出版者。
