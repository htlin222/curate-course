#!/usr/bin/env python3
"""獨立驗證所有 PubMed 引用是否真實存在，且標題與 PMID 對得上。

不信任任何上游宣稱（含 agent 自稱已驗證），一律重打 PubMed E-utilities。
捏造的引用比沒有引用更糟，這是最後一道關卡。

用法：
    python3 verify_refs.py           # 驗證並列出不符者
    python3 verify_refs.py --fix     # 額外用 API 回傳值覆寫 title/journal/year
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
BATCH = 180


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fetch(pmids: list[str]) -> dict:
    data = urllib.parse.urlencode(
        {"db": "pubmed", "retmode": "json", "id": ",".join(pmids)}
    ).encode()
    req = urllib.request.Request(ESUMMARY, data=data, headers={"User-Agent": "body-course/1.0"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read()).get("result", {})


BLOBS: dict[Path, dict] = {}


def collect() -> list[tuple[str, str, str, dict]]:
    """回傳 (檔名, 類別 id, pmid, citation dict)。citation 是可就地修改的參照。"""
    out = []
    for path in sorted(DATA.glob("drill-evidence-*.json")):
        blob = json.loads(path.read_text())
        BLOBS[path] = blob
        for cat in blob.get("categories", []):
            if not isinstance(cat, dict):
                continue
            for c in cat.get("citations", []):
                pmid = str(c.get("pmid") or "").strip()
                if pmid.isdigit():
                    out.append((path.name, cat.get("id", "?"), pmid, c))
                else:
                    out.append((path.name, cat.get("id", "?"), "", c))
    return out


def main() -> int:
    fix = "--fix" in sys.argv
    rows = collect()
    bad_pmid = [r for r in rows if not r[2]]
    rows = [r for r in rows if r[2]]
    pmids = sorted({r[2] for r in rows})

    print(f"檢查 {len(rows)} 筆引用（{len(pmids)} 個不重複 PMID）…\n")

    meta: dict = {}
    for i in range(0, len(pmids), BATCH):
        meta.update(fetch(pmids[i : i + BATCH]))
        time.sleep(0.4)

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

    if bad_pmid:
        print(f"✗ PMID 格式無效 {len(bad_pmid)} 筆：")
        for f, cid, _, c in bad_pmid[:10]:
            print(f"   {f} · {cid} · {c.get('title', '')[:60]}")

    if missing:
        print(f"\n✗ PubMed 查無此筆 {len(missing)} 個（極可能是捏造的）：")
        for f, cid, p, t in missing[:20]:
            print(f"   {f} · {cid} · PMID {p} · {t[:56]}")

    if mismatch:
        print(f"\n⚠ 標題與 PMID 不符 {len(mismatch)} 筆：")
        for _f, cid, p, claimed, actual in mismatch[:15]:
            print(f"   {cid} · PMID {p}")
            print(f"      宣稱: {claimed[:78]}")
            print(f"      實際: {actual[:78]}")

    ok = len(rows) - len(missing) - len(mismatch)
    print(f"\n通過 {ok} / {len(rows)}（{ok / max(len(rows), 1) * 100:.1f}%）")

    if fix:
        for path, blob in BLOBS.items():
            path.write_text(json.dumps(blob, ensure_ascii=False, indent=1))
        print(f"→ --fix：已用 PubMed 回傳值覆寫 {len(BLOBS)} 個檔案的 title/journal/year")

    return 1 if (missing or bad_pmid) else 0


if __name__ == "__main__":
    sys.exit(main())
