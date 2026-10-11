# AI 新闻资讯平台

一个前后端完整的新闻资讯系统：FastAPI 异步后端提供新闻、用户、收藏、历史等业务能力，
并内置一套带工程约束的 AI 摘要服务；Vue 3 移动端 H5 提供完整的用户界面。

**核心能力**

- **AI 摘要**：SSE 流式输出、内容指纹缓存、失败自动降级、批量异步任务、可观测指标
- **新闻业务**：分类、分页列表、详情、相关推荐、浏览量统计，Redis 多级缓存
- **用户体系**：注册、登录、个人资料、修改密码，bcrypt 加密 + Token 鉴权
- **用户内容**：文章收藏、浏览历史
- **移动端**：首页 / 分类 / 详情 / 收藏 / 历史 / 个人中心 / AI 问答等 11 个页面，中英文切换、暗色主题

**技术栈**

| 层 | 技术 |
|---|---|
| 后端 | Python 3.13 · FastAPI · SQLAlchemy 2.0（异步 ORM）· Pydantic v2 · httpx |
| 存储 | MySQL 8（aiomysql）· Redis |
| 鉴权 | bcrypt · UUID Token |
| 前端 | Vue 3 · Vite · Pinia · Vue Router · Vant 4 · vue-i18n · axios |

---

## 一、项目结构

```text
AI-news/
├── main.py                     # 后端入口：注册路由与全局异常处理
├── requirements.txt            # 后端依赖清单
├── .env.example                # 后端配置模板：复制成 .env 后填 Key
├── config/
│   ├── db_conf.py              # 异步引擎 + 会话工厂 + get_db 依赖
│   ├── cache_conf.py           # Redis 客户端与读写封装（异常自动降级）
│   └── llm_conf.py             # 大模型 / 缓存 / 批量任务配置
├── models/                     # SQLAlchemy 模型（news / users / favorite / history）
├── schemas/                    # Pydantic 模型（含 ai.py）
├── crud/                       # 数据库操作（news / users / favorite / history）
├── cache/                      # 缓存封装（news_cache / summary_cache）
├── services/                   # 业务服务层：与外部依赖交互的逻辑
│   ├── llm_service.py          # 大模型客户端：SSE 流式解析、超时、有限重试、错误分类
│   ├── summary_service.py      # 摘要编排：缓存优先 → 生成 → 降级；批量并发
│   ├── task_registry.py        # 批量任务注册表（task_id + 状态）
│   └── metrics.py              # 指标采集
├── routers/                    # 路由层（news / user / favorite / history / ai）
├── utils/                      # 响应封装、鉴权、全局异常处理
├── verify_ai_summary.py        # 端到端验证 + 性能实测脚本
├── verify_ai_degraded.py       # 降级路径验证脚本（无 Key / 无效 Key）
└── xwzx-news/                  # 前端（Vue 3 + Vite）
    ├── .env.example            # 前端环境变量模板
    ├── index.html
    ├── vite.config.js
    └── src/
        ├── config/api.js       # API 地址与 AI Key（从环境变量读取）
        ├── router/             # 路由表（11 个页面）
        ├── store/              # Pinia：user / news / favorite / history / theme / language
        ├── i18n/               # 中英文语言包
        ├── components/         # NewsItem / TabBar
        └── views/              # Home / Category / NewsDetail / Favorite / History
                                # My / Profile / Settings / Login / Register / AIChat
```

**分层约定**：`routers` 只做参数校验与响应组装 → `services` 处理外部依赖与大模型 → `crud` 只管数据库 →
`cache` 只管缓存。`routers` 和 `crud` 中不出现 `httpx`。

---

## 二、AI 摘要的工程设计

直接调用一次大模型接口很容易，但要把它做成可上线的功能，需要处理延迟、成本、故障和可观测性四类问题。
本项目的处理方式：

| 问题 | 解决方案 | 代码位置 |
|---|---|---|
| 单次调用需 3–4 秒，界面长时间空白 | **SSE 流式输出**，前端边生成边显示 | `routers/ai.py: stream_news_summary`、`services/summary_service.py: stream_summary` |
| 同一条新闻被反复请求，重复消耗 token | **按正文内容 hash 缓存**摘要，命中后毫秒级返回；正文变更时 key 自动失效 | `cache/summary_cache.py` |
| 大模型不可用或未配置 Key 时拖垮新闻接口 | **降级**：返回原文摘录并标记 `degraded=true`，接口始终返回 200；区分"未配置 Key"与"调用失败"两种原因 | `services/summary_service.py: fallback_summary` |
| 批量生成摘要导致请求长时间挂起 | **后台任务**：立即返回 `task_id`，前端轮询进度；并发通过 `Semaphore` 限流（默认 3） | `routers/ai.py: batch_summary`、`services/task_registry.py` |
| 功能上线后缺少运行数据 | **可观测指标**：缓存命中率、token 用量、调用延迟 P50/P95、首字延迟 | `services/metrics.py`、`GET /api/ai/metrics` |

