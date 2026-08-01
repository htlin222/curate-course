#!/usr/bin/env python3
"""離線品質稽核：設定檔、配額、影片長度與中繼資料、實證深度。

刻意不打任何網路——連結與 PMID 是否真實存在由 verify_links.py / verify_refs.py 負責。
這支腳本只看 course/ 底下的資料與 src/web 的產物，因此同樣的輸入永遠得到同樣的輸出，
可以放進 CI 或交給 agent 自我檢查，不會因為 API 抽風而閃爍。

門檻全部從 course.config.json 的 `audit` 區塊讀，沒寫就用 DEFAULTS，
框架本身不預設任何主題。

用法：
    python3 audit.py            # 人看的報告；有錯誤回傳 1
    python3 audit.py --strict   # 警告也視為錯誤
    python3 audit.py --json     # 機器可讀，給 agent 用
"""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑

ROOT = coursepath.ROOT
COURSE = coursepath.course_dir()
COURSE_REL = COURSE.relative_to(ROOT) if COURSE.is_relative_to(ROOT) else COURSE
DATA = COURSE / "data"
WEB = ROOT / "src" / "web"
DIST = coursepath.dist_dir(COURSE)
SCHEMA = Path(__file__).parent / "course.schema.json"

# 沒寫 audit 區塊時的通則門檻。單位：秒數用 "分:秒" 字串，比例用 0–1。
DEFAULTS = {
    "duration": {
        "lesson": {"min": "3:00", "max": "30:00"},
        "drill": {"min": "0:20", "max": "15:00"},
    },
    "driftSeconds": 45,
    "minViews": 1000,
    "metaCoverage": 0.95,
    "drillsPerUnit": {"min": 1, "max": 30},
    "maxSharedVideos": 60,
    "requireAssessment": [],
    "minAssessmentChars": 40,
    "minCitations": 1,
    "allowMissingUrls": 0,
    # 單一類別佔「已分類項目」的比例上限。超過通常代表 patterns 寫得太寬
    # （典型死法：把會出現在 target 欄位的分面詞彙拿來當 pattern），
    # 那一類會把別類餓死，而歸類結果不會有任何錯誤訊息。
    "maxCategoryShare": 0.25,
    # course/data/ 底下刻意不給建置讀的檔案（草稿、備份）。其餘讀不到的一律報錯。
    "ignoreDataFiles": [],
}

YT = re.compile(
    r"^https://(?:www\.)?youtube\.com/watch\?v=[\w-]{11}(?:&\S*)?$|^https://youtu\.be/[\w-]{11}"
)
SECTIONS = ("設定檔", "文案", "主題耦合", "結構與配額", "影片", "內容深度")

# 文案欄位所在的頂層區塊。這些區塊底下的字串一律走「先逸出、只認得 **粗體**」，
# 寫 HTML 標籤不會有效果，只會原樣印在頁面上。
COPY_SECTIONS = ("site", "hero", "ui", "nav", "landing", "stance", "footer", "llms", "og",
                 "kinds", "grades", "languages", "counter", "paywall")

# 資料檔依「頂層有哪些鍵」判斷用途，不看檔名——oe- / drill-evidence- 這些前綴
# 是「這門課用 OpenEvidence」的歷史，而 ui.evidenceSource 是可換的。
DATA_KEYS = ("conditions", "categories", "lessons", "chapters", "chapter", "units")
VIDEO_META = "video-meta.json"


# ── 小工具 ────────────────────────────────────────────────────────────────


def clock(total: int) -> str:
    h, rem = divmod(int(total), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def parse_clock(s: str | int | None) -> int:
    """'12:34' / '1:02:33' / 750 -> 秒。無法解析回 -1。"""
    if isinstance(s, int):
        return s
    if not s:
        return -1
    parts = str(s).strip().split(":")
    if not all(p.isdigit() for p in parts):
        return -1
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs


def video_id(url: str | None) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url or "")
    return m.group(1) if m else None


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = (
            deep_merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
        )
    return out


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        return e


_BLOBS: dict[Path, dict] | None = None
_BAD_JSON: list[tuple[str, str]] = []  # (檔名, 說明)


def data_blobs() -> dict[Path, dict]:
    """course/data/*.json 一次全部讀進來（只留解析成功的物件），與 build.py 同一套規則。"""
    global _BLOBS
    if _BLOBS is None:
        _BLOBS = {}
        for path in sorted(DATA.glob("*.json")):
            blob = load_json(path)
            if isinstance(blob, dict):
                _BLOBS[path] = blob
            elif isinstance(blob, json.JSONDecodeError):
                _BAD_JSON.append((path.name, f"data/{path.name}：第 {blob.lineno} 行 {blob.msg}"))
    return _BLOBS


def data_rows(key: str):
    """yield (path, dict)：所有資料檔頂層 `key` 陣列裡的物件節點。"""
    for path, blob in data_blobs().items():
        node = blob.get(key)
        if isinstance(node, list):
            for row in node:
                if isinstance(row, dict):
                    yield path, row


def stance_prefix(cfg: dict) -> str:
    return (cfg.get("stance") or {}).get("keyPrefix") or "concept-"


def load_taxonomy(cfg: dict, key: str):
    """匯入課程的詞彙模組；沒設定或匯入失敗都回 None（失敗由 audit_config 報）。"""
    name = (cfg.get("taxonomy") or {}).get(key)
    if not name:
        return None
    sys.path.insert(0, str(COURSE))
    try:
        return importlib.import_module(name)
    except Exception:
        return None


