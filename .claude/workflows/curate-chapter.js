export const meta = {
  name: 'curate-chapter',
  description: '策展一個章節：拆單元 → 搜尋候選 → oEmbed 驗證 → 確定性稽核 → 寫檔',
  whenToUse:
    '要為 curate-course 的某一章找齊影片時。一次一章，可恢復、可重跑、每一步都留下結構化紀錄。args 必須是 JSON 物件，不能是自由文字字串：Workflow({name: "curate-chapter", args: {chapter: "CH10", title: "膝蓋", units: 4, drills: 43, kinds: ["release","stretch","train"], unitType: "posture", out: "examples/body/data/ch10.json", goal: "…", minViews: 5000}})。chapter/title/units/drills/kinds/unitType/out 全部必填，值照課程設定檔抄，不要自己編。',
  phases: [
    { title: '拆單元', detail: '把章節目標拆成單元與每單元的動作清單（只有名字，還沒有影片）' },
    { title: '搜尋', detail: '每個單元一個 agent，用 yt-dlp 找候選並抄下真實中繼資料' },
    { title: '驗證', detail: '每個單元一個 agent，逐支打 oEmbed，只有 200 且標題頻道相符才算數' },
    { title: '潤稿', detail: '把 assessment／why／note 的 AI 寫作痕跡去掉，事實一字不動' },
    { title: '寫檔', detail: '通過確定性稽核後才寫進 args.out 指定的課程資料檔' },
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

/* ── 0. 參數：不猜 ────────────────────────────────────────────────────────
   以前這裡每一個參數都有預設值，而那些預設值全是錯的——`course/data/` 這個
   目錄早就不存在了（課程住在 courses/ 或 examples/），`kinds` 是某個舊主題
   的類型，`drills` 預設 0 讓配額檢查變成 0 === 0 恆真。實際踩到的死法是：
   args 傳成 JSON 字串 → 每一個欄位都拿不到 → 整章照著預設值跑完 → 稽核
   回報「全數通過」→ 寫出一份 chapter: "CH1"、title: "未命名章節"、
   0 個動作的檔案。七分半鐘、四十萬 token，而且沒有任何一行是紅的。

   所以身分與配額一律必填。這跟 coursepath.py 對 COURSE 的態度是同一條：
   猜錯的代價是把 A 章的資料寫成 B 章，而且不會有錯誤訊息。          */

// args 實測會以字串抵達（呼叫端傳物件，執行環境序列化過一手），所以 JSON 字串要收；
// 但自由文字（skill 自動產生的呼叫範例長「CH10 膝蓋，4 單元」那樣）一定要擋——
// 那正是把整章跑成預設值的那條路。能 parse 成物件就收，其餘一律拒絕。
function readArgs(raw) {
  if (raw && typeof raw === 'object') return raw
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed
    } catch {
      /* 下面統一報錯 */
    }
    throw new Error(
      `args 是一段自由文字（${JSON.stringify(raw.slice(0, 40))}…），不是 JSON 物件。` +
        '要給 {chapter: "CH10", title: "膝蓋", units: 4, drills: 43, kinds: [...], ' +
        'unitType: "posture", out: "examples/body/data/ch10.json"}——' +
        '收下自由文字的話每個欄位都讀不到，整章會照預設值跑完並回報成功。',
    )
  }
  throw new Error('沒有給 args。這份工作流程不猜要策展哪一章，參數見 meta.whenToUse。')
}

const A = readArgs(args)

const need = (key, hint) => {
  const v = A[key]
  const empty = v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length)
  if (empty) throw new Error(`args.${key} 是必填的：${hint}`)
  return v
}

const CHAPTER = need('chapter', '章節碼，例如 "CH10"')
const TITLE = need('title', '章節標題，例如 "膝蓋"')
const UNIT_COUNT = need('units', '這一章要幾個單元（設定檔 chapters[].units）')
const DRILL_TOTAL = need('drills', '這一章的動作總數（設定檔 chapters[].drills）')
const KINDS = need('kinds', '動作類型 id，必須跟設定檔的 kinds 一字不差，否則 make audit 會擋')
const UNIT_TYPE = need('unitType', '單元型別，通常是設定檔的 ui.problemType')
const OUT = need('out', '寫到哪，例如 "examples/body/data/ch10.json"——框架不猜是哪一門課')

