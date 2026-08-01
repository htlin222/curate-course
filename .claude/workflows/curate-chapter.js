export const meta = {
  name: 'curate-chapter',
  description: '策展一個章節：拆單元 → 搜尋候選 → oEmbed 驗證 → 確定性稽核 → 寫檔',
  whenToUse:
    '要為 curate-course 的某一章找齊影片時。一次一章，可恢復、可重跑、每一步都留下結構化紀錄。',
  phases: [
    { title: '拆單元', detail: '把章節目標拆成單元與每單元的動作清單（只有名字，還沒有影片）' },
    { title: '搜尋', detail: '每個單元一個 agent，用 yt-dlp 找候選並抄下真實中繼資料' },
    { title: '驗證', detail: '每個單元一個 agent，逐支打 oEmbed，只有 200 且標題頻道相符才算數' },
    { title: '寫檔', detail: '通過確定性稽核後才寫進 course/data/' },
  ],
}

/* ──────────────────────────────────────────────────────────────────────────
   為什麼這樣切

   這個框架的策展有三種截然不同的工作，混在一起就沒辦法稽核：

   1. 判斷（哪些單元、選哪支片）   → 只能交給 agent
   2. 取得事實（長度、觀看數、存活）→ agent 跑指令，但**必須回傳原始值**
   3. 算術（配額、去重、覆蓋率）   → 留在這支腳本裡，絕不問 agent

   第 3 類是這份工作流程存在的理由。實務上踩過的坑幾乎都出在這裡：
   agent 自稱「都驗過了」但配額差一支、跨單元重複沒人發現、
   yt-dlp 被限流時 exit 0 + 空輸出被當成影片下架。
   這些用 JS 算三行就抓得到，卻很難靠讀 agent 的散文報告發現。

   注意：工作流程本身不能碰檔案或 shell（見官方文件的「行為和限制」），
   所以所有指令都由 agent 執行；腳本只對它們回傳的結構化資料做運算。
   ────────────────────────────────────────────────────────────────────────── */

const A = args || {}
const CHAPTER = A.chapter || 'CH1'
const TITLE = A.title || '未命名章節'
const GOAL = A.goal || ''
const UNIT_COUNT = A.units || 4
const DRILL_TOTAL = A.drills || 0
const KINDS = A.kinds || ['test', 'release', 'activate', 'lift']
const UNIT_TYPE = A.unitType || 'movement'
const LANGS = A.languages || ['繁中', '簡中', '英文']
const CHANNELS = A.channels || []
const MIN_VIEWS = A.minViews || 5000
const OUT = A.out || `course/data/${CHAPTER.toLowerCase()}.json`

const RULES = `
硬性規則（違反就是這一輪失敗，不要自行放寬）：
- video id 一律取自 yt-dlp 的實際輸出，**絕不可憑記憶拼湊**。捏造一個看起來合理的 id 比留空更糟。
- 標題、頻道、秒數、觀看數一律照抄工具輸出，不要自己記憶或估算。
- 搜尋一律用：
    yt-dlp "ytsearch20:<查詢>" --flat-playlist --no-update \\
      --print "%(id)s|%(title)s|%(channel)s|%(duration)s|%(view_count)s"
  （--print 裡的 \\t 不會被解析成 tab，所以用 | 當分隔；標題本身可能含 |，切欄位時從左邊切）
- 觀看數 < ${MIN_VIEWS} 一律不採用。
- 語言優先序：${LANGS.join(' > ')}。同等品質下前者勝出。
- 找不到合格影片就把 url 設為 null，並在 note 寫清楚**查過哪些關鍵字、為什麼都不合格**。
  留空是允許的；留空而沒有 note 不是。
${CHANNELS.length ? `- 優先頻道：${CHANNELS.join('、')}` : ''}
`

/* ── 1. 拆單元 ─────────────────────────────────────────────────────────── */

phase('拆單元')

