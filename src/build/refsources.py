#!/usr/bin/env python3
"""外部資料庫的憑證與呼叫，集中在這裡一份。

`verify_refs.py`、`verify_changed.py`、`verify_links.py` 三支都要打外部 API，
以前各自寫一遍 User-Agent、退避重試與速率間隔——同一個 bug 要修三次，而且
`CROSSREF_MAILTO` 這種設定只有其中一支讀得到。

**這個模組的每一個來源都必須能在缺憑證時降級，絕不 raise。**
GitHub Actions 在 fork 來的 PR 上拿不到 repository secrets：任何一條路徑在
缺憑證時失敗，外部貢獻者的 PR 就會一律紅掉，而錯誤訊息指向一個他們無權取得
的東西。缺憑證時的行為必須跟這個模組存在之前逐字元相同。

申請流程寫在 .env.example，設計理由在 docs/plans/2026-08-04-external-db-apis-design.md。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """把 repo 根目錄的 .env 讀進 os.environ。**不覆蓋**已經存在的值。

    這個框架的建置腳本刻意零相依（見 pyproject.toml），所以不用 python-dotenv。
    需要這 15 行是因為：wrangler 會自動載入 .env，Python 不會——使用者照著
    .env.example 填完 NCBI_API_KEY，然後發現 make verify 完全沒變快，而且沒有
    任何錯誤訊息。那正是 .env.example 開頭在警告的那種無聲失效。

    不覆蓋既有值，是為了讓 CI 的 secrets（真的環境變數）永遠贏過任何殘留的
    本機 .env。
    """
    env = path or (ROOT / ".env")
    try:
        text = env.read_text()
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        # 去掉成對的引號；.env 裡 KEY="值" 與 KEY=值 都常見
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key and val and key not in os.environ:
            os.environ[key] = val


load_dotenv()


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


NCBI_API_KEY = _env("NCBI_API_KEY")
YOUTUBE_API_KEY = _env("YOUTUBE_API_KEY")
OPENALEX_MAILTO = _env("OPENALEX_MAILTO")
UNPAYWALL_EMAIL = _env("UNPAYWALL_EMAIL")

# Crossref 的 polite pool 要求 User-Agent 帶聯絡信箱，沒帶會被降速。
CONTACT = _env("CROSSREF_MAILTO") or "curate-course@example.com"
UA = f"curate-course/1.0 (mailto:{CONTACT})"

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
CROSSREF = "https://api.crossref.org/works/"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENALEX = "https://api.openalex.org/works/"
UNPAYWALL = "https://api.unpaywall.org/v2/"
YOUTUBE = "https://www.googleapis.com/youtube/v3/videos"

# NCBI 匿名是 3 req/s，帶金鑰是 10 req/s。留餘裕，不要踩在線上。
NCBI_DELAY = 0.11 if NCBI_API_KEY else 0.4

# YouTube 的 videos.list 一次最多 50 個 id，而且不論幾個都只算 1 unit 配額。
YOUTUBE_BATCH = 50


def credentials_summary() -> str:
    """一行文字說明這次帶了哪些憑證。印在驗證開頭，省得事後猜為什麼慢。"""
    on = [
        name
        for name, val in (
            ("NCBI", NCBI_API_KEY),
            ("YouTube", YOUTUBE_API_KEY),
            ("Crossref", _env("CROSSREF_MAILTO")),
            ("OpenAlex", OPENALEX_MAILTO),
            ("Unpaywall", UNPAYWALL_EMAIL),
        )
        if val
    ]
    if not on:
        return "外部憑證：無（全部走匿名／降級路徑，功能不變但較慢）"
    return f"外部憑證：{'、'.join(on)}"


def get_json(url: str, *, data: bytes | None = None, timeout: int = 30, tries: int = 3):
    """打一個回 JSON 的端點。失敗回 None——外部服務抽風不該讓交付流程爆掉。

    退避重試在這裡做一次，三支腳本就不必各自重寫。
    """
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return json.loads(res.read())
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def ncbi_query(**params) -> str:
    """組 E-utilities 的 query string，有金鑰就帶上。"""
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return urllib.parse.urlencode(params)


# ── PubMed ────────────────────────────────────────────────────────────────


def esummary(pmids: list[str]) -> dict:
    """一批 PMID 的 esummary。回 {pmid: record}，整批失敗時回 {}。

    金鑰走 POST body 而不是 URL——一次 180 個 id 的 GET 會過長，而且金鑰
    出現在 URL 裡容易被 CI 日誌收走。
    """
    if not pmids:
        return {}
    body = ncbi_query(db="pubmed", retmode="json", id=",".join(pmids)).encode()
    got = get_json(ESUMMARY, data=body, timeout=60)
    return (got or {}).get("result", {}) or {}


def esearch_title(title: str, retmax: int = 3) -> list[str]:
    """用標題搜 PubMed，回 PMID 清單。查不到或失敗都回空。"""
    q = ncbi_query(db="pubmed", retmode="json", retmax=str(retmax), term=f"{title}[Title]")
    got = get_json(f"{ESEARCH}?{q}")
    return ((got or {}).get("esearchresult", {}) or {}).get("idlist") or []


# ── Europe PMC（免憑證，NCBI 失敗時的替補）─────────────────────────────────


def europepmc(pmid: str) -> dict | None:
    """回傳與 esummary **同形狀**的紀錄，讓呼叫端不必分辨資料來自哪裡。

    存在的理由只有一個：NCBI 偶爾回 HTTP 500，而以前的處理是退避三次然後
    放棄整批——那一整批引用就這樣沒有被驗到，而輸出看起來像是通過了。
    """
    q = urllib.parse.urlencode(
        {"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "resultType": "core"}
    )
    got = get_json(f"{EUROPEPMC}?{q}")
    hits = ((got or {}).get("resultList") or {}).get("result") or []
    if not hits:
        return None
    r = hits[0]
    journal = ((r.get("journalInfo") or {}).get("journal") or {}).get("title") or ""
    return {
        "title": r.get("title") or "",
        "source": journal,
        "pubdate": str(r.get("pubYear") or ""),
        "pubtype": (r.get("pubTypeList") or {}).get("pubType") or [],
    }


# ── Crossref ──────────────────────────────────────────────────────────────

# Crossref 標記撤稿的方式不只一種，而最常見的那種是**改標題**。
# 實測 Wakefield 1998（10.1016/S0140-6736(97)11096-0）：update-to 是 null、
# relation 是 {}，唯一的線索是標題變成 "RETRACTED: Ileal-lymphoid-…"。
RETRACTED_TITLE = re.compile(r"^\s*(retracted|withdrawn)\b[:\s]", re.I)


def crossref(doi: str) -> dict | None:
    """Crossref 逐筆反查，回傳與 esummary 對齊的欄位 + 撤稿判定。"""
    got = get_json(CROSSREF + urllib.parse.quote(doi, safe=""))
    if not got or "message" not in got:
        return None
    m = got["message"]
    title = (m.get("title") or [""])[0]
    updates = m.get("update-to") or []
    return {
        "title": title,
        "source": (m.get("container-title") or [""])[0],
        "pubdate": str((m.get("issued", {}).get("date-parts") or [[""]])[0][0] or ""),
        "pubtype": [],
        "retracted": bool(RETRACTED_TITLE.match(title))
        or any(str(u.get("type", "")).lower() == "retraction" for u in updates),
    }


def crossref_by_title(title: str, rows: int = 3) -> list[dict]:
    """用標題搜 Crossref，回 items。查不到或失敗都回空。"""
    q = urllib.parse.urlencode({"query.bibliographic": title, "rows": str(rows)})
    got = get_json(f"{CROSSREF}?{q}")
    return ((got or {}).get("message") or {}).get("items") or []


# ── OpenAlex（撤稿補洞 + 被引用次數）───────────────────────────────────────


def openalex(doi: str) -> dict | None:
    """回 {"retracted": bool, "cited_by": int}。查不到或失敗回 None。

    這是走 DOI 的引用**唯一**的撤稿防線：Crossref 的 update-to 對真實的撤稿
    論文可能整個是 null（見 RETRACTED_TITLE 上面那段實測）。
    """
    url = OPENALEX + "doi:" + urllib.parse.quote(doi, safe="")
    if OPENALEX_MAILTO:
        url += "?" + urllib.parse.urlencode({"mailto": OPENALEX_MAILTO})
    got = get_json(url)
    if not got or not got.get("id"):
        return None
    return {
        "retracted": bool(got.get("is_retracted")),
        "cited_by": int(got.get("cited_by_count") or 0),
    }


# ── Unpaywall（開放取用全文）──────────────────────────────────────────────


def unpaywall_oa_url(doi: str) -> str | None:
    """這個 DOI 的免費全文連結，沒有就回 None。缺 UNPAYWALL_EMAIL 時直接跳過。

    OA 狀態只信 Unpaywall：實測 10.1001/jama.2022.22625，Unpaywall 給得出
    PMC 全文，OpenAlex 的 best_oa_location 是 None。
    """
    if not UNPAYWALL_EMAIL:
        return None
    url = (
        UNPAYWALL
        + urllib.parse.quote(doi, safe="")
        + "?"
        + urllib.parse.urlencode({"email": UNPAYWALL_EMAIL})
    )
    got = get_json(url)
    if not got or not got.get("is_oa"):
        return None
    best = got.get("best_oa_location") or {}
    return best.get("url_for_pdf") or best.get("url") or None


def pmc_oa_url(pmid: str, rec: dict | None = None) -> str | None:
    """PMID 的免費全文。走 Europe PMC，因為它免憑證且直接回 PMCID。

    走 PMID 的引用佔絕大多數，卻沒有 DOI 可以問 Unpaywall——沒有這一支的話
    「免費全文」只會出現在少數幾筆上，前端看起來像壞掉。
    """
    q = urllib.parse.urlencode(
        {"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "resultType": "core"}
    )
    got = get_json(f"{EUROPEPMC}?{q}")
    hits = ((got or {}).get("resultList") or {}).get("result") or []
    if not hits:
        return None
    r = hits[0]
    if r.get("isOpenAccess") == "Y" and r.get("pmcid"):
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{r['pmcid']}/"
    # 沒有 PMC 全文時，退而求其次找標示為免費的連結（作者自存版、期刊 OA 版）
    for u in ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
        if str(u.get("availabilityCode") or "").upper() in {"OA", "F"} and u.get("url"):
            return u["url"]
    return None


# ── YouTube ───────────────────────────────────────────────────────────────

VIDEO_ID = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})")
ISO_DURATION = re.compile(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def video_id(url: str) -> str | None:
    m = VIDEO_ID.search(url or "")
    return m.group(1) if m else None


def duration_seconds(iso: str) -> int | None:
    """ISO 8601 期間（PT4M13S）→ 秒。解析不了回 None，不要猜。"""
    m = ISO_DURATION.fullmatch((iso or "").strip())
    if not m:
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def youtube_videos(ids: list[str]) -> dict[str, dict] | None:
    """一批影片 id 的狀態。回 {id: item}；**缺金鑰或查詢失敗回 None**。

    回 None 與回 {} 意義完全不同：{} 是「這批 id 一個都不存在」（全部被刪），
    None 是「這條路走不通，請走 oEmbed」。混為一談會讓缺金鑰的環境把所有影片
    報成已刪除。

    查不到的 id 不會出現在 items 裡——那就是「已刪除或網址錯誤」。
    """
    if not YOUTUBE_API_KEY or not ids:
        return None
    out: dict[str, dict] = {}
    for i in range(0, len(ids), YOUTUBE_BATCH):
        chunk = ids[i : i + YOUTUBE_BATCH]
        q = urllib.parse.urlencode(
            {
                "part": "status,contentDetails,snippet",
                "id": ",".join(chunk),
                "key": YOUTUBE_API_KEY,
                "maxResults": str(YOUTUBE_BATCH),
            }
        )
        got = get_json(f"{YOUTUBE}?{q}")
        if got is None:
            # 配額用完或金鑰無效。半套結果比沒有結果更危險——它會讓沒查到的
            # 那幾批被當成「影片已刪除」。整個放棄，讓呼叫端退回 oEmbed。
            return None
        for item in got.get("items") or []:
            out[item["id"]] = item
    return out