**关键设计说明**

1. **摘要缓存以「正文 hash」为 key，而非仅用 `news_id`**
   `news_id` 无法标识内容版本。新闻被编辑后，按 id 缓存会返回过期摘要；将内容 hash 纳入 key 后，
   正文一变 key 自然失效，无需主动清理逻辑。另配 `news:summary:index:{id}` 索引 key，
   用于正文更新后删除旧 key，避免 Redis 中堆积无效数据。

2. **连接超时与读取超时分开设置**
   `connect=5s` 保证上游不可达时快速失败；整体 `30s` 为大模型生成留出时间。
   若混用同一个值，要么误杀正常的长生成，要么让连接失败长时间占用 worker。

3. **仅对 5xx 与网络错误重试，4xx 不重试**
   401/403/400 重试只会重复消耗额度且必然再次失败。

4. **降级结果同样写入缓存（短 TTL）**
   大模型不可用期间，若每次请求都重新执行"查库 → 截断 → 拼接兜底文案"，前端列表滚动即可打满后端。
   缓存 600s 既能挡住流量，又能在大模型恢复后尽快取到真实摘要。

5. **并发受控，不使用无上限的 `asyncio.gather`**
   大模型服务通常有并发/QPS 限制。使用 `Semaphore(3)` 将并发压在可控范围，并发度作为配置项，
   可按上游额度调整。

6. **批量任务注册表为进程内实现**
   目标是先跑通「异步任务 + 进度查询」的接口契约（`task_id` + 状态轮询），
   进程内实现零中间件、开箱即可运行。接口契约与真实队列一致，
   后续替换为 Celery / ARQ + Redis 不影响前端调用方式。

7. **前端 AI Key 通过环境变量注入**
   前端代码会原样打包进 `dist` 并暴露给任何访问者，硬编码 Key 等同于公开泄露。
   现通过 `VITE_AI_API_KEY` 注入，仓库中仅保留空占位符，本地 `.env.local` 不进入版本库。

---

## 三、接口清单

后端共 **25 个路由**，启动后可在 `http://localhost:8000/docs` 交互式查看。

### AI 摘要（`/api/ai`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/ai/health` | 大模型是否可用（未配 Key 时前端可隐藏 AI 入口） |
| GET | `/api/ai/news/summary?id=1` | 非流式摘要，返回 `cached` / `degraded` / `elapsed_ms` / `tokens` |
| POST | `/api/ai/news/summary/stream?id=1` | **SSE 流式摘要**：`meta → delta×N → done` |
| POST | `/api/ai/news/batch/summary` | 批量摘要，立即返回 `task_id`（body：`{"newsIds":[1,2,3],"concurrency":2}`） |
| GET | `/api/ai/news/batch/status?taskId=xxx` | 查询批量任务进度与结果 |
| GET | `/api/ai/metrics` | 缓存命中率 / token / 延迟分位 |
| POST | `/api/ai/metrics/reset` | 清空指标（压测前调用） |

SSE 事件格式：

```text
event: meta
data: {"news_id": 210, "cached": false, "model": "deepseek-chat", "degraded": false}

event: delta
data: {"text": "周杰伦专辑《最伟大的作品》"}

event: done
data: {"news_id": 210, "cached": false, "degraded": false, "elapsed_ms": 4403.5,
       "first_token_ms": 4135.2, "parsed": {"summary": "...", "points": [...], "keywords": [...]}}
```

### 业务接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/news/categories` | 新闻分类（Redis 缓存 7200s） |
| GET | `/api/news/list?categoryId=1&page=1&pageSize=10` | 分页列表（缓存 1800s） |
| GET | `/api/news/detail?id=1` | 详情 + 浏览量自增 + 相关推荐（缓存 3600s） |
| POST | `/api/user/register` | 注册（bcrypt 加密 + UUID Token） |
| POST | `/api/user/login` | 登录 |
| GET | `/api/user/info` | 当前用户信息（需 `Authorization` 头） |
| PUT | `/api/user/update` | 修改个人资料：昵称 / 头像 / 性别 / 简介（仅更新传入字段） |
| PUT | `/api/user/password` | 修改密码（需旧密码校验） |
| GET/POST/DELETE | `/api/favorite/...` | 收藏：检查 / 添加 / 移除 / 列表 / 清空 |
| GET/POST/DELETE | `/api/history/...` | 浏览历史：添加 / 列表 / 删除单条 / 清空 |

**统一响应格式**：`{"code": 200, "message": "...", "data": {...}}`。
例外：`/api/news/categories` 与 `/api/news/list` 使用 `msg` 字段（前端两者均兼容）。

---

## 四、快速开始

### 前置依赖

- Python 3.13
- Node.js 18+
- MySQL 8（数据库名 `news_app`）
- Redis 5+

