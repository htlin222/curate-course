#!/usr/bin/env python3
"""獨立驗證所有引用是否真實存在，且標題與識別碼對得上。

生醫走 PubMed（pmid），人文社科走 Crossref（doi）——PubMed 幾乎不收邏輯學、
論證理論與倫理學的期刊，在那些主題硬要 PMID 只會逼出捏造的引用。

不信任任何上游宣稱（含 agent 自稱已驗證），一律重打 PubMed E-utilities 或 Crossref。
捏造的引用比沒有引用更糟，這是最後一道關卡。

除了「存不存在」，還查兩件事：**這篇有沒有被撤稿**（esummary 的 pubtype 一直
有回傳，只是以前沒讀——引用撤稿論文比沒有引用更糟，因為它看起來完全通過驗證），
以及**研究設計是什麼**（PubMed 自己標的 publication type，比策展 agent 手寫的
自由文字可靠；evidence_grade 建立在這上面）。

用法：
    python3 verify_refs.py             # 驗證並列出不符者
    python3 verify_refs.py --fix       # 用 API 回傳值覆寫 title/journal/year/design
    python3 verify_refs.py --resolve   # 補上缺失的識別碼：先從 url 抽，再用標題
                                       # 反查 PubMed，最後試 Crossref。配 --fix 用
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


FILLED: list[str] = []


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# PubMed 的 publication type → 課程用的 design 名稱。
#
# 研究設計以前是策展 agent 自己填的自由文字：它說 meta-analysis 就是
# meta-analysis，而 evidence_grade 又建立在這上面——等於整個證據階梯的地基
# 是一句宣稱。但 PubMed 自己就標了 publication type，esummary 一直有回傳，
# 只是沒人讀。`--fix` 從這裡填 design，階梯的底層就從「宣稱」變成「可覆核」。
#
# 順序有意義：一篇論文常常同時是 Meta-Analysis 與 Systematic Review，取最強的。
PUBTYPE_DESIGN = [
    ("meta-analysis", "meta-analysis"),
    ("systematic review", "systematic review"),
    ("randomized controlled trial", "RCT"),
    ("clinical trial", "RCT"),
    ("observational study", "observational"),
    ("case reports", "case report"),
    ("review", "narrative review"),
]


def design_of(pubtypes: list) -> str | None:
    """PubMed 的 pubtype 清單 → 最強的那個設計名稱。認不出來就回 None，不要猜。"""
    have = {str(t).lower() for t in (pubtypes or [])}
    for needle, design in PUBTYPE_DESIGN:
        if needle in have:
            return design
    return None


ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


def resolve_pmid(title: str) -> tuple[str, str] | None:
    """用標題反查 PMID。回傳 (pmid, PubMed 上的標題)；比對不夠像就回 None。

    這是給「有標題、有期刊、有年份，就是沒有識別碼」的引用用的。它們多半是真的
    論文，只是當初沒抄下 PMID——而沒有識別碼的引用**任何人都無法覆核**，跟捏造的
    在稽核上沒有分別。

    比對刻意嚴格：PubMed 的 esearch 對長標題常常回一堆近似結果，取第一筆而不驗
    等於在資料裡種一個看起來完全合理的錯誤。前 60 個正規化字元不相符就寧可留空。
    """
    q = urllib.parse.urlencode(
        {"db": "pubmed", "retmode": "json", "retmax": "3", "term": f"{title}[Title]"}
    )
    hits = []
    for attempt in range(3):
        try:
            req = urllib.request.Request(f"{ESEARCH}?{q}", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as res:
                hits = json.loads(res.read()).get("esearchresult", {}).get("idlist") or []
            break
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    if not hits:
        return None
    # NCBI 無金鑰時是 3 req/s，而這裡每筆要打 esearch + esummary 兩次，很容易撞到
    # HTTP 500。單一筆查不到不該讓整批中斷——退避重試，還是不行就當作沒查到。
    got = {}
    for attempt in range(3):
        try:
            got = fetch(hits)
            break
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    if not got:
        return None
    want = norm(title)
    for pmid in hits:
        rec = got.get(pmid) or {}
        actual = (rec.get("title") or "").rstrip(".")
        if actual and (norm(actual)[:60] == want[:60]):
            return pmid, actual
    return None


def ids_in_url(url: str) -> tuple[str, str] | None:
    """從 url 抽出 ("pmid", …) 或 ("doi", …)。抽不到回 None。"""
    if m := re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{6,9})", url or ""):
        return "pmid", m.group(1)
    if m := re.search(r"doi\.org/(10\.\S+)", url or ""):
        return "doi", m.group(1).rstrip("/.")
    return None


def resolve_doi(title: str) -> tuple[str, str] | None:
    """用標題反查 DOI。比對規則與 resolve_pmid 一樣嚴格，不夠像就回 None。"""
    q = urllib.parse.urlencode({"query.bibliographic": title, "rows": "3"})
    try:
        req = urllib.request.Request(f"{CROSSREF}?{q}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as res:
            items = json.loads(res.read())["message"].get("items") or []
    except Exception:
        return None
    want = norm(title)
    for it in items:
        actual = (it.get("title") or [""])[0].rstrip(".")
        if actual and norm(actual)[:60] == want[:60] and it.get("DOI"):
            return it["DOI"], actual
    return None


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

    if "--resolve" in sys.argv and bad_pmid:
        print(f"用標題反查 PMID：{len(bad_pmid)} 筆缺識別碼的引用…")
        found = 0
        for _fname, _cid, _, c in bad_pmid:
            title = c.get("title") or ""
            # 先看 url——識別碼常常就躺在裡面，只是沒被抄進 pmid／doi 欄位。
            # 實測最後查不到的 5 筆全部屬於這一類：url 明明寫著
            # pubmed.ncbi.nlm.nih.gov/9580896，卻要去打標題搜尋繞遠路。
            # 免費、零 API 呼叫、而且不可能配錯（識別碼是作者自己寫的）。
            if ident := ids_in_url(c.get("url") or ""):
                key, val = ident
                c[key] = val
                found += 1
            elif hit := resolve_pmid(title):
                c["pmid"], c["title"] = hit[0], hit[1]
                found += 1
            elif hit := resolve_doi(title):
                # PubMed 只收生醫，Crossref 涵蓋範圍大得多。查不到 PMID 不代表
                # 這篇論文不存在——evidence.md 早就寫過 DOI 是更通用的識別碼。
                c["doi"], c["title"] = hit[0], hit[1]
                found += 1
            time.sleep(0.4)  # NCBI 無金鑰時 3 req/s，留餘裕
        for path, blob in BLOBS.items():
            path.write_text(json.dumps(blob, ensure_ascii=False, indent=1))
        print(f"→ 反查到 {found}/{len(bad_pmid)} 筆並寫回；剩下的請人工補或刪掉\n")
        rows = collect()  # 重讀，讓這一輪就驗到剛補上的
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

    missing, mismatch, retracted = [], [], []
    for fname, cid, pmid, c in rows:
        rec = meta.get(pmid)
        if not rec or rec.get("error") or not rec.get("title"):
            missing.append((fname, cid, pmid, c.get("title", "")))
            continue

        # 撤稿。esummary 本來就回傳 pubtype，只是以前沒讀——一篇論文可以「真的
        # 存在」、標題也完全對得上，卻早就被撤回。引用撤稿論文比沒有引用更糟：
        # 它看起來完全通過驗證。Crossref 那邊對應的是 update-to 裡 type=retraction。
        types = [str(t).lower() for t in (rec.get("pubtype") or [])]
        updates = rec.get("update-to") or []
        if "retracted publication" in types or any(
            str(u.get("type", "")).lower() == "retraction" for u in updates
        ):
            retracted.append((fname, cid, pmid, rec["title"]))

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
            # design 一律以 PubMed 的 publication type 為準，蓋掉手寫的值——
            # 手寫的那個正是要消滅的東西。認不出來就留白，不要猜。
            if d := design_of(rec.get("pubtype")):
                c["design"] = d
                FILLED.append(d)

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

    if retracted:
        print(f"\n✗ 引用了已撤稿的論文 {len(retracted)} 筆（換掉，或明確標示為「被撤回的主張」）：")
        for f, cid, p, t in retracted:
            print(f"   {f} · {cid} · {p} · {t[:60]}")

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
        import collections as _c
        tally = "、".join(f"{k}×{v}" for k, v in _c.Counter(FILLED).most_common())
        print(f"→ --fix：已用 API 回傳值覆寫 {len(BLOBS)} 個檔案的 title/journal/year")
        print(f"   design 由 PubMed 的 publication type 填了 {len(FILLED)} 筆：{tally or '（無）'}")

    # 撤稿一律讓交付失敗。它跟「查無此筆」是同一個等級的問題：這篇文獻撐不起
    # 任何主張，而且它比捏造的引用更難發現——標題、期刊、年份全部對得上。
    return 1 if (missing or bad_pmid or BROKEN or retracted) else 0


if __name__ == "__main__":
    sys.exit(main())