const PLAN_SCHEMA = {
  type: 'object',
  required: ['units'],
  properties: {
    units: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'name', 'drillNames'],
        properties: {
          id: { type: 'string', description: `${CHAPTER.toLowerCase()}-u1 這種格式` },
          name: { type: 'string' },
          rationale: { type: 'string', description: '為什麼這樣切，一句話' },
          drillNames: {
            type: 'array',
            items: { type: 'string' },
            description: '這個單元要找的動作名稱，只有名字，還沒有影片',
          },
        },
      },
    },
  },
}

const plan = await agent(
  `為課程章節「${CHAPTER} ${TITLE}」規劃單元結構。${GOAL ? `\n章節目標：${GOAL}` : ''}

必須剛好 ${UNIT_COUNT} 個單元，所有單元的 drillNames 加總必須剛好 ${DRILL_TOTAL} 個。
配額是硬性的——建置時數量不符會直接失敗。

分配時**依主題的複雜度加權，不要平均攤**：常見或動作變化多的主題給多一點。
先把總數算一次確認等於 ${DRILL_TOTAL} 再回答。

這一步不要搜尋任何影片，只規劃結構與動作名稱。`,
  { schema: PLAN_SCHEMA, label: `plan:${CHAPTER}` },
)

// ── 確定性檢查：配額。不問 agent，自己算。
const planned = plan?.units || []
const plannedDrills = planned.reduce((n, u) => n + (u.drillNames?.length || 0), 0)
log(`拆出 ${planned.length}/${UNIT_COUNT} 個單元，動作 ${plannedDrills}/${DRILL_TOTAL} 個`)

if (planned.length !== UNIT_COUNT || plannedDrills !== DRILL_TOTAL) {
  log(`⚠ 配額不符，要求重新分配（單元 ${planned.length}≠${UNIT_COUNT} 或動作 ${plannedDrills}≠${DRILL_TOTAL}）`)
  const fixed = await agent(
    `這份單元規劃的配額不對：單元 ${planned.length} 個（應為 ${UNIT_COUNT}），` +
      `動作合計 ${plannedDrills} 個（應為 ${DRILL_TOTAL}）。\n\n` +
      `原規劃：\n${JSON.stringify(planned, null, 1)}\n\n` +
      `請重新分配到剛好符合，保留原本的單元主題與命名，只調整數量。`,
    { schema: PLAN_SCHEMA, label: `replan:${CHAPTER}` },
  )
  if (fixed?.units) plan.units = fixed.units
}

const units = plan?.units || []

/* ── 2+3. 搜尋 → 驗證（pipeline：不設屏障） ──────────────────────────────
   用 pipeline 而不是 parallel：某個單元找完就立刻進驗證，
   不必等最慢的單元。單元之間本來就沒有跨項依賴。            */

const VIDEO_PROPS = {
  name: { type: 'string' },
  en: { type: 'string' },
  kind: { type: 'string', enum: KINDS },
  target: { type: 'string', description: '目標，用頓號分隔的名詞（框架拿來建分面索引，不要寫成句子）' },
  dose: { type: 'string' },
  videoId: { type: ['string', 'null'], description: '11 碼 YouTube id，照抄工具輸出' },
  title: { type: ['string', 'null'] },
  channel: { type: ['string', 'null'] },
  seconds: { type: ['integer', 'null'], description: '秒數，照抄不要換算' },
  views: { type: ['integer', 'null'] },
  note: { type: 'string', description: 'videoId 為 null 時必填：查過什麼、為什麼不合格' },
}

const SEARCH_SCHEMA = {
  type: 'object',
  required: ['unitId', 'lesson', 'drills'],
  properties: {
    unitId: { type: 'string' },
    assessment: { type: 'string', description: '讀者可自己做的檢核方法，至少 80 字，要可操作' },
    tight: { type: 'array', items: { type: 'string' } },
    weak: { type: 'array', items: { type: 'string' } },
    lesson: { type: 'object', properties: { ...VIDEO_PROPS, why: { type: 'string' } } },
    drills: { type: 'array', items: { type: 'object', properties: VIDEO_PROPS } },
    searchLog: {
      type: 'array',
      items: { type: 'string' },
      description: '每個查詢字串一行，含回傳筆數。這是稽核軌跡，不要省略',
    },
  },
}

