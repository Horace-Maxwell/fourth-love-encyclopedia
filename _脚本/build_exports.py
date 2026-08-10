#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出构建器 —— 把 Markdown 主库编译成可直接喂给 AI 的三种产物。

产物（落在 12-导出/）：
  书房世界书包-N.json    酒馆书房 POST /api/oc/desk/import/worlds 可直接导入
                         （单次上限 900 条，超出自动拆批；旧的单文件形态已废弃）
  SillyTavern世界书.json ST 标准格式，酒馆用户可直接导入
  第四爱百科.html        单文件离线百科，浏览器打开即用（含全文搜索）

设计原则：
  · 世界书条目要「用到才上桌」，所以绝大多数条目走关键词触发，
    只有少数纲领性条目设 constant（常驻）。全常驻会瞬间撑爆上下文。
  · 每条控制在 1200 字以内——世界书是注入用的，不是给人读的。
    长条目会挤掉正文的位置。
  · 条目正文里剥掉 markdown 语法与库内互链，AI 不需要那些。

用法：python3 build_exports.py
"""

import re
import json
import html
from pathlib import Path

from paths import LIB

OUT = LIB / "12-导出"
OUT.mkdir(parents=True, exist_ok=True)

# 卷 → (是否常驻, 关键词提取策略)
VOLUME_CFG = {
    "00-编纂规约": None,                       # 不导出（是编库规则，不是创作素材）
    "01-总论": ("kw", ["第四爱", "GB", "女攻男受", "圈史", "英文圈", "AO3"]),
    "02-术语百科": ("kw", []),
    "03-世界观设定": ("kw", ["女尊", "ABO", "世界观", "设定"]),
    "04-人设原型": ("kw", ["人设", "原型", "角色"]),
    "05-剧情套路": ("kw", ["套路", "剧情", "节拍"]),
    "06-尺度与写法": ("kw", ["尺度", "分级", "训诫", "情欲"]),
    "07-语言风格": ("kw", ["语感", "文风", "反AI"]),
    "08-平台生态": ("kw", ["平台", "发文", "晋江", "海棠", "tag"]),
    # 09 卷（逐部作品的精读笔记）已下架：本地保留、.gitignore 排除、不入库，
    # 理由见 00-编纂规约/03-版权与内容红线 1.4。既不入库也不导出——
    # 世界书与 HTML 都是对外产物，把不该发的东西编译进去等于绕过 .gitignore。
    "09-拆解卡": None,
    "10-藏书索引": None,                        # 数据表，不适合注入
    "11-模板包": None,                          # 本身就是成品
    "12-导出": None,
    # 13 卷是从语料里数出来的频次真相，写文时按元素查用，正适合做世界书
    "13-语料挖掘": ("kw", ["人名", "命令", "称谓", "信息素", "宗门", "开场", "名场面"]),
}

# 常驻条目的选取原则：**只有每一楼都该带着的全局约束才常驻**。
# 世界书是注入进上下文的——常驻 N 条就等于每次生成都先付 N 条的 token。
# 实测：把整个 07 卷设为常驻会产生 161 条常驻（约 13 万字），直接挤掉正文位置。
# 因此改为白名单：只挑真正需要「每一楼都遵守」的那几节。
# 匹配用「文档标题关键字 + 节标题关键字」，避免全角/空格差异导致漏配。
ALWAYS_CONST_RULES = [
    ("反 AI 味指南", ["速查", "矫正指令", "人味"]),      # 全局文风约束
    ("女攻叙事语感", ["权力写在叙述层", "称谓双轨"]),      # 女攻语感的两条底线
    ("第二人称写作专论", ["规则清单", "自检"]),           # 只在写第二人称时才该常驻，此处收窄
]


def is_const(doc_title, sec_title):
    for doc_kw, sec_kws in ALWAYS_CONST_RULES:
        if doc_kw.replace(" ", "") in doc_title.replace(" ", ""):
            if any(k in sec_title for k in sec_kws):
                return True
    return False


def strip_md(s: str) -> str:
    """把 markdown 压成 AI 友好的纯文本。"""
    s = re.sub(r"^---\n.*?\n---\n", "", s, flags=re.S)          # front matter
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)              # 链接留文字
    s = re.sub(r"`{3}[\s\S]*?`{3}", "", s)                       # 代码块
    s = re.sub(r"[`*_]", "", s)                                  # 行内标记
    s = re.sub(r"^>\s?", "", s, flags=re.M)                      # 引用符
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.M)                 # 标题符
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def split_sections(md: str, max_chars=1200):
    """按 ## / ### 标题切段，过长的再按段落切。返回 [(标题, 正文)]。"""
    parts = re.split(r"\n(?=#{2,3}\s)", md)
    out = []
    for p in parts:
        m = re.match(r"#{2,4}\s*(.+)", p)
        title = m.group(1).strip() if m else ""
        body = strip_md(p)
        if not title or len(body) < 60:
            continue
        if len(body) <= max_chars:
            out.append((title, body))
        else:
            # 先按段落切；大表格没有空行，段落切不动，故再按行兜底。
            def chunk_by(units, sep):
                # 判长时必须把分隔符算进去，否则正好卡在 max_chars 时
                # 拼上 sep 会变成 max_chars + len(sep)（实测溢出过 1 字）。
                out, cur = [], ""
                for u in units:
                    if len(cur) + len(sep) + len(u) > max_chars and cur:
                        out.append(cur)
                        cur = u
                    else:
                        cur = f"{cur}{sep}{u}" if cur else u
                if cur:
                    out.append(cur)
                return out

            chunks = []
            for para in chunk_by(body.split("\n\n"), "\n\n"):
                if len(para) <= max_chars:
                    chunks.append(para)
                else:                       # 多半是长表格，按行再切
                    chunks += chunk_by(para.split("\n"), "\n")
            for i, c in enumerate(chunks, 1):
                out.append((f"{title}（{i}/{len(chunks)}）", c))
    return out


