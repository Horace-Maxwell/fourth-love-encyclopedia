# 12-导出

> 主库是 Markdown，这一目录是给机器吃的三种形态。
> 全部由 [`_脚本/build_exports.py`](../_脚本/build_exports.py) 生成，可复跑——
> 主库改了就重跑一次，不要手改这里的文件。

当期产物（2026-08 重建）

| 文件 | 内容 | 大小 |
|---|---|---:|
| `书房世界书包-1.json` | 880 条（常驻 0） | 1.5 MB |
| `书房世界书包-2.json` | 824 条（常驻 9） | 1243 KB |
| `SillyTavern世界书.json` | 1,704 条（常驻 9） | 3.0 MB |
| `index.html`（**在仓库根目录**） | 126 篇全文，双击即开 | 4.4 MB |

拆成两个包是因为书房单次导入上限 900 条，不是内容上的分卷。两个都要导。

---

## 一、酒馆书房（tavern-study）

### 关键：鉴权走**路径前缀**，不是 Bearer

这是最容易卡住的一步。书房的 `/api/oc/*` 全部挂在 `AUTH_TOKEN` 后面：

```
http://localhost:8787/<AUTH_TOKEN>/api/oc/desk/import/worlds
```

`AUTH_TOKEN` 在 `tavern-study/.dev.vars` 里。用 `Authorization: Bearer` 走这个命名空间会一路 404。路由是在的。404 在这里的意思是前缀没带对。

### 请求体必须带 `project`

导出的 JSON 里已经写好了 `project` 字段（值为 `第四爱百科`）。手动拼请求体时，漏了它会返回：

```
{"success":false,"error":"缺 project 字段(前端应该把当前打字桌project拼进请求体)"}
```

### 导入命令

```bash
cd ../tavern-study && A=$(grep '^AUTH_TOKEN' .dev.vars | cut -d= -f2- | tr -d ' "') && for f in 1 2; do curl -s -X POST "http://localhost:8787/$A/api/oc/desk/import/worlds" -H "Content-Type: application/json" --data @"../第四爱百科/12-导出/书房世界书包-$f.json"; echo; done
```

两次都应返回 `{"success":true,"project":"第四爱百科","count":N}`。

### 核验导入结果

```bash
cd ../tavern-study && A=$(grep '^AUTH_TOKEN' .dev.vars | cut -d= -f2- | tr -d ' "') && curl -s "http://localhost:8787/$A/api/oc/memories?project=%E7%AC%AC%E5%9B%9B%E7%88%B1%E7%99%BE%E7%A7%91&limit=5"
```

应看到条目的 `category` 为 `world`。只有 `world` 与 `outline` 参与装配。别的分类导进去也不会进上下文。

### 常驻条目为什么只有 9 条

世界书是注入进上下文的，常驻 N 条等于每次生成先付 N 条的 token。

实测教训：把整个 07 卷设为常驻会产生 161 条常驻、约 13 万字，直接把正文位置挤没。现改为白名单。只有真正需要「每一楼都遵守」的那几节常驻（反 AI 味速查、分级红线、版权红线），固定开销约 5,175 字。其余全部靠关键词触发。

### 关于 `constant` 与 `trigger_mode`

两者不是一回事，容易搞混：

| | 适用 | 何时生效 |
|---|---|---|
| `constant: true` | 世界书条目（`is_char=0`） | 导入时直接生效，无需后续操作 |
| `trigger_mode: 'presence'` | 角色卡条目（`is_char=1`） | 导入后需再 `PUT /api/oc/desk/lore/{id}` 设置 |

导出包里的 9 条常驻走的是前者，已实测在导入后即为常驻。不用补刀。

### 已知限制：向量检索不可用

本机 `wrangler.toml` 移除了 `[[vectorize]]` 与 `[ai]`（它们是云端专属绑定）。因此：

- ✅ 导入、装配、关键词触发全部正常
- ❌ `/api/oc/search` 与 `backfill-vectors` 会报 `Cannot read properties of undefined (reading 'run')`

这不影响世界书的实际使用。世界书本来就靠关键词触发，不靠向量。要恢复向量检索，需在 Cloudflare 云端部署并接回那两个绑定。

---

## 二、SillyTavern

`SillyTavern世界书.json` 是标准 ST 世界书格式（`entries` 为对象字典，含 `uid`/`key`/`keysecondary`/`order`/`probability` 等全字段）。

导入路径：World Info → Import → 选择该文件。

1,704 条会让条目列表很长，建议导入后在 ST 里按需禁用整组。文件里每条的 `comment` 字段带着「卷名 · 篇名 · 节名」三级来源，按前缀筛选即可。

---

## 三、HTML 单文件百科

`index.html` 在**仓库根目录**，4.4 MB，126 篇全文内嵌，双击即开，无需服务器、无外部依赖、断网可用。

- 全文检索（含正文，不只标题）
- 跟随系统深浅色
- 内置极简 Markdown 渲染，表格与代码块正常显示

> **分发约定**：本文件含全部主库内容。按 [00-编纂规约/版权与内容红线](../00-编纂规约/03-版权与内容红线.md) 第四节，
> 它是本地文件，是否传播由你决定。藏书原文从未进入任何导出产物。

---

## 重新生成

```bash
python3 _脚本/build_exports.py
```

改了主库就重跑。脚本会按 `VOLUME_CFG` 决定哪些卷进导出——
`00-编纂规约`、`10-藏书索引`、`11-模板包`、`12-导出` 四个目录不导出
（分别是编库规则、数据表、成品、导出物本身，注入进上下文只会稀释信号）。
