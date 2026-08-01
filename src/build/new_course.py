#!/usr/bin/env python3
"""產生一門新課的骨架：make new-course NAME=my-course

骨架的驗收標準只有一條：**產出來就能直接 `make build` 成功**。
一門「零單元」的課如果建不起來，那骨架就沒有用——使用者第一件事會是
去猜哪些欄位是必填的，而框架本來就該替他回答這件事。

所以範本刻意只留必填的部分（site / ui / kinds / chapters），
選用的區塊（grades、stance、paywall、counter、discussions、taxonomy…）
一個都不放：需要的人去 reference/config.md 查，不需要的人不必先刪一堆東西。
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑

ROOT = coursepath.ROOT
TEMPLATE = Path(__file__).resolve().parent / "templates" / "new-course"

# site.project 直接餵給 Cloudflare Pages，也拿來當 localStorage 前綴，
# 所以名字的限制跟 schema 的 pattern 一致，先擋在這裡比事後 audit 好。
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def die(msg: str) -> int:
    print(f"✗ {msg}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if not argv:
        return die("用法：make new-course NAME=my-course [DIR=courses/my-course]")

    name = argv[0].strip()
    if not NAME_RE.match(name):
        return die(f"NAME「{name}」只能用小寫英數與連字號，且不能以連字號開頭或結尾")

    raw_dir = argv[1].strip() if len(argv) > 1 and argv[1].strip() else f"courses/{name}"
    target = Path(raw_dir)
    target = target if target.is_absolute() else ROOT / target
    rel = target.relative_to(ROOT) if target.is_relative_to(ROOT) else target

    if target.exists():
        return die(f"{rel} 已經存在，不覆蓋。換個 NAME，或先把它移走")

    shutil.copytree(TEMPLATE, target)

    config = target / "course.config.json"
    # 顯示用的名字先用 NAME 原樣；schema 只管 project，標題是給人看的，之後隨時改
    config.write_text(
        config.read_text().replace("__PROJECT__", name).replace("__NAME__", name)
    )

    # $schema 是相對路徑，深度跟著實際落點走，寫死 ../../ 只有 courses/x 會對
    depth = len(rel.parts) if target.is_relative_to(ROOT) else 2
    config.write_text(
        config.read_text().replace(
            '"$schema": "../../src/build/course.schema.json"',
            f'"$schema": "{"../" * depth}src/build/course.schema.json"',
        )
    )

    print(f"→ {rel}  課程骨架已建立")
    for path in sorted(p for p in target.rglob("*") if p.is_file()):
        print(f"   · {path.relative_to(target)}")
    print(
        f"\n接下來：\n"
        f"    COURSE={rel} make build     # 現在就會成功——零單元也是一門合法的課\n"
        f"    COURSE={rel} make audit     # 看看還缺什麼\n"
        f"    COURSE={rel} make icons     # 改了章節圖示之後重打包（需要網路）\n"
        f"\n這個 repo 現在有不只一門課，所以指令一律要帶 COURSE=。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