const GOAL = A.goal || ''
const LANGS = A.languages || ['繁中', '簡中', '英文']
const CHANNELS = A.channels || []
const MIN_VIEWS = A.minViews || 5000

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
      `逐一驗證單元 ${u.id}（${u.name}）的 YouTube 影片是否存在且公開。
**不要相信上游宣稱**，一支一支打：

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
      // unitId 一律以腳本手上的 u.id 為準，不收 agent 回傳的。這個欄位在 schema 裡
      // 是必填，但驗證的 prompt 本來沒告訴 agent 單元 id，它只能編一個——實測全部
      // 編成 "unknown"，於是寫檔時 units.find() 找不到對應單元，四個單元的 id 撞成
      // 同一個、name 全是 null，而稽核從頭到尾沒有一句話。
      // 這是第 3 類工作（算術），照這份工作流程自己的分工就不該問 agent。
    ).then((v) => ({ ...v, unitId: u.id, _search: res }))
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

// ── 單元身分。以前完全沒查，於是 id 全撞成 "unknown"、name 全是 null 的一份檔案
// 照樣通過稽核並落地。判斷力一點都用不上，純粹是集合運算。
const plannedIds = new Set(units.map((u) => u.id).filter(Boolean))
const gotIds = rows.map((r) => r.unitId)
const badIds = gotIds.filter((id) => !plannedIds.has(id))
const dupeIds = [...new Set(gotIds.filter((id, i) => gotIds.indexOf(id) !== i))]
const namelessUnits = rows
  .filter((r) => !units.find((u) => u.id === r.unitId)?.name)
  .map((r) => r.unitId)

// 同單元重複與跨單元共用是兩件事，以前混在一起叫 duplicatesAcrossUnits，而且都不擋。
// 但 make audit 對這兩者的態度相反：跨單元共用只是「規格允許的少量重疊」，
// 同一個單元裡放兩次同一支影片是**錯誤**。混著報的結果是這份工作流程會開心寫出
// 一份 audit 會拒收的檔案——策展跑了十幾分鐘，卻要到 build 才知道白跑。
const withinUnit = [...seen.entries()]
  .map(([id, us]) => [id, us.filter((u, i) => us.indexOf(u) !== i)])
  .filter(([, repeats]) => repeats.length)
  .map(([id, repeats]) => `${id} 在 ${[...new Set(repeats)].join('、')} 裡出現不只一次`)
const dupes = [...seen.entries()].filter(([, us]) => new Set(us).size > 1)
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
  unknownUnitIds: badIds,
  duplicateUnitIds: dupeIds,
  unitsWithoutName: namelessUnits,
  dead,
  mismatched,
  duplicatesWithinUnit: withinUnit,
  duplicatesAcrossUnits: dupes.map(([id, us]) => `${id} 出現在 ${[...new Set(us)].join('、')}`),
  blanks,
  blanksWithoutNote: blanksNoNote,
  belowMinViews: lowViews,
  searchLog: rows.flatMap((r) => (r._search?.searchLog || []).map((l) => `${r.unitId} · ${l}`)),
}

log(
  `稽核：單元 ${report.units.got}/${report.units.want}、動作 ${report.drills.got}/${report.drills.want}、` +
    `驗證通過 ${okIds.size}、失效 ${dead.length}、` +
    `同單元重複 ${withinUnit.length}、跨單元共用 ${dupes.length}、` +
    `留空 ${blanks.length}（其中 ${blanksNoNote.length} 筆沒寫 note）、` +
    `身分異常 ${badIds.length + dupeIds.length + namelessUnits.length}`,
)

const blocking =
  !report.units.ok ||
  !report.drills.ok ||
  dead.length > 0 ||
  blanksNoNote.length > 0 ||
  withinUnit.length > 0 ||
  badIds.length > 0 ||
  dupeIds.length > 0 ||
  namelessUnits.length > 0

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

/* ── 5. 潤稿：把散文欄位的 AI 痕跡去掉 ───────────────────────────────────
   策展 agent 一次要寫幾十段 assessment 與 why，寫出來的中文會很穩定地帶上
   那組痕跡：否定式排比、揭示前的破折號、沒有出處的「專家認為」。它不會讓
   任何檢查變紅，網站也完全正常，只是聽起來像機器——而這是課程唯一直接
   對使用者說話的地方。

   只送散文，而且只送字串。`title` / `channel` 是照抄 YouTube 的事實，
   `name` / `target` / `dose` 是課程術語，改一個字就是錯的——所以整份
   payload 不交給 agent，只給它「路徑 → 字串」，回來由腳本自己貼回去。
   結構、順序、其餘欄位它一概碰不到。

   權威的檢查在 `make audit` 的「文案」區段（同一組規則，還會掃設定檔），
   這裡是先過一手，免得每次策展完都要人工回頭改。            */

phase('潤稿')

const prose = []
payload.forEach((u, i) => {
  if (u.assessment) prose.push({ key: `${i}.assessment`, text: u.assessment })
  if (u.lesson?.why) prose.push({ key: `${i}.lesson.why`, text: u.lesson.why })
  if (u.lesson?.note) prose.push({ key: `${i}.lesson.note`, text: u.lesson.note })
  ;(u.drills || []).forEach((d, j) => {
    if (d?.note) prose.push({ key: `${i}.drills.${j}.note`, text: d.note })
  })
})

if (prose.length) {
  const POLISH_SCHEMA = {
    type: 'object',
    required: ['rewritten'],
    properties: {
      rewritten: {
        type: 'array',
        items: {
          type: 'object',
          required: ['key', 'text'],
          properties: {
            key: { type: 'string', description: '照抄輸入的 key，不要改' },
            text: { type: 'string', description: '改寫後的字串；沒有要改就原樣回傳' },
          },
        },
      },
    },
  }

  const polished = await agent(
    `把下面這些課程散文的 AI 寫作痕跡去掉，語域維持**正式**。