const VERIFY_SCHEMA = {
  type: 'object',
  required: ['unitId', 'results'],
  properties: {
    unitId: { type: 'string' },
    results: {
      type: 'array',
      items: {
        type: 'object',
        required: ['videoId', 'httpStatus', 'ok'],
        properties: {
          videoId: { type: 'string' },
          httpStatus: { type: 'integer', description: 'oEmbed 的實際 HTTP 狀態碼' },
          ok: { type: 'boolean', description: '200 且標題與頻道與策展資料相符' },
          oembedTitle: { type: 'string' },
          oembedChannel: { type: 'string' },
          mismatch: { type: 'string', description: '不符時說明差在哪' },
        },
      },
    },
  },
}

const curated = await pipeline(
  units,
  // ── 搜尋
  (u) =>
    agent(
      `為單元「${u.name}」（id: ${u.id}，章節 ${CHAPTER} ${TITLE}）找影片。

要找：
- 1 支主課（講解型，4:00–24:00）
- ${u.drillNames?.length || 0} 支動作影片，依序對應：${(u.drillNames || []).join('、')}

每支動作影片長度 0:30–10:00。kind 從 ${KINDS.join(' / ')} 裡選。
assessment 要寫成**讀者可以自己做的檢核方法**，不是問題描述——
「側面錄影看肋廓下緣有沒有掀起來」是可操作的，「核心穩定很重要」不是。

searchLog 每個查詢字串記一行，含回傳筆數。這是後續稽核的軌跡。
${RULES}`,
      { schema: SEARCH_SCHEMA, label: `search:${u.id}`, phase: '搜尋' },
    ),
  // ── 驗證（同一單元找完就立刻驗，不等別人）
  (res, u) => {
    const ids = [res?.lesson?.videoId, ...(res?.drills || []).map((d) => d.videoId)].filter(Boolean)
    if (!ids.length) return { unitId: u.id, results: [], _search: res }
    return agent(
      `逐一驗證這些 YouTube 影片是否存在且公開。**不要相信上游宣稱**，一支一支打：

curl -s -o /dev/null -w "%{http_code}" \\
  "https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D<ID>&format=json"

200 = 存在且公開；401 = 已設為私人或禁止嵌入；404 = 已刪除。
200 時再取回 JSON，比對 title 與 author_name 是否與策展資料相符
（YouTube 會做標題 A/B 測試，不符時以 oEmbed 回傳值為準並寫進 mismatch）。

要驗的影片：
${JSON.stringify(
  [res?.lesson, ...(res?.drills || [])]
    .filter((v) => v?.videoId)
    .map((v) => ({ videoId: v.videoId, title: v.title, channel: v.channel })),
  null,
  1,
)}`,
      { schema: VERIFY_SCHEMA, label: `verify:${u.id}`, phase: '驗證', effort: 'low' },
    ).then((v) => ({ ...v, _search: res }))
  },
)

/* ── 4. 確定性稽核：這一段刻意全部留在 JS ────────────────────────────────
   沒有任何一項需要判斷力，所以沒有任何一項該問 agent。      */

phase('寫檔')

const rows = curated.filter(Boolean)
const okIds = new Set()
const dead = []
const mismatched = []

for (const r of rows) {
  for (const v of r.results || []) {
    if (v.ok) okIds.add(v.videoId)
    else dead.push(`${r.unitId} · ${v.videoId} · HTTP ${v.httpStatus}`)
    if (v.ok && v.mismatch) mismatched.push(`${r.unitId} · ${v.videoId} · ${v.mismatch}`)
  }
}

const seen = new Map() // videoId -> [unitId]
const blanks = []
const blanksNoNote = []
let lessons = 0
let drills = 0

