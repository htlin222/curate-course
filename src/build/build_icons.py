#!/usr/bin/env python3
"""下載 Lucide 圖示並打包成內嵌 SVG sprite。網站不吃任何外部請求。

**兩份 sprite，因為 sprite 不能是全域的。**

* `src/web/js/icons.js` —— 只放 `FRAMEWORK_ICONS`，也就是 src/web 裡寫死的
  `icon("…")` 與 `#i-…`。內容**與 COURSE 無關**，跑哪一門課產出都一模一樣。
* `$COURSE/assets/js/icons.js` —— 這門課自己的那一份（框架 ∪ 課程圖示）。
  `build.py` 的 `sync_web()` 會先複製 src/web、再用 `$COURSE/assets/` 覆蓋，
  所以這一份會蓋掉 `dist/js/icons.js`，前端一行都不必改。

以前只有前者，而且課程的圖示也塞在裡面：兩門課並存時，後跑 `make icons`
的那一門會把前一門的圖示洗掉，被洗掉的那門課線上就是一排空白方塊——
不會報錯，只有打開網站才看得出來。現在課程圖示寫在自己的目錄，
第二門課再怎麼跑都碰不到第一門課的產物。

課程要打包哪些圖示是從 `$COURSE/course.config.json` **推導**出來的：任何叫
`icon` 或 `xxxIcon` 的欄位（site.brandIcon、chapters[].icon、ui.stats[].icon、
landing.steps[].icon…），外加選用的頂層 `icons` 陣列當逃生門。

用法：
    make icons                          # 用預設解析出來的那門課
    COURSE=examples/body make icons     # 多課程並存時明講是哪一門
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑

LUCIDE_VERSION = "0.469.0"
CDN = f"https://unpkg.com/lucide-static@{LUCIDE_VERSION}/icons/{{}}.svg"

ROOT = coursepath.ROOT
COURSE = coursepath.course_dir()
# 框架那一份：內容不隨課程改變，所以兩門課同時存在也不會互相覆蓋
FRAMEWORK_OUT = ROOT / "src" / "web" / "js" / "icons.js"
# 課程那一份：sync_web() 會拿它覆蓋 dist/js/icons.js
COURSE_OUT = COURSE / "assets" / "js" / "icons.js"

# 框架介面自己要用的圖示。這些名稱在 src/web 裡是寫死的字串，
# tests/decoupling.test.js 會雙向比對，多一個少一個都會被抓出來。
FRAMEWORK_ICONS = [
    # 介面
    "search",
    "x",
    "sun",
    "moon",
    "chevron-right",
    "chevron-left",
    "check",
    "play",
    "external-link",
    "layers",
    "rotate-ccw",
    "inbox",
    "info",
    "clock",
    "graduation-cap",
    "microscope",
    "eye",
    "grip-vertical",
    "message-circle",
    "github",
    "sliders-horizontal",
    # paywall
    "lock",
    "lock-open",
    "shopping-cart",
    "receipt",
    "credit-card",
    "tag",
    "sparkles",
    "circle-check-big",
    "trash-2",
    # 單元內容
    "clipboard-check",
    "triangle-alert",
    "flame",
    "battery-low",
    "circle-dot",
    "book-open",
]


def course_icons(config_path: Path) -> set[str]:
    """從課程設定檔掃出所有圖示名。

    認的是欄位名而不是位置，所以之後設定檔多一個 `ui.facetIcon`、
    `landing.cards[].icon` 之類的欄位，這支腳本不必跟著改。
    """
    try:
        cfg = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"✗ 讀不到 {config_path}：{e}", file=sys.stderr)
        return set()

    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if isinstance(val, str) and (key == "icon" or key.endswith("Icon")):
                    found.add(val)
                else:
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(cfg)
    # 逃生門：設定檔欄位以外的地方（course/assets 裡的自訂樣板）也想用圖示時
    found.update(i for i in cfg.get("icons") or [] if isinstance(i, str))
    return {i for i in found if re.fullmatch(r"[a-z0-9-]+", i)}


def fetch(name: str) -> tuple[str, str | None]:
    try:
        with urllib.request.urlopen(CDN.format(name), timeout=20) as res:
            svg = res.read().decode()
        inner = re.search(r"<svg[^>]*>(.*?)</svg>", svg, re.S).group(1)
        return name, re.sub(r"\s+", " ", inner).strip()
    except (urllib.error.HTTPError, AttributeError):
        return name, None


def render(names: list[str], bodies: dict[str, str], note: str) -> str:
    """產生一份完整可用的 icons.js。

    課程那一份是**整檔覆蓋** dist/js/icons.js，不是合併，所以它必須自帶
    mountIcons()／icon() 與框架圖示，少一樣前端就整個掛掉。
    """
    sprite = "".join(f'<symbol id="i-{n}" viewBox="0 0 24 24">{bodies[n]}</symbol>' for n in names)
    return f"""\
// icons.js — 由 build_icons.py 產生，請勿手動編輯
// {note}
// Lucide v{LUCIDE_VERSION}（ISC License）· https://lucide.dev/icons/
export const ICON_SPRITE =
  {json.dumps(sprite, ensure_ascii=False)};

export const ICON_NAMES = {json.dumps(names, ensure_ascii=False, indent=2)};

/** 注入 sprite 到 document，只需呼叫一次 */
export function mountIcons() {{
  if (document.getElementById("lucide-sprite")) return;
  const el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  el.setAttribute("id", "lucide-sprite");
  el.setAttribute("aria-hidden", "true");
  el.style.display = "none";
  el.innerHTML = ICON_SPRITE;
  document.body.prepend(el);
}}

/** 產生一個 <svg><use></svg> 字串 */
export function icon(name, size = 16, cls = "") {{
  return `<svg class="${{cls}}" width="${{size}}" height="${{size}}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><use href="#i-${{name}}"/></svg>`;
}}
"""


def write(path: Path, text: str, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"→ {shown}  {label}，{path.stat().st_size / 1024:.1f} KB")


def main() -> int:
    framework = sorted(set(FRAMEWORK_ICONS))
    from_course = course_icons(COURSE / "course.config.json")
    course_only = sorted(from_course - set(framework))
    wanted = sorted(set(framework) | from_course)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(fetch, wanted))

    missing = [n for n, v in results.items() if v is None]
    if missing:
        print(f"✗ 取不到 {len(missing)} 個圖示：{', '.join(missing)}", file=sys.stderr)
        print("  Lucide 沒有這個名字？到 https://lucide.dev/icons/ 對一下拼字", file=sys.stderr)
        return 1

    write(
        FRAMEWORK_OUT,
        render(framework, results, "框架介面用的圖示，與課程無關——不要把章節圖示加進來"),
        f"框架 {len(framework)} 個圖示",
    )

    if course_only:
        write(
            COURSE_OUT,
            render(wanted, results, f"{COURSE.name} 這門課的 sprite（框架 + 課程），覆蓋 dist/js/icons.js"),
            f"{COURSE.name} {len(wanted)} 個圖示（含 {len(course_only)} 個課程專屬）",
        )
    elif COURSE_OUT.exists():
        # 課程把自訂圖示拿光了，殘留的那一份會繼續覆蓋 dist，而且永遠不再更新
        COURSE_OUT.unlink()
        print(f"→ 移除 {COURSE_OUT.relative_to(ROOT)}（這門課沒有框架以外的圖示）")
    else:
        print(f"·  {COURSE.name} 沒有框架以外的圖示，直接用框架那一份")
    return 0


if __name__ == "__main__":
    sys.exit(main())
