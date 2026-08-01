#!/usr/bin/env python3
"""解析「這次要建置哪一門課」——框架所有進入點的唯一真相來源。

以前每支腳本各自寫 `Path(os.environ.get("COURSE") or ROOT / "course")`：
`COURSE` 看起來是選項，實際上是一條沒有人走過的路徑，而預設值 `course/`
把範例課程釘死在框架的目錄層級上，「換主題只改 course/」永遠只能靠自律。

現在課程一律住在 `courses/<名字>/` 或 `examples/<名字>/`，框架本身不內含
任何一門課，`COURSE` 是主要路徑。解析規則只有三條：

1. 有設 `COURSE` 就用它（相對路徑相對於 repo 根目錄，也吃絕對路徑）。
2. 沒設，而整個 repo 剛好只有一門課 → 用那一門，並把選到誰印出來。
3. 沒設而有兩門以上 → **直接報錯**並列出來。猜錯的代價是把 A 課的資料
   建成 B 課的站台，而且不會有任何錯誤訊息；寧可要求講清楚。

單獨執行時把解析結果印到 stdout，給 Makefile 用：

    python3 src/build/coursepath.py            # 印出課程路徑，解析不了就 exit 1
    python3 src/build/coursepath.py --or-empty # 解析不了印空字串，exit 0
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONFIG_NAME = "course.config.json"

# 課程可以放在哪裡。`courses/` 是自己的課，`examples/` 是隨框架附的範例課；
# 兩者結構完全相同——範例課沒有任何特權，才能證明框架真的與主題無關。
COURSE_GLOBS = ("courses/*", "examples/*")


class CourseError(RuntimeError):
    """解析失敗。訊息本身就是給人看的說明，不要再包裝。"""


def candidates(root: Path = ROOT) -> list[Path]:
    """repo 裡所有「看起來是一門課」的目錄，依路徑排序。"""
    found = {
        cfg.parent
        for pattern in COURSE_GLOBS
        for cfg in root.glob(f"{pattern}/{CONFIG_NAME}")
        if cfg.is_file()
    }
    return sorted(found)


def _rel(path: Path, root: Path = ROOT) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def resolve(root: Path = ROOT, env: dict | None = None) -> Path:
    """回傳這次要用的課程目錄；解析不了就丟 CourseError。"""
    env = os.environ if env is None else env
    raw = (env.get("COURSE") or "").strip()

    if raw:
        # 相對路徑一律相對於 repo 根目錄：make 是在根目錄跑的，但 python 的
        # cwd 不保證，用 cwd 會在 subdirectory 執行時解析到不存在的地方。
        path = Path(raw)
        path = (path if path.is_absolute() else root / path).resolve()
        if not (path / CONFIG_NAME).is_file():
            raise CourseError(
                f"COURSE={raw} 底下沒有 {CONFIG_NAME}（找的是 {_rel(path / CONFIG_NAME, root)}）"
            )
        return path

    found = candidates(root)
    if len(found) == 1:
        return found[0].resolve()
    if not found:
        raise CourseError(
            "找不到任何課程。課程要放在 courses/<名字>/ 或 examples/<名字>/，"
            "裡面要有 course.config.json。\n"
            "  新開一門：make new-course NAME=my-course"
        )
    listing = "\n".join(f"    COURSE={_rel(p, root)} make <目標>" for p in found)
    raise CourseError(
        f"這個 repo 有 {len(found)} 門課，沒設 COURSE 的話框架不猜是哪一門：\n{listing}"
    )


def course_dir(root: Path = ROOT, env: dict | None = None) -> Path:
    """給各腳本模組層級呼叫：解析失敗就印訊息並結束，不要吐 traceback。"""
    try:
        return resolve(root, env)
    except CourseError as e:
        print(f"✗ {e}", file=sys.stderr)
        raise SystemExit(2) from None


def dist_dir(course: Path, root: Path = ROOT, env: dict | None = None) -> Path:
    """產物目錄。**必須跟著課程走**，否則兩門課會互相覆蓋 dist/。"""
    env = os.environ if env is None else env
    raw = (env.get("DIST") or "").strip()
    if raw:
        path = Path(raw)
        return (path if path.is_absolute() else root / path).resolve()
    return (root / "dist" / course.name).resolve()


def main() -> int:
    args = sys.argv[1:]

    if "--list" in args:
        found = candidates()
        if not found:
            print("（沒有任何課程。開一門：make new-course NAME=my-course）")
            return 0
        try:
            active = resolve()
        except CourseError:
            active = None
        for path in found:
            mark = "→" if path.resolve() == active else " "
            print(f" {mark} {_rel(path)}")
        if active is None:
            print("\n沒有指定 COURSE，而且不只一門課——請明講要建置哪一門。")
        return 0

    lenient = "--or-empty" in args
    try:
        print(_rel(resolve()))
    except CourseError as e:
        if lenient:
            print("")
            return 0
        print(f"✗ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
