// 測試共用的路徑解析。與 src/build/coursepath.py 對應：課程住在 courses/<名字>/
// 或 examples/<名字>/，框架本身不內含任何一門課，所以測試也不能寫死 course/。
//
// COURSE 與 DIST 由 Makefile export 進來；直接跑 node --test 時退回「repo 裡
// 只有一門課就用那一門」，跟 Python 那邊同一條規則。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export const repo = (...parts) => path.join(ROOT, ...parts);

const CONFIG_NAME = "course.config.json";

/** repo 裡所有「看起來是一門課」的目錄（絕對路徑，已排序）。 */
export function courseDirs(groups = ["courses", "examples"]) {
  const found = [];
  for (const group of groups) {
    const base = repo(group);
    if (!fs.existsSync(base)) continue;
    for (const name of fs.readdirSync(base).sort()) {
      const dir = path.join(base, name);
      if (fs.existsSync(path.join(dir, CONFIG_NAME))) found.push(dir);
    }
  }
  return found;
}

/** 這次測試對應的課程目錄，解析不出來就回 null（測試自己決定要不要跳過）。 */
export function activeCourse() {
  const env = (process.env.COURSE || "").trim();
  if (env) return path.isAbsolute(env) ? env : repo(env);
  const all = courseDirs();
  return all.length === 1 ? all[0] : null;
}

/** 這次測試對應的產物目錄。DIST 必須跟著 COURSE 走，否則兩門課會互相覆蓋。 */
export function activeDist() {
  const env = (process.env.DIST || "").trim();
  if (env) return path.isAbsolute(env) ? env : repo(env);
  const course = activeCourse();
  return course ? repo("dist", path.basename(course)) : repo("dist");
}

export const readJSON = (file) => JSON.parse(fs.readFileSync(file, "utf8"));

/** 課程「實際生效」的設定：處理過 extends 的那一份。
 *
 * 刻意用子行程去問 coursepath.load_config，而不是在 JS 裡照抄合併規則。
 * 測試複製一份規則的話，它驗證的就是自己的副本而不是產品程式碼——設定
 * 繼承這種東西一旦兩份實作分岔，症狀是「build 過了但產出物少一段」，
 * 而測試會很有信心地說沒問題。
 */
export function loadConfig(courseDir) {
  const code = [
    "import sys, json, pathlib",
    `sys.path.insert(0, ${JSON.stringify(repo("src", "build"))})`,
    "import coursepath",
    `print(json.dumps(coursepath.load_config(pathlib.Path(${JSON.stringify(courseDir)}))))`,
  ].join("\n");
  return JSON.parse(execFileSync("python3", ["-c", code], { encoding: "utf8" }));
}
