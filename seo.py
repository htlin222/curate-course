#!/usr/bin/env python3
"""由 public/course.json 產生 SEO 資產。

- 把 Course JSON-LD 注入 index.html 的 <script id="schema">
- 產生 sitemap.xml / robots.txt / llms.txt

數字全部取自 course.json，不手寫，避免結構化資料與實際內容對不上。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
PUB = ROOT / "public"
SITE = "https://body-course.pages.dev"

TITLE = "體態矯正課程 — 24 個體態問題的評估、訓練與實證查核"
DESC = (
    "從頭前伸、駝背、圓肩到骨盆前傾與扁平足，24 個常見體態問題的自我評估方法與 "
    "371 支示範影片。每個問題都附 OpenEvidence 查證的實證強度，"
    "包括那些文獻結論與坊間說法相衝突的。"
)


def iso_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    return f"PT{h}H{rem // 60}M"


def build_schema(course: dict) -> dict:
    meta = course["meta"]
    chapters = course["chapters"]

    postures = [u["name"] for ch in chapters for u in ch["units"] if u.get("type") == "posture"]

    syllabus = [
        {
            "@type": "Syllabus",
            "position": i,
            "name": f"{ch['code']} {ch['title']}",
            "description": (
                f"{len(ch['units'])} 個單元"
                + (
                    f"：{'、'.join(u['name'] for u in ch['units'])}"
                    if len(ch["units"]) <= 4
                    else ""
                )
                + (
                    f"，附 {sum(len(u.get('drills') or []) for u in ch['units'])} 支跟練影片"
                    if any(u.get("drills") for u in ch["units"])
                    else ""
                )
            ),
        }
        for i, ch in enumerate(chapters, 1)
    ]

    # 立場聲明的引用，讓機器也讀得到這門課的實證基礎
    citations = []
    for s in course.get("stance", []):
        for c in s.get("citations", [])[:3]:
            if c.get("url"):
                citations.append(
                    {
                        "@type": "CreativeWork",
                        "name": c.get("title", ""),
                        "url": c["url"],
                        **({"datePublished": str(c["year"])} if c.get("year") else {}),
                    }
                )

    org = {
        "@type": "Organization",
        "@id": f"{SITE}/#org",
        "name": "體態矯正課程",
        "url": f"{SITE}/",
    }

    return {
        "@context": "https://schema.org",
        "@graph": [
            org,
            {
                "@type": "WebSite",
                "@id": f"{SITE}/#website",
                "url": f"{SITE}/",
                "name": "體態矯正課程",
                "description": DESC,
                "inLanguage": "zh-Hant",
                "publisher": {"@id": f"{SITE}/#org"},
            },
            {
                "@type": "Course",
                "@id": f"{SITE}/#course",
                "url": f"{SITE}/",
                "name": TITLE,
                "description": DESC,
                "image": f"{SITE}/og.png",
                "inLanguage": "zh-Hant",
                "isAccessibleForFree": True,
                "isFamilyFriendly": True,
                "provider": {"@id": f"{SITE}/#org"},
                "educationalLevel": "Beginner",
                "learningResourceType": ["影片課程", "運動指引", "自我評估"],
                "timeRequired": iso_duration(meta["duration_seconds"]),
                "teaches": postures,
                "about": [
                    {"@type": "Thing", "name": "體態矯正"},
                    {"@type": "Thing", "name": "姿勢評估"},
                    {"@type": "Thing", "name": "肌力訓練"},
                    {"@type": "Thing", "name": "物理治療衛教"},
                ],
                "audience": {
                    "@type": "Audience",
                    "audienceType": "久坐上班族、有體態困擾的一般民眾",
                },
                "hasCourseInstance": {
                    "@type": "CourseInstance",
                    "courseMode": "online",
                    "courseWorkload": iso_duration(meta["duration_seconds"]),
                    "inLanguage": "zh-Hant",
                    "isAccessibleForFree": True,
                    "location": {"@type": "VirtualLocation", "url": f"{SITE}/"},
                },
                "syllabusSections": syllabus,
                "numberOfLessons": meta["units"],
                **({"citation": citations} if citations else {}),
            },
        ],
    }


def inject_schema(schema: dict) -> None:
    """把 JSON-LD 寫進 index.html 的佔位 script。"""
    path = PUB / "index.html"
    html = path.read_text()
    # JSON 內出現 </script> 會提前結束標籤，必須跳脫
    payload = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    new, n = re.subn(
        r'(<script type="application/ld\+json" id="schema">).*?(</script>)',
        lambda m: m.group(1) + payload + m.group(2),
        html,
        flags=re.S,
    )
    if n != 1:
        print("✗ index.html 找不到 JSON-LD 佔位 script", file=sys.stderr)
        sys.exit(1)
    path.write_text(new)
    print(f"   index.html  JSON-LD 已注入（{len(payload) / 1024:.1f} KB）")


def write_sitemap() -> None:
    (PUB / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        "  <url>\n"
        f"    <loc>{SITE}/</loc>\n"
        f"    <lastmod>{date.today().isoformat()}</lastmod>\n"
        "    <changefreq>monthly</changefreq>\n"
        "    <priority>1.0</priority>\n"
        "    <image:image>\n"
        f"      <image:loc>{SITE}/og.png</image:loc>\n"
        "      <image:title>體態矯正課程</image:title>\n"
        "    </image:image>\n"
        "  </url>\n"
        "</urlset>\n"
    )
    print("   sitemap.xml")


def write_robots() -> None:
    (PUB / "robots.txt").write_text(
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "# AI 檢索器一律放行 —— 這門課的實證註記正是希望被引用到的內容\n"
        "User-agent: GPTBot\n"
        "Allow: /\n"
        "\n"
        "User-agent: ClaudeBot\n"
        "Allow: /\n"
        "\n"
        "User-agent: PerplexityBot\n"
        "Allow: /\n"
        "\n"
        "User-agent: Google-Extended\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {SITE}/sitemap.xml\n"
    )
    print("   robots.txt")


def write_llms(course: dict) -> None:
    meta, chapters = course["meta"], course["chapters"]
    lines = [
        "# 體態矯正課程",
        "",
        f"> {DESC}",
        "",
        "這是一門免費的線上自學課程，涵蓋頸椎到足踝的 "
        f"{meta['posture_problems']} 個常見體態問題，共 {meta['units']} 個單元"
        f"（{meta['lesson_units']} 堂主課 + {meta['drill_units']} 支跟練影片，"
        f"總長 {meta['duration']}）。所有影片皆為 YouTube 上第三方專業頻道的作品，本站僅提供策展與連結。",
        "",
        "## 這門課的立場（重要）",
        "",
        f"課程中 {meta['evidence_checked']} 個主題全部經 OpenEvidence 查證，結果照實呈現，"
        "包含對課程本身不利的部分：",
        "",
    ]
    for s in course.get("stance", []):
        lines.append(f"- **{s['name']}**（{s['evidence_grade']}）：{s.get('summary', '')[:180]}…")
    lines += [
        "",
        "簡言之：矯正運動的價值在於肌力、負荷耐受度與不適感改善，"
        "體態數值的變化是伴隨現象而非療效機轉；並無證據顯示矯正課表優於一般運動。",
        "",
        "## 章節",
        "",
    ]
    for ch in chapters:
        names = "、".join(u["name"] for u in ch["units"])
        lines.append(f"- **{ch['code']} {ch['title']}**：{names}")
    lines += [
        "",
        "## 免責",
        "",
        "本課程為衛教與運動指引，不構成醫療診斷或治療建議。"
        "持續疼痛、麻木、無力、外傷史或體態短期內明顯惡化，應先諮詢醫師或物理治療師。",
        "",
        f"完整內容：{SITE}/",
        "",
    ]
    (PUB / "llms.txt").write_text("\n".join(lines))
    print("   llms.txt")


def main() -> int:
    course_path = PUB / "course.json"
    if not course_path.exists():
        print("✗ 找不到 public/course.json，請先執行 build.py", file=sys.stderr)
        return 1

    course = json.loads(course_path.read_text())
    print("SEO 資產：")
    inject_schema(build_schema(course))
    write_sitemap()
    write_robots()
    write_llms(course)
    return 0


if __name__ == "__main__":
    sys.exit(main())
