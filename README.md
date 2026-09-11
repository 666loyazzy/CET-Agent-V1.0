# CET Agent

面向大学英语四、六级备考的 AI 学习平台。一套本地单机服务同时提供 **AI 对话辅导**、**词汇打字训练**、**默写自评**、**学习进度分析**，并附带一层可扩展的**向量检索**，用于错词联想、相关词推荐，未来可承载听力/阅读错题的语义检索。

> 当前状态：**V1 对话 → V2 数据层 → V3 艾宾浩斯排期 → V4 Agent 词汇打通 → V5 向量检索** 已全部交付。词表 8500+ 词全量向量化（cet4 4543 + cet6 3991）。

## 功能一览

| 模块 | 入口 | 状态 | 说明 |
|---|---|---|---|
| AI 备考对话 | `/vocab/#/` | ✅ | 写作 / 翻译 / 阅读 / 听力 / 词汇 五种模式；SSE 流式；system prompt 由 `SKILL.md` 动态切片 |
| 词汇打字训练 | `/vocab/#/typing` | ✅ | Vue 3 SPA，四/六级词表，40 词一 List，逐词发音 + 打字反馈 |
| 默写自评 | `/vocab/#/dictation` | ✅ | 四种题型（英→中 / 中→英带提示 / 中→英 / 混合），三级判分短路 |
| 学习进度 | `/vocab/#/progress` | ✅ | KPI + 今日队列 + 记忆热力图 + 薄弱 List + 一键"问 agent" |
| 数据层持久化 | SQLite | ✅ | `users` / `books` / `words` / `reviews` / `book_lists`；SQLAlchemy 2.0 async + aiosqlite |
| 艾宾浩斯排期 | 后端 | ✅ | List 级排期，STAGES=[0,1,2,4,7,15,30] 天，忘记回 stage=1 而非 0 |
| Agent 打通词汇 | vocab 模式 | ✅ | 运行时把用户上下文（今日到期、错词 Top、弱 List、掌握度）拼进 system prompt |
| 向量检索 | 后端 | ✅ | `sqlite-vec` + DashScope embedding，判别表设计，可扩展到听力/阅读 |
| 已掌握标记 | HomeView / DictationView | ✅ | `Review.flag` 4 档，flag=2 屏蔽出练习队列并计入掌握度 |

## 快速开始

