#!/usr/bin/env python3
"""下載 Lucide 圖示並打包成內嵌 SVG sprite（src/web/js/icons.js）。

網站不吃任何外部請求，圖示在建置時就打包進 JS。

要打包哪些圖示分成兩半：

* `FRAMEWORK_ICONS` —— 框架自己的介面用得到的（搜尋、播放、深淺色…）。
  這份清單對應 src/web 裡寫死的 `icon("…")` 與 `#i-…`，換主題不會變動。
* 課程的圖示 —— 直接從 `$COURSE/course.config.json` 掃出來：任何叫 `icon`
  或 `xxxIcon` 的欄位（site.brandIcon、chapters[].icon、ui.stats[].icon、
  landing.steps[].icon…），外加選用的頂層 `icons` 陣列當逃生門。

所以「章節想換一個圖示」只要改 `course/`，不必再編輯這支框架腳本——
這是 README 對使用者的承諾。

用法：
    make icons                         # 預設打包 course/
    COURSE=courses/guitar make icons   # 多課程並存時，切到哪門課就打包哪門課
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LUCIDE_VERSION = "0.469.0"
CDN = f"https://unpkg.com/lucide-static@{LUCIDE_VERSION}/icons/{{}}.svg"

ROOT = Path(__file__).resolve().parents[2]
COURSE = Path(os.environ.get("COURSE") or ROOT / "course").resolve()
OUT = ROOT / "src" / "web" / "js" / "icons.js"

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


def main() -> int:
    from_course = course_icons(COURSE / "course.config.json")
    wanted = sorted(set(FRAMEWORK_ICONS) | from_course)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(fetch, wanted))

    missing = [n for n, v in results.items() if v is None]
    if missing:
        print(f"✗ 取不到 {len(missing)} 個圖示：{', '.join(missing)}", file=sys.stderr)
        print("  Lucide 沒有這個名字？到 https://lucide.dev/icons/ 對一下拼字", file=sys.stderr)
        return 1

    names = sorted(results)
    sprite = "".join(f'<symbol id="i-{n}" viewBox="0 0 24 24">{results[n]}</symbol>' for n in names)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(f"""\
// icons.js — 由 build_icons.py 產生，請勿手動編輯
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
""")
    shown = OUT.relative_to(ROOT) if OUT.is_relative_to(ROOT) else OUT
    print(
        f"→ {shown}  {len(names)} 個圖示"
        f"（框架 {len(FRAMEWORK_ICONS)} + {COURSE.name} {len(from_course)}）"
        f"，{OUT.stat().st_size / 1024:.1f} KB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