class Report:
    """收集稽核結果。錯誤 = 一定要修；警告 = 值得看一眼。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, list[str]]] = []
        self.stats: dict[str, object] = {}

    def _add(self, level: str, section: str, msg: str, detail: list[str] | None = None) -> None:
        self.rows.append((section, level, msg, detail or []))

    def err(self, section, msg, detail=None):
        self._add("error", section, msg, detail)

    def warn(self, section, msg, detail=None):
        self._add("warn", section, msg, detail)

    def ok(self, section, msg, detail=None):
        self._add("ok", section, msg, detail)

    def count(self, level: str) -> int:
        return sum(1 for _, lv, _, _ in self.rows if lv == level)

    def emit(self) -> None:
        mark = {"ok": "✓", "warn": "⚠", "error": "✗"}
        for section in SECTIONS:
            rows = [r for r in self.rows if r[0] == section]
            if not rows:
                continue
            print(f"\n{section}")
            for _, level, msg, detail in rows:
                print(f"  {mark[level]} {msg}")
                for d in detail[:8]:
                    print(f"      · {d[:118]}{'…' if len(d) > 118 else ''}")
                if len(detail) > 8:
                    print(f"      … 另有 {len(detail) - 8} 筆")

    def as_json(self) -> dict:
        return {
            "errors": [
                {"section": s, "message": m, "detail": d}
                for s, lv, m, d in self.rows
                if lv == "error"
            ],
            "warnings": [
                {"section": s, "message": m, "detail": d}
                for s, lv, m, d in self.rows
                if lv == "warn"
            ],
            "stats": self.stats,
        }


# ── 迷你 JSON Schema 驗證器（只支援本專案 schema 用到的關鍵字）────────────


def validate(node, schema: dict, path: str, defs: dict, out: list[str]) -> None:
    if "$ref" in schema:
        schema = defs.get(schema["$ref"].rsplit("/", 1)[-1], {})

    types = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    t = schema.get("type")
    if t and not isinstance(node, types[t]):
        out.append(f"{path} 應為 {t}，實際是 {type(node).__name__}")
        return
    if t == "integer" and isinstance(node, bool):
        out.append(f"{path} 應為 integer")
        return

    if variants := schema.get("oneOf"):
        # 任一分支通過就算過（paywall.products[].unlocks 是 "*" 或章節陣列）
        failures = []
        for variant in variants:
            errs: list[str] = []
            validate(node, variant, path, defs, errs)
            if not errs:
                failures = []
                break
            failures.append(errs)
        if failures:
            out.append(f"{path} 不符合任何一種允許的形式：{node!r}")

    if (enum := schema.get("enum")) and node not in enum:
        out.append(f"{path} 只能是 {'/'.join(map(str, enum))}，實際是 {node!r}")
    if (pat := schema.get("pattern")) and isinstance(node, str) and not re.match(pat, node):
        out.append(f"{path} 不符合格式 {pat}：{node!r}")
    if (lo := schema.get("minimum")) is not None and isinstance(node, (int, float)) and node < lo:
        out.append(f"{path} 不得小於 {lo}")
    if isinstance(node, list):
        if len(node) < schema.get("minItems", 0):
            out.append(f"{path} 至少要有 {schema['minItems']} 項")
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in node}) != len(
            node
        ):
            out.append(f"{path} 有重複項目")
        if item_schema := schema.get("items"):
            for i, item in enumerate(node):
                validate(item, item_schema, f"{path}[{i}]", defs, out)
    if isinstance(node, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in node:
                out.append(f"{path} 缺少必要欄位 {key}")
        if schema.get("additionalProperties") is False:
            for key in node:
                if key not in props and not key.startswith("$"):
                    out.append(f"{path}.{key} 不是已知欄位（拼錯了？）")
        for key, sub in props.items():
            if key in node:
                validate(node[key], sub, f"{path}.{key}", defs, out)
        if isinstance(extra := schema.get("additionalProperties"), dict):
            for key, val in node.items():
                if key not in props:
                    validate(val, extra, f"{path}.{key}", defs, out)


# ── 設定檔 ────────────────────────────────────────────────────────────────


def _sprite_names(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    m = re.search(r"ICON_NAMES = (\[.*?\]);", path.read_text(), re.S)
    return set(json.loads(m.group(1))) if m else set()


def sprite_icons() -> set[str]:
    """這門課線上實際會拿到的圖示。

    sync_web() 先複製 src/web、再讓 $COURSE/assets/ 覆蓋，所以課程有自己的
    sprite 時，dist 拿到的是課程那一份。稽核必須看同一份，否則 A 課的
    sprite 會替 B 課背書——這正是 sprite 還是全域檔案時的老問題。
    """
    return _sprite_names(COURSE / "assets" / "js" / "icons.js") or _sprite_names(
        WEB / "js" / "icons.js"
    )


def css_tones() -> set[str]:
    """tone 是設計語彙的一部分，定義在 tokens.css，不看其他主題性的樣式檔。"""
    return set(re.findall(r"\.Label--([a-z-]+)", (WEB / "css" / "tokens.css").read_text()))


def audit_topic_coupling(cfg: dict, rep: Report) -> None:
    """抓「換主題時會靜靜壞掉」的那一類問題。

    這些 bug 的共同特徵是**不會報錯**：類型 id 寫死在前端，換主題後項目全部
    不顯示；`teaches` 找不到單元就產出空陣列，JSON-LD 依然合法。稽核不查，
    就要等上線後使用者回報。
    """
    sec = "主題耦合"
    src = ROOT / "src" / "web"
    kind_ids = {k.get("id") for k in cfg.get("kinds") or [] if isinstance(k, dict)}

    # 1) 前端不得寫死任何 kind id
    offenders = []
    for f in [*sorted(src.glob("js/*.js")), src / "index.html"]:
        if not f.exists() or f.name == "icons.js":
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split("//")[0]
            # data-filter="${...}" 是 renderFilterBar() 自己在生成，那是正解不是問題
            if "data-filter=" in code and 'data-filter="all"' not in code and "${" not in code:
                offenders.append(f"{f.name}:{i} 篩選鈕寫死 kind id，應由 renderFilterBar() 生成")
            for kid in kind_ids:
                if kid and f'"{kid}"' in code and "Drill__marker--" not in code:
                    offenders.append(f"{f.name}:{i} 寫死 kind id「{kid}」，應迭代 CFG.kinds")
    if offenders:
        rep.err(sec, f"前端寫死了項目類型 id（{len(offenders)} 處）", offenders[:8])
    else:
        rep.ok(sec, "前端未寫死任何項目類型 id")

    # 1b) 建置腳本同理。它不會讓網站壞掉，但輸出與產物會**用上一個主題的話講話**：
    #     `ui.problemType` 退回寫死的預設值，換主題後統計數字會莫名歸零或亂數。
    vocab = {
        **{k: "kinds" for k in kind_ids if k},
        **{k: "ui.unitTypes" for k in (cfg.get("ui") or {}).get("unitTypes", {})},
        **{g.get("id"): "grades" for g in cfg.get("grades") or [] if isinstance(g, dict)},
    }
    leaks = []
    for f in sorted((ROOT / "src" / "build").glob("*.py")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split("#")[0]
            for word, origin in vocab.items():
                if word and f'"{word}"' in code:
                    leaks.append(f"{f.name}:{i} 寫死了 {origin} 的 id「{word}」")
    if leaks:
        rep.warn(sec, f"建置腳本寫死了課程詞彙（{len(leaks)} 處），換主題會靜靜講錯話", leaks)

    # 2) ui.problemType 必須真的對得到單元，否則 JSON-LD 的 teaches 會是空的
    ptype = (cfg.get("ui") or {}).get("problemType")
    if ptype and ptype not in (cfg.get("ui") or {}).get("unitTypes", {}):
        rep.err(sec, f"ui.problemType「{ptype}」不在 ui.unitTypes 裡，JSON-LD 的 teaches 會是空的")


# ── 文案 ──────────────────────────────────────────────────────────────────
# 這一節看的是「設定檔的字怎麼變成頁面上的字」。三種失敗都不會讓建置掛掉，
# 只會讓使用者看到字面的 {{ui.progressLabel}} 或 <strong>——所以只能靠稽核擋。

# 文案佔位符只有這一份定義，必須與 src/build/seo.py 的 TOKEN_FIELDS
# 及 src/web/js/copy.js 的 TOKEN_FIELDS 完全一致（tests/copy-contract.test.js 會比對）。
COPY_TOKENS = ("units", "lessonUnits", "drillUnits", "slots", "videos", "problems", "evidence")

# HTML 標籤：文案契約改成「逸出 + **粗體**」之後，這些寫法一律無效。
# 從舊版本升級上來的設定檔會靜靜地把 <strong> 印在畫面上，所以要主動抓。
TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*\s*/?>")


def copy_strings(cfg: dict):
    """yield (dotted path, 字串)：設定檔裡所有會變成畫面文案的字串。"""

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            yield_.append((path.lstrip("."), node))

    yield_: list[tuple[str, str]] = []
    for key in COPY_SECTIONS:
        if key in cfg:
            walk(cfg[key], key)
    return yield_


def template_tokens() -> list[str]:
    """index.html 裡所有 {{a.b}}。這是「首屏需要哪些設定欄位」唯一的真相來源。"""
    path = WEB / "index.html"
    if not path.exists():
        return []
    return sorted(set(re.findall(r"\{\{([\w.]+)\}\}", path.read_text())))


def audit_copy(cfg: dict, rep: Report) -> None:
    sec = "文案"

    # 1) 佔位符打錯字：{units} 打成 {unit} 會原樣印在頁面上。
    #    ui.facetFilterHint 有自己的 {name}（由前端填入分面名稱），不走這套。
    bad = [
        f"{path} 用了未定義的佔位符 {{{tok}}}"
        for path, val in copy_strings(cfg)
        for tok in re.findall(r"\{(\w+)\}", val)
        if tok not in COPY_TOKENS and not (path == "ui.facetFilterHint" and tok == "name")
    ]
    if bad:
        rep.err(sec, f"文案佔位符打錯字（{len(bad)} 處），會原樣印在頁面上"
                     f"。可用：{'、'.join(COPY_TOKENS)}", bad[:8])

    # 2) #28：index.html 用到的 {{a.b}} 沒設定，就會原樣輸出到正式 HTML。
    #    以前 build 只印一行「未解析 [...]」，audit 依然 0 錯誤——換主題的人根本
    #    不知道有這幾個欄位存在（它們也不在 schema 裡，見 #15）。
    def lookup(dotted: str):
        node = cfg
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    tokens = template_tokens()
    if missing := [t for t in tokens if lookup(t) is None]:
        rep.err(
            sec,
            f"index.html 用到 {len(missing)} 個沒有設定的文案欄位，"
            "會有字面的 {{…}} 出現在正式頁面上",
            [f"{{{{{t}}}}} ← 設定檔缺 {t}" for t in missing],
        )
    elif tokens:
        rep.ok(sec, f"index.html 的 {len(tokens)} 個文案佔位符都有對應的設定")

    # 3) 產物複驗：真的送出去的那份 HTML 裡不該有任何 {{…}}。
    #    第 2 條只看得到 index.html 這個模板，這一條連 seo.py 自己漏掉的都抓得到。
    built = DIST / "index.html"
    dist_cfg = load_json(DIST / "course.json")
    same_course = isinstance(dist_cfg, dict) and (dist_cfg.get("config") or {}).get(
        "site", {}
    ).get("project") == (cfg.get("site") or {}).get("project")
    if built.exists() and same_course:
        if left := sorted(set(re.findall(r"\{\{[\w.]+\}\}", built.read_text()))):
            rep.err(sec, f"{DIST.name}/index.html 還有 {len(left)} 個沒替換掉的佔位符"
                         "（重跑 make build 再看一次）", left)
        else:
            rep.ok(sec, f"{DIST.name}/index.html 沒有殘留的佔位符")

    # 4) 文案不吃 HTML：一律先逸出，只認得 `**粗體**`。
    #    寫 <strong> 以前在少數幾個欄位「剛好會生效」，其餘欄位原樣印出——
    #    同一個 stance 物件的 intro 與 outro 就是相反的（#20）。現在全部一致。
    if tagged := [f"{path}：{val[:60]}" for path, val in copy_strings(cfg) if TAG.search(val)]:
        rep.err(
            sec,
            f"{len(tagged)} 個文案欄位寫了 HTML 標籤。文案一律先逸出，"
            "標籤只會原樣印在頁面上——要強調請改用 **粗體**",
            tagged[:8],
        )
    else:
        rep.ok(sec, "文案欄位都沒有 HTML 標籤（一律逸出 + **粗體**）")


def audit_config(cfg: dict, rep: Report) -> None:
    sec = "設定檔"
    # 設定檔可能本身就壞掉——稽核要能報出來，不能自己爆掉，所以一律用 .get()
    chapters = [c for c in cfg.get("chapters") or [] if isinstance(c, dict)]

    schema = load_json(SCHEMA)
    if isinstance(schema, dict):
        errs: list[str] = []
        validate(cfg, schema, "config", schema.get("$defs", {}), errs)
        if errs:
            rep.err(sec, f"course.config.json 不符合 schema（{len(errs)} 項）", errs)
        else:
            rep.ok(
                sec,
                f"schema 通過 · {len(chapters)} 章 · {len(cfg.get('kinds', []))} 種項目類型",
            )
    else:
        rep.warn(sec, f"找不到 {SCHEMA.name}，略過 schema 驗證")

    # 章節碼唯一、來源檔存在
    codes = [c.get("code") for c in chapters]
    if dupe := [c for c, n in Counter(codes).items() if n > 1]:
        rep.err(sec, f"章節碼重複：{'、'.join(dupe)}")
    if missing := sorted(
        {
            c["source"]
            for c in chapters
            if c.get("source") and not (DATA / f"{c['source']}.json").exists()
        }
    ):
        rep.err(sec, f"找不到來源檔 {len(missing)} 個", [f"data/{s}.json" for s in missing])

    # nav 分組必須不多不少剛好涵蓋所有章節，否則側欄會漏掉一整章
    nav_codes = [code for grp in cfg.get("nav", []) for code in grp.get("chapters", [])]
    if cfg.get("nav"):
        if orphan := [c for c in codes if c not in nav_codes]:
            rep.err(sec, f"nav 沒有涵蓋 {'、'.join(orphan)}（側欄會看不到）")
        if ghost := [c for c in nav_codes if c not in codes]:
            rep.err(sec, f"nav 指向不存在的章節：{'、'.join(ghost)}")
        if again := [c for c, n in Counter(nav_codes).items() if n > 1]:
            rep.err(sec, f"nav 重複列出：{'、'.join(again)}")

    # 圖示必須已經打包進 sprite，否則線上是空白方塊
    icons = sprite_icons()
    used = {
        f"site.brandIcon={cfg.get('site', {}).get('brandIcon')}": cfg.get("site", {}).get(
            "brandIcon"
        ),
        **{f"{c.get('code')}={c.get('icon')}": c.get("icon") for c in chapters},
        **{
            f"stats[{i}]={s.get('icon')}": s.get("icon")
            for i, s in enumerate(cfg.get("ui", {}).get("stats", []))
        },
        **{
            f"landing.steps[{i}]={s.get('icon')}": s.get("icon")
            for i, s in enumerate(cfg.get("landing", {}).get("steps", []))
        },
    }
    if absent := sorted(label for label, name in used.items() if name and name not in icons):
        rep.err(
            sec,
            f"{len(absent)} 個圖示不在 sprite 內（跑 COURSE={COURSE_REL} make icons 重打包）",
            absent,
        )
    else:
        rep.ok(
            sec,
            f"圖示 {len({n for n in used.values() if n})} 個全部已打包（sprite 共 {len(icons)} 個）",
        )

    # tone 必須有對應的 .Label--<tone> 樣式，否則標籤會變成沒有顏色的灰底
    tones = css_tones()
    bad_tone = [
        f"{group}[{o['id']}].tone={o['tone']}"
        for group in ("kinds", "grades")
        for o in cfg.get(group, [])
        if o.get("tone") and o["tone"] not in tones
    ]
    if bad_tone:
        rep.err(
            sec,
            f"{len(bad_tone)} 個 tone 沒有對應樣式（可用：{'、'.join(sorted(tones))}）",
            bad_tone,
        )

    # id 唯一
    for group in ("kinds", "grades"):
        ids = [o.get("id") for o in cfg.get(group, []) if isinstance(o, dict)]
        if d := [i for i, n in Counter(ids).items() if n > 1]:
            rep.err(sec, f"{group} id 重複：{'、'.join(d)}")

    # 詞彙模組可 import 且介面齊全
    sys.path.insert(0, str(COURSE))
    for key, attrs in (
        ("facets", ("extract", "GROUPS", "GROUP_OF")),
        ("categories", ("classify", "NAMES")),
    ):
        name = (cfg.get("taxonomy") or {}).get(key)
        if not name:
            continue
        try:
            mod = importlib.import_module(name)
        except Exception as e:  # 任何 import 失敗都要報出來，不能讓稽核自己爆掉
            rep.err(sec, f"taxonomy.{key} 模組 {name} 匯入失敗：{type(e).__name__}: {e}")
            continue
        if lack := [a for a in attrs if not hasattr(mod, a)]:
            rep.err(sec, f"taxonomy.{key} 模組 {name} 缺少 {'、'.join(lack)}")

    # 統計欄位要對得上 build 產出的 meta（沒建置過就跳過）
    built = load_json(DIST / "course.json")
    if isinstance(built, dict):
        fields = set(built.get("meta", {}))
        if unknown := [
            str(s.get("field"))
            for s in cfg.get("ui", {}).get("stats", [])
            if s.get("field") not in fields
        ]:
            rep.err(
                sec,
                f"ui.stats 參照不存在的統計欄位：{'、'.join(unknown)}",
                [f"可用：{'、'.join(sorted(fields))}"],
            )

    # 佔位符檢查已移到 audit_topic_coupling()：那裡掃 hero/landing/llms/stance
    # 的所有欄位，涵蓋範圍比這裡原本寫死的四條路徑廣。


def checkout_repo() -> str | None:
    """這個 checkout 對應的 GitHub repo（owner/name）；問不到回 None。

    只讀本地 git 設定，不打網路，符合這支腳本「同樣輸入永遠同樣輸出」的前提。
    """
    try:
        out = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    m = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?$", out.stdout.strip())
    return m.group(1) if m else None


def audit_identity(cfg: dict, rep: Report) -> None:
    """留言與網址必須指向**這門課自己**，不是上一個主題、也不是框架作者。

    這一條是真的發生過的：`discussions` 沿用了範例值，讀者的留言全部靜靜流進
    框架自己的 repo，上線之後才被框架作者發現。失敗模式特別惡劣——前端不報錯、
    討論面板正常顯示、出事的是讀者、發現的是別人。

    判斷基準刻意用「這個 checkout 的 origin」而不是寫死框架的 repo 名：
    寫死只擋得住指向框架的那一種，而且框架自己要填回真值就得再寫死一個例外
    （「site.project 不是 body-course 才檢查」——那是把範例課程的名字寫進框架，
    正是這個專案在消滅的東西）。比對 origin 一併擋掉「從別的課程複製設定檔」，
    範例課程也不需要任何例外。
    """
    sec = "設定檔"
    site = cfg.get("site") or {}
    project = str(site.get("project") or "")

    # 1) site.url 與 site.project 對不起來 → sitemap、JSON-LD、OG 卡全指向別人的網域
    m = re.match(r"^https://([\w-]+)\.pages\.dev/?$", str(site.get("url") or ""))
    if m and project and m.group(1) != project:
        rep.err(
            sec,
            f"site.url 指向 {m.group(1)}.pages.dev，但 site.project 是 {project}"
            f"：sitemap、JSON-LD 與 OG 卡都會指向別人的網站",
        )

    disc = cfg.get("discussions") or {}
    if not disc:
        return  # 沒有討論面板是合法的（也是還沒有自己 repo 時的正解）

    # 2) 佔位值只警告：出貨的設定檔本來就是 REPLACE_ME，壞掉好過靜靜送進別人家
    fields = ("repo", "repoId", "categoryId")
    todo = [k for k in fields if not disc.get(k) or "REPLACE_ME" in str(disc.get(k))]
    if todo:
        rep.warn(
            sec,
            f"discussions 有 {len(todo)} 個欄位還沒換（{'、'.join(todo)}）：討論面板會顯示 giscus "
            f"錯誤。到 https://giscus.app 換成自己的 repo，或整組 discussions 刪掉",
        )
        return  # 還是佔位就沒有「指向誰」的問題

    repo = str(disc.get("repo"))
    if disc.get("allowExternalRepo"):
        rep.ok(sec, f"discussions 指向 {repo}（已宣告 allowExternalRepo）")
        return

    own = checkout_repo()
    if own and repo.lower() != own.lower():
        rep.err(
            sec,
            f"discussions.repo 是 {repo}，但這個 checkout 是 {own}"
            f"：讀者的留言會靜靜送進別人的 repo。刻意要送到別的 repo 請設"
            f" discussions.allowExternalRepo: true",
        )
    elif own:
        rep.ok(sec, f"discussions 指向這個 checkout 自己的 repo（{own}）")
    elif project and repo.split("/")[-1] != project:
        # 問不到 origin（下載 tarball、沒有 remote）就退回名字比對這個較弱的訊號
        rep.warn(
            sec,
            f"問不到這個 checkout 的 GitHub repo，無法確認 discussions.repo（{repo}）"
            f"指向自己；它的 repo 名與 site.project（{project}）也對不起來，請人工確認",
        )


def audit_data_files(cfg: dict, opts: dict, rep: Report) -> None:
    """course/data/ 底下每個 JSON 都要有人讀。

    建置改成看內容不看檔名之後，「檔名不對所以整片實證消失」不會再發生；
    剩下的沉默失敗是**頂層鍵打錯**（conditions 寫成 condition）或章節檔沒被
    任何 chapters[].source 指到——資料在檔案裡，網站上卻沒有，且不報錯。
    """
    sec = "設定檔"
    blobs = data_blobs()
    sources = {c.get("source") for c in cfg.get("chapters") or [] if isinstance(c, dict)}
    ignore = set(opts["ignoreDataFiles"])

    # 章節來源檔的解析錯誤由 walk() 報過了，這裡只補其餘的檔案
    if broken := [msg for name, msg in _BAD_JSON if Path(name).stem not in sources]:
        rep.err(sec, f"{len(broken)} 個資料檔不是合法 JSON（內容會整片被跳過）", broken)

    orphan, unused = [], []
    for path, blob in blobs.items():
        if path.name == VIDEO_META or path.name in ignore:
            continue
        if not any(k in blob for k in DATA_KEYS):
            orphan.append(f"data/{path.name}（頂層鍵：{'、'.join(list(blob)[:6]) or '空的'}）")
        elif ("chapter" in blob or "chapters" in blob) and path.stem not in sources:
            unused.append(f"data/{path.name}")

    if orphan:
        rep.err(
            sec,
            f"{len(orphan)} 個資料檔沒有任何一步會讀到"
            f"（可用的頂層鍵：{'、'.join(DATA_KEYS)}；刻意放的請列進 audit.ignoreDataFiles）",
            orphan,
        )
    if unused:
        rep.warn(sec, f"{len(unused)} 個章節檔沒有被任何 chapters[].source 指到", unused)
    if blobs and not orphan:
        rep.ok(sec, f"course/data/ 的 {len(blobs)} 個資料檔全部讀得到（依內容判斷，不看檔名）")


# ── 資料走訪 ──────────────────────────────────────────────────────────────


def walk(cfg: dict, rep: Report) -> list[dict]:
    """把各章來源檔攤平成 [{code, unit}]，順便檢查 JSON 是否壞掉。"""
    chapters = [c for c in cfg.get("chapters") or [] if isinstance(c, dict) and c.get("source")]
    sources: dict[str, object] = {}
    for c in chapters:
        if c["source"] not in sources:
            sources[c["source"]] = load_json(DATA / f"{c['source']}.json")

    for name, blob in sources.items():
        if isinstance(blob, json.JSONDecodeError):
            rep.err("設定檔", f"data/{name}.json 不是合法 JSON：第 {blob.lineno} 行 {blob.msg}")

    out = []
    for c in chapters:
        blob = sources.get(c["source"])
        if not isinstance(blob, dict):
            continue
        if blob.get("chapters"):
            node = next((x for x in blob["chapters"] if x.get("chapter") == c["code"]), None)
        else:
            node = blob if blob.get("chapter") == c["code"] else None
        for u in (node or {}).get("units", []):
            if isinstance(u, dict):
                out.append({"code": c.get("code"), "unit": u})
    return out


def audit_structure(cfg: dict, units: list[dict], opts: dict, rep: Report) -> None:
    sec = "結構與配額"
    quota = {
        c["code"]: (c.get("units", 0), c.get("drills", 0))
        for c in cfg.get("chapters") or []
        if isinstance(c, dict) and c.get("code")
    }
    kind_ids = {k.get("id") for k in cfg.get("kinds", []) if isinstance(k, dict)}
    unit_types = set(cfg.get("ui", {}).get("unitTypes", {}))

    per_chapter = defaultdict(list)
    for row in units:
        per_chapter[row["code"]].append(row["unit"])

    off = []
    for code, (want_u, want_d) in quota.items():
        got_u = len(per_chapter[code])
        got_d = sum(len(u.get("drills") or []) for u in per_chapter[code])
        if got_u != want_u:
            off.append(f"{code} 單元 {got_u}，設定為 {want_u}")
        if got_d != want_d:
            off.append(f"{code} 項目 {got_d}，設定為 {want_d}")
    total_u = len(units)
    total_d = sum(len(r["unit"].get("drills") or []) for r in units)
    if off:
        rep.err(sec, f"配額不符 {len(off)} 項", off)
    else:
        rep.ok(
            sec,
            f"{len(quota)} 章 · 主課 {total_u} · 項目 {total_d} · 合計 {total_u + total_d}，配額全數符合",
        )

    # id 唯一（進度追蹤與深連結都靠它）
    ids = [r["unit"].get("id") for r in units]
    if d := [i for i, n in Counter(ids).items() if n > 1]:
        rep.err(sec, f"單元 id 重複 {len(d)} 個", d)
    if blank := [
        f"{r['code']} 第 {i + 1} 個單元" for i, r in enumerate(units) if not r["unit"].get("id")
    ]:
        rep.err(sec, f"{len(blank)} 個單元沒有 id", blank)

    # 未定義的 kind / type 會讓標籤變成生的 id
    bad_kind = [
        f"{r['unit'].get('id')} / {d.get('name')} kind={d.get('kind')!r}"
        for r in units
        for d in r["unit"].get("drills") or []
        if d.get("kind") not in kind_ids
    ]
    if bad_kind:
        rep.err(
            sec,
            f"{len(bad_kind)} 個項目的 kind 不在 config.kinds（{'、'.join(sorted(kind_ids))}）",
            bad_kind,
        )
    bad_type = [
        f"{r['unit'].get('id')} type={r['unit'].get('type')!r}"
        for r in units
        if r["unit"].get("type") and r["unit"]["type"] not in unit_types
    ]
    if bad_type:
        rep.err(sec, f"{len(bad_type)} 個單元的 type 不在 ui.unitTypes", bad_type)

    # 項目數失衡：一個單元 2 支、隔壁 30 支，通常是策展 agent 偷懶或超載
    lo, hi = opts["drillsPerUnit"]["min"], opts["drillsPerUnit"]["max"]
    skew = [
        f"{r['unit'].get('id')} {len(r['unit'].get('drills') or [])} 支"
        for r in units
        if r["unit"].get("drills") and not (lo <= len(r["unit"]["drills"]) <= hi)
    ]
    if skew:
        rep.warn(sec, f"{len(skew)} 個單元的項目數超出 {lo}–{hi} 支", skew)

    # 同一單元裡的項目名稱重複
    same = [
        f"{r['unit'].get('id')} / {name}"
        for r in units
        for name, n in Counter(d.get("name") for d in r["unit"].get("drills") or []).items()
        if n > 1
    ]
    if same:
        rep.err(sec, f"{len(same)} 個項目在同一單元內重名", same)

    # evidenceAlias 必須指向真的存在的單元
    if ghost := [k for k in cfg.get("evidenceAlias", {}) if k not in set(ids)]:
        rep.err(sec, f"evidenceAlias 指向不存在的單元：{'、'.join(ghost)}")

    rep.stats.update(chapters=len(quota), lesson_units=total_u, drill_units=total_d)


def audit_taxonomy(cfg: dict, units: list[dict], opts: dict, rep: Report) -> None:
    """分類分布：單一類別吃掉不成比例的項目 = patterns 寫太寬。

    根因幾乎都是同一個：`classify()` 的 haystack 含 `target`，所以拿**會出現在
    target 的詞**（分面詞彙、部位詞、目標詞）當 pattern，等於比對到所有以它為
    目標的項目。兩個 taxonomy 模組的詞彙必須互斥。這件事不會報錯，只會讓
    歸類結果悄悄變形，所以改用統計特徵抓。
    """
    sec = "結構與配額"
    mod = load_taxonomy(cfg, "categories")
    if mod is None:
        return  # 沒設定分類維度是合法的，不是缺陷，別發假警報

    counts: Counter = Counter()
    uncategorised = 0
    for r in units:
        for d in r["unit"].get("drills") or []:
            try:
                cid = mod.classify(d)
            except Exception as e:
                rep.err(sec, f"taxonomy.categories 的 classify() 執行失敗：{type(e).__name__}: {e}")
                return
            if cid:
                counts[cid] += 1
            else:
                uncategorised += 1

    classified = sum(counts.values())
    total = classified + uncategorised
    if not total:
        return
    names = getattr(mod, "NAMES", {})
    top = [
        f"{names.get(cid, cid)} {n}（{n / classified:.0%}）" for cid, n in counts.most_common(3)
    ]
    line = (
        f"{len(counts)} 個類別 · 已分類 {classified}/{total}"
        f"（未分類 {uncategorised}，{uncategorised / total:.0%}）· 前三：{'、'.join(top)}"
    )

    share = counts.most_common(1)[0][1] / classified if classified else 0
    if share > opts["maxCategoryShare"]:
        cid, n = counts.most_common(1)[0]
        rep.warn(
            sec,
            f"「{names.get(cid, cid)}」吃掉 {n}/{classified} 個已分類項目（{share:.0%}），"
            f"超過 audit.maxCategoryShare {opts['maxCategoryShare']:.0%}"
            f"——patterns 是不是用到了會出現在 target 欄位的詞？",
            [line],
        )
    elif classified == 0:
        rep.warn(sec, f"{total} 個項目一個都沒被分類（patterns 對不上資料？）")
    else:
        rep.ok(sec, line)

    rep.stats.update(categories_used=len(counts), uncategorised=uncategorised)


# ── 影片 ──────────────────────────────────────────────────────────────────


def videos_of(units: list[dict]) -> list[tuple[str, str, str, dict]]:
    """yield (unit_id, 角色, 標籤, 影片 dict)。角色是 lesson / drill。"""
    out = []
    for r in units:
        u = r["unit"]
        uid = u.get("id") or "?"
        if u.get("lesson"):
            out.append((uid, "lesson", u["lesson"].get("title") or "主課", u["lesson"]))
        for d in u.get("drills") or []:
            out.append((uid, "drill", d.get("name") or "?", d))
    return out


def audit_videos(cfg: dict, units: list[dict], opts: dict, rep: Report) -> None:
    sec = "影片"
    vmeta = load_json(DATA / "video-meta.json")
    if not isinstance(vmeta, dict):
        vmeta = {}
        rep.warn(sec, "找不到 data/video-meta.json，長度與觀看數無從稽核（見 SKILL 第 4 節）")

    nodes = videos_of(units)
    for path in sorted(DATA.glob("alt-lessons-*.json")):
        blob = load_json(path)
        for les in (blob or {}).get("lessons", []) if isinstance(blob, dict) else []:
            if isinstance(les, dict):
                nodes.append((les.get("unit", "?"), "lesson", f"{les.get('lang', '')} 版", les))

    explained, unexplained, malformed = [], [], []
    seen: Counter = Counter()
    within: Counter = Counter()
    hits = 0
    dead, drift, short, long_, unpopular = [], [], [], [], []
    seconds = Counter()

    bounds = {
        role: (
            parse_clock(opts["duration"][role]["min"]),
            parse_clock(opts["duration"][role]["max"]),
        )
        for role in ("lesson", "drill")
    }

    for uid, role, label, v in nodes:
        url = v.get("url")
        if not url:
            # 找不到合格影片而誠實留空是允許的，但一定要在 note 說明為什麼
            note = (v.get("note") or "").strip()
            (explained if note else unexplained).append(f"{uid} / {label}：{note or '沒有 note'}")
            continue
        if not YT.match(url):
            malformed.append(f"{uid} / {label}：{url}")
            continue
        seen[url] += 1
        within[(uid, url)] += 1

        info = vmeta.get(video_id(url) or "")
        if not info:
            continue
        if info.get("status") != "OK":
            dead.append(f"{uid} / {label}：{info.get('status')} {url}")
            continue
        hits += 1
        secs = int(info.get("seconds") or 0)
        seconds[role] += secs

        lo, hi = bounds[role]
        if secs < lo:
            short.append(f"{uid} / {label} {clock(secs)}（下限 {clock(lo)}）")
        elif secs > hi:
            long_.append(f"{uid} / {label} {clock(secs)}（上限 {clock(hi)}）")

        claimed = parse_clock(v.get("duration"))
        if claimed >= 0 and abs(claimed - secs) > opts["driftSeconds"]:
            drift.append(f"{uid} / {label} 寫 {v.get('duration')}，實際 {clock(secs)}")

        if (views := info.get("views")) is not None and views < opts["minViews"]:
            unpopular.append(f"{uid} / {label} {views:,} 次觀看")

    slots = len(nodes)
    filled = slots - len(explained) - len(unexplained)
    coverage = hits / filled if filled else 0
    line = (
        f"{slots} 個影片欄位 · 去重 {len(seen)} 支 · 中繼資料命中 {hits}/{filled}（{coverage:.1%}）"
    )
    if filled and coverage < opts["metaCoverage"]:
        rep.err(sec, f"{line}，低於門檻 {opts['metaCoverage']:.0%}（重跑一次 innertube 取數）")
    else:
        rep.ok(sec, line)

    if unexplained:
        rep.err(sec, f"{len(unexplained)} 個欄位沒有連結也沒有 note 說明原因", unexplained)
    if explained:
        level = rep.warn if len(explained) <= opts["allowMissingUrls"] else rep.err
        level(
            sec,
            f"{len(explained)} 個欄位誠實留空（容許 {opts['allowMissingUrls']} 個）",
            explained,
        )
    if malformed:
        rep.err(sec, f"{len(malformed)} 個連結不是合法的 YouTube watch 網址", malformed)
    if dead:
        rep.err(sec, f"{len(dead)} 支影片在中繼資料裡是不可用狀態", dead)
    if dupe := [f"{uid} 重複用了 {url}" for (uid, url), n in within.items() if n > 1]:
        rep.err(sec, f"{len(dupe)} 支影片在同一單元內重複", dupe)

    shared = sum(1 for n in seen.values() if n > 1)
    if shared > opts["maxSharedVideos"]:
        rep.warn(
            sec, f"跨單元共用 {shared} 支影片，超過門檻 {opts['maxSharedVideos']}（內容重疊過多？）"
        )

    if drift:
        rep.warn(sec, f"{len(drift)} 支影片的宣稱長度與實際差超過 {opts['driftSeconds']} 秒", drift)
    if short or long_:
        rep.warn(
            sec,
            f"{len(short) + len(long_)} 支影片長度超出設定區間"
            f"（主課 {opts['duration']['lesson']['min']}–{opts['duration']['lesson']['max']}、"
            f"項目 {opts['duration']['drill']['min']}–{opts['duration']['drill']['max']}）",
            short + long_,
        )
    if unpopular:
        rep.warn(
            sec,
            f"{len(unpopular)} 支影片觀看數低於 {opts['minViews']:,}（品質門檻，人工看一眼）",
            unpopular,
        )

    total = sum(seconds.values())
    rep.ok(
        sec,
        f"所有欄位合計 {clock(total)}"
        f"（主課 {clock(seconds['lesson'])} + 項目 {clock(seconds['drill'])}，含多語言版本）",
    )
    rep.stats.update(
        video_slots=slots,
        video_unique=len(seen),
        meta_coverage=round(coverage, 4),
        duration_seconds=total,
    )


# ── 內容深度 ──────────────────────────────────────────────────────────────


def audit_depth(cfg: dict, units: list[dict], opts: dict, rep: Report) -> None:
    sec = "內容深度"
    grades = {g.get("id") for g in cfg.get("grades", []) if isinstance(g, dict)}
    need = set(opts["requireAssessment"])
    min_chars = opts["minAssessmentChars"]

    thin = [
        f"{r['unit'].get('id')} / {r['unit'].get('name')}"
        f"（{len(r['unit'].get('assessment') or '')} 字）"
        for r in units
        if r["unit"].get("type") in need and len(r["unit"].get("assessment") or "") < min_chars
    ]
    if need:
        if thin:
            rep.err(sec, f"{len(thin)} 個單元缺少可操作的 assessment（至少 {min_chars} 字）", thin)
        else:
            rep.ok(
                sec,
                f"{sum(1 for r in units if r['unit'].get('type') in need)} 個 {'/'.join(sorted(need))} 單元都有 assessment",
            )

    if nowhy := [
        f"{r['unit'].get('id')}"
        for r in units
        if r["unit"].get("lesson") and not r["unit"]["lesson"].get("why")
    ]:
        rep.warn(sec, f"{len(nowhy)} 堂主課沒有寫選片理由 why", nowhy)

    # 單元層級實證
    ev_units, bad_grade = set(), []
    for path, cond in data_rows("conditions"):
        if not cond.get("unit"):
            continue
        ev_units.add(cond["unit"])
        if grades and cond.get("evidence_grade") not in grades:
            bad_grade.append(f"{path.name} · {cond['unit']} grade={cond.get('evidence_grade')!r}")

    alias = cfg.get("evidenceAlias", {})

    # 實證條目的 key 只有兩種歸宿：對得到單元，或是立場聲明（前綴 concept-）。
    # 兩者皆非就是寫了也不會出現在網站任何地方，而且數字照樣把它算進去。
    prefix = stance_prefix(cfg)
    all_ids = {r["unit"].get("id") for r in units}
    valid = all_ids | {alias.get(i, i) for i in all_ids}
    if lost := sorted(k for k in ev_units if k not in valid and not k.startswith(prefix)):
        rep.err(
            sec,
            f"{len(lost)} 筆實證的 unit 既對不到單元，也不是立場聲明"
            f"（要當立場聲明請用 {prefix}* 命名，要掛到單元請用 evidenceAlias）",
            lost,
        )

    stance_keys = sorted(k for k in ev_units if k.startswith(prefix))
    targeted = {
        alias.get(r["unit"].get("id"), r["unit"].get("id"))
        for r in units
        if r["unit"].get("type") in need
    }
    # config 沒有 grades 就是宣告「這門課沒有實證維度」（語言課、技能課常見）。
    # 這時候還一直列出「未查核」的單元只是噪音，會淹掉真正該看的警告。
    if need and targeted and grades:
        covered = len(targeted & ev_units)
        gap = sorted(targeted - ev_units)
        msg = f"實證查核 {covered}/{len(targeted)} 個主題（另有 {len(ev_units - targeted)} 個非章節主題）"
        rep.warn(sec, msg + "，未查核：" + "、".join(gap), []) if gap else rep.ok(sec, msg)

    # 類別層級文獻
    cats, thin_cats, bad_ref = {}, [], []
    for path, cat in data_rows("categories"):
        if not cat.get("id"):
            continue
        cats[cat["id"]] = cat
        if grades and cat.get("evidence_grade") not in grades:
            bad_grade.append(f"{path.name} · {cat['id']} grade={cat.get('evidence_grade')!r}")
        cites = cat.get("citations") or []
        if len(cites) < opts["minCitations"]:
            thin_cats.append(f"{cat['id']}（{len(cites)} 篇）")
        for c in cites:
            # 生醫走 PubMed（pmid），人文社科走 Crossref（doi）——兩者擇一即可。
            # PubMed 幾乎不收邏輯、語言學、倫理學的期刊，硬要 PMID 只會逼出捏造的引用。
            pmid = str(c.get("pmid") or "").strip()
            doi = str(c.get("doi") or "").strip()
            ok_pmid = pmid.isdigit() and 6 <= len(pmid) <= 9
            ok_doi = doi.startswith("10.") and "/" in doi
            if not (ok_pmid or ok_doi):
                bad_ref.append(
                    f"{cat['id']} · pmid={c.get('pmid')!r} doi={c.get('doi')!r}"
                    f" · {(c.get('title') or '')[:40]}"
                )

    if bad_grade:
        rep.err(
            sec,
            f"{len(bad_grade)} 筆 evidence_grade 不在 config.grades（{'、'.join(sorted(grades))}）",
            bad_grade,
        )
    if bad_ref:
        rep.err(
            sec,
            f"{len(bad_ref)} 筆引用沒有合法的 pmid 或 doi（跑 make verify 打真實 API 才算數）",
            bad_ref,
        )
    if thin_cats:
        rep.warn(sec, f"{len(thin_cats)} 個類別的文獻少於 {opts['minCitations']} 篇", thin_cats)
    if cats:
        n_cites = sum(len(c.get("citations") or []) for c in cats.values())
        # 三個數字一起講。只講其中一個，README 與首頁就會各說各話（#16）。
        rep.ok(
            sec,
            f"實證合計 {len(ev_units) + len(cats)} 則 = 單元層級 {len(ev_units)}"
            f"（含立場聲明 {len(stance_keys)}）+ 類別層級 {len(cats)} · 引用 {n_cites} 篇",
        )

    rep.stats.update(
        evidence_units=len(ev_units),
        stance=len(stance_keys),
        categories=len(cats),
        evidence_total=len(ev_units) + len(cats),
    )
    audit_built_meta(cfg, units, ev_units, stance_keys, cats, rep)


def audit_built_meta(
    cfg: dict, units: list[dict], ev_units: set, stance_keys: list, cats: dict, rep: Report
) -> None:
    """比對 build 產物與稽核自己數出來的數字。

    #13 的病徵就是這個：資料裡有 7 則立場聲明，audit 數得出來，build 只放了 3 則，
    兩邊對不起來卻沒有人比對。這條規則讓「build 悄悄丟掉資料」直接變成錯誤。
    """
    sec = "內容深度"
    built = load_json(DIST / "course.json")
    if not isinstance(built, dict):
        return  # 還沒建置過就沒得比
    meta = built.get("meta") or {}
    if meta.get("lesson_units") != len(units):
        return  # dist/ 是別門課或還沒重建的產物，比了只會誤報

    expect = {
        "stance（首頁立場聲明）": (len(built.get("stance") or []), len(stance_keys)),
        "meta.evidence_checked": (meta.get("evidence_checked"), len(ev_units)),
    }
    for key, want in (
        ("meta.category_evidence_checked", len(cats)),
        ("meta.evidence_total", len(ev_units) + len(cats)),
    ):
        if key.split(".")[1] in meta:
            expect[key] = (meta[key.split(".")[1]], want)

    if off := [f"{k}：產物 {got}，資料裡有 {want}" for k, (got, want) in expect.items() if got != want]:
        rep.err(
            sec,
            f"{len(off)} 個數字與 dist/course.json 對不起來（build 把資料丟掉了？重跑 make build）",
            off,
        )


# ── 進入點 ────────────────────────────────────────────────────────────────


def main() -> int:
    strict = "--strict" in sys.argv
    as_json = "--json" in sys.argv

    cfg = load_json(COURSE / "course.config.json")
    if not isinstance(cfg, dict):
        print(f"✗ 讀不到 {COURSE / 'course.config.json'}：{cfg}", file=sys.stderr)
        return 1
    opts = deep_merge(DEFAULTS, cfg.get("audit") or {})

    rep = Report()
    audit_config(cfg, rep)
    audit_copy(cfg, rep)
    audit_topic_coupling(cfg, rep)
    audit_identity(cfg, rep)
    audit_data_files(cfg, opts, rep)
    units = walk(cfg, rep)
    audit_structure(cfg, units, opts, rep)
    audit_taxonomy(cfg, units, opts, rep)
    audit_videos(cfg, units, opts, rep)
    audit_depth(cfg, units, opts, rep)

    errors, warnings = rep.count("error"), rep.count("warn")

    if as_json:
        print(json.dumps({**rep.as_json(), "ok": errors == 0}, ensure_ascii=False, indent=1))
    else:
        print(f"稽核 {COURSE.name}/（離線，不打網路；連結存活與 PMID 真偽請跑 make verify）")
        rep.emit()
        verdict = (
            f"\n✗ {errors} 個錯誤" if errors else ("\n⚠ 沒有錯誤" if warnings else "\n✓ 全部通過")
        )
        print(f"{verdict}、{warnings} 個警告\n" if warnings else f"{verdict}\n")

    return 1 if errors or (strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
