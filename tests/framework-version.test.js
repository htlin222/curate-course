// 框架版號的自我一致性。零依賴、不需要瀏覽器：node --test tests/
//
// 版號機制本身也會靜靜壞掉，而且壞法很難看：`make audit` 叫課程作者去讀
// docs/MIGRATION.md 的「v2 → v3」，那一段卻不存在——訊息看起來很專業，
// 照做卻無事可做。這裡把「跳主版號」與「補遷移指南」綁成同一件事。
//
// 稽核那邊（audit.py 的 audit_framework_version）比對的是「設定檔 vs 框架」，
// 是課程作者的問題；這裡比對的是「框架 vs 自己的文件」，是框架維護者的問題。
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { ROOT, repo, courseDirs, readJSON } from "./_paths.js";

/** pyproject.toml 的 [project] version。只要這一個值，不值得為它引入 TOML 解析器。 */
function frameworkVersion() {
  const toml = fs.readFileSync(repo("pyproject.toml"), "utf8");
  const hit = toml.match(/^\s*version\s*=\s*"([^"]+)"/m);
  assert.ok(hit, "pyproject.toml 找不到 project.version");
  return hit[1];
}

const majorOf = (v) => Number(v.split(".")[0]);

test("框架版號是 semver，主版號是正整數", () => {
  const version = frameworkVersion();
  assert.match(version, /^\d+\.\d+\.\d+$/, `pyproject.toml 的版號「${version}」不是 主.次.修`);
  assert.ok(majorOf(version) >= 1, "主版號從 1 開始");
});

test("每一次跳主版號都有對應的遷移指南章節", () => {
  const major = majorOf(frameworkVersion());
  const guide = fs.readFileSync(repo("docs", "MIGRATION.md"), "utf8");

  // audit.py 會逐段列出 v1 → v2、v2 → v3 …，所以每一段都得真的存在。
  for (let n = 1; n < major; n += 1) {
    const heading = `v${n} → v${n + 1}`;
    assert.ok(
      guide.includes(heading),
      `docs/MIGRATION.md 缺「${heading}」——audit 會叫人去讀一段不存在的文件`,
    );
  }
});

test("audit 指向的遷移指南路徑真的存在", () => {
  const audit = fs.readFileSync(repo("src", "build", "audit.py"), "utf8");
  const hit = audit.match(/^MIGRATION\s*=\s*"([^"]+)"/m);
  assert.ok(hit, "audit.py 找不到 MIGRATION 常數");
  assert.ok(fs.existsSync(path.join(ROOT, hit[1])), `audit.py 指向不存在的 ${hit[1]}`);
});

test("repo 裡每一門課宣告的主版號都對得上框架", () => {
  const major = majorOf(frameworkVersion());
  const dirs = courseDirs();
  assert.ok(dirs.length > 0, "repo 裡至少要有一門課（範例課也算）");

  for (const dir of dirs) {
    const rel = path.relative(ROOT, dir);
    const cfg = readJSON(path.join(dir, "course.config.json"));
    assert.ok(cfg.frameworkVersion, `${rel} 沒宣告 frameworkVersion`);
    assert.equal(
      majorOf(cfg.frameworkVersion),
      major,
      `${rel} 寫給 v${majorOf(cfg.frameworkVersion)}，框架是 v${major}`,
    );
  }
});

test("新課骨架帶著版號佔位符，不是寫死的版號", () => {
  const tpl = fs.readFileSync(
    repo("src", "build", "templates", "new-course", "course.config.json"),
    "utf8",
  );
  const cfg = JSON.parse(tpl);
  // 寫死的話，框架跳版之後新開的課會立刻收到一則叫它去遷移的錯誤，而它根本就是新的。
  assert.equal(
    cfg.frameworkVersion,
    "__FRAMEWORK_VERSION__",
    "骨架的 frameworkVersion 要由 new_course.py 在建立當下填入",
  );
});
