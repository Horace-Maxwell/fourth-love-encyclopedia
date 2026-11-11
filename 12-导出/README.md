# 12-导出

> 主库用 Markdown 写，这个目录放三种导出格式。
> 全部由 [`_脚本/build_exports.py`](../_脚本/build_exports.py) 生成，能重跑。
> 主库一改就重跑一次，这里的文件别手改。

当期产物（2026-08 重建）

| 文件 | 内容 | 大小 |
|---|---|---:|
| `书房世界书包-1.json` | 880 条（常驻 0） | 1.5 MB |
| `书房世界书包-2.json` | 824 条（常驻 9） | 1243 KB |
| `SillyTavern世界书.json` | 1,704 条（常驻 9） | 3.0 MB |
| `index.html`（**在仓库根目录**） | 135 篇全文，双击即开 | 4.4 MB |

书房单次最多导入 900 条，所以拆成了两个包，内容上并没有分卷。两个都要导。

---

## 一、酒馆书房（tavern-study）

### 关键：鉴权走**路径前缀**，不是 Bearer

这一步最容易卡住。书房的 `/api/oc/*` 全都挂在 `AUTH_TOKEN` 后面：

```
http://localhost:8787/<AUTH_TOKEN>/api/oc/desk/import/worlds
```

`AUTH_TOKEN` 在 `tavern-study/.dev.vars` 里。拿 `Authorization: Bearer` 去请求这个命名空间，会一路 404。路由其实是在的，404 说明前缀没带对。

### 请求体必须带 `project`

导出的 JSON 里已经写好了 `project` 字段（值是 `第四爱百科`）。自己手拼请求体时漏了它，会返回：

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

应该看到条目的 `category` 是 `world`。只有 `world` 和 `outline` 会参与装配，别的分类导进去也进不了上下文。

### 常驻条目为什么只有 9 条

世界书是注入到上下文里的。常驻 N 条，就是每次生成前先花掉 N 条的 token。

实测吃过亏：把整个 07 卷设成常驻，会出来 161 条常驻、约 13 万字，正文直接没地方放了。现在改成白名单，只有真要「每一楼都遵守」的那几节常驻（反 AI 味速查、分级红线、版权红线），固定开销约 5,175 字。其余全部靠关键词触发。

### 关于 `constant` 与 `trigger_mode`

两者不是一回事，容易搞混：

| | 适用 | 何时生效 |
|---|---|---|
| `constant: true` | 世界书条目（`is_char=0`） | 导入时直接生效，无需后续操作 |
| `trigger_mode: 'presence'` | 角色卡条目（`is_char=1`） | 导入后需再 `PUT /api/oc/desk/lore/{id}` 设置 |

导出包里那 9 条常驻用的是前一种，实测导入后就是常驻，不用再补操作。

### 已知限制：向量检索不可用

本机 `wrangler.toml` 去掉了 `[[vectorize]]` 和 `[ai]`，这两个是云端才有的绑定。所以：

- ✅ 导入、装配、关键词触发全部正常
- ❌ `/api/oc/search` 与 `backfill-vectors` 会报 `Cannot read properties of undefined (reading 'run')`

世界书照常能用，它本来就靠关键词触发，用不到向量。想恢复向量检索，得部署到 Cloudflare 云端，把那两个绑定接回去。

---

## 二、SillyTavern

`SillyTavern世界书.json` 是标准的 ST 世界书格式（`entries` 是对象字典，`uid`/`key`/`keysecondary`/`order`/`probability` 等字段一应俱全）。

导入路径：World Info → Import → 选择该文件。

1,704 条会让条目列表拉得很长，建议导入后在 ST 里按需整组禁用。文件里每条的 `comment` 字段都带着「卷名 · 篇名 · 节名」三级来源，按前缀筛就行。

---

## 三、HTML 单文件百科

`index.html` 在**仓库根目录**，4.4 MB，内嵌 135 篇全文，双击就能打开，不用服务器，没有外部依赖，断网也能看。

- 全文检索，含正文，不只标题
- 跟随系统深浅色
- 内置极简的 Markdown 渲染，表格和代码块都能正常显示

> **分发约定**：这个文件包含主库的全部内容。按 [00-编纂规约/版权与内容红线](../00-编纂规约/03-版权与内容红线.md) 第四节，
> 它是本地文件，传不传播由你决定。藏书原文从来没进过任何导出产物。

---

## 重新生成

```bash
python3 _脚本/build_exports.py
```

改了主库就重跑。脚本按 `VOLUME_CFG` 决定哪些卷进导出。`00-编纂规约`、`10-藏书索引`、`11-模板包`、`12-导出` 这四个目录不导出，它们分别是编库规则、数据表、成品和导出物本身，放进上下文只会占地方。