### 启动后端

```bash
# 依赖（建议使用项目内 venv）
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt

# 配置
copy .env.example .env
#   编辑 .env 填入 LLM_API_KEY
#   不填也能运行：AI 摘要自动降级为原文摘录，接口返回 degraded=true，不会 500

# 启动（需本机 MySQL + Redis）
venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000

# 接口文档
#   http://localhost:8000/docs
```

> 数据库连接串默认是 `mysql+aiomysql://root:123456@localhost:3306/news_app`，
> 请按实际环境修改 `config/db_conf.py`。

### 启动前端

```bash
cd xwzx-news
npm install

# 配置（AI 问答页需要 Key；不配则提示"API Key未配置"，其余功能不受影响）
copy .env.example .env.local
#   编辑 .env.local 填入 VITE_AI_API_KEY

npm run dev        # 开发服务器
npm run build      # 生产构建，产物在 xwzx-news/dist
```

前端默认请求 `http://127.0.0.1:8000`，可通过 `VITE_API_BASE_URL` 覆盖。

### 运行验证脚本

```bash
venv\Scripts\python.exe verify_ai_summary.py    # 端到端 + 性能实测
venv\Scripts\python.exe verify_ai_degraded.py   # 降级路径（无 Key / 无效 Key）
```

---

## 五、配置项说明

后端配置位于项目根目录 `.env`（模板见 `.env.example`），由 `config/llm_conf.py` 解析。

| 分类 | 配置项 | 默认值 | 说明 |
|---|---|---|---|
| 大模型 | `LLM_API_KEY` | 空 | 留空则 AI 摘要自动降级，不影响服务启动 |
| | `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容接口地址 |
| | `LLM_MODEL` | `deepseek-chat` | 模型名 |
| | `LLM_CONNECT_TIMEOUT` | `5` | 连接超时（秒） |
| | `LLM_TIMEOUT` | `30` | 读取超时（秒） |
| | `LLM_MAX_RETRY` | `1` | 失败重试次数（仅 5xx / 网络错误） |
| | `LLM_TEMPERATURE` | `0.3` | 生成温度 |
| | `LLM_MAX_TOKENS` | `400` | 最大生成 token |
| | `LLM_MAX_INPUT_CHARS` | `4000` | 正文截断长度，控制单次调用成本 |
| 缓存 | `SUMMARY_CACHE_VERSION` | `v1` | 缓存 key 版本号，改提示词或换模型时递增可使旧缓存失效 |
| | `SUMMARY_CACHE_EXPIRE` | `604800` | 摘要缓存有效期（秒，默认 7 天） |
| | `SUMMARY_DEGRADED_CACHE_EXPIRE` | `600` | 降级摘要缓存时间（秒） |
| 批量任务 | `SUMMARY_BATCH_CONCURRENCY` | `3` | 批量生成并发度 |
| | `SUMMARY_BATCH_MAX_ITEMS` | `30` | 单批最大条数 |
| | `SUMMARY_TASK_EXPIRE` | `3600` | 任务结果保留时间（秒） |

前端配置位于 `xwzx-news/.env.local`（模板见 `xwzx-news/.env.example`）：
`VITE_API_BASE_URL`、`VITE_AI_API_KEY`、`VITE_AI_API_ENDPOINT`、`VITE_AI_MODEL`。

---

## 六、性能实测

以下数据来自 `verify_ai_summary.py` 与 `verify_ai_degraded.py` 的实际运行结果
（完整输出见 `verify_ai_summary_result.txt` 与 `verify_ai_degraded_result.txt`）。

**延迟与缓存**

| 场景 | 实测值 |
|---|---|
| 首次摘要（未命中缓存，调用大模型） | **3986 ms**（服务端计时），prompt 413 + completion 154 tokens |
| 再次摘要（命中缓存） | **2.7 ms** → 提速 **≈1496×** |
| 大模型调用延迟 P50 / P95 | **3488 ms / 4790 ms** |
| 流式首字延迟 | **4135 ms**；整段 4403 ms，共 **75 个 delta 事件** |
| 批量 3 条（并发 2） | **6817 ms** 全部成功，0 失败 |

**降级路径**

| 故障 | 结果 |
|---|---|
| 未配置 `LLM_API_KEY` | HTTP **200** + `degraded=true`，`degrade_reason="未配置 LLM_API_KEY"`，返回原文摘录 |
| Key 无效（上游 401） | HTTP **200** + `degraded=true`，`degrade_reason="HTTP 401: Invalid API key."` |
| 降级结果 | 同样写入缓存（短 TTL，默认 600s），大模型不可用期间不会打满后端 |

**边界校验**

| 用例 | 结果 |
|---|---|
| 不存在的新闻 id | 404 `新闻不存在` |
| 单批超过 30 条 | 400 `单批最多 30 条，当前 59 条` |
| 不存在的任务 id | 404 `任务不存在或已过期` |