# ══ 受控触发词表 ══════════════════════════════════════════════════════
# 关键词不能靠「按字数切中文串」生成——那会切出「规则的内容结」这类断词。
# 世界书的关键词是给正文扫描用的，必须是**读者真的会写出来的完整词**。
# 因此改为受控词表匹配：只有词表里的词命中，才作为触发词。
VOCAB = [
    "第四爱","四爱","GB","女攻男受","女攻","男受","女尊","半女尊","女强",
    "女A男O","ABO","femdom","pegging","精神四爱","总攻","1v1","np","逆后宫",
    "双性","性转","大女主","御姐","女霸总","女帝","妻主",
    "攻受","主导权","支配","服从","调教","训诫","SP","BDSM","主奴","Dom",
    "sub","安全词","aftercare","权力交换","破防","失控","示弱","驯服",
    "圈养","囚禁","掌控欲","占有欲","强制爱","gentle femdom",
    "正君","侧夫","夫郎","夫侍","父后","通房","男德","七出","三从四德",
    "纳夫","娶夫","下嫁","和离","休夫","扶正","男子生子","一妻多夫","平夫制",
    "帝卿","皇太女","母父",
    "信息素","易感期","发情期","标记","腺体","分化","抑制剂","Alpha","Omega",
    "高岭之花","美强惨","白切黑","黑莲花","绿茶","忠犬","狼狗","奶狗","狂犬",
    "病娇","疯批","偏执","清冷","禁欲","人夫","娇夫","糙汉","腹黑","傲娇",
    "万人迷","扮猪吃虎","男妈妈","雄小鬼","brat","顺从的性质","核心矛盾",
    "追妻火葬场","火葬场","破镜重圆","先婚后爱","契约","替身","马甲","掉马",
    "穿书","快穿","重生","双重生","系统","骨科","师生","上下级","年下","年上",
    "生子","救赎","复仇","失忆","暗恋","甜宠","狗血","女扮男装","雄竞",
    "修罗场","白月光","强取豪夺","记忆覆写","掉马模型","惩罚经济学","请罚循环",
    "现代都市","古代","架空","修仙","武侠","星际","末世","西幻","校园",
    "娱乐圈","民国","宫廷","无限流","非人","同人","职场",
    "清水","微H","高H","分级","预警","排雷","洁党","双洁","拉灯","张力",
    "节拍","视角","人称","第二人称","叙事","语感","称谓","反AI味","AI味",
    "写崩","镜头","留白","潜台词","内心独白",
    "晋江","长佩","海棠","废文","po18","LOFTER","AO3","话本","镜文学",
    "锁章","锁文","审核","V章","签约","tag","淫秽物品","牟利","支付处理商",
    "monster romance","why choose","reverse harem","Dead Dove",
    "制度三问","权力落差","世界观","设定","原型","套路","术语",
]
VOCAB_SORTED = sorted(set(VOCAB), key=len, reverse=True)


def keywords_for(title: str, body: str, extra):
    """受控词表匹配 + 标题英文缩写 + 卷级补充词。绝不产生断词。"""
    kws = []
    for w in VOCAB_SORTED:          # ① 标题命中，权重最高
        if w in title:
            kws.append(w)
    for w in VOCAB_SORTED:          # ② 正文出现 >=2 次
        if w in kws:
            continue
        if body.count(w) >= 2:
            kws.append(w)
        if len(kws) >= 10:
            break
    for w in re.findall(r"\b[A-Za-z][A-Za-z0-9/\-]{1,14}\b", title):
        if len(w) >= 2 and w not in kws:
            kws.append(w)
    for k in extra:                 # ④ 兜底，保证每条都有触发口
        if k not in kws:
            kws.append(k)
    seen, final = set(), []
    for k in kws:
        k = k.strip()
        if len(k) < 2 or k.lower() in seen:
            continue
        seen.add(k.lower())
        final.append(k)
    return final[:12]



