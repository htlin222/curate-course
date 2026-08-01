// store.js — localStorage 的命名空間與舊資料搬遷。
//
// 前綴一定要跟著 course.config.json 的 site.project 走。寫死一個前綴的話，
// 同一個 origin 底下放兩門課（子路徑部署、本機都開 localhost）時，兩門課的
// 完成進度、展開狀態、購物車與訂單會互相覆蓋——而且不會有任何錯誤訊息，
// 使用者只會看到進度莫名其妙變了。
//
// 主題是刻意的例外：那是這台裝置的偏好，不是課程狀態，兩門課共用一個鍵
// 反而是對的。而且 index.html 裡「繪製前套用主題」的 inline script 必須在
// course.json 載入之前就讀得到它，那個時間點根本還不知道 project 是什麼。

/** 跨課程共用的主題鍵。curate 是框架名，不是任何一門課的名字。 */
export const THEME_KEY = "curate:theme";

/** 會被課程前綴包起來的狀態。新增狀態時記得加進來，搬遷才會一起帶走。 */
export const STATE_KEYS = ["done", "open", "tab", "playing", "wide", "listW", "cart", "order"];

/** 隱私模式／檔案協定下取 localStorage 會直接拋例外，不能讓它擋住整個啟動。 */
export function safeStorage() {
  try {
    return globalThis.localStorage || null;
  } catch {
    return null;
  }
}

/** site.project 就是 Cloudflare Pages 的專案名，天生唯一，拿來當前綴剛好。 */
export function prefixOf(config) {
  const project = config?.site?.project;
  return /^[a-z0-9-]+$/.test(project || "") ? `${project}:` : "course:";
}

/** { done: "gym-course:done", ... } */
export function keysFor(config, names = STATE_KEYS) {
  const prefix = prefixOf(config);
  return Object.fromEntries(names.map((n) => [n, prefix + n]));
}

/**
 * 一次性搬遷舊前綴的資料。
 *
 * 框架早期把前綴寫死成某一門課的縮寫，改成 project 前綴之後，既有使用者的
 * 進度不能無聲消失——所以由課程自己宣告 site.legacyStorePrefix，有宣告才搬。
 * 新課程不設這個欄位就完全不作用，不會把別門課的資料撿進來。
 *
 * 只補「新鍵還不存在」的項目，因此重跑安全，也不會蓋掉新資料。
 * 舊鍵刻意保留不刪：萬一使用者退回舊版本，資料還在。
 */
export function migrateLegacy(config, storage = safeStorage()) {
  const legacy = config?.site?.legacyStorePrefix;
  if (!storage || !legacy) return [];

  const prefix = prefixOf(config);
  if (legacy === prefix) return [];

  const moved = [];
  const copy = (from, to) => {
    try {
      if (storage.getItem(to) !== null) return;
      const raw = storage.getItem(from);
      if (raw === null) return;
      storage.setItem(to, raw);
      moved.push(to);
    } catch {
      /* 配額滿或隱私模式：搬不動就維持現狀，總比整個啟動失敗好 */
    }
  };

  for (const name of STATE_KEYS) copy(legacy + name, prefix + name);
  copy(legacy + "theme", THEME_KEY);
  return moved;
}
