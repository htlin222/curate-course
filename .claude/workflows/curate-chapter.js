export const meta = {
  name: 'curate-chapter',
  description: '策展一個章節：拆單元 → 搜尋候選 → oEmbed 驗證 → 確定性稽核 → 寫檔',
  whenToUse:
    '要為 curate-course 的某一章找齊影片時。一次一章，可恢復、可重跑、每一步都留下結構化紀錄。args 必須是 JSON 物件，不能是自由文字字串：Workflow({name: "curate-chapter", args: {chapter: "CH10", title: "膝蓋", units: 4, drills: 43, kinds: ["release","stretch","train"], unitType: "posture", out: "examples/body/data/ch10.json", goal: "…", minViews: 5000}})。chapter/title/units/drills/kinds/unitType/out 全部必填，值照課程設定檔抄，不要自己編。',
  phases: [
    { title: '對帳', detail: '參數對照課程設定檔：kinds、章節配額對不上就在第 0 秒失敗' },
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
// 長度區間（秒）。預設對齊 audit.py 的通則門檻；課程有自己的 audit.duration 就傳進來。
const LESSON_SEC = A.lessonSeconds || [240, 1440]
const DRILL_SEC = A.drillSeconds || [30, 600]

/* 搜尋的成本結構——量過才知道，不是猜的。

   實測一次策展（4 單元 43 動作）的遙測：四個搜尋 agent 佔全部 cache 的 88%，
   而 cache 幾乎正比於**回合數**，不是搜尋結果的大小（cache/turn 在 29K–52K
   之間近乎常數；線性擬合變異係數 0.26，平方 0.82）。短 agent 的 29K/turn
   就是固定底價：system prompt 與工具定義每一回合都要重讀一次。

   換句話說，貴的不是「搜了 25 次」，是「分成 25 次 Bash 呼叫」。45 回合的
   agent 光底價就吃掉 1.3M。所以規則改成兩件事：

   1. 批次：一次 Bash 跑完一批查詢，25 個回合變 4–5 個。
   2. 先濾再進 context：實測同一個查詢 20 行 1972 bytes → 5 行 481 bytes，
      而真跑時選中的那支還在濾完的結果裡——濾掉的不是答案，是 agent 本來
      就要花 token 讀完再拒絕的東西。

   濾用 awk 而不是 yt-dlp 的 --match-filter，理由是**稽核軌跡**：總筆數要
   留在 log 裡。quality.md 記載 yt-dlp 被限流時會 exit 0 + 空輸出，看起來
   像「這個查詢沒結果」——批次跑會讓它更難發現，所以每個查詢都必須印出
   「共 N 筆」，讓「20 筆濾成 3 筆」跟「0 筆」長得不一樣。 */
const RULES = `
硬性規則（違反就是這一輪失敗，不要自行放寬）：
- video id 一律取自 yt-dlp 的實際輸出，**絕不可憑記憶拼湊**。捏造一個看起來合理的 id 比留空更糟。
- 標題、頻道、秒數、觀看數一律照抄工具輸出，不要自己記憶或估算。

- **搜尋一律批次跑，不要一個查詢叫一次 Bash。** 一次送 5–8 個查詢。
  先把這個函式貼進 shell（每個 agent 一次就好）：

    P=/tmp/curate-<你的單元 id>        # 每個 agent 各自的前綴，不要用 q.txt 這種通用名
    mkdir -p \$P; n=0
    find_videos() {                    # 用法：find_videos <下限秒> <上限秒> "查詢" ...
      local lo=\$1 hi=\$2; shift 2
      for q in "\$@"; do
        n=\$((n+1))
        yt-dlp "ytsearch20:\$q" --flat-playlist --no-update \\
          --print "%(id)s|%(title)s|%(channel)s|%(duration)s|%(view_count)s" \\
          > \$P/\$n.txt 2>/dev/null
        echo "### \$q（\${lo}-\${hi}s）→ 共 \$(wc -l < \$P/\$n.txt) 筆，符合："
        awk -F'|' -v v=${MIN_VIEWS} -v lo=\$lo -v hi=\$hi \\
          '\$NF+0>=v && \$(NF-1)+0>=lo && \$(NF-1)+0<=hi' \$P/\$n.txt
      done
    }

  然後**主課與動作分開叫，長度區間是參數不是預設值**：

    find_videos ${LESSON_SEC[0]} ${LESSON_SEC[1]} "主課查詢一" "主課查詢二" "主課查詢三"
    find_videos ${DRILL_SEC[0]} ${DRILL_SEC[1]} "動作查詢一" "動作查詢二" "動作查詢三" "動作查詢四"

  **為什麼寫成函式而不是一段可以直接改的迴圈**：上一版把動作的區間寫死在
  範例裡，主課的區間只寫在下面一行附註「記得換 lo/hi」。附註打不贏複製貼上——
  實測整章四支主課有三支被 600 秒的上限濾掉，選出來的主課長度中位數只有
  332 秒，而人工把關的版本是 716 秒。講解型的長片根本沒進視野，稽核也不會
  說話，因為每一支都「符合門檻」。**能填錯的參數就不要給預設值。**

  另外兩件事：
  · **欄位從右邊數**：標題本身可能含 \`|\`，所以 \$NF 才是觀看數、\$(NF-1) 才是秒數，\$5 會錯位。
  · **「共 N 筆」那一行不能省**：0 筆代表被限流（yt-dlp 這時是 exit 0 + 空輸出，
    不是影片不存在），跟「有結果但都不合格」是完全不同的兩件事，要分得出來。
  · 原始的 20 筆留在 \$P/\$n.txt 裡，要回頭看被濾掉什麼隨時 grep 得到。

- 觀看數 < ${MIN_VIEWS} 一律不採用（上面的 awk 已經先濾掉了）。
- 語言優先序：${LANGS.join(' > ')}。同等品質下前者勝出。
- searchLog 每個查詢記一行，**帶上「共 N 筆 → 符合 M 筆」**。這是稽核軌跡，不要省。
- 找不到合格影片就把 url 設為 null，並在 note 寫清楚**查過哪些關鍵字、為什麼都不合格**。
  留空是允許的；留空而沒有 note 不是。
${CHANNELS.length ? `- 優先頻道：${CHANNELS.join('、')}` : ''}
`

/* ── 0.5 對帳：參數 vs 設定檔 ─────────────────────────────────────────────
   上一節擋掉了「沒填」，但擋不掉「填錯」。kinds 給了設定檔沒有的 id、
   unitType 跟 ui.problemType 對不上、配額抄錯一位數——這幾種錯不會讓任何
   東西當場壞掉，要等策展跑完十幾分鐘、寫完檔、再跑 make audit 才會知道。
   （audit.py 是逐支比對 kind 是否在 kinds 裡的，對不上就是錯誤。）

   工作流程自己不能讀檔，所以派一個 agent 去讀，回結構化資料；**比對留在
   這裡**。agent 只負責抄，判斷是誰對誰錯不歸它管。            */

phase('對帳')

// out 通常長成 <課程目錄>/data/<章>.json，所以設定檔的位置多半算得出來——
// 但「多半」不等於「一定」：寫到暫存路徑做驗證時就推不出來，而推錯的下場是
// 對帳去讀一個不存在的檔案，然後把「檔案不存在」報成「kinds 對不上」。
// 所以可以用 args.config 明講，推導只是預設值。
const CONFIG_PATH = A.config || `${OUT.split('/').slice(0, -2).join('/')}/course.config.json`

const CONFIG_SCHEMA = {
  type: 'object',
  required: ['configFound', 'kinds', 'chapterFound'],
  properties: {
    configFound: { type: 'boolean', description: '這個路徑到底讀不讀得到檔案' },
    kinds: { type: 'array', items: { type: 'string' }, description: 'kinds[].id，照抄順序' },
    problemType: { type: ['string', 'null'], description: 'ui.problemType，沒有就 null' },
    chapterFound: { type: 'boolean', description: 'chapters 裡有沒有這個 code' },
    chapterTitle: { type: ['string', 'null'] },
    chapterUnits: { type: ['integer', 'null'], description: '該章的 units 配額，沒寫就 null' },
    chapterDrills: { type: ['integer', 'null'], description: '該章的 drills 配額，沒寫就 null' },
    unitTypes: {
      type: 'array',
      items: { type: 'string' },
      description: 'ui.unitTypes 之類「合法的單元型別」清單；沒有這種欄位就回空陣列',
    },
  },
}

const cfg = await agent(
  `讀 \`${CONFIG_PATH}\`，把下面這幾個值**照抄**出來。不要推論、不要修正、
不要因為覺得哪裡怪就改成你認為對的值——你的工作只有抄。

**檔案不存在或讀不到就把 configFound 設成 false，其餘欄位留空**，
不要去別的地方找一個看起來像課程設定檔的東西來頂替。

- \`kinds\` 陣列裡每個元素的 \`id\`（保持原順序）
- \`ui.problemType\`
- \`chapters\` 裡 \`code\` 等於 \`${CHAPTER}\` 的那一項：有沒有找到、\`title\`、\`units\`、\`drills\`
- 如果設定檔有列舉「合法單元型別」的欄位，一併抄出來；沒有就回空陣列

檔案讀不到就直接說讀不到，不要猜內容。`,
  { schema: CONFIG_SCHEMA, label: `reconcile:${CHAPTER}`, phase: '對帳', effort: 'low' },
)

// ── 比對留在腳本裡。agent 抄回來的是事實，這裡才是判斷。
const mismatches = []
if (!cfg || !cfg.configFound) {
  // 這一條要先判、而且要單獨判：檔案不存在的話底下每一項都會「對不上」，
  // 報出來的會是一串看似 kinds 與章節碼有問題的假線索。
  mismatches.push(
    `讀不到 ${CONFIG_PATH}` +
      (A.config ? '' : `（由 out 推導而來；out 不在課程目錄底下的話，用 args.config 明講設定檔位置）`),
  )
} else {
  const declared = cfg.kinds || []
  const unknown = KINDS.filter((k) => !declared.includes(k))
  if (unknown.length) {
    mismatches.push(
      `args.kinds 有 ${unknown.join('、')}，但 ${CONFIG_PATH} 的 kinds 只有 ${declared.join('、')}` +
        '（make audit 會逐支擋下 kind 對不上的動作）',
    )
  }
  if (!cfg.chapterFound) {
    mismatches.push(`${CONFIG_PATH} 的 chapters 裡沒有 ${CHAPTER}——章節碼抄錯，或這一章還沒加進設定檔`)
  } else {
    if (cfg.chapterUnits != null && cfg.chapterUnits !== UNIT_COUNT) {
      mismatches.push(`args.units=${UNIT_COUNT}，但設定檔寫 ${CHAPTER} 是 ${cfg.chapterUnits} 個單元`)
    }
    if (cfg.chapterDrills != null && cfg.chapterDrills !== DRILL_TOTAL) {
      mismatches.push(`args.drills=${DRILL_TOTAL}，但設定檔寫 ${CHAPTER} 是 ${cfg.chapterDrills} 個動作`)
    }
    if (cfg.chapterTitle && cfg.chapterTitle !== TITLE) {
      mismatches.push(`args.title「${TITLE}」，但設定檔寫「${cfg.chapterTitle}」`)
    }
  }
  if (cfg.problemType && UNIT_TYPE !== cfg.problemType) {
    // 只警告：一章的單元型別不見得等於 ui.problemType（觀念章就常常不是）。
    log(`⚠ args.unitType「${UNIT_TYPE}」與 ui.problemType「${cfg.problemType}」不同——刻意的就無視`)
  }
}

if (mismatches.length) {
  throw new Error(
    `參數與設定檔對不上，現在停下來比跑完十幾分鐘再發現便宜：\n  · ${mismatches.join('\n  · ')}`,
  )
}
log(`對帳通過：${CHAPTER}「${cfg.chapterTitle || TITLE}」${UNIT_COUNT} 單元 / ${DRILL_TOTAL} 動作 · kinds ${KINDS.join('、')}`)

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
          // ok 的定義以前寫「200 且標題與頻道相符」，但同一份 prompt 又說「標題不符
          // 時以 oEmbed 為準」——兩句話互相矛盾，agent 照字面選了嚴格的那句，
          // 於是一支 HTTP 200、頻道相符、只是 YouTube 回了另一種語言標題的影片
          // 擋掉整章寫檔，報告還印出「dead · HTTP 200」這種讀不通的話。
          // 現在只有一個定義：**能不能嵌入**。標題差異不是失敗。
          ok: {
            type: 'boolean',
            description: 'HTTP 200 且頻道相符。標題不同不算失敗（YouTube 有多語言與 A/B 標題）',
          },
          oembedTitle: { type: 'string', description: 'oEmbed 回傳的標題，這才是權威值' },
          oembedChannel: { type: 'string' },
          mismatch: { type: 'string', description: '與策展資料有出入時說明差在哪（ok 仍可為 true）' },
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
- 1 支主課（講解型，${LESSON_SEC[0]}–${LESSON_SEC[1]} 秒）
- ${u.drillNames?.length || 0} 支動作影片，依序對應：${(u.drillNames || []).join('、')}

每支動作影片長度 ${DRILL_SEC[0]}–${DRILL_SEC[1]} 秒。kind 從 ${KINDS.join(' / ')} 裡選。
assessment 要寫成**讀者可以自己做的檢核方法**，不是問題描述——
「側面錄影看肋廓下緣有沒有掀起來」是可操作的，「核心穩定很重要」不是。

**先把要查的關鍵字一次想齊**，分成 2–3 批送出去（每批 5–8 個查詢，見下面的批次寫法），
看完一批的結果再決定還缺什麼。不要一個動作查一次、看一次、再查下一個——
那會讓這個 agent 的成本變成三倍以上，而找到的片不會比較好。
${RULES}`,
      { schema: SEARCH_SCHEMA, label: `search:${u.id}`, phase: '搜尋' },
    ),
  // ── 驗證（同一單元找完就立刻驗，不等別人）
  (res, u) => {
    const ids = [res?.lesson?.videoId, ...(res?.drills || []).map((d) => d.videoId)].filter(Boolean)
    if (!ids.length) return { unitId: u.id, results: [], _search: res }
    return agent(
      `逐一驗證單元 ${u.id}（${u.name}）的 YouTube 影片是否存在且公開。
**不要相信上游宣稱**，一支一支打。

**不要用中間檔。** 這些驗證 agent 是並行跑的，寫 \`/tmp/o.json\` 這種通用檔名
一定會跟別的單元撞在一起——實測就撞過：兩個 agent 同時用 \`o.json\`，各自讀回
對方剛寫的內容，於是回報了七筆假的「頻道不符」，看起來像策展把 id 抄錯了。
（macOS 的 \`/tmp\` 就是 \`/private/tmp\`，換前綴不會讓它變成兩個檔案。）

直接把回應接到 stdout，一次跑完一批：

for id in <所有 id>; do
  printf '=== %s ' "\$id"
  curl -s -w '\\nHTTP:%{http_code}\\n' \\
    "https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D\$id&format=json" \\
    | python3 -c "
import sys, json
raw = sys.stdin.read()
body, _, tail = raw.rpartition('HTTP:')
print(tail.strip(), end=' ')
try:
    d = json.loads(body)
    print(repr(d.get('title')), '|', repr(d.get('author_name')))
except Exception:
    print('(no json)')
"
done

真的需要落檔就用 \`\$P/oe-\$id.json\`（\`P=/tmp/curate-${u.id}\`，先 mkdir -p），
**檔名一定要含 id**——固定檔名在迴圈裡連自己都會覆蓋自己。

200 = 存在且公開；401 = 已設為私人或禁止嵌入；404 = 已刪除。
200 時再取回 JSON，抄下 title 與 author_name。

**ok 只回答一件事：這支影片能不能嵌入。** 判準是 HTTP 200 且**頻道**相符。

- 標題不同**不是失敗**。YouTube 有多語言標題與 A/B 測試，同一支片不同時間會回不同
  標題。照抄 oEmbed 回的那個到 oembedTitle，把差異寫進 mismatch，ok 仍然是 true——
  oEmbed 是權威值，策展時記的標題才是過期的那個。
- 頻道不同才要把 ok 設成 false：那通常代表策展時抄錯了 id，指到了別支影片。

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
   沒有任何一項需要判斷力，所以沒有任何一項該問 agent。

   這 60 行決定要不要落地，是整份工作流程唯一的品質關卡——而它本來一行測試
   都沒有。實測在裡面找到三個 bug（unitId 由 agent 猜、身分完全沒查、同單元
   重複沒擋），全部是靠跑出來的，不是靠測試。一個沒有測試的品質關卡，本身
   就是最不該信任的東西。

   所以整段抽成一個純函式，用下面的哨兵註解框起來：
   tests/curation-audit.test.js 會把這兩行之間的原始碼原地抽出來執行，
   測的就是這裡真正跑的程式碼，不是另外抄一份。改動哨兵之間的東西，
   測試就會跟著測到；把哨兵刪掉，測試會直接失敗。            */

// <audit-core>
/** 策展結果 → { report, blocking, summary }。純函式：不讀檔、不呼叫 agent、
    同樣的輸入永遠同樣的輸出，所以可以測。 */
function auditCuration({ chapter, units, rows, wantUnits, wantDrills, minViews }) {
  const okIds = new Set()
  const dead = []
  const wrongVideo = []
  const mismatched = []

  for (const r of rows) {
    for (const v of r.results || []) {
      if (v.ok) {
        okIds.add(v.videoId)
        if (v.mismatch) mismatched.push(`${r.unitId} · ${v.videoId} · ${v.mismatch}`)
      } else if (v.httpStatus === 200) {
        // 200 卻不 ok = 影片活著但不是我們以為的那支（頻道對不上），多半是抄錯 id。
        // 以前這種也丟進 dead，於是報告印出「dead · HTTP 200」——讀不通，而且會
        // 讓人跑去查連結是不是掛了，真正的問題卻是策展資料指錯了片。
        wrongVideo.push(`${r.unitId} · ${v.videoId} · ${v.mismatch || '頻道與策展資料不符'}`)
      } else {
        dead.push(`${r.unitId} · ${v.videoId} · HTTP ${v.httpStatus}`)
      }
    }
  }

  const seen = new Map() // videoId -> [unitId]
  const blanks = []
  const blanksNoNote = []
  let lessons = 0
  let drills = 0

  for (const r of rows) {
    const s = r._search || {}
    const all = [['lesson', s.lesson], ...(s.drills || []).map((d) => ['drill', d])]
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

  // ── 單元身分。以前完全沒查，於是 id 全撞成 "unknown"、name 全是 null 的一份
  // 檔案照樣通過稽核並落地。判斷力一點都用不上，純粹是集合運算。
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
      .filter((v) => v?.videoId && typeof v.views === 'number' && v.views < minViews)
      .map((v) => `${r.unitId} · ${v.videoId} · ${v.views} 次觀看`),
  )

  const report = {
    chapter,
    units: { got: rows.length, want: wantUnits, ok: rows.length === wantUnits },
    drills: { got: drills, want: wantDrills, ok: drills === wantDrills },
    lessons,
    verified: okIds.size,
    unknownUnitIds: badIds,
    duplicateUnitIds: dupeIds,
    unitsWithoutName: namelessUnits,
    dead,
    wrongVideo,
    mismatched,
    duplicatesWithinUnit: withinUnit,
    duplicatesAcrossUnits: dupes.map(([id, us]) => `${id} 出現在 ${[...new Set(us)].join('、')}`),
    blanks,
    blanksWithoutNote: blanksNoNote,
    belowMinViews: lowViews,
    searchLog: rows.flatMap((r) => (r._search?.searchLog || []).map((l) => `${r.unitId} · ${l}`)),
  }

  // 擋不擋的判準：只有「寫出去一定是錯的」才擋。跨單元共用、觀看數偏低、
  // 標題與 oEmbed 不符都只是要人看一眼，不該讓十幾分鐘的策展整批作廢。
  const blocking =
    !report.units.ok ||
    !report.drills.ok ||
    dead.length > 0 ||
    wrongVideo.length > 0 ||
    blanksNoNote.length > 0 ||
    withinUnit.length > 0 ||
    badIds.length > 0 ||
    dupeIds.length > 0 ||
    namelessUnits.length > 0

  const summary =
    `稽核：單元 ${report.units.got}/${report.units.want}、` +
    `動作 ${report.drills.got}/${report.drills.want}、` +
    `驗證通過 ${okIds.size}、失效 ${dead.length}、指錯片 ${wrongVideo.length}、` +
    `同單元重複 ${withinUnit.length}、跨單元共用 ${dupes.length}、` +
    `留空 ${blanks.length}（其中 ${blanksNoNote.length} 筆沒寫 note）、` +
    `身分異常 ${badIds.length + dupeIds.length + namelessUnits.length}`

  return { report, blocking, summary }
}
// </audit-core>

phase('寫檔')

const rows = curated.filter(Boolean)
const { report, blocking, summary } = auditCuration({
  chapter: CHAPTER,
  units,
  rows,
  wantUnits: UNIT_COUNT,
  wantDrills: DRILL_TOTAL,
  minViews: MIN_VIEWS,
})

log(summary)

if (blocking) {
  log('✗ 未通過確定性稽核，不寫檔——修好上面列出的問題再重跑（可用 resumeFromRunId 保留已完成的搜尋）')
  return { written: false, report }
}

// 只有全部過關才落地。寫檔是 agent 做的（腳本沒有檔案系統存取）。
//
// oEmbed 回的標題是權威值，策展時抄下來的是可能已經過期的那個——規則早就這樣寫，
// 但寫檔一直用策展的值，等於那句話從來沒有生效。這裡真的採用它，而且是在腳本裡
// 對著 videoId 查表，不是再問一次 agent。
const oembed = new Map()
for (const r of rows) {
  for (const v of r.results || []) {
    if (v.ok && v.videoId) oembed.set(v.videoId, v)
  }
}
let retitled = 0

const payload = rows.map((r) => {
  const s = r._search || {}
  const shape = (v, extra = {}) => {
    if (!v?.videoId) {
      return { ...(v?.name ? { name: v.name, kind: v.kind } : {}), url: null, note: v?.note }
    }
    const o = oembed.get(v.videoId)
    const title = o?.oembedTitle || v.title
    const channel = o?.oembedChannel || v.channel
    if (o?.oembedTitle && o.oembedTitle !== v.title) retitled++
    return {
      ...(v.name ? { name: v.name, en: v.en, kind: v.kind, target: v.target, dose: v.dose } : {}),
      title,
      channel,
      url: `https://www.youtube.com/watch?v=${v.videoId}`,
      duration: `${Math.floor(v.seconds / 60)}:${String(v.seconds % 60).padStart(2, '0')}`,
      ...extra,
    }
  }
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

if (retitled) log(`${retitled} 支影片改用 oEmbed 回的標題（策展時抄的那個已經過期或是別的語言版本）`)

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
  `還沒做完：(1) 這 ${report.verified} 支影片還不在 video-meta.json 裡，` +
    '要跑 yt-dlp --batch-file 補中繼資料，否則 audit 的覆蓋率會不足；' +
    '(2) 這份工作流程只寫這一章的資料檔，看不到多語言的 alt-lessons——' +
    '課程若有多語言版本，同一支影片可能已經被別的語言版用掉了。',
)
return { written: true, out: OUT, report }
