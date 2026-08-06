#!/usr/bin/env python3
"""一次把瀏覽次數計數器的雲端資源建好：D1 資料庫 → 建表 → 寫出 wrangler 設定。

冪等：重跑會沿用已存在的資料庫，不會重建、不會清空數字。

用法：
    make counter
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑

ROOT = coursepath.ROOT
COURSE = coursepath.course_dir()
DIST = coursepath.dist_dir(COURSE)
CFG = coursepath.load_config(COURSE)
PROJECT = CFG["site"]["project"]
DB_NAME = f"{PROJECT}-hits"
WRANGLER = ["npx", "--yes", "wrangler@4"]
WRANGLER_LABEL = " ".join(WRANGLER)

TOKEN_URL = "https://dash.cloudflare.com/profile/api-tokens"


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    # cwd 一律固定在 ROOT：wrangler 會自動載入「執行目錄的 .env」，
    # 不釘住的話同一支腳本在不同步驟可能讀到不同憑證。
    kw.setdefault("cwd", ROOT)
    return subprocess.run(WRANGLER + args, capture_output=True, text=True, timeout=300, **kw)


# ── 失敗診斷 ────────────────────────────────────────────────────────────
#
# wrangler 對「沒登入」「token 無效」「token 權限不夠」回的訊息長得很像，
# 而這三種的處置方式完全不同。這裡只做一件事：不要替使用者猜病因，
# 把 wrangler 的原話帶上來，再依訊息特徵列出對得上的可能。


def token_source() -> list[str]:
    """回報 wrangler 這次會拿到哪一組憑證——這是最常被忽略的變因。"""
    lines: list[str] = []
    if os.environ.get("CLOUDFLARE_API_TOKEN", "").strip():
        lines.append(
            "shell 環境變數有 CLOUDFLARE_API_TOKEN，wrangler 會優先用它，不會用 `wrangler login` 的 OAuth。"
        )
    env_file = ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("#"):
                continue
            m = re.match(r"^(?:export\s+)?CLOUDFLARE_API_TOKEN\s*=\s*(.*)$", line)
            if m and m.group(1).strip().strip("\"'"):
                lines.append(
                    f"{env_file.name} 裡的 CLOUDFLARE_API_TOKEN 有值。wrangler 會自動載入這個檔案，"
                    "並用它蓋掉 `wrangler login` 的 OAuth——要改用 OAuth 就把那一行清空或註解掉。"
                )
                break
    if not lines:
        lines.append(
            "沒有偵測到 CLOUDFLARE_API_TOKEN（環境變數與 .env 都沒有），wrangler 這次走的是 OAuth。"
        )
    return lines


NOT_LOGGED_IN = [
    f"尚未登入，或登入的是另一份 wrangler。這裡用的是 `{WRANGLER_LABEL}`。",
    f"    先跑：{WRANGLER_LABEL} login",
    "    注意版本差異：不同版本的 wrangler 設定檔位置不同（~/.wrangler/ 與"
    " ~/Library/Preferences/.wrangler/），在自己 shell 用 `wrangler login` 登入的那一份，"
    "未必是這裡呼叫到的那一份。",
]

NO_D1_PERMISSION = [
    "API token 缺少 D1:Edit 權限。Cloudflare 的「Cloudflare Pages」範本【不含】D1，"
    "所以同一把 token 可以成功部署 Pages、卻建不了資料庫。",
    f"    到 {TOKEN_URL} 編輯 token，加一列 Account → D1 → Edit。",
]

BAD_TOKEN = [
    "API token 本身無效或已過期（不是權限問題，是這串字 Cloudflare 不認）。",
    "    如果你其實想用 OAuth：把 .env 的 CLOUDFLARE_API_TOKEN 清空即可，"
    "wrangler 會自動載入 .env 並優先採用它。",
]


def explain(output: str) -> list[str]:
    """依 wrangler 的原始輸出挑出對得上的可能。挑不出來就兩種都列。"""
    o = output.lower()
    causes: list[list[str]] = []

    if "9109" in o or "invalid access token" in o or "invalid api token" in o:
        causes.append(BAD_TOKEN)
    if (
        "non-interactive environment" in o
        or "10001" in o
        or "not authenticated" in o
        or "not logged in" in o
        or "you need to be logged in" in o
    ):
        causes.append(NOT_LOGGED_IN)
    if (
        "10000" in o
        or "incorrect permissions" in o
        or "authentication error" in o
        or "retrieve account id" in o
        or "unauthorized" in o
        or "authorization" in o
        or "7403" in o
    ):
        causes.append(NO_D1_PERMISSION)
        if NOT_LOGGED_IN not in causes:
            causes.append(NOT_LOGGED_IN)

    if not causes:
        causes = [NO_D1_PERMISSION, NOT_LOGGED_IN]

    lines: list[str] = []
    for i, cause in enumerate(causes):
        head, *rest = cause
        lines.append(f"({chr(ord('a') + i)}) {head}")
        lines.extend(rest)
    return lines


def fail(step: str, output: str) -> int:
    """統一的失敗輸出：wrangler 原話 → 憑證來源 → 可能原因。"""
    raw = output.strip()
    sys.stdout.flush()  # 讓進度與錯誤在管線裡也維持正確順序
    print(f"\n✗ {step}", file=sys.stderr)
    if raw:
        print("\nwrangler 原始訊息：", file=sys.stderr)
        for line in raw[-800:].splitlines():
            print(f"  │ {line}", file=sys.stderr)
    print("\n這次用的憑證：", file=sys.stderr)
    for line in token_source():
        print(f"  · {line}", file=sys.stderr)
    print("\n對得上的可能原因：", file=sys.stderr)
    for line in explain(raw):
        print(f"  {line}", file=sys.stderr)
    return 1


# ── 流程 ────────────────────────────────────────────────────────────────


def list_dbs() -> tuple[list[dict] | None, str]:
    """回傳 (資料庫清單, 原始輸出)。清單為 None 代表這一步就失敗了。"""
    proc = run(["d1", "list", "--json"])
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        return None, out
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, out
    return (parsed if isinstance(parsed, list) else []), out


def create_db() -> tuple[str | None, str]:
    proc = run(["d1", "create", DB_NAME])
    out = proc.stdout + proc.stderr
    m = re.search(r"database_id\s*=\s*\"([0-9a-f-]{36})\"", out) or re.search(
        r"\"database_id\"\s*:\s*\"([0-9a-f-]{36})\"", out
    )
    return (m.group(1) if m else None), out


def main() -> int:
    if "counter" not in CFG:
        print("✗ course.config.json 沒有 counter 區塊——這個功能是選用的，先加上再跑", file=sys.stderr)
        return 1

    print(f"專案 {PROJECT} · 資料庫 {DB_NAME} · wrangler `{WRANGLER_LABEL}`")

    # preflight：先問一次「你看得到 D1 嗎」。權限或登入有問題的話，
    # 在這裡就會爆——比讓它在 create 失敗、再回頭猜原因清楚得多。
    dbs, out = list_dbs()
    if dbs is None:
        return fail("列出 D1 資料庫失敗，還沒開始建立任何東西。", out)

    db_id = next(
        (db.get("uuid") or db.get("database_id") for db in dbs if db.get("name") == DB_NAME), None
    )
    if db_id:
        print(f"  ✓ 沿用既有資料庫 {db_id}")
    else:
        print("  · 建立資料庫…")
        db_id, out = create_db()
        if not db_id:
            return fail(f"建立資料庫 {DB_NAME} 失敗。", out)
        print(f"  ✓ 已建立 {db_id}")

    print("  · 套用 schema（CREATE TABLE IF NOT EXISTS，不會清掉既有數字）…")
    proc = run(["d1", "execute", DB_NAME, "--file", "functions/schema.sql", "--remote", "-y"])
    if proc.returncode != 0:
        return fail("套用 schema 失敗（資料庫已存在，重跑這個指令是安全的）。", proc.stdout + proc.stderr)
    print("  ✓ schema 就緒")

    cfg_path = ROOT / "wrangler.jsonc"
    cfg_path.write_text(
        json.dumps(
            {
                "name": PROJECT,
                # 產物目錄跟著課程走，兩門課各自有自己的 wrangler 設定
                "pages_build_output_dir": str(
                    DIST.relative_to(ROOT) if DIST.is_relative_to(ROOT) else DIST
                ),
                "compatibility_date": "2025-01-01",
                "d1_databases": [
                    {"binding": "HITS", "database_name": DB_NAME, "database_id": db_id}
                ],
            },
            indent=2,
        )
        + "\n"
    )
    print(f"  ✓ 已寫出 {cfg_path.relative_to(ROOT)}（含 D1 綁定，已被 gitignore）")
    print("\n接著跑 `make deploy`，徽章就會出現在 header。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
