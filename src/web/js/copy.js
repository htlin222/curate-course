// copy.js — 設定檔文案進到 HTML 的唯一契約。
//
// 這個檔案存在的理由：同一個欄位以前會因為「在哪裡被渲染」而有不同行為。
// `stance.intro` 逸出、相鄰的 `stance.outro` 不逸出；`{videos}` 在建置期是去重支數、
// 在前端是影片欄位數。兩者都不會報錯，只會安靜地講錯話。
//
// 現在的規則只有一句：**所有文案都先逸出，然後只認得 `**粗體**`**。
// 想強調就寫 `**這樣**`；寫 `<strong>` 只會在頁面上看到字面的 `<strong>`。
//
// 這裡的每一個函式在 src/build/seo.py 都有一份等價實作（建置期注入首屏用），
// 兩份必須永遠給出同一個字串——tests/copy-contract.test.js 會拿同一組樣本比對。

/** HTML 逸出。五個字元與 Python 的 html.escape(quote=True) 完全一致。 */
export const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" })[c],
  );

/** 受限標記：`**粗體**`。只有這一種，而且一定跑在逸出之後，所以標記本身不可能夾帶標籤。 */
const BOLD = /\*\*([\s\S]+?)\*\*/g;

/** 段落文案（元素內容）：逸出後把 `**粗體**` 展開成 <strong>。 */
export const rich = (s) => esc(s).replace(BOLD, "<strong>$1</strong>");

/** 屬性與純文字（placeholder、title、meta content）：標籤在這裡塞不進去，
    所以把 `**` 記號拿掉只留文字——優雅退化，不要讓作者看到字面的星號。 */
export const plain = (s) => esc(s).replace(BOLD, "$1");

/** 給 DOM 的純文字 sink 用（setAttribute、textContent、document.title）：
    這些 API 不會再解析一次 HTML，逸出反而會讓使用者看到 &amp;，所以只去掉 `**`。 */
export const text = (s) => String(s ?? "").replace(BOLD, "$1");

/** 文案佔位符 → course.json 的 meta 欄位。
    這份對應表是資料而不是程式碼，才能跟 src/build/seo.py 的那份逐項比對。
    三個數字互不相同：units 是影片欄位合計，lessonUnits 才是章節單元數，
    videos 是去重後的實際支數。以前前端只認得 {units}/{videos}，而且 {videos}
    指到 video_slots——同一個 token 在首屏與前端得到兩個答案（#18）。 */
export const TOKEN_FIELDS = {
  units: "units",
  lessonUnits: "lesson_units",
  drillUnits: "drill_units",
  slots: "video_slots",
  videos: "video_unique",
  problems: "problem_units",
  evidence: "evidence_checked",
};

/** 未知的 token 原樣保留，讓 make audit 抓得到，不要靜靜吞掉。 */
export function fillTokens(source, meta) {
  const m = meta || {};
  return String(source ?? "").replace(/\{(\w+)\}/g, (hit, key) =>
    key in TOKEN_FIELDS ? String(m[TOKEN_FIELDS[key]] ?? 0) : hit,
  );
}

/** 先填數字再逸出：token 展開出來的是數字，不可能夾帶標記。 */
export const richTokens = (source, meta) => rich(fillTokens(source, meta));