def collect():
    """遍历全库，产出条目列表。"""
    entries = []
    for vol_dir in sorted(LIB.iterdir()):
        if not vol_dir.is_dir() or vol_dir.name.startswith("_"):
            continue
        cfg = VOLUME_CFG.get(vol_dir.name, ("kw", []))
        if cfg is None:
            continue
        mode, extra = cfg
        for md_file in sorted(vol_dir.rglob("*.md")):
            if md_file.name.startswith("_") or "/_模板/" in str(md_file):
                continue
            text = md_file.read_text(encoding="utf-8")
            doc_title = re.match(r"#\s*(.+)", text)
            doc_title = doc_title.group(1).strip() if doc_title else md_file.stem
            const_all = (mode == "const")
            for sec_title, body in split_sections(text):
                name = f"{doc_title} · {sec_title}"[:80]
                entries.append({
                    "name": name,
                    "content": body,
                    "keys": keywords_for(sec_title + " " + doc_title, body, extra),
                    "constant": const_all or is_const(doc_title, sec_title),
                    "vol": vol_dir.name,
                    "src": str(md_file.relative_to(LIB)),
                })
    return entries


# ══ 产出 1：书房世界书包 ══════════════════════════════════════════════
def build_tavern(entries):
    """酒馆书房 POST /api/oc/desk/import/worlds 的 body。
    该口只认 keys/content/name/constant/enabled/position 六个字段，
    且 ≤900 条/批，超了要分包。"""
    packs, cur = [], []
    for e in entries:
        cur.append({
            "keys": e["keys"],
            "name": e["name"],
            "content": e["content"],
            "constant": bool(e["constant"]),
            "enabled": True,
            "position": "before_char",
        })
        if len(cur) >= 880:
            packs.append(cur)
            cur = []
    if cur:
        packs.append(cur)

    for i, pack in enumerate(packs, 1):
        suffix = f"-{i}" if len(packs) > 1 else ""
        (OUT / f"书房世界书包{suffix}.json").write_text(
            json.dumps({"project": "第四爱百科", "entries": pack},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    return len(packs), sum(len(p) for p in packs)


# ══ 产出 2：SillyTavern 世界书 ════════════════════════════════════════
def build_st(entries):
    """ST 标准世界书格式（entries 为 uid 索引的对象）。"""
    st = {}
    for i, e in enumerate(entries):
        st[str(i)] = {
            "uid": i,
            "key": e["keys"],
            "keysecondary": [],
            "comment": e["name"],
            "content": e["content"],
            "constant": bool(e["constant"]),
            "selective": True,
            "order": 100,
            "position": 0,
            "disable": False,
            "addMemo": True,
            "excludeRecursion": False,
            "probability": 100,
            "useProbability": True,
        }
    (OUT / "SillyTavern世界书.json").write_text(
        json.dumps({"entries": st}, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(st)


# ══ 产出 3：单文件 HTML 百科 ══════════════════════════════════════════
HTML_HEAD = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>第四爱百科</title>
<style>"""

CSS_BLOCK = r"""
:root{--bg:#fbfaf8;--fg:#1f1d1a;--mut:#6f6862;--line:#e5e0d8;--acc:#8a6f45;--card:#fff;--box:#f5f2ec;--hl:#fff3c4}
@media(prefers-color-scheme:dark){:root{--bg:#15140f;--fg:#e9e5dc;--mut:#9c948a;--line:#302c26;--acc:#d0b183;--card:#1c1b17;--box:#211f1a;--hl:#4a3f1c}}
*{box-sizing:border-box}
body{margin:0;font:16px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--fg)}
#wrap{display:flex;min-height:100vh}
#side{width:248px;flex:0 0 248px;border-right:1px solid var(--line);padding:14px 12px;overflow-y:auto;height:100vh;position:sticky;top:0;background:var(--card)}
#brand{font-size:19px;font-weight:700;margin:0 0 2px}
#sub{color:var(--mut);font-size:12px;margin-bottom:12px;line-height:1.55}
#q{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--fg);font-size:13.5px}
#hits{font-size:12px;color:var(--mut);margin:6px 0 4px;min-height:1em}
.vol{font-size:11.5px;color:var(--mut);margin:13px 0 3px;letter-spacing:.06em;font-weight:700;cursor:pointer;user-select:none}
.vol::before{content:"\25be  "}
.vol.fold::before{content:"\25b8  "}
a.doc{display:block;padding:4px 8px;border-radius:5px;color:var(--fg);text-decoration:none;font-size:13px;cursor:pointer;line-height:1.5}
a.doc:hover{background:var(--line)}
a.doc.on{background:var(--acc);color:#fff}
/* 830px 时代宽屏右侧全是死空间（用户实测截图）。放宽到 1120px 并用
   flex 自动外边距吸收剩余空间——余量对半分到两侧，而不是全堆在右边。
   这个库三分之二的内容是表格，宽一档是实打实的可读性收益。 */
#main{flex:1;padding:26px 44px 90px;min-width:0;max-width:1120px;margin:0 auto}
#crumb{font-size:12.5px;color:var(--mut);margin-bottom:10px}
#crumb b{color:var(--fg);font-weight:600}
#toc{width:214px;flex:0 0 214px;padding:26px 12px;height:100vh;position:sticky;top:0;overflow-y:auto;border-left:1px solid var(--line);font-size:12.5px}
#toc .th{font-weight:700;color:var(--mut);font-size:11.5px;letter-spacing:.06em;margin-bottom:7px}
#toc a{display:block;color:var(--mut);text-decoration:none;padding:2.5px 6px;border-radius:4px;border-left:2px solid transparent;line-height:1.45}
#toc a:hover{color:var(--fg);background:var(--line)}
#toc a.l3{padding-left:16px;font-size:12px}
#toc a.act{color:var(--acc);border-left-color:var(--acc);font-weight:600}
.ibox{float:right;width:268px;margin:0 0 14px 18px;background:var(--box);border:1px solid var(--line);border-radius:8px;padding:11px 13px;font-size:12.5px;line-height:1.65}
.ibox .t{font-weight:700;text-align:center;padding-bottom:6px;margin-bottom:7px;border-bottom:1px solid var(--line);font-size:13.5px}
.ibox dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:3px 9px}
.ibox dt{color:var(--mut);white-space:nowrap}
.ibox dd{margin:0}
.ibox code{font-size:.9em}
#main h1{font-size:25px;margin:.2em 0 .5em;border-bottom:2px solid var(--line);padding-bottom:.3em;line-height:1.35}
#main h2{font-size:20px;margin:1.7em 0 .5em;border-bottom:1px solid var(--line);padding-bottom:.25em;line-height:1.4}
#main h3{font-size:16.5px;margin:1.4em 0 .4em}
#main h4{font-size:15px;margin:1.2em 0 .35em;color:var(--acc)}
.anch{color:var(--mut);opacity:0;text-decoration:none;font-weight:400;font-size:.72em;margin-left:.4em}
h1:hover .anch,h2:hover .anch,h3:hover .anch,h4:hover .anch{opacity:.55}
/* display:block 的表格 width:100% 只撑外框不撑行（匿名表格盒按内容定宽）。
   改为 .tw 滚动容器包裹：表格真正铺满栏宽，窄屏时容器内滚动，页面不横滚 */
table{border-collapse:collapse;font-size:13.5px;width:100%}
.tw{overflow-x:auto;margin:.9em 0}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--box);font-weight:600;white-space:nowrap}
tbody tr:nth-child(even){background:rgba(128,128,128,.045)}
blockquote{border-left:3px solid var(--acc);margin:.9em 0;padding:.35em 0 .35em .95em;color:var(--mut)}
code{background:var(--line);padding:.1em .35em;border-radius:3px;font-size:.87em}
pre{background:var(--card);border:1px solid var(--line);padding:11px;border-radius:7px;overflow-x:auto}
pre code{background:none;padding:0}
hr{border:0;border-top:1px solid var(--line);margin:1.8em 0}
mark{background:var(--hl);color:inherit;padding:0 2px;border-radius:2px}
#main a{color:var(--acc)}
#top{position:fixed;right:236px;bottom:22px;width:34px;height:34px;border-radius:50%;background:var(--acc);color:#fff;border:0;cursor:pointer;font-size:15px;display:none;z-index:9}
.sr{padding:7px 9px;border-bottom:1px solid var(--line);cursor:pointer;font-size:12.5px;line-height:1.5}
.sr:hover{background:var(--line)}
.sr b{display:block;color:var(--fg);font-size:13px}
.sr span{color:var(--mut)}
@media(max-width:1180px){#toc{display:none}#top{right:22px}}
@media(max-width:820px){#wrap{flex-direction:column}#side{width:100%;flex:none;height:auto;position:static;border-right:0;border-bottom:1px solid var(--line)}#main{padding:18px;max-width:100%}.ibox{float:none;width:100%;margin:0 0 14px}}
"""

HTML_BODY = """</style></head><body><div id="wrap">
<nav id="side">
  <div id="brand">第四爱百科</div><div id="sub">__SUB__</div>
  <input id="q" placeholder="全文搜索（2 字以上）"><div id="hits"></div>
  <div id="nav"></div>
</nav>
<main id="main"></main>
<aside id="toc"><div class="th">本页目录</div><div id="tocb"></div></aside>
</div>
<button id="top" title="回到顶部">&#8593;</button>
<script>
const DOCS=__DATA__;
const nav=document.getElementById('nav'),main=document.getElementById('main'),
      q=document.getElementById('q'),hits=document.getElementById('hits'),
      tocb=document.getElementById('tocb');
let cur=0,kw='';
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
"""

JS_MD = r"""function mdInner(t){
  // 内层：跳过引用块与代码块处理，其余与 md 相同
  return md('@@NOQ@@'+t);
}
function slug(s){return 's'+s.replace(/<[^>]+>/g,'').replace(/[^\w一-鿿]/g,'').slice(0,32)}
function md(s){
  const noq=s.startsWith('@@NOQ@@');
  if(noq)s=s.slice(7);else s=esc(s);
  const blocks=[];
  s=s.replace(/```([\s\S]*?)```/g,(m,c)=>{blocks.push('<pre><code>'+c.trim()+'</code></pre>');return '@@CB'+(blocks.length-1)+'@@'});
  // 库内自写的版式 HTML（根 README 的居中头与双栏表）要真渲染，不能当源码展示——
  // 曾整页裸露 <div align="center"> 与 <table>，首页在离线百科里坏了很久没被发现。
  // 只还原「整行以标签开头」的行：围栏已抽走成 @@CB@@，正文里的字面示例（反引号内）
  // 不在行首出现标签，不会被误还原。esc 不动引号，属性原样保留。
  const TAGS='div|table|thead|tbody|tr|td|th|br|h[1-6]|b|strong|i|em';
  const lineTag=new RegExp('^&lt;\\/?(?:'+TAGS+')(?:\\s|&gt;|\\/)');
  const unesc=new RegExp('&lt;(\\/?)('+TAGS+')((?:[^&]|&amp;)*?)\\s*\\/?&gt;','gi');
  s=s.split('\n').map(l=>lineTag.test(l.trim())?l.replace(unesc,'<$1$2$3>'):l).join('\n');
  // <br> 单独全局放行：六个卷在 markdown 表格单元格内用它换行（GitHub 惯用法），
  // 这些行以 | 开头，行锚定还原够不着。全库无一处反引号内的字面 <br> 示例，已核。
  s=s.replace(/&lt;br\s*\/?&gt;/gi,'<br>');
  // 行内豁免注释 `<!-- 例外:规则号 理由 -->` 是给检查器看的元数据，不该印给读者。
  // 更要紧的是它会**弄坏表格**：豁免挂在表格行末尾的 | 之后，下面那条正则要求
  // 正文行以 | 收尾，于是整张表的 tbody 空掉，三行数据掉出来变成一段带竖线的文字。
  // 铁律的「病例」表就这么坏了很久，直到有人真去浏览器里翻了一眼才发现。
  s=s.replace(/\s*(?:&lt;|<)!--\s*例外[:：][^]*?--(?:&gt;|>)/g,'');
  // 允许行首缩进：列表项里的表格是常见写法（实测「老男人」卡的两张表缩进 5 空格）
  s=s.replace(/^[ \t]*\|(.+)\|[ \t]*$\n[ \t]*\|[ :\-|]+\|[ \t]*$\n((?:[ \t]*\|.*\|[ \t]*$\n?)*)/gm,(m,h,b)=>{
    const th=h.split('|').map(x=>x.trim()).filter(x=>x!=='').map(x=>'<th>'+x+'</th>').join('');
    const tr=b.trim()?b.trim().split('\n').map(r=>'<tr>'+r.trim().split('|').slice(1,-1).map(x=>'<td>'+x.trim()+'</td>').join('')+'</tr>').join(''):'';
    // 结尾要补换行：表格正则吃掉了最后一行的 \n，若紧跟标题（中间无空行），
    // 标题就不在行首了，^### 匹配不上（实测 02-GB-ABO 的 2.9 节漏成原文）。
    return '<div class="tw"><table><thead><tr>'+th+'</tr></thead><tbody>'+tr+'</tbody></table></div>\n'});
  const H=(n)=>(m,t)=>{const id=slug(t);return '<h'+n+' id="'+id+'">'+t+'<a class="anch" href="#'+id+'">#</a></h'+n+'>'};
  s=s.replace(/^######\s*(.+)$/gm,H(6)).replace(/^#####\s*(.+)$/gm,H(5))
     .replace(/^####\s*(.+)$/gm,H(4)).replace(/^###\s*(.+)$/gm,H(3))
     .replace(/^##\s*(.+)$/gm,H(2)).replace(/^#\s*(.+)$/gm,H(1));
  // 引用块要先摘出来、剥掉前缀后**递归渲染**内部，否则块内的表格与标题会漏成原文。
  // （实测：06-速查表 卷首的安全框架块整段没解析，因为它的表格行是「&gt; |」开头。）
  // 引用块也要允许行首缩进（列表项里的引用块，实测「卑微的霸总夫君」有）
  if(!noq)s=s.replace(/^[ \t]*(&gt;\s?.*(?:\n[ \t]*&gt;\s?.*)*)/gm,m=>{
    const inner=m.replace(/^[ \t]*&gt;\s?/gm,'');
    blocks.push('<blockquote>'+mdInner(inner)+'</blockquote>');
    return '@@CB'+(blocks.length-1)+'@@';
  });
  s=s.replace(/^---+$/gm,'<hr>');
  s=s.replace(/^([-*+])\s+(.+)$/gm,'<li>$2</li>').replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g,'<ul>$1</ul>');
  s=s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>');
  s=s.replace(/\[\[([^\]\n]+)\]\]/g,(m,t)=>{
    const i=DOCS.findIndex(d=>d.t===t||d.t.replace(/^\d+-/,'')===t);
    return i<0?'<i title="待建条目">'+t+'</i>':'<a href="#" data-go="'+i+'">'+t+'</a>'});
  s=s.replace(/\[([^\]\n]+)\]\(([^)\s]*?)([^\/)]+)\.md(#[^)]*)?\)/g,(m,t,d,base)=>{
    const i=DOCS.findIndex(x=>x.t===base);
    return i<0?t:'<a href="#" data-go="'+i+'">'+t+'</a>'});
  s=s.replace(/\[([^\]\n]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  s=s.replace(/\[([^\]]+)\]\([^)]*\)/g,'$1');
  // 段落包裹的免包名单要认还原出来的版式标签（含闭合形态），
  // 否则 <tr><td> 会被裹进 <p>，浏览器的 foster parenting 把表格拆得七零八落
  s=s.split(/\n{2,}/).map(p=>/^<\/?(h\d|ul|ol|table|thead|tbody|tr|td|th|div|blockquote|hr|pre|br)/.test(p.trim())?p:(p.trim()?'<p>'+p.replace(/\n/g,'<br>')+'</p>':'')).join('\n');
  return s.replace(/@@CB(\d+)@@/g,(m,i)=>blocks[+i]);
}
"""

JS_APP = r"""
/* 三行头 -> 信息框。库内约定：标题之后依次是 分级/预警行、亚型标签行、来源行 */
function infobox(title,body){
  const L=body.split('\n').slice(0,16);
  const rows=[],raws=[];let hat='';
  // 库内有三种头格式，都要认：
  //  ① `M` `⚠️主奴` 三行头（多数内容卷）
  //  ② > 分级 G ｜ 预警 无 ｜ 亚型 …（13 卷，头写在引用块里）
  //  ③ | **作者** | … | 的二列表（拆解卡，这张表本身就是信息框）
  const RATE=/`?[GTME]`?\s*[–\-—]\s*`?[GTME]`?|`[GTME]`|(分级|评级)[^\n]{0,4}[GTME](?![A-Za-z])/;
  const LABEL=/^\**(分级|预警|亚型|来源|作者|体量|完成度)\**\s*[：:｜|]?/;

  // ③ 拆解卡：卷首二列表 → 直接当信息框
  const tstart=L.findIndex(l=>/^\|\s*\|?\s*\|/.test(l.trim())||/^\|\s*\*\*/.test(l.trim()));
  if(tstart>=0&&/^\|[\s:\-|]+\|/.test((L[tstart+1]||'').trim())){
    const all=body.split('\n');
    let k=tstart+2,used=[all[tstart],all[tstart+1]];
    while(k<all.length&&all[k].trim().startsWith('|')&&rows.length<7){
      const c=all[k].split('|').map(x=>x.trim()).filter(x=>x!=='');
      if(c.length>=2)rows.push([c[0].replace(/\*\*/g,''),c.slice(1).join(' ')]);
      used.push(all[k]);k++;
    }
    if(rows.length){
      const dl=rows.map(([a,b])=>'<dt>'+esc(a)+'</dt><dd>'+md(b).replace(/<\/?p>/g,'')+'</dd>').join('');
      const kept=all.filter((l,ix)=>ix<tstart||ix>=k).join('\n');
      return['<aside class="ibox"><div class="t">'+esc(title)+'</div><dl>'+dl+'</dl></aside>','',kept];
    }
  }

  for(const raw of L){
    let s=raw.trim();
    const wasQuote=s.startsWith('>');
    if(wasQuote)s=s.replace(/^>\s?/,'').trim();
    if(!s||s.startsWith('# '))continue;
    if(s.startsWith('##')||s.startsWith('|')||s.startsWith('---'))break;
    if(/^提示[：:]/.test(s)){hat=s;raws.push(raw.trim());continue}
    const isHead=RATE.test(s)||LABEL.test(s)||/^`[^`]+`(\s|$)/.test(s);
    if(wasQuote&&!isHead)break;
    if(!wasQuote&&!isHead&&rows.length)break;
    if(/^来源[：:]/.test(s))                     {rows.push(['来源',s.replace(/^来源[：:]\s*/,'')]);raws.push(raw.trim())}
    else if(RATE.test(s)&&!rows.some(r=>r[0]==='分级')) {rows.push(['分级',s]);raws.push(raw.trim())}
    else if(LABEL.test(s)&&!rows.some(r=>r[0]==='说明')) {rows.push(['说明',s]);raws.push(raw.trim())}
    else if(/`[^`]+`/.test(s)&&!rows.some(r=>r[0]==='亚型')) {rows.push(['亚型',s]);raws.push(raw.trim())}
    if(rows.length>=3)break;
  }
  if(!rows.length)return['',hat,body];
  const dl=rows.map(([k,v])=>'<dt>'+k+'</dt><dd>'+md(v).replace(/<\/?p>/g,'')+'</dd>').join('');
  const used=new Set(raws.concat(hat?[hat]:[]));
  const kept=body.split('\n').filter((l,i)=>i>15||!used.has(l.trim())).join('\n');
  return['<aside class="ibox"><div class="t">'+esc(title)+'</div><dl>'+dl+'</dl></aside>',hat,kept];
}
function buildNav(){
  const byVol={};
  DOCS.forEach((d,i)=>{(byVol[d.v]=byVol[d.v]||[]).push([d.t,i])});
  nav.innerHTML=Object.entries(byVol).map(([v,ds])=>
    '<div class="vol" data-v="'+v+'">'+v+'</div><div class="grp" data-g="'+v+'">'+
    ds.map(([t,i])=>'<a class="doc" data-go="'+i+'">'+esc(t)+'</a>').join('')+'</div>').join('');
  nav.querySelectorAll('.vol').forEach(el=>el.onclick=()=>{
    el.classList.toggle('fold');
    const g=nav.querySelector('[data-g="'+el.dataset.v+'"]');
    g.style.display=el.classList.contains('fold')?'none':'';
  });
}
function buildToc(){
  const hs=[...main.querySelectorAll('h2,h3')];
  tocb.innerHTML=hs.length?hs.map(h=>'<a href="#'+h.id+'" class="'+(h.tagName==='H3'?'l3':'')+'" data-id="'+h.id+'">'
    +esc(h.textContent.replace(/#$/,''))+'</a>').join(''):'<span style="color:var(--mut)">（无小节）</span>';
  tocb.querySelectorAll('a').forEach(a=>a.onclick=e=>{
    e.preventDefault();document.getElementById(a.dataset.id)?.scrollIntoView({behavior:'smooth',block:'start'});
  });
}
function show(i){
  cur=i;const d=DOCS[i];
  const r=infobox(d.t,d.c),box=r[0],hat=r[1],bodyMd=r[2]!==undefined?r[2]:d.c;
  let html=md(bodyMd);
  if(kw){const re=new RegExp('('+kw.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','gi');
    html=html.replace(/>([^<]+)</g,(m,t)=>'>'+t.replace(re,'<mark>$1</mark>')+'<')}
  main.innerHTML='<div id="crumb">'+esc(d.v)+' › <b>'+esc(d.t)+'</b></div>'
    +(hat?'<div class="ibox" style="float:none;width:auto;margin:0 0 14px">'+esc(hat)+'</div>':'')
    +box+html;
  window.scrollTo(0,0);
  nav.querySelectorAll('a.doc').forEach(a=>a.classList.toggle('on',+a.dataset.go===i));
  buildToc();
}
document.addEventListener('click',e=>{
  const g=e.target.closest('[data-go]');
  if(g){e.preventDefault();show(+g.dataset.go)}
});
q.addEventListener('input',()=>{
  kw=q.value.trim();
  if(kw.length<2){hits.textContent='';buildNav();show(cur);return}
  const k=kw.toLowerCase(),res=[];
  DOCS.forEach((d,i)=>{
    const lc=d.c.toLowerCase(),p=lc.indexOf(k);
    if(p>=0)res.push([i,d.c.slice(Math.max(0,p-24),p+54).replace(/\n/g,' '),lc.split(k).length-1]);
  });
  res.sort((a,b)=>b[2]-a[2]);
  hits.textContent=res.length?('命中 '+res.length+' 篇'):'无结果';
  nav.innerHTML=res.map(r=>'<div class="sr" data-go="'+r[0]+'"><b>'+esc(DOCS[r[0]].t)+' ('+r[2]+')</b><span>…'+esc(r[1])+'…</span></div>').join('');
});
const topBtn=document.getElementById('top');
topBtn.onclick=()=>window.scrollTo({top:0,behavior:'smooth'});
window.addEventListener('scroll',()=>{
  topBtn.style.display=scrollY>420?'block':'none';
  let act=null;
  main.querySelectorAll('h2,h3').forEach(h=>{if(h.getBoundingClientRect().top<120)act=h.id});
  tocb.querySelectorAll('a').forEach(a=>a.classList.toggle('act',a.dataset.id===act));
});
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT')return;
  if(e.key==='/'){e.preventDefault();q.focus()}
  if(e.key==='j'&&cur<DOCS.length-1)show(cur+1);
  if(e.key==='k'&&cur>0)show(cur-1);
});
buildNav();show(0);
"""

HTML_FOOT = """</script></body></html>"""

# 这张表与 VOLUME_CFG 是两套口径，必须分别维护——
# VOLUME_CFG 只管世界书，把某卷设成 None 不会把它挡在 HTML 之外。
# 09 卷（逐部作品的精读笔记）下架时先只改了 VOLUME_CFG，index.html 照旧内嵌了那 10 篇全文，
# 而 index.html 是进仓库的产物：等于绕过 .gitignore 把不该发的东西发了出去。
# 新增「整卷不入库」的目录时，两处都要加。
HTML_EXCLUDE = {"10-藏书索引", "09-拆解卡"}


def build_html():
    """单文件 HTML 百科，wiki 版式。

    与上一版的差别：上一版是「侧栏文档列表 + 正文」两栏，长条目里定位困难，
    也没有信息框与本页目录。与萌娘百科条目逐项对照后补齐五件：
    三栏布局（卷目 / 正文 / 本页目录）、信息框、标题锚点、面包屑、搜索结果片段。
    """
    docs = []
    for vol_dir in sorted(LIB.iterdir()):
        if not vol_dir.is_dir() or vol_dir.name.startswith("_"):
            continue
        # 10-藏书索引 是本地私人收藏的逐条清单（书名 + 作者 + 尺度），
        # 公开它等同于发布一份藏书目录。见 00-编纂规约/06-发布风险评估。
        if vol_dir.name in HTML_EXCLUDE:
            continue
        for md_file in sorted(vol_dir.rglob("*.md")):
            if "/_模板/" in str(md_file):
                continue
            docs.append((vol_dir.name, md_file.stem,
                         md_file.read_text(encoding="utf-8")))
    for f in sorted(LIB.glob("*.md")):
        # CLAUDE.md 是给接手会话/agent 的维护手册，不是给读者的百科内容。
        # 它讲的是「怎么动这个仓库」（命令代价、检查器豁免、提交纪律），
        # 混进离线百科只会让读者困惑，也会把篇数算歪。
        # 仓库元文件不进离线百科：它们讲的是「怎么参与这个仓库」，
        # 不是给读者的百科内容，混进去只会让读者困惑，也会把篇数算歪。
        if f.name in ("CLAUDE.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md"):
            continue
        docs.insert(0, ("总览", f.stem, f.read_text(encoding="utf-8")))

    payload = json.dumps([{"v": v, "t": t, "c": c} for v, t, c in docs],
                         ensure_ascii=False)
    total = sum(len(c) for _, _, c in docs)

    tpl = (HTML_HEAD + CSS_BLOCK + HTML_BODY + JS_MD + JS_APP + HTML_FOOT)
    html = (tpl.replace("__DATA__", payload)
               .replace("__SUB__", f"{len(docs)} 篇 · {total/10000:.0f} 万字符<br>"
                                   f"/ 搜索　j k 翻页"))
    # 落在仓库根目录并命名 index.html：下载解压后双击即用，不用先翻到 12-导出。
    # 只保留这一份，避免两处副本各自漂移。
    # 首行留一个机读标记：篇数在 README / INDEX / 12 卷 / 06-发布风险评估 四处手写过，
    # 每次加卷都会漏改。有了标记，sync_index 就能自己核，不用人盯。
    html = f"<!--gb-html-docs:{len(docs)}-->\n" + html
    (LIB / "index.html").write_text(html, encoding="utf-8")
    old = OUT / "第四爱百科.html"
    if old.exists():
        old.unlink()
    return len(docs), total

if __name__ == "__main__":
    ents = collect()
    npack, ncnt = build_tavern(ents)
    nst = build_st(ents)
    ndoc, nchar = build_html()
    from collections import Counter
    print(f"世界书条目 {len(ents)} 条（常驻 {sum(1 for e in ents if e['constant'])} 条）")
    print(f"  各卷分布：{Counter(e['vol'] for e in ents).most_common()}")
    print(f"→ 书房导入包 {npack} 个文件，共 {ncnt} 条")
    print(f"→ SillyTavern 世界书 {nst} 条")
    print(f"→ HTML 百科 {ndoc} 篇 / {nchar:,} 字")
