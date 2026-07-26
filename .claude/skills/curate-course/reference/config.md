# 設定檔

`course/course.config.json` 決定站台的一切。程式裡沒有一個字是寫死的——分頁名稱、篩選標籤、
統計欄位、證據分級的顯示文字，全部從這裡讀。

## 關鍵欄位

| 欄位 | 作用 |
|---|---|
| `site` | 標題、描述、網址、語系、關鍵字 → 直接餵給 SEO 與 JSON-LD |
| `hero` | 首頁大標與說明，可用 `{units}` `{problems}` 佔位 |
| `ui` | **所有介面文案**。分頁名、篩選標籤、統計欄位、實證欄位標題、單元型別 |
| `kinds` | 項目類型與配色（`id` / `label` / `tone`），至少一種 |
| `grades` | 證據分級（沒有實證維度就整組刪掉） |
| `chapters` | 章節碼、標題、Lucide 圖示、資料來源檔、配額 |
| `nav` | 側欄的章節分組。**必須不多不少涵蓋所有章節** |
| `evidenceAlias` | unit id → 實證資料的 key，用在共用同一份查核的單元 |
| `taxonomy` | 選用的詞彙模組（見下） |
| `audit` | **品質門檻** → `make audit` 照這裡檢查（見 `quality.md`） |
| `counter` | 選用：header 的累計瀏覽次數徽章（Pages Function + D1）。整組拿掉就不顯示，也完全不打 API |
| `discussions` | 選用：giscus 設定，每支影片一串 GitHub Discussions。整組拿掉就沒有討論面板。**換主題必換 `repo`/`repoId`/`categoryId`**，否則留言會靜靜掉到上一個主題的 repo |
| `landing` / `stance` / `footer` / `llms` | 首頁、立場頁、頁尾、`llms.txt` 的文案 |

## Schema

欄位結構定義在 `src/build/course.schema.json`。設定檔頂端的 `$schema` 讓編輯器自動完成，
`make audit` 也會拿它擋錯：欄位拼錯（`units` 打成 `unit`）、型別不對、`tone` 用了不存在的值。

```jsonc
{
  "$schema": "../src/build/course.schema.json",
  "site":  { "project": "guitar-course", "name": "…", "url": "https://…" },
  "kinds": [
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

## 圖示

名稱去 <https://lucide.dev/icons/> 查，把用到的加進 `src/build/build_icons.py` 的 `ICONS`
再跑 `make icons`。網站不吃任何外部請求，圖示在建置時就打包成內嵌 sprite——
**沒打包的圖示線上會是空白**，`make audit` 會先抓到。

config 裡會用到圖示的地方：`site.brandIcon`、`chapters[].icon`、`ui.stats[].icon`、
`landing.steps[].icon`。

## tone

`kinds` 與 `grades` 的 `tone` 只是指向設計語彙，跟主題無關。可用值等於 `src/web/css/tokens.css`
裡有 `.Label--<tone>` 定義的那幾個：`accent` / `success` / `attention` / `danger` / `done` /
`neutral`。用了沒定義的值，標籤會變成沒有顏色的灰底，`make audit` 會擋。

## 詞彙模組（選用）

`course/taxonomy/` 放兩個可選模組，在 config 的 `taxonomy` 指定 import 路徑：

- **`facets`**——提供 `extract(*texts) -> [str]`、`GROUPS`、`GROUP_OF`。
  用來做側欄的分面篩選。體態課是肌群；烹飪課可能是食材或技法；程式課可能是語言特性。
  重點是**正規化同義詞**（「背闊肌」與「闊背肌」是同一個）。
- **`categories`**——提供 `classify(item) -> id | None`、`NAMES`、`KINDS`。
  把項目歸類，讓文獻可以掛在類別上（見 `evidence.md`）。

兩個都可以不要，config 拿掉 `taxonomy` 即可，篩選面板會自動消失。