需要 Python 3.11+、Node 18+，推荐用 [`uv`](https://github.com/astral-sh/uv) 管理 Python 依赖。

```bash
# 1. 后端依赖
uv sync

# 2. 前端产物（首次或改前端源码时）
cd vocab-frontend
npm install
npm run build          # → ../frontend/vocab/
cd ..

# 3. 配置
cp .env.example .env
# 编辑 .env，填 API key（主聊天 / 判分 / embedding 三条链路独立）

# 4. 启动（首次启动自动 seed 词库到 data/cet-agent.db）
uv run python -m backend.main

# 5. （可选）向量检索层灌数据 —— 一次性活，跑完就有相似词能查
uv run python -m backend.vocab.embedding_backfill --book cet4
uv run python -m backend.vocab.embedding_backfill --book cet6
```

浏览器打开：

- `http://127.0.0.1:8000/` → 302 到 `/vocab/#/`（对话）
- 四个 tab 都在 `/vocab/#/*`，hash 切换瞬间响应
- `/healthz` → 快速自检：provider、SKILL.md 加载、DB 路径、向量维度

## 目录结构

```
cet-agent/
├── backend/
│   ├── agent/
│   │   ├── prompts.py           # 按 ## 标题切 SKILL.md 拼 system prompt
│   │   ├── router.py            # 用户输入 → 模式判断（含 vocab 模式关键词）
│   │   ├── validators.py        # 输出格式校验
│   │   └── llm_client.py        # anthropic / openai 兼容抽象
│   ├── api/
│   │   ├── chat.py              # /api/chat：SSE，vocab 模式注入 runtime-context
│   │   ├── vocab.py             # /api/vocab/judge：默写判分（独立 provider 路由）
│   │   ├── vocab_data.py        # /api/vocab/{books,lists,list,word,review,today,stats} 等
│   │   └── embeddings.py        # /api/vocab/similar + /api/embeddings/{search,backfill}
│   ├── db/
│   │   ├── models.py            # Book / Word / Review / BookList / EmbeddingItem
│   │   ├── session.py           # async engine + sqlite-vec 扩展加载钩子
│   │   └── seed.py              # 首次启动灌词表（幂等）
│   ├── vocab/
│   │   ├── service.py           # 复习提交、进度统计、agent 上下文构造
│   │   ├── ebbinghaus.py        # List 级排期算法
│   │   ├── embedding.py         # 向量客户端 + upsert + kNN 搜索
│   │   └── embedding_backfill.py# 词表向量化 CLI（幂等，按模型跳过已灌）
│   ├── config.py                # 三条 provider 链路：chat / judge / embedding
│   └── main.py                  # FastAPI 入口，lifespan 里 create_all + 建 vec 虚拟表
├── frontend/
│   ├── static/
│   │   ├── nav.css              # 全站主题令牌（浅色默认 + data-theme=dark 覆盖）
│   │   ├── click-effect.css     # 点击特效样式
│   │   ├── cet4-effect.iife.js  # 点击特效脚本（挂 window.CET4Effect）
│   │   ├── words-cet4.txt       # 四级词表（前后端单一来源）
│   │   └── words-cet6.txt       # 六级词表
│   └── vocab/                   # Vite 构建产物（.gitignore）
├── vocab-frontend/              # 统一 SPA 源码（Vue 3 + Vite + Element Plus）
│   └── src/
│       ├── views/
│       │   ├── ChatView.vue         # 对话（SSE + marked 渲染 + click-effect）
│       │   ├── HomeView.vue         # 词汇打字
│       │   ├── DictationView.vue    # 默写自评
│       │   └── ProgressView.vue     # 学习进度
│       ├── api/                     # 前端 API 客户端
│       ├── stores/
│       ├── composables/
│       └── router/                  # hash router，base=/vocab/
├── skill/                       # 知识资产：题型规则、模板、示例
│   ├── SKILL.md                 # 行为规约（含 Vocab Mode 章节）
│   ├── templates/
│   └── examples/
├── data/                        # SQLite（.gitignore）
├── tests/
├── pyproject.toml
├── .env.example
└── uv.lock
```

## 配置

`.env` 三组独立链路——**主聊天**、**默写判分**、**向量 embedding**，互不影响。

```env
# ---- 主聊天 ----
LLM_PROVIDER=openai                 # anthropic / openai / deepseek
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# ---- 默写判分（可选，留空则复用主聊天）----
JUDGE_PROVIDER=openai
JUDGE_OPENAI_API_KEY=sk-xxx
JUDGE_OPENAI_BASE_URL=https://api.deepseek.com
JUDGE_MODEL=deepseek-v4-flash

# ---- 向量 embedding ----
EMBEDDING_PROVIDER=openai
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIM=1024
```

**为什么三条独立？**

- 主聊天是流式，用户看着 token 逐字冒出来，慢一点感知不到——保留最强模型。
- 判分等一整段 JSON 才出结论，慢就是慢——路由到最快的模型（如 DeepSeek Flash）。
- Embedding 是批处理，用便宜且中英跨语言效果好的即可（DashScope `text-embedding-v3` 1024 维）。

切链路只改环境变量，代码不动。

## 设计要点

1. **`SKILL.md` 是可编辑的知识资产。** `prompts.py` 按 `##` 顶级标题切片，"总规则 + 当前模式"运行时拼装。改题型规则、评分标准只改 markdown，不动 Python。

2. **默写判分三级短路。** 大多数题目不走 AI：
   - 完全匹配（`_norm(ans) == _norm(reference)`）→ 约 100ms
   - 词库候选匹配（英→中，拆多词性首义命中，如 mood → "n. 心情，情绪" 命中 "情绪"）→ 约 80ms
   - AI 判分 fallback（`reasoning_effort=low` + `max_tokens=200` + `temperature=0`）→ 约 1.3s 热调用
   
   AI 调用率压到 20% 以下，同时兜住 good/great/wonderful 一类语义等价场景。

3. **List 级艾宾浩斯排期。** `STAGES=[0,1,2,4,7,15,30]` 天，stage 0 保留给"从未复习"；任何一次完成后 stage ≥ 1，防止"忘记回 0 → 今天再来"死循环；忘记回 stage=1 不是 0。学习日切换点上偏移 4 小时（凌晨 3 点算前一天），友好熬夜党。

4. **Agent 打通词汇数据。** vocab 模式识别关键词后（`背单词 / 生词 / 记不住 / 该背什么 / list N / ...`），运行时调 `service.get_user_context()` 抓 `{level, mastery, today_due_lists, weak_lists, recent_error_words}`，序列化后追加到 system prompt 的 `<runtime-context>` 段。SKILL.md 是静态知识、DB 是动态状态，两者解耦——不走 tool-call 避免多轮往返，数据量 <10KB 塞 prompt 完全够用。

5. **向量检索——多实体判别表设计。** `embedding_items` 表用 `(entity_type, entity_ref)` 唯一键做判别，词汇是第一个 `entity_type='word'`；`vec_embedding_items`（`sqlite-vec` vec0 虚拟表，`FLOAT[1024]`）承载 kNN，与主表 id 一一对应。写入时 L2 归一化，让 vec0 默认 L2 距离等价于 cosine，省一次 `vec_distance_cosine()` 调用。**未来接听力/阅读错题**只需新 `entity_type='listening_error' / 'reading_error'`，`meta_json` 存 type-specific 字段（question_type、error_reason 等），搜索 API 用 `entity_types` 过滤，同一向量空间不用改任何 schema。

6. **单一词库来源。** `frontend/static/words-cet{4,6}.txt` 同时供前端加载与后端判分候选拆解、seed 灌库使用。上游文件（KyleBing/english-vocabulary）按主题重复列词，`seed.py::parse_wordlist` 按 `en.lower()` 去重、保留首次出现。**这决定了 List 编号**：cet4 → 114 lists、cet6 → 100 lists。

7. **主题系统。** `<html data-theme="light|dark">` + `localStorage`，全站设计令牌统一在 `frontend/static/nav.css`。Vue SPA 的 `<head>` 有个预设脚本在 render 前应用 data-theme，避免 light→dark 首屏闪烁。改主题只动 CSS 变量，不动组件。

## 向量检索使用

一次性把词表灌进向量库：

```bash
uv run python -m backend.vocab.embedding_backfill --book cet4
uv run python -m backend.vocab.embedding_backfill --book cet6
```

幂等：按 `(entity_type='word', model=当前模型)` 跳过已灌数据，中断后重跑自动续。

### 查询相似词

```bash
# 便捷接口——词汇专用，命中缓存时零 API 调用
curl 'http://127.0.0.1:8000/api/vocab/similar?en=abandon&book=cet4&limit=8'
```

```bash
# 通用 kNN——给未来听力/阅读用的入口
curl -X POST http://127.0.0.1:8000/api/embeddings/search \
  -H 'Content-Type: application/json' \
  -d '{"query_text":"经济危机","entity_types":["word"],"book_code":"cet4","limit":6}'
# → crisis / recession / economic / economy / famine / emergency
```

### 换模型 / 重灌

`EMBEDDING_MODEL` 或 `EMBEDDING_DIM` 改动后：

1. `sqlite3 data/cet-agent.db "DROP TABLE vec_embedding_items;"`
2. 重启服务（lifespan 会用新 dim 重建虚拟表）
3. `uv run python -m backend.vocab.embedding_backfill --book cet4 --force` 强制重灌

不自动 drop，避免静默数据丢失。

## 路线图（下一步方向）

- **听力错题向量集成**：新增 `entity_type='listening_error'`，`meta_json` 存 question_type / user_id / audio_transcript 摘要；agent 能拉"最近听力错题聚类"做重点回顾。
- **阅读错题向量集成**：同上思路，`entity_type='reading_error'`；配合 passage_type 分类，可以做"你在长难句题上错得多"这种结构化诊断。
- **错词聚类**：拉用户 `recent_error_words` 的向量做 kNN 聚类，识别语义组（情感形容词 / 学术动词 / 具体名词），agent 输出诊断。
- **前端相似词面板**：HomeView / DictationView 侧栏调 `/api/vocab/similar`，实时展示当前词的近义扩展。
- **重难词单独刷**：`Review.flag=-1` 通道走词级排期（`Word.next_due_at`），跟 List 级排期并行。

## 测试

```bash
uv run pytest
```

覆盖 prompt 切片、模式路由、判分链路短路逻辑、复习提交、排期算法。

## 许可

MIT。