要拿掉的：
- 否定式排比（「不只是 A，而是 B」）→ 只講你真正要講的那一半
- 揭示前的破折號（「…——其實是…」）→ 改成句號或逗號
- 宣傳性最高級（「最好的」「最佳範例」）→ 拿掉，除非給得出比較依據
- 模糊歸因（「專家認為」「研究表明」）→ 指名出處，指不出來就刪掉這個主張
- 填充連接詞（「此外」「換句話說」「值得注意的是」）→ 直接刪
- 膚淺的意義昇華（「彰顯了」「標誌著」「奠定了基礎」）→ 換成具體事實
- 三段式湊數：拿掉一項句子還完整的話，那三項就是湊的。兩項通常比三項好

**不要做的事**（這幾條違反就是這一輪失敗）：
- 不要改動任何事實：數字、秒數、解剖名詞、動作名稱、肌肉名稱一字不動
- 不要改 key，也不要增減項目。輸入幾筆就回幾筆
- assessment 必須維持**可操作**：它要告訴讀者怎麼自己做這個檢查，
  不是描述問題。改寫後仍須保留具體的動作、位置與判讀標準
- 不要加入第一人稱、感想或修辭。這是課程文案，不是部落格
- 沒有需要改的就把原文原樣回傳

共 ${prose.length} 筆：
${JSON.stringify(prose, null, 1)}`,
    { schema: POLISH_SCHEMA, label: `polish:${CHAPTER}`, phase: '潤稿' },
  )

  // ── 確定性把關：agent 只能改字，不能改結構。回傳的 key 一律以輸入為準比對。
  const byKey = new Map((polished?.rewritten || []).map((r) => [r.key, r.text]))
  const missing = prose.filter((p) => !byKey.has(p.key)).map((p) => p.key)
  const extra = [...byKey.keys()].filter((k) => !prose.some((p) => p.key === k))
  const emptied = prose.filter((p) => byKey.has(p.key) && !String(byKey.get(p.key) || '').trim())

  if (missing.length || extra.length || emptied.length) {
    log(
      `⚠ 潤稿回傳對不上（少 ${missing.length}、多 ${extra.length}、空 ${emptied.length}），` +
        '整批不採用，保留原文——寧可文字帶點 AI 味，也不要靜靜掉一段 assessment',
    )
  } else {
    let changed = 0
    for (const { key, text } of prose) {
      const next = byKey.get(key)
      if (next === text) continue
      changed++
      const [i, ...rest] = key.split('.')
      const u = payload[Number(i)]
      if (rest[0] === 'assessment') u.assessment = next
      else if (rest[0] === 'lesson') u.lesson[rest[1]] = next
      else if (rest[0] === 'drills') u.drills[Number(rest[1])].note = next
    }
    log(`潤稿：${prose.length} 筆散文，改寫 ${changed} 筆`)
  }
}

phase('寫檔')

await agent(
  `把下面這份 JSON 原封不動寫進 \`${OUT}\`，外層包成：

{"chapter": "${CHAPTER}", "title": "${TITLE}", "units": <下面的陣列>}

**不要修改任何欄位值**——它已經通過驗證與稽核，你的工作只有寫檔。
寫完跑 \`python3 -c "import json; json.load(open('${OUT}'))"\` 確認 JSON 合法，回報結果。

${JSON.stringify(payload, null, 1)}`,
  { label: `write:${CHAPTER}`, phase: '寫檔' },
)

log(`✓ 已寫入 ${OUT}`)

// 寫完不等於這一章做完了。實測把產出灌進 make audit 之後才發現，這兩件事
// 沒人提醒就會忘記——而它們都要到 build／audit 才會變成紅字。
log(
  `還沒做完：(1) 這 ${okIds.size} 支影片還不在 video-meta.json 裡，` +
    '要跑 yt-dlp --batch-file 補中繼資料，否則 audit 的覆蓋率會不足；' +
    '(2) 這份工作流程只寫這一章的資料檔，看不到多語言的 alt-lessons——' +
    '課程若有多語言版本，同一支影片可能已經被別的語言版用掉了。',
)
return { written: true, out: OUT, report }
