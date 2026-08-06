#!/usr/bin/env python3
"""只驗這次改動到的資料檔——給 PR 用的增量版 make verify。

為什麼需要這支：

`make verify` 打幾百個 YouTube 與 PubMed 端點，跑 30 分鐘，所以它只排在每週。
但「每週」的意思是**改壞了要等最多七天才知道**，而且實測更慘——這個 repo 的
verify.yml 從加進來到現在一次都沒跑過（cron 還沒輪到），於是 conditions 那一層
144 筆沒有識別碼的引用躺了不知道多久，而 verify_refs.py 一直在報，只是沒有人
在執行路徑上。

**有檢查不等於檢查在執行路徑上。** 這支腳本讓「這個 PR 動到的東西」在 PR 上
就驗完：改一章通常是十幾支影片、幾十筆引用，幾秒鐘的事。沒動到資料檔就直接
跳過，不浪費 CI 配額。全量驗證仍然每週跑，兩者不互相取代。

用法：
    python3 src/build/verify_changed.py <base-ref>    # 例如 origin/main
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑
import refsources
import verify_refs

ROOT = coursepath.ROOT


def changed_data_files(base: str) -> list[Path]:
    """這次改動到的課程資料檔。取不到 diff 就回空，讓呼叫端安全跳過。"""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return []
    return [
        ROOT / line
        for line in out.splitlines()
        # 只看課程的 data/：改框架程式碼不需要重打外部 API，那是 make check 的事
        if "/data/" in line and line.endswith(".json") and (ROOT / line).is_file()
    ]


def citations_in(paths: list[Path]) -> list[tuple[str, str, str, dict]]:
    """(檔名, 條目 id, 識別碼, citation)。形狀刻意與 verify_refs.collect() 一致。"""
    rows = []
    for path in paths:
        try:
            blob = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(blob, dict):
            continue
        for key, id_field in verify_refs.LAYERS:
            for entry in blob.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                for c in entry.get("citations", []):
                    pmid = str(c.get("pmid") or "").strip()
                    doi = str(c.get("doi") or "").strip()
                    ident = (
                        f"pmid:{pmid}" if pmid.isdigit()
                        else f"doi:{doi}" if doi.startswith("10.")
                        else ""
                    )
                    rows.append((path.name, entry.get(id_field, "?"), ident, c))
    return rows


def main(argv: list[str]) -> int:
    base = argv[0] if argv else "origin/main"
    files = changed_data_files(base)
    if not files:
        print(f"這次沒有動到任何課程資料檔（比對 {base}），略過增量驗證。")
        return 0

    print(f"改動的資料檔 {len(files)} 個：")
    for f in files:
        print(f"   {f.relative_to(ROOT)}")

    rows = citations_in(files)
    if not rows:
        print("\n這些檔案裡沒有引用，只需要 make check 的離線稽核。")
        return 0

    no_id = [r for r in rows if not r[2]]
    rows = [r for r in rows if r[2]]
    pmids = sorted({r[2].removeprefix("pmid:") for r in rows if r[2].startswith("pmid:")})
    dois = sorted({r[2].removeprefix("doi:") for r in rows if r[2].startswith("doi:")})
    print(refsources.credentials_summary())
    print(f"\n驗證 {len(rows)} 筆引用（{len(pmids)} 個 PMID、{len(dois)} 個 DOI）…")

    meta: dict = {}
    for i in range(0, len(pmids), verify_refs.BATCH):
        batch = verify_refs.fetch(pmids[i : i + verify_refs.BATCH])
        if not batch:
            # fetch 內部已經退避重試、也試過 Europe PMC 了。兩邊都拿不到就是
            # 外部服務出事，不該讓 PR 紅掉——每週的全量驗證仍會抓到。
            print("⚠ PubMed 與 Europe PMC 都取不到數——這一輪跳過")
            return 0
        meta.update({f"pmid:{k}": v for k, v in batch.items()})

    # DOI 以前整段跳過（原註解：「Crossref 逐筆打太慢，留給每週的全量驗證」）。
    # 但走 DOI 的撤稿偵測正是這次補起來的洞——Crossref 的 update-to 對真實的
    # 撤稿論文可能整個是 null，要靠 OpenAlex 才看得見。一個 PR 通常只動幾十筆
    # 引用，逐筆打是幾秒鐘的事；為了省這幾秒讓撤稿的 DOI 進 main、再等一週才
    # 被發現，不划算。
    for doi in dois:
        if rec := verify_refs.fetch_doi(doi):
            meta[f"doi:{doi}"] = rec
        time.sleep(0.15)

    missing, retracted = [], []
    for fname, cid, ident, c in rows:
        rec = meta.get(ident)
        if not rec or rec.get("error") or not rec.get("title"):
            missing.append(f"{fname} · {cid} · {ident} · {(c.get('title') or '')[:50]}")
            continue
        types = {str(t).lower() for t in (rec.get("pubtype") or [])}
        if "retracted publication" in types or rec.get("retracted"):
            retracted.append(f"{fname} · {cid} · {ident} · {rec['title'][:50]}")

    if no_id:
        print(f"\n✗ {len(no_id)} 筆引用沒有 pmid 或 doi（沒有識別碼就沒有人能覆核）：")
        for f, cid, _, c in no_id[:10]:
            print(f"   {f} · {cid} · {(c.get('title') or '')[:56]}")
    if missing:
        print(f"\n✗ API 查無此筆 {len(missing)} 筆（極可能是捏造的）：")
        for m in missing[:10]:
            print(f"   {m}")
    if retracted:
        print(f"\n✗ 引用了已撤稿的論文 {len(retracted)} 筆：")
        for r in retracted:
            print(f"   {r}")

    bad = len(no_id) + len(missing) + len(retracted)
    print(f"\n{'✗' if bad else '✓'} 這次改動的引用：{len(rows) - len(missing) - len(retracted)} 通過"
          f"{f'，{bad} 筆有問題' if bad else ''}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
