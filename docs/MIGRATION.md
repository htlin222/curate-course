# 遷移指南

`make audit` 說你的設定檔寫給舊版框架時，看這裡。

## 版號怎麼運作

框架的版號在 `pyproject.toml` 的 `project.version`，課程在自己的
`course.config.json` 頂層宣告它寫給哪一版：

```jsonc
{
  "$schema": "../../src/build/course.schema.json",
  "frameworkVersion": "2.0.0",
  "site": { … }
}
```

**只有主版號有意義。** 主版號對得上就保證相容；次版號與修訂號差多少，稽核一個字
都不會說。沒填 `frameworkVersion` 一律視為 v1——這個欄位是 v2 才有的，v1 的設定檔
本來就不可能填。

版號存在的理由是**破壞性變更不會是紅色的**。框架靠 `git pull` 前進，課程躺在自己的
目錄裡不動；沒有版號的話，改掉一條渲染規則之後設定檔照樣通過 schema、`make build`
照樣成功，只有頁面上的字悄悄變成字面的 `<strong>`。稽核先問版號，就是不讓後面
一整頁的檢查拿新框架的規則去量一份舊設定檔。

跨兩個以上主版號就照順序做，一段都不能跳。

---

## v1 → v2：文案契約

v1 的文案沒有契約，只有一堆呼叫點各自的習慣：同一個 `stance` 物件底下 `intro` 逸出、
`outro` 是 raw HTML；`site.title` 裡一個雙引號就會產生壞掉的 `<meta>`，而 build、
audit、測試全部照樣通過。v2 把這件事收斂成一句話：

> **所有文案都會先被逸出，然後只認得 `**粗體**`。**

實作在 `src/web/js/copy.js`（執行期）與 `src/build/seo.py`（建置期首屏注入），
`tests/copy-contract.test.js` 拿同一組樣本逐字比對兩份。

### 1. HTML 標籤改成 `**粗體**`（必改）

v1 有三個欄位吃 raw HTML：`hero.lede`、`footer.disclaimer`、`stance.outro`。
v2 全部不吃了，寫 `<strong>` 會原樣印在頁面上，而且 `make audit` 的「文案」區段
直接報錯。

```diff
- "lede": "每個問題都告訴你三件事：<strong>怎麼自己評估</strong>、<strong>該練什麼</strong>。"
+ "lede": "每個問題都告訴你三件事：**怎麼自己評估**、**該練什麼**。"
```

短標籤與屬性（`site.title`、`ui.searchPlaceholder`、`ui.playlistSearch`、各種
`title=`）塞不進 `<strong>`，那裡的 `**` 記號會被拿掉只留文字，不會讓使用者看到
字面的星號——所以整份設定檔可以無腦替換，不必分辨哪個欄位渲染在哪裡。

### 2. `og.title` / `og.lede` 的 `<br />` 改成真的換行（必改）

og 是一張 1200×630 的固定畫布，斷句位置必須由你決定，所以這兩個欄位保留了換行語意——
但記號從標籤改成 JSON 字串裡真正的 `\n`。

```diff
- "title": "從頭到腳，<br />把體態拆解成<em>可以練的東西</em>"
+ "title": "從頭到腳，\n把體態拆解成**可以練的東西**"
```

`<em>` 沒有對應的記號，用 `**粗體**`。

### 3. `ui` / `footer` / `stance` / `llms` / `landing` 不再收沒宣告的欄位（可能要改）

這五個區塊在 v2 是 `additionalProperties: false`：schema 沒宣告的欄位一律報錯，
不再靜靜被忽略。反過來說，schema 裡有的就是前端真的會讀的全部。

v1 留下的自訂欄位、拼錯的欄位、從別門課複製過來但這一版已經改名的欄位，都會在
`make audit` 的 schema 檢查裡一次列出來。照著刪或改名即可，訊息會給出完整路徑。

### 4. `index.html` 需要的文案欄位缺一個就是錯誤（可能要改）

v1 缺欄位只印一行警告，然後把字面的 `{{ui.progressLabel}}` 送上線。v2 會讓
`make audit` 變紅並列出缺哪幾個。補齊就好。

### 5. `{videos}` 在前端的數字會變（不必改，但要知道）

v1 的 `{videos}` 在建置期是**去重後的影片支數**，在前端卻是**影片欄位數**——同一個
token 在首屏與捲動之後得到兩個答案。v2 統一成去重後支數。

不需要動設定檔，但如果你的文案是照著前端那個（比較大的）數字寫的，句子可能要重寫。
七個 token 的定義見 `reference/config.md` 的「數字佔位符」。

### 做完之後

```bash
COURSE=courses/<你的課> make audit
```

修到零錯誤，再把版號加上去：

```jsonc
"frameworkVersion": "2.0.0",
```

版號是**最後才改**的。先改版號會讓稽核以為你已經遷移完，然後把上面那些錯誤
混在一般的品質警告裡報給你。