for (const r of rows) {
  const s = r._search || {}
  const all = [
    ['lesson', s.lesson],
    ...(s.drills || []).map((d) => ['drill', d]),
  ]
  for (const [role, v] of all) {
    if (!v) continue
    if (role === 'lesson') lessons++
    else drills++
    if (!v.videoId) {
      blanks.push(`${r.unitId} · ${v.name || '主課'}`)
      if (!v.note) blanksNoNote.push(`${r.unitId} · ${v.name || '主課'}`)
      continue
    }
    seen.set(v.videoId, [...(seen.get(v.videoId) || []), r.unitId])
  }
}

const dupes = [...seen.entries()].filter(([, us]) => us.length > 1)
const lowViews = rows.flatMap((r) =>
  [(r._search || {}).lesson, ...((r._search || {}).drills || [])]
    .filter((v) => v?.videoId && typeof v.views === 'number' && v.views < MIN_VIEWS)
    .map((v) => `${r.unitId} · ${v.videoId} · ${v.views} 次觀看`),
)

const report = {
  chapter: CHAPTER,
  units: { got: rows.length, want: UNIT_COUNT, ok: rows.length === UNIT_COUNT },
  drills: { got: drills, want: DRILL_TOTAL, ok: drills === DRILL_TOTAL },
  lessons,
  verified: okIds.size,
  dead,
  mismatched,
  duplicatesAcrossUnits: dupes.map(([id, us]) => `${id} 出現在 ${us.join('、')}`),
  blanks,
  blanksWithoutNote: blanksNoNote,
  belowMinViews: lowViews,
  searchLog: rows.flatMap((r) => (r._search?.searchLog || []).map((l) => `${r.unitId} · ${l}`)),
}

log(
  `稽核：單元 ${report.units.got}/${report.units.want}、動作 ${report.drills.got}/${report.drills.want}、` +
    `驗證通過 ${okIds.size}、失效 ${dead.length}、跨單元重複 ${dupes.length}、` +
    `留空 ${blanks.length}（其中 ${blanksNoNote.length} 筆沒寫 note）`,
)

const blocking =
  !report.units.ok || !report.drills.ok || dead.length > 0 || blanksNoNote.length > 0

if (blocking) {
  log('✗ 未通過確定性稽核，不寫檔——修好上面列出的問題再重跑（可用 resumeFromRunId 保留已完成的搜尋）')
  return { written: false, report }
}

// 只有全部過關才落地。寫檔是 agent 做的（腳本沒有檔案系統存取）。
const payload = rows.map((r) => {
  const s = r._search || {}
  const shape = (v, extra = {}) =>
    v?.videoId
      ? {
          ...(v.name ? { name: v.name, en: v.en, kind: v.kind, target: v.target, dose: v.dose } : {}),
          title: v.title,
          channel: v.channel,
          url: `https://www.youtube.com/watch?v=${v.videoId}`,
          duration: `${Math.floor(v.seconds / 60)}:${String(v.seconds % 60).padStart(2, '0')}`,
          ...extra,
        }
      : { ...(v?.name ? { name: v.name, kind: v.kind } : {}), url: null, note: v?.note }
  return {
    id: r.unitId,
    name: units.find((u) => u.id === r.unitId)?.name,
    type: UNIT_TYPE,
    assessment: s.assessment,
    tight: s.tight || [],
    weak: s.weak || [],
    lesson: shape(s.lesson, { why: s.lesson?.why }),
    drills: (s.drills || []).map((d) => shape(d)),
  }
})

await agent(
  `把下面這份 JSON 原封不動寫進 \`${OUT}\`，外層包成：

{"chapter": "${CHAPTER}", "title": "${TITLE}", "units": <下面的陣列>}

**不要修改任何欄位值**——它已經通過驗證與稽核，你的工作只有寫檔。
寫完跑 \`python3 -c "import json; json.load(open('${OUT}'))"\` 確認 JSON 合法，回報結果。

${JSON.stringify(payload, null, 1)}`,
  { label: `write:${CHAPTER}`, phase: '寫檔' },
)

log(`✓ 已寫入 ${OUT}`)
return { written: true, out: OUT, report }
