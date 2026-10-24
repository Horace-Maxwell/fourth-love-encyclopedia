#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
藏书语料探针 —— 第四爱百科 10-藏书索引 的数据引擎

对本地藏书目录做一次全量元数据扫描，产出结构化 JSON + markdown 索引。
只读语料文件，不修改、不移动、不写入藏书目录。

处理的坑（来自摸底调查）：
  · 编码三分天下：UTF-8(53.6%) / GBK 系(42.2%) / UTF-16(10 个)
  · 117 个文件带 BOM，89% 是 CRLF
  · 混入 BL/BG 作品需靠代词分布识别
  · 文件名标签只覆盖约一半亚型，需靠正文探针补
用法：
    python3 probe_corpus.py
"""

import os
import re
import json
import hashlib
import unicodedata
from pathlib import Path
from collections import Counter, defaultdict

from paths import CORPUS, LIB

# ── 路径配置 ──────────────────────────────────────────────────────────
GB_ROOT = LIB.parent
# v1 只扫两个合集目录。目录名是资源站打包时起的名字，属于藏书清单信息，
# 不写进公开仓库（preflight 会拦）。要重跑 v1 时用环境变量给出目录名，
# 多个用 os.pathsep 隔开；全量扫描请用 probe_v2.py。
CORPUS_DIRS = [CORPUS / n for n in
               os.environ.get("GB_PROBE_V1_DIRS", "").split(os.pathsep) if n]
OUT_DIR = GB_ROOT / "第四爱百科" / "10-藏书索引"
OUT_JSON = OUT_DIR / "_藏书元数据.json"

PROBE_BYTES = 6000      # 站头/文案探测读取的字节数
BODY_SAMPLE = 400_000   # 代词统计的正文采样上限（字符），够稳且不炸内存


# ── 编码处理 ──────────────────────────────────────────────────────────
def decode_bytes(raw: bytes):
    """按 BOM 与试解码顺序还原文本，返回 (text, encoding_label)。"""
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le", errors="replace").lstrip("﻿"), "UTF-16LE"
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace").lstrip("﻿"), "UTF-16BE"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "UTF-8-BOM"
    try:
        return raw.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        pass
    # GB18030 是 GBK 超集，摸底验证 100/100 全通过
    try:
        return raw.decode("gb18030"), "GB18030"
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace"), "GB18030-lossy"


def read_text(path: Path, limit=None):
    with open(path, "rb") as f:
        raw = f.read() if limit is None else f.read(limit)
    text, enc = decode_bytes(raw)
    return text.replace("\r\n", "\n").replace("\r", "\n"), enc


# ── 文件名标签词表 ────────────────────────────────────────────────────
# 顺序有意义：先匹配长词，避免「女尊」吃掉「半女尊」
FILENAME_TAGS = [
    # 类型标识
    ("第四爱", "第四爱"), ("女攻", "女攻"), ("男受", "男受"), ("总攻", "总攻"),
    ("半女尊", "半女尊"), ("女尊", "女尊"), ("女强", "女强"), ("妻主", "妻主"),
    ("女A男O", "女A男O"), ("女a男o", "女A男O"), ("女Alpha", "女A男O"),
    ("ABO", "ABO"), ("abo", "ABO"), ("Abo", "ABO"),
    ("GB", "GB"), ("gb", "GB"), ("Gb", "GB"),
    # 关系结构
    ("1v1", "1v1"), ("1V1", "1v1"), ("一对一", "1v1"),
    ("np", "np"), ("NP", "np"), ("Np", "np"),
    # 权力动态
    ("训诫", "训诫"), ("调教", "调教"), ("BDSM", "BDSM"), ("bdsm", "BDSM"),
    ("sp", "sp"), ("主奴", "主奴"), ("奴", "奴系"), ("忠犬", "忠犬"),
    ("疯狗", "犬系"), ("狗", "犬系"), ("驯服", "驯服"), ("征服", "征服"),
    ("强制", "强制"), ("囚禁", "囚禁"), ("虐受", "虐受"), ("虐", "虐"),
    # 人设
    ("高岭之花", "高岭之花"), ("美强惨", "美强惨"), ("清冷", "清冷"),
    ("禁欲", "禁欲"), ("病娇", "病娇"), ("偏执", "偏执"), ("黑莲花", "黑莲花"),
    ("人夫", "人夫"), ("娇夫", "娇夫"), ("小媳妇", "娇夫"), ("沙雕", "沙雕"),
    # 身份关系
    ("霸总", "霸总"), ("师尊", "师尊"), ("师父", "师徒"), ("老师", "师生"),
    ("公主", "公主"), ("长公主", "公主"), ("女帝", "女帝"), ("女皇", "女帝"),
    ("将军", "将军"), ("元帅", "军旅"), ("侍卫", "侍卫"), ("男宠", "男宠"),
    ("哥哥", "兄弟"), ("弟弟", "兄弟"), ("姐姐", "姐弟"), ("皇姐", "骨科"),
    ("骨科", "骨科"), ("父女", "骨科"), ("义父", "骨科"), ("养父", "骨科"),
    ("正君", "女尊称谓"), ("侧夫", "女尊称谓"), ("夫郎", "女尊称谓"),
    # 世界背景
    ("修仙", "修仙"), ("魔尊", "修仙"), ("魔君", "修仙"), ("剑君", "修仙"),
    ("圣女", "修仙"), ("道姑", "修仙"), ("武林", "武侠"), ("江湖", "武侠"),
    ("星际", "星际"), ("末日", "末世"), ("末世", "末世"), ("血族", "非人"),
    ("怪物", "非人"), ("校园", "校园"), ("穿书", "穿书"), ("快穿", "快穿"),
    ("穿越", "穿越"), ("重生", "重生"), ("双重生", "双重生"), ("系统", "系统"),
    ("种田", "种田"), ("宫", "宫廷"),
    # 情节套路
    ("火葬场", "追妻火葬场"), ("破镜重圆", "破镜重圆"), ("替身", "替身"),
    ("出轨", "NTR"), ("绿", "NTR"), ("包养", "包养"), ("契约", "契约"),
    ("先婚后爱", "先婚后爱"), ("失忆", "失忆"), ("掉马", "马甲掉马"),
    ("生子", "生子"), ("怀了", "生子"), ("受孕", "生子"), ("好孕", "生子"),
    ("双性", "双性"),
    # 尺度
    ("高H", "高H"), ("高h", "高H"), ("清水", "清水"), ("微H", "微H"),
    ("微h", "微H"),
    # 完成度与来源
    ("完结", "完结"), ("番外", "有番外"), ("be", "BE"), ("BE", "BE"),
    ("废文", "源:废文"), ("FW", "源:废文"), ("HT", "源:海棠"),
    ("MJ", "源:MJ"), ("po18", "源:po18"), ("v文", "源:V文"),
]

# 站头自述标签（各站导出文件的页眉格式）
HEADER_PATTERNS = [
    (r"Original Novel\s*-\s*(BL|GL|BG)", "站头体裁"),
    (r"原创小说\s*[-–]\s*(BL|GL|GB|BG)", "站头体裁"),
    (r"原创[\s·、-]*(男男|女女|男女)", "站头体裁"),
    (r"文章类型[:：]\s*([^\n]{1,20})", "文章类型"),
    (r"作品视角[:：]\s*([^\n]{1,20})", "作品视角"),
    (r"文案[:：]", "有文案"),
    (r"内容标签[:：]\s*([^\n]{1,80})", "内容标签"),
    (r"搜索关键字[:：]\s*([^\n]{1,80})", "搜索关键字"),
    (r"主角[:：]\s*([^\n]{1,40})", "主角"),
]

CHAPTER_PATTERNS = [
    re.compile(r"^\s*☆[、,]"),
    re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百千零两]+\s*章"),
    re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百千零两]+\s*节"),
    re.compile(r"^\s*Chapter\s*\d+", re.I),
]


def extract_filename_tags(name: str):
    tags, seen = [], set()
    for pat, tag in FILENAME_TAGS:
        if pat in name and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def extract_serial_state(name: str):
    """从文件名判断完成度：完结 / 连载中(更XX) / 未知"""
    if re.search(r"更\s*\d+", name):
        m = re.search(r"更\s*(\d+)", name)
        return "连载快照", int(m.group(1))
    if "完结" in name or "完" in name:
        return "完结", None
    return "未知", None


def extract_author(name: str):
    for pat in (r"作者[:：]\s*([^\s（(\[【]{1,20})",
                r"作家[:：]\s*([^\s（(\[【]{1,20})",
                r"[Bb][Yy]\s*([^\s（(\[【]{1,20})"):
        m = re.search(pat, name)
        if m:
            return m.group(1).strip("-—_. ")
    return ""


def clean_title(name: str):
    """从文件名剥出作品名。"""
    t = re.sub(r"\.(txt|TXT)$", "", name)
    t = re.split(r"作者[:：]|作家[:：]|\sby\s|\sBy\s|\sBY\s", t)[0]
    t = re.sub(r"[（(\[【].*?[)）\]】]", "", t)
    t = re.sub(r"[《》]", "", t)
    t = re.sub(r"^\s*(完结|\[完结\]|【完结】|\d+)\s*", "", t)
    return t.strip(" -—_.·") or name


# ── 正文探针 ──────────────────────────────────────────────────────────
QUOTE_SPANS = re.compile(r"[「『“\"][^」』”\"]{0,300}[」』”\"]")

# 女尊/GB 制度词：出现即为强证据，BL/BG 里不会出现
FEMDOM_LEXICON = [
    "妻主", "正君", "侧君", "侍君", "夫郎", "夫侍", "男妻", "父君", "父后",
    "女尊", "女攻", "男受", "第四爱", "女帝", "女皇", "男宠", "小爹",
    "纳夫", "入赘", "女A", "女alpha", "女Alpha", "雌君",
]
# 男男向强证据。注意：攻/受/小攻/小受/腹黑攻 这类词 GB 圈同样在用（攻受术语
# 本就借自耽美圈），拿它们判 BL 会大面积误伤——只保留 BL 独占的体裁自述词。
BL_LEXICON = ["男男", "耽美", "纯爱文", "BL文", "双男主"]

# 第一人称叙事时用来判断叙述者性别的旁证词（女性自指侧）
FEM_NARRATOR_LEXICON = [
    "裙子", "裙摆", "长裙", "高跟鞋", "口红", "眉笔", "化妆", "胸罩", "文胸",
    "内衣", "月经", "大姨妈", "长发", "马尾", "丝袜", "耳环", "指甲油",
    "我一个女人", "我是女人", "我这个女人", "身为女人", "女朋友", "闺蜜",
]
# 男性自指侧
MASC_NARRATOR_LEXICON = [
    "喉结", "胡茬", "胡子", "刮胡", "领带", "西装裤", "我一个男人", "我是男人",
    "身为男人", "我这个男人", "兄弟们", "哥们",
]


def probe_body(text: str):
    """代词分布 + 章节数 + 尺度信号 + 制度词证据。"""
    sample = text[:BODY_SAMPLE]
    # 对话里的「你」是对白特征而非叙事人称，剥掉引号内容再算第二人称
    narration = QUOTE_SPANS.sub("", sample)

    ta, she, me = sample.count("他"), sample.count("她"), sample.count("我")
    you_narr = narration.count("你")
    total_3rd = ta + she
    she_ratio = she / total_3rd if total_3rd else 0.0
    # 第一人称占比：叙事人称由「我」承担时，「她」的低占比不能作为无女性角色的证据
    me_ratio = me / (me + total_3rd) if (me + total_3rd) else 0.0
    narr_tokens = you_narr + narration.count("他") + narration.count("她") + narration.count("我")
    you_ratio = you_narr / narr_tokens if narr_tokens else 0.0

    femdom_hits = sum(sample.count(w) for w in FEMDOM_LEXICON)
    bl_hits = sum(sample.count(w) for w in BL_LEXICON)
    fem_narr = sum(sample.count(w) for w in FEM_NARRATOR_LEXICON)
    masc_narr = sum(sample.count(w) for w in MASC_NARRATOR_LEXICON)

    chapters = 0
    for line in text.split("\n"):
        if any(p.search(line) for p in CHAPTER_PATTERNS):
            chapters += 1

    # 尺度粗判：露骨词密度（每万字）
    explicit_hits = sum(sample.count(w) for w in
                        ("性器", "阴茎", "肉棒", "抽插", "情潮", "高潮",
                         "呻吟", "湿润", "喘息", "交合", "巨物", "腿间"))
    per_10k = explicit_hits / max(len(sample) / 10000, 1)
    if per_10k >= 8:
        heat = "E(高H)"
    elif per_10k >= 2:
        heat = "M(有肉)"
    elif per_10k >= 0.3:
        heat = "T(微H/擦边)"
    else:
        heat = "G/T(清水向)"

    return {
        "他": ta, "她": she, "我": me, "你(叙事层)": you_narr,
        "她占比": round(she_ratio, 3),
        "我占比": round(me_ratio, 3),
        "你占比": round(you_ratio, 3),
        "女尊词命中": femdom_hits,
        "BL词命中": bl_hits,
        "女性叙述者旁证": fem_narr,
        "男性叙述者旁证": masc_narr,
        "章节数": chapters,
        "露骨词密度/万字": round(per_10k, 2),
        "尺度推定": heat,
    }


def probe_header(text: str):
    head = text[:PROBE_BYTES]
    found = {}
    for pat, label in HEADER_PATTERNS:
        m = re.search(pat, head)
        if m:
            found[label] = (m.group(1) if m.groups() else True)
    # 文案首段（只留短摘，不落长文，避免搬运原文）
    blurb = ""
    m = re.search(r"文案[:：]?\s*\n+(.{10,120})", head, re.S)
    if m:
        blurb = re.sub(r"\s+", " ", m.group(1)).strip()[:80]
    return found, blurb


GB_FILENAME_MARKERS = {"女攻", "女尊", "第四爱", "GB", "妻主", "女A男O",
                       "总攻", "女帝", "半女尊", "女强", "男受", "女尊称谓"}

# ── 人工核验覆盖层 ──────────────────────────────────────────────────
# 自动信号无法定案的篇目，逐一读开头人工判定后固化于此。这是权威层，覆盖一切自动判定。
# 判定日期 2026-08。格式：文件名前缀 → (判定, 依据)
MANUAL_VERDICTS = {
    # —— 男男向混入（非本类型，提炼时排除）——
    "《银色器物》": ("BL(混入)", "站头 Original Novel-BL；攻受双方均为男性"),
    "【ABO】仙王蛊鼎": ("BL(混入)", "男性 Alpha × 男性 Omega；剑三同人向"),
    "【ABO】无意勾引": ("BL(混入)", "宣子方为男性（父称其子）×苏纪男性"),
    "【ABO】缺钙怎么办": ("BL(混入)", "文案：端木睿男性受孕，1V1不换攻"),
    "【ABO】逃婚指南": ("BL(混入)", "文案：鬼畜攻×傲娇受，帝国大王子为男性Omega"),
    "和主人的十个约定": ("BL(混入)", "阮向远/雷伊斯等均为男性；另为残卷（自第97章起）"),
    "女王的疯狗": ("BL(混入)", "站头 耽美/男男；戾气攻×双性男受，非女主"),
    "娘娘腔": ("BL(混入)", "水千丞作品，李程秀为男性主角"),
    "强制受孕BY叫我小肉肉": ("BL(混入)", "陆锐明为男性 Alpha 受孕，全员男性"),
    "穿越ABO：大缸": ("BL(混入)", "站头 原创男男；1攻1受1夹心全男性"),
    "未展眉": ("BL(混入)", "苏眉穿越进男性身体，自述『一贯喜欢的弱攻形象』"),
    # —— 男攻女受混入（言情向，非本类型）——
    "宠妻如令": ("BG(混入)", "雾矢翊古言；重生男主卫烜囚禁女主阿菀，男方主导"),
    "看过来，我的Omega": ("BG(混入)", "文案：痴汉男主皇太子勾引太子妃，男攻女受"),
    # —— 自动误判、实为本类型（纠正）——
    "两次捡到药奴小狗": ("GB", "站头『清冷美女医圣攻vs忠犬药奴肌肉受』，GB/bdsm"),
    "失忆后你和霸总破镜重圆了": ("GB(第二人称)", "站头【女攻】；从良渣女×痴情男人，你=女主"),
    "将军总被欺负哭": ("GB", "龚心文；女扮男装女主×忠犬男将军"),
    "异类": ("GB", "女主『我』为特殊生理设定女性，与男助教发展关系"),
    "无法戒断": ("GB", "文案『女攻男，♀药剂师×♂总裁』"),
    "春色微明": ("GB(第二人称)", "文案『女A男O，商户之女×男乞丐，第二人称』"),
    "禁欲": ("GB(第二人称)", "文案『女A男O，骨科，双生子』，你=女Alpha"),
    "肆意": ("GB", "文案『女攻，女主男奴，现代女尊，一女二男』"),
    "贱狗": ("GB", "文案『GB/女攻男受/第四爱』"),
    "错位宠夫": ("GB", "何绮（女）×黎园（男）形婚，女方主导"),
    "隐藏大雕的100种方法": ("GB", "司璟为重生女 Alpha"),
    "她的omega甜又软": ("GB", "标题标注[女A男O]；BL词命中源自文件内群广告"),
    "主角受怀了我的崽": ("GB(穿书)", "女主穿进耽美文与『主角受』发展关系；BL词源自群广告"),
    "喵嗷是个傻白甜-青城": ("GB", "聂青城（女）×何照（男）；BL词源自整理站页眉"),
}


def apply_manual_verdict(filename):
    for prefix, (verdict, reason) in MANUAL_VERDICTS.items():
        if filename.startswith(prefix) or prefix in filename:
            return verdict, "人工核验", [f"人工核验：{reason}"]
    return None


def classify_gender_axis(body, fname_tags, header, filename):
    """
    判定作品的性别配置，并给出置信度。
    返回 (判定, 置信度, 依据列表)。置信度：高/中/低——低的进人工核验队列。

    判定难点（已知，不假装解决）：
      · 第一人称女主叙事会让「她」占比趋零，与 BL 的代词特征重合
      · 纯代词分布无法区分 GB 与 BG（两者都是他+她并存）
    因此制度词（妻主/正君/女攻…）与站头自述才是主证据，代词只作辅证。
    """
    manual = apply_manual_verdict(filename)
    if manual:
        return manual

    reasons = []
    she_ratio, me_ratio = body["她占比"], body["我占比"]
    femdom, blwords = body["女尊词命中"], body["BL词命中"]
    first_person = me_ratio >= 0.35

    # ① 站头自述——最权威
    ht = header.get("站头体裁")
    if isinstance(ht, str):
        up = ht.upper()
        if "BL" in up or "男男" in ht:
            return "BL(混入)", "高", [f"站头自述体裁={ht}"]
        if "GB" in up:
            return "GB", "高", [f"站头自述体裁={ht}"]
        if "BG" in up or "男女" in ht:
            reasons.append(f"站头自述体裁={ht}")

    # ② 制度词——女尊/GB 特有称谓，BL/BG 中不会成规模出现
    if femdom >= 20 and femdom > blwords * 3:
        return "GB", "高", reasons + [f"女尊/GB制度词命中{femdom}次"]
    # BL 词只作弱信号：GB 小说里角色「看耽美小说」之类的情节会命中，不能据此定案
    if blwords >= 8 and femdom < 5:
        reasons.append(f"BL体裁词命中{blwords}次(弱信号，需核验)")

    # ③ 文件名标记——收藏者的分类，可信但非自证
    if GB_FILENAME_MARKERS & set(fname_tags):
        conf = "高" if femdom >= 5 or she_ratio >= 0.15 else "中"
        return "GB", conf, reasons + [
            f"文件名带GB标记{sorted(GB_FILENAME_MARKERS & set(fname_tags))}",
            f"她占比{she_ratio}／女尊词{femdom}"]

    # ④ 第一人称叙事：「她」占比失真，改判叙述者性别
    if first_person:
        fem, masc = body["女性叙述者旁证"], body["男性叙述者旁证"]
        base = [f"第一人称(我占比{me_ratio})，她占比({she_ratio})不作判据"]
        if fem >= 5 and fem > masc * 2:
            return "GB(第一人称女主)", "中", reasons + base + [
                f"女性叙述者旁证{fem}次 vs 男性{masc}次"]
        if masc >= 5 and masc > fem * 2:
            return "存疑(男性叙述者)", "低", reasons + base + [
                f"男性叙述者旁证{masc}次 vs 女性{fem}次"]
        return "存疑(第一人称叙事)", "低", reasons + base + [
            f"叙述者性别旁证不足(女{fem}/男{masc})"]

    if she_ratio < 0.06 and femdom < 3:
        return "BL(疑似混入)", "中", reasons + [
            f"第三人称叙事下她占比极低({she_ratio})，且无女尊制度词"]
    if she_ratio < 0.18:
        return "存疑(男性视角为主)", "低", reasons + [f"她占比偏低({she_ratio})"]

    return "GB(推定)", "中", reasons + [f"她占比{she_ratio}，无制度词旁证"]


# ── 主流程 ────────────────────────────────────────────────────────────
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    for d in CORPUS_DIRS:
        if not d.exists():
            print(f"跳过不存在的目录: {d}")
            continue
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            if p.suffix.lower() not in (".txt",):
                continue

            raw = p.read_bytes()
            size = len(raw)
            md5 = hashlib.md5(raw).hexdigest()
            text, enc = decode_bytes(raw)
            text = text.replace("\r\n", "\n").replace("\r", "\n")

            # 汉字数（剔空白，这才是真实字数）
            chars = sum(1 for c in text if not c.isspace())
            header, blurb = probe_header(text)
            body = probe_body(text)
            fname_tags = extract_filename_tags(p.name)
            axis, axis_conf, axis_reasons = classify_gender_axis(body, fname_tags, header, p.name)
            serial, serial_n = extract_serial_state(p.name)

            records.append({
                "文件名": p.name,
                "目录": d.name,
                "作品名": clean_title(p.name),
                "作者": extract_author(p.name),
                "字节": size,
                "KB": round(size / 1024, 1),
                "字数": chars,
                "万字": round(chars / 10000, 1),
                "编码": enc,
                "md5": md5,
                "性别配置": axis,
                "判定置信度": axis_conf,
                "判定依据": axis_reasons,
                "完成度": serial,
                "连载章数": serial_n,
                "文件名标签": fname_tags,
                "站头信息": {k: v for k, v in header.items() if k != "有文案"},
                "文案摘要": blurb,
                **body,
            })

    # 重复检测
    by_md5 = defaultdict(list)
    for r in records:
        by_md5[r["md5"]].append(r["文件名"])
    dup_groups = {k: v for k, v in by_md5.items() if len(v) > 1}
    dup_files = {f for v in dup_groups.values() for f in v[1:]}
    for r in records:
        r["重复"] = r["文件名"] in dup_files

    # 近重复：作品名相同但 md5 不同
    by_title = defaultdict(list)
    for r in records:
        by_title[r["作品名"]].append(r)
    near_dups = {t: [x["文件名"] for x in v] for t, v in by_title.items()
                 if len(v) > 1 and len({x["md5"] for x in v}) > 1}

    OUT_JSON.write_text(json.dumps({
        "统计时间": "2026-08",
        "文件数": len(records),
        "完全重复组": dup_groups,
        "同名不同版本": near_dups,
        "记录": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 控制台摘要 ──
    total_chars = sum(r["字数"] for r in records)
    need_check = [r for r in records if r["判定置信度"] == "低"
                  or r["性别配置"].startswith("BL")]
    print(f"扫描完成：{len(records)} 篇 / {total_chars:,} 字 ({total_chars/10000:.0f} 万字)")
    print(f"编码分布：{Counter(r['编码'] for r in records).most_common()}")
    print(f"性别配置：{Counter(r['性别配置'] for r in records).most_common()}")
    print(f"置信度：{Counter(r['判定置信度'] for r in records).most_common()}")
    print(f"尺度分布：{Counter(r['尺度推定'] for r in records).most_common()}")
    print(f"完全重复组 {len(dup_groups)} 组，同名不同版本 {len(near_dups)} 组")
    print(f"\n需人工核验 {len(need_check)} 篇：")
    for r in need_check:
        print(f"   · [{r['性别配置']}/{r['判定置信度']}] {r['文件名'][:46]}")
        print(f"       {'; '.join(r['判定依据'])}")
    print(f"\n元数据已写入 {OUT_JSON}")


if __name__ == "__main__":
    main()
