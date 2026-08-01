#!/usr/bin/env python3
"""獨立驗證所有引用是否真實存在，且標題與識別碼對得上。

生醫走 PubMed（pmid），人文社科走 Crossref（doi）——PubMed 幾乎不收邏輯學、
論證理論與倫理學的期刊，在那些主題硬要 PMID 只會逼出捏造的引用。

不信任任何上游宣稱（含 agent 自稱已驗證），一律重打 PubMed E-utilities 或 Crossref。
捏造的引用比沒有引用更糟，這是最後一道關卡。

用法：
    python3 verify_refs.py           # 驗證並列出不符者
    python3 verify_refs.py --fix     # 額外用 API 回傳值覆寫 title/journal/year
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑

ROOT = coursepath.ROOT
DATA = coursepath.course_dir() / "data"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
CROSSREF = "https://api.crossref.org/works/"
BATCH = 180

# Crossref 的 polite pool 要求 User-Agent 帶聯絡信箱，沒帶會被降速。
CONTACT = os.environ.get("CROSSREF_MAILTO", "curate-course@example.com")
UA = f"curate-course/1.0 (mailto:{CONTACT})"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fetch(pmids: list[str]) -> dict:
    data = urllib.parse.urlencode(
        {"db": "pubmed", "retmode": "json", "id": ",".join(pmids)}
    ).encode()
    req = urllib.request.Request(ESUMMARY, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read()).get("result", {})


def fetch_doi(doi: str) -> dict | None:
    """Crossref 逐筆反查，回傳與 esummary 對齊的 {title, source, pubdate}。"""
    url = CROSSREF + urllib.parse.quote(doi, safe="")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as res:
            m = json.loads(res.read())["message"]
    except Exception:
        return None
    return {
        "title": (m.get("title") or [""])[0],
        "source": (m.get("container-title") or [""])[0],
        "pubdate": str((m.get("issued", {}).get("date-parts") or [[""]])[0][0] or ""),
    }


BLOBS: dict[Path, dict] = {}
BROKEN: list[str] = []

# 兩層都要掃：類別層級（categories）與單元層級（conditions）。只驗其中一層
# 等於留了一半的門沒鎖。
LAYERS = (("categories", "id"), ("conditions", "unit"))


def collect() -> list[tuple[str, str, str, dict]]:
    """回傳 (檔名, 類別／單元 id, 識別碼, citation dict)。citation 是可就地修改的參照。

    掃 `course/data/*.json` 並**依頂層鍵**判斷是哪一層，不看檔名。這裡本來寫死
    `drill-evidence-*.json` 與 `oe-*.json` 兩個 glob，但那兩個前綴是「這門課用
    OpenEvidence」的歷史（見 build.py）：換一個實證來源、改了檔名，這支腳本會
    安靜地驗 0 筆然後印「通過 0/0」——漏驗比報錯更糟，因為它會通過。

    識別碼優先取 `pmid`（生醫），沒有就取 `doi`（人文社科走 Crossref）。
    """
    out = []
    for path in sorted(DATA.glob("*.json")):
        try:
            blob = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            BROKEN.append(f"{path.name}：第 {e.lineno} 行 {e.msg}")
            continue
        if not isinstance(blob, dict):
            continue
        for key, id_field in LAYERS:
            entries = blob.get(key)
            if not isinstance(entries, list):
                continue
            # 只有真的含引用層的檔案才進 BLOBS，--fix 才不會去重寫章節檔
            BLOBS[path] = blob
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                eid = entry.get(id_field, "?")
                for c in entry.get("citations", []):
                    pmid = str(c.get("pmid") or "").strip()
                    doi = str(c.get("doi") or "").strip()
                    if pmid.isdigit():
                        out.append((path.name, eid, f"pmid:{pmid}", c))
                    elif doi.startswith("10."):
                        out.append((path.name, eid, f"doi:{doi}", c))
                    else:
                        out.append((path.name, eid, "", c))
    return out


def main() -> int:
    fix = "--fix" in sys.argv
    rows = collect()
    bad_pmid = [r for r in rows if not r[2]]
    rows = [r for r in rows if r[2]]
    ids = sorted({r[2] for r in rows})
    pmids = [i.removeprefix("pmid:") for i in ids if i.startswith("pmid:")]
    dois = [i.removeprefix("doi:") for i in ids if i.startswith("doi:")]

    parts = [f"{len(pmids)} 個 PMID"] if pmids else []
    if dois:
        parts.append(f"{len(dois)} 個 DOI")
    print(f"檢查 {len(rows)} 筆引用（{'、'.join(parts) or '0 個識別碼'}）…\n")

    meta: dict = {}
    for i in range(0, len(pmids), BATCH):
        meta.update({f"pmid:{k}": v for k, v in fetch(pmids[i : i + BATCH]).items()})
        time.sleep(0.4)
    for doi in dois:  # Crossref 沒有批次端點，逐筆打
        rec = fetch_doi(doi)
        if rec:
            meta[f"doi:{doi}"] = rec
        time.sleep(0.15)

    missing, mismatch = [], []
    for fname, cid, pmid, c in rows:
        rec = meta.get(pmid)
        if not rec or rec.get("error") or not rec.get("title"):
            missing.append((fname, cid, pmid, c.get("title", "")))
            continue
        actual, claimed = rec["title"].rstrip("."), c.get("title", "")
        a, b = norm(actual), norm(claimed)
        if not (a.startswith(b[:55]) or b.startswith(a[:55]) or b[:55] in a):
            mismatch.append((fname, cid, pmid, claimed, actual))
        if fix:
            c["title"] = actual
            c["journal"] = rec.get("source", c.get("journal"))
            year = (rec.get("pubdate") or "")[:4]
            if year.isdigit():
                c["year"] = int(year)

    if BROKEN:
        print(f"✗ {len(BROKEN)} 個資料檔不是合法 JSON（裡面的引用整批沒驗到）：")
        for b in BROKEN:
            print(f"   {b}")

    if bad_pmid:
        print(f"✗ 缺少可驗證的識別碼（pmid 或 doi）{len(bad_pmid)} 筆：")
        for f, cid, _, c in bad_pmid[:10]:
            print(f"   {f} · {cid} · {c.get('title', '')[:60]}")

    if missing:
        print(f"\n✗ API 查無此筆 {len(missing)} 個（極可能是捏造的）：")
        for f, cid, p, t in missing[:20]:
            print(f"   {f} · {cid} · {p} · {t[:56]}")

    if mismatch:
        print(f"\n⚠ 標題與識別碼不符 {len(mismatch)} 筆：")
        for _f, cid, p, claimed, actual in mismatch[:15]:
            print(f"   {cid} · {p}")
            print(f"      宣稱: {claimed[:78]}")
            print(f"      實際: {actual[:78]}")

    ok = len(rows) - len(missing) - len(mismatch)
    print(f"\n通過 {ok} / {len(rows)}（{ok / max(len(rows), 1) * 100:.1f}%）")

    if fix:
        for path, blob in BLOBS.items():
            path.write_text(json.dumps(blob, ensure_ascii=False, indent=1))
        print(f"→ --fix：已用 API 回傳值覆寫 {len(BLOBS)} 個檔案的 title/journal/year")

    return 1 if (missing or bad_pmid or BROKEN) else 0


if __name__ == "__main__":
    sys.exit(main())
