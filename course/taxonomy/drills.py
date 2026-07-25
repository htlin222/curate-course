#!/usr/bin/env python3
"""動作類別定義與比對。

334 支跟練影片其實只有數十種動作原型。單一動作（例如「臀橋」）沒有專屬文獻，
但它所屬的類別（「臀肌活化訓練」）有。文獻掛在類別上才站得住腳。

比對規則：patterns 內任一關鍵字出現在 動作中文名 / 英文名 / 目標肌群 即命中。
由上而下比對，先命中者勝——所以特異的類別要排在通用類別前面。
"""

from __future__ import annotations

import re

# (id, 顯示名稱, kind, 比對關鍵字)
CATEGORIES: list[tuple[str, str, str, list[str]]] = [
    # ---- 放鬆：特異者優先 ----
    ("subocc-release", "枕下肌群放鬆", "release", ["枕下", "Suboccipital"]),
    ("diaphragm-release", "橫膈膜徒手放鬆", "release", ["橫膈", "Diaphragm"]),
    ("plantar-release", "足底筋膜放鬆", "release", ["足底", "Plantar"]),
    ("scm-release", "頸前肌群徒手放鬆", "release", ["胸鎖乳突", "SCM", "斜角"]),
    ("trigger-point", "激痛點按壓放鬆", "release", ["激痛點", "Trigger Point"]),
    (
        "ball-release",
        "按摩球軟組織放鬆",
        "release",
        [
            "按摩球",
            "網球",
            "Ball Release",
            "Lacrosse",
            "Massage Ball",
            "自我按摩",
            "徒手放鬆",
            "自我放鬆",
            "Self-Release",
            "Self Release",
            "Self-Massage",
            "筋膜放鬆",
            "Myofascial",
        ],
    ),
    ("foam-roll", "泡棉滾筒自我筋膜放鬆", "release", ["滾筒", "Foam Roll", "Foam Rolling", "SMR"]),
    ("soft-tissue", "軟組織自我放鬆", "release", ["放鬆", "Release", "按摩", "Massage", "鬆動"]),
    # ---- 伸展：特異者優先 ----
    ("mckenzie", "McKenzie 俯臥撐起", "stretch", ["McKenzie", "俯臥撐起", "Press-Up", "眼鏡蛇"]),
    ("couch-stretch", "沙發伸展（髖屈肌）", "stretch", ["沙發伸展", "沙發式", "Couch Stretch"]),
    (
        "hipflexor-stretch",
        "髖屈肌伸展",
        "stretch",
        ["髖屈肌伸展", "髂腰肌伸展", "Hip Flexor Stretch", "半跪姿髖", "單跪姿"],
    ),
    (
        "thoracic-rotation",
        "胸椎旋轉鬆動",
        "stretch",
        ["開書", "Open Book", "穿針", "Thread the Needle", "胸椎旋轉", "Thoracic Rotation"],
    ),
    ("sleeper-stretch", "睡姿伸展（後關節囊）", "stretch", ["睡姿伸展", "Sleeper Stretch"]),
    ("hip-9090", "90/90 髖旋轉伸展", "stretch", ["90/90 髖", "90/90 Hip"]),
    (
        "pec-stretch",
        "胸肌門框伸展",
        "stretch",
        [
            "胸大肌伸展",
            "胸小肌伸展",
            "門框",
            "Doorway",
            "Pec Stretch",
            "Pectoral Stretch",
            "胸前伸展",
        ],
    ),
    (
        "hamstring-stretch",
        "腿後肌伸展",
        "stretch",
        ["腿後肌伸展", "腿後側伸展", "Hamstring Stretch", "膕旁肌伸展"],
    ),
    (
        "calf-stretch",
        "小腿伸展",
        "stretch",
        [
            "小腿伸展",
            "比目魚肌",
            "腓腸肌伸展",
            "Calf Stretch",
            "Soleus Stretch",
            "Gastrocnemius Stretch",
        ],
    ),
    (
        "ankle-mob",
        "踝關節背屈鬆動",
        "stretch",
        ["踝關節背屈", "踝背屈", "Ankle Dorsiflexion", "Banded Ankle"],
    ),
    (
        "glute-stretch",
        "臀肌／梨狀肌伸展",
        "stretch",
        ["四字", "Figure-4", "臀肌伸展", "梨狀肌伸展", "Glute Stretch", "Piriformis Stretch"],
    ),
    ("childs-pose", "嬰兒式與後側肋廓呼吸", "stretch", ["嬰兒式", "Child's Pose"]),
    (
        "neck-stretch",
        "頸部肌群伸展",
        "stretch",
        [
            "上斜方肌伸展",
            "提肩胛肌伸展",
            "頸.*伸展",
            "Levator Scapulae Stretch",
            "Upper Trap.*Stretch",
            "Neck Stretch",
        ],
    ),
    ("adductor-stretch", "內收肌伸展", "stretch", ["內收肌伸展", "Adductor Stretch", "蛙式"]),
    ("lat-stretch", "背闊肌伸展", "stretch", ["闊背肌伸展", "背闊肌伸展", "Lat Stretch"]),
    (
        "joint-mob",
        "關節鬆動術",
        "stretch",
        ["關節鬆動", "後向鬆動", "Joint Mobilization", "Posterior Glide", "彈力帶.*鬆動"],
    ),
    ("static-stretch", "靜態伸展", "stretch", ["伸展", "Stretch", "延展"]),
    # ---- 訓練：特異者優先 ----
    (
        "chin-tuck",
        "頸深屈肌訓練（chin tuck）",
        "train",
        ["收下巴", "Chin Tuck", "顱頸屈曲", "Craniocervical Flexion", "頸深屈肌"],
    ),
    (
        "neck-extensor",
        "頸伸肌群訓練",
        "train",
        ["頸深伸肌", "頸伸肌", "頸椎後伸", "Neck Extensor", "Cervical Extension"],
    ),
    (
        "serratus",
        "前鋸肌訓練",
        "train",
        ["前鋸肌", "Serratus", "Push-Up Plus", "Wall Slide", "牆面滑行", "Protraction"],
    ),
    (
        "scap-retract",
        "中下斜方肌與菱形肌訓練",
        "train",
        [
            "下斜方肌",
            "中斜方肌",
            "菱形肌",
            "Y 字",
            "T 字",
            "W 字",
            "Prone Y",
            "Prone T",
            "Face Pull",
            "肩胛後收",
            "Scapular Retraction",
        ],
    ),
    (
        "rotator-cuff",
        "旋轉肌群訓練",
        "train",
        ["外旋", "旋轉肌", "External Rotation", "Rotator Cuff", "棘下肌"],
    ),
    ("scap-upward-rot", "肩胛上旋訓練", "train", ["上旋", "Upward Rotation", "聳肩", "Shrug"]),
    # 具名動作要排在通用的核心／呼吸類別之前，否則會被吃掉
    ("dead-bug", "死蟲式", "train", ["死蟲", "Dead Bug", "Deadbug"]),
    ("bird-dog", "鳥狗式", "train", ["鳥狗", "Bird Dog", "Birddog"]),
    ("mcgill-curlup", "McGill 捲腹", "train", ["McGill", "Curl-Up", "Curl Up", "捲腹"]),
    (
        "spinal-articulation",
        "脊椎分節控制",
        "train",
        ["分節", "Articulation", "Roll-Up", "捲起", "Segmental"],
    ),
    ("side-plank", "側橋", "train", ["側橋", "側平板", "Side Plank", "Side Bridge"]),
    ("plank", "平板支撐", "train", ["平板支撐", "Plank", "棒式"]),
    (
        "pri-breathing",
        "PRI 呼吸與髖抬",
        "train",
        ["90/90 Hip Lift", "PRI", "氣球", "Balloon", "All-Four Belly Lift", "Belly Lift"],
    ),
    ("pelvic-tilt", "骨盆傾斜控制", "train", ["骨盆前後傾", "骨盆後傾", "骨盆前傾", "Pelvic Tilt"]),
    (
        "hipflexor-strength",
        "髖屈肌肌力訓練",
        "train",
        ["行軍", "March", "抬膝", "Knee Raise", "髖屈肌訓練"],
    ),
    (
        "landing-control",
        "落地緩衝與減速控制",
        "train",
        ["落地", "Landing", "緩衝", "跳", "Hop", "Jump", "減速"],
    ),
    (
        "glute-bridge",
        "臀橋與髖伸展啟動",
        "train",
        ["臀橋", "Glute Bridge", "Hip Thrust", "臀推", "髖伸展啟動", "Hip Extension"],
    ),
    (
        "tva-activation",
        "腹橫肌與深層核心啟動",
        "train",
        ["腹橫肌", "腹內壓", "Draw-In", "TVA", "核心啟動", "Abdominal Bracing"],
    ),
    ("breathing", "橫膈膜呼吸訓練", "train", ["呼吸", "Breathing", "360", "Diaphragmatic"]),
    ("clamshell", "蚌殼式", "train", ["蚌殼", "Clamshell", "Clam"]),
    (
        "hip-abduction",
        "髖外展肌訓練",
        "train",
        [
            "髖外展",
            "臀中肌",
            "側躺抬腿",
            "怪獸走",
            "Monster Walk",
            "Side-Lying Abduction",
            "Lateral Walk",
            "側走",
        ],
    ),
    ("copenhagen", "哥本哈根平板（內收肌）", "train", ["哥本哈根", "Copenhagen"]),
    (
        "hip-hinge",
        "髖鉸鏈與硬舉",
        "train",
        ["髖鉸鏈", "Hip Hinge", "RDL", "羅馬尼亞", "硬舉", "Deadlift"],
    ),
    (
        "squat-pattern",
        "深蹲動作控制",
        "train",
        ["深蹲", "Squat", "分腿蹲", "弓箭步", "Lunge", "下踏", "Step-Down"],
    ),
    ("nordic", "腿後肌離心訓練", "train", ["Nordic", "北歐", "離心.*腿後"]),
    ("calf-raise", "提踵訓練", "train", ["提踵", "Calf Raise", "Heel Raise"]),
    (
        "short-foot",
        "足內在肌訓練（short foot）",
        "train",
        ["Short Foot", "足內在肌", "足弓", "縮足", "Toe Yoga", "腳趾瑜伽", "抓毛巾"],
    ),
    ("peroneal-strength", "腓骨肌群訓練（外翻）", "train", ["外翻", "Eversion", "腓骨肌"]),
    ("tibialis-post", "脛後肌訓練（內翻）", "train", ["內翻", "Inversion", "脛後肌", "脛骨後肌"]),
    (
        "balance",
        "平衡與本體感覺訓練",
        "train",
        ["平衡", "本體感覺", "Balance", "Proprioception", "單腳站", "Single-Leg Stance"],
    ),
    ("hip-ir", "髖內旋訓練", "train", ["髖內旋", "Internal Rotation", "內旋"]),
    (
        "erector-endurance",
        "背伸肌耐力訓練",
        "train",
        ["背伸展", "豎脊肌", "Back Extension", "Superman", "俯臥伸展"],
    ),
    (
        "posture-cue",
        "姿勢再教育與動作提示",
        "train",
        ["站姿", "本體感覺再教育", "姿勢", "Posture", "對位", "Alignment"],
    ),
]


def _match(cat_patterns: list[str], haystack: str) -> bool:
    for p in cat_patterns:
        if (
            re.search(p, haystack, re.I)
            if any(c in p for c in ".*+?[]")
            else p.lower() in haystack.lower()
        ):
            return True
    return False


def classify(drill: dict) -> str | None:
    """回傳動作所屬的類別 id。"""
    hay = " ".join(str(drill.get(k) or "") for k in ("name", "en", "target", "title"))
    kind = drill.get("kind")
    # 先在同 kind 內找，避免「伸展」類關鍵字誤抓訓練動作
    for cid, _, ck, pats in CATEGORIES:
        if ck == kind and _match(pats, hay):
            return cid
    for cid, _, ck, pats in CATEGORIES:
        if ck != kind and _match(pats, hay):
            return cid
    return None


NAMES = {cid: name for cid, name, _, _ in CATEGORIES}
KINDS = {cid: kind for cid, _, kind, _ in CATEGORIES}
