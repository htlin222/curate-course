#!/usr/bin/env python3
"""獨立驗證所有引用是否真實存在，且標題與識別碼對得上。

生醫走 PubMed（pmid），人文社科走 Crossref（doi）——PubMed 幾乎不收邏輯學、
論證理論與倫理學的期刊，在那些主題硬要 PMID 只會逼出捏造的引用。

不信任任何上游宣稱（含 agent 自稱已驗證），一律重打 PubMed E-utilities 或 Crossref。
捏造的引用比沒有引用更糟，這是最後一道關卡。

除了「存不存在」，還查三件事：**這篇有沒有被撤稿**、**研究設計是什麼**（PubMed
自己標的 publication type，比策展 agent 手寫的自由文字可靠；evidence_grade 建立
在這上面），以及**有沒有免費全文**（`--fix` 會寫進 oa_url）。

撤稿要問三個來源，因為單一來源會漏。實測 Wakefield 1998
（DOI 10.1016/S0140-6736(97)11096-0）：PubMed 的 pubtype 抓得到，但 Crossref 的
`update-to` 是 null、`relation` 是 {}——走 DOI 的引用如果只問 Crossref，撤稿偵測
等於不存在。所以 PMID 問 PubMed，DOI 問 Crossref（含標題的 RETRACTED: 前綴）
**加上** OpenAlex 的 is_retracted。

用法：
    python3 verify_refs.py             # 驗證並列出不符者
    python3 verify_refs.py --fix       # 用 API 回傳值覆寫 title/journal/year/design/oa_url
    python3 verify_refs.py --resolve   # 補上缺失的識別碼：先從 url 抽，再用標題
                                       # 反查 PubMed，最後試 Crossref。配 --fix 用
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑
import refsources  # 外部資料庫的憑證與呼叫，全部集中在那裡

ROOT = coursepath.ROOT
DATA = coursepath.course_dir() / "data"
BATCH = 180

UA = refsources.UA  # 保留給既有呼叫端；真正的來源是 refsources


FILLED: list[str] = []
OA_FILLED: list[str] = []
# (被引用次數, 條目 id, 識別碼, 標題)。只用來印，永遠不寫回資料檔——見 main()。
CITED: list[tuple[int, str, str, str]] = []
_OA_CACHE: dict[str, str | None] = {}


def oa_url_for(ident: str) -> str | None:
    """`pmid:…` / `doi:…` → 免費全文連結。查不到或缺憑證回 None。

    兩條路是因為兩邊的權威來源不同：DOI 問 Unpaywall（實測它找得到 OpenAlex
    漏掉的 PMC 全文），PMID 問 Europe PMC（免憑證，而且直接回 PMCID）。
    走 PMID 的引用佔絕大多數，少了後者「免費全文」只會出現在零星幾筆上，
    前端看起來像壞掉。

    同一個識別碼可能出現在很多筆引用裡，快取住，不要重複打。
    """
    if ident in _OA_CACHE:
        return _OA_CACHE[ident]
    if ident.startswith("doi:"):
        url = refsources.unpaywall_oa_url(ident.removeprefix("doi:"))
    elif ident.startswith("pmid:"):
        url = refsources.pmc_oa_url(ident.removeprefix("pmid:"))
    else:
        url = None
    _OA_CACHE[ident] = url
    time.sleep(0.1)
    return url


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


def resolve_pmid(title: str) -> tuple[str, str] | None:
    """用標題反查 PMID。回傳 (pmid, PubMed 上的標題)；比對不夠像就回 None。

    這是給「有標題、有期刊、有年份，就是沒有識別碼」的引用用的。它們多半是真的
    論文，只是當初沒抄下 PMID——而沒有識別碼的引用**任何人都無法覆核**，跟捏造的
    在稽核上沒有分別。

    比對刻意嚴格：PubMed 的 esearch 對長標題常常回一堆近似結果，取第一筆而不驗
    等於在資料裡種一個看起來完全合理的錯誤。前 60 個正規化字元不相符就寧可留空。
    """
    # 退避重試已經在 refsources.get_json 裡做掉了。每筆要打 esearch + esummary
    # 兩次，匿名時 3 req/s 很容易撞 HTTP 500；單一筆查不到不該讓整批中斷。
    hits = refsources.esearch_title(title)
    if not hits:
        return None
    got = fetch(hits)
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
    items = refsources.crossref_by_title(title)
    want = norm(title)
    for it in items:
        actual = (it.get("title") or [""])[0].rstrip(".")
        if actual and norm(actual)[:60] == want[:60] and it.get("DOI"):
            return it["DOI"], actual
    return None


def fetch(pmids: list[str]) -> dict:
    """一批 PMID 的 metadata。整批打不到就逐筆退到 Europe PMC。

    以前這裡失敗會往上拋，由呼叫端退避三次然後**放棄整批**——那一整批引用就
    這樣沒被驗到，而輸出看起來跟通過一模一樣。Europe PMC 免憑證、資料同源
    （SRC:MED 就是 MEDLINE），拿來當 NCBI 抽風時的替補剛好。
    """
    got = refsources.esummary(pmids)
    if got:
        return got
    if not pmids:
        return {}
    print(f"   ⚠ PubMed 整批取數失敗（{len(pmids)} 筆），改走 Europe PMC…")
    out = {}
    for pmid in pmids:
        if rec := refsources.europepmc(pmid):
            out[pmid] = rec
        time.sleep(0.1)  # Europe PMC 沒有公告的硬限速，但不要打太兇
    return out


def fetch_doi(doi: str) -> dict | None:
    """Crossref 逐筆反查 + OpenAlex 的撤稿與被引用次數。

    為什麼一定要多打一次 OpenAlex：Crossref 對真實的撤稿論文可能什麼都不說。
    實測 Wakefield 1998 的 update-to 是 null、relation 是 {}，唯一線索是標題
    被改成 "RETRACTED: …"（refsources.crossref 已經認這個前綴）。OpenAlex 則
    直接回 is_retracted: true。少了它，走 DOI 的引用等於沒有撤稿防線。
    """
    rec = refsources.crossref(doi)
    if rec is None:
        return None
    if extra := refsources.openalex(doi):
        rec["retracted"] = rec.get("retracted") or extra["retracted"]
        rec["cited_by"] = extra["cited_by"]
    return rec


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
            time.sleep(refsources.NCBI_DELAY)  # 匿名 3 req/s、有金鑰 10 req/s
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
    print(refsources.credentials_summary())
    print(f"檢查 {len(rows)} 筆引用（{'、'.join(parts) or '0 個識別碼'}）…\n")

    meta: dict = {}
    for i in range(0, len(pmids), BATCH):
        meta.update({f"pmid:{k}": v for k, v in fetch(pmids[i : i + BATCH]).items()})
        time.sleep(refsources.NCBI_DELAY)
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

        # 撤稿。一篇論文可以「真的存在」、標題也完全對得上，卻早就被撤回——
        # 引用撤稿論文比沒有引用更糟，因為它看起來完全通過驗證。
        #
        # 兩條路各有各的來源，而且都不能省：
        #   PMID → esummary 的 pubtype 有 "Retracted Publication"
        #   DOI  → Crossref 的 update-to **可能整個是 null**（實測 Wakefield
        #          1998 就是），所以 refsources 另外認標題的 RETRACTED: 前綴，
        #          並用 OpenAlex 的 is_retracted 補上。rec["retracted"] 是那
        #          三個訊號 or 起來的結果。
        types = [str(t).lower() for t in (rec.get("pubtype") or [])]
        if "retracted publication" in types or rec.get("retracted"):
            retracted.append((fname, cid, pmid, rec["title"]))

        actual, claimed = rec["title"].rstrip("."), c.get("title", "")
        a, b = norm(actual), norm(claimed)
        if not (a.startswith(b[:55]) or b.startswith(a[:55]) or b[:55] in a):
            mismatch.append((fname, cid, pmid, claimed, actual))
        # 被引用次數**只印出來，不寫回資料檔**。它三個月就變了，寫進 repo 等於
        # 種一個會慢慢變錯、又沒有任何檢查會抓到的數字——跟當初手寫 design 是
        # 同一類問題，只是錯誤來自時間而不是人。
        if (n := rec.get("cited_by")) is not None:
            CITED.append((n, cid, pmid, actual))

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
            # 免費全文。跟 design 一樣寫回資料檔：一篇論文的開放取用狀態幾乎
            # 不倒退，寫進去是淨賺——學習者點得到全文，而不是撞上付費牆。
            if oa := oa_url_for(pmid):
                c["oa_url"] = oa
                OA_FILLED.append(pmid)

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

    # OpenAlex 的被引用次數。這裡**不判定通過與否**——引用次數低不代表論文有問題
    # （新論文、冷門但正確的次領域都會很低），它只是一個值得人看一眼的訊號。
    # 把門檻寫死成 pass/fail 才是真的在製造假訊號。
    if CITED:
        cold = sorted(CITED)[:8]
        print(f"\nℹ 被引用次數（OpenAlex，僅供參考，不寫回資料檔）：{len(CITED)} 筆查得到")
        print(f"   最低的 {len(cold)} 筆：")
        for n, cid, ident, title in cold:
            print(f"      {n:>5} 次 · {cid} · {ident} · {title[:48]}")

    # 撤稿也要從「通過」裡扣掉。以前 ok 只扣 missing 與 mismatch，於是一份報告
    # 可以同時印「✗ 2 筆已撤稿」和「通過 3/3（100.0%）」——那個 100% 正是這支
    # 腳本存在的理由要消滅的東西。三類問題可能落在同一筆上（撤稿論文的標題常
    # 被改成 RETRACTED: 開頭，順帶觸發 mismatch），所以去重再扣。
    flagged = {r[:3] for r in missing} | {r[:3] for r in retracted} | {r[:3] for r in mismatch}
    ok = len(rows) - len(flagged)
    print(f"\n通過 {ok} / {len(rows)}（{ok / max(len(rows), 1) * 100:.1f}%）")

    if fix:
        for path, blob in BLOBS.items():
            path.write_text(json.dumps(blob, ensure_ascii=False, indent=1))
        import collections as _c
        tally = "、".join(f"{k}×{v}" for k, v in _c.Counter(FILLED).most_common())
        print(f"→ --fix：已用 API 回傳值覆寫 {len(BLOBS)} 個檔案的 title/journal/year")
        print(f"   design 由 PubMed 的 publication type 填了 {len(FILLED)} 筆：{tally or '（無）'}")
        if OA_FILLED:
            print(f"   oa_url 免費全文填了 {len(OA_FILLED)} 筆")
        # 這兩個訊息要各自獨立印。PMID 走 Europe PMC（免憑證）、DOI 走 Unpaywall，
        # 只有後者需要信箱——串成 if/elif 的話，PMID 填成功就會把「DOI 全部被跳過」
        # 這件事整個吃掉，看報告的人會以為 oa_url 已經填齊了。
        if dois and not refsources.UNPAYWALL_EMAIL:
            print(f"   oa_url：{len(dois)} 個 DOI 已跳過（沒有 UNPAYWALL_EMAIL，見 .env.example）")

    # 撤稿一律讓交付失敗。它跟「查無此筆」是同一個等級的問題：這篇文獻撐不起
    # 任何主張，而且它比捏造的引用更難發現——標題、期刊、年份全部對得上。
    return 1 if (missing or bad_pmid or BROKEN or retracted) else 0


if __name__ == "__main__":
    sys.exit(main())
