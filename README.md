# globex-agent

**AgentScope 2.0.9 + Python 3.11 + React 18 的跨境电商 Agent 学习工程。**
包含自然语言聊天、商品卡片与对比、购物车、订单报价/确认/取消、长期偏好确认、任务计划、子 Agent 派发、检索降级、事件追踪和任务恢复。默认即可运行，不需要模型密钥。

> 默认 `APP_MODE=demo`：规则演示，不调用 LLM。设置 `APP_MODE=llm` 并填写模型配置后，聊天和工具选择才由真正的大模型完成。界面顶部始终显示模式。商品、订单、税率、汇率都是教学数据，不产生真实支付。

## 1. 最快启动：Docker Compose

需要 Docker Desktop（Compose v2）。在解压后的项目根目录运行：

```bash
cp .env.example .env
docker compose up -d --build
```

打开 **http://localhost:8080**。后端 API 文档在 http://localhost:8000/docs 。

```bash
docker compose logs -f app worker        # 查看日志
docker compose down                      # 停止，保留数据
```

首次构建需要下载镜像、Python 和 npm 依赖。Compose 使用共享 SQLite 数据卷，app 与 worker 不要改为各自独立的数据库文件。不要同时开启 `INLINE_WORKER=true` 和独立 worker；本配置已为两者设置 false。

## 2. 本地开发：VSCode / PyCharm

需要 Python 3.11、uv、Node.js 22。安装 uv 可使用 `pip install uv`。

终端一（项目根目录）：

```bash
cp .env.example .env
uv sync --frozen
uv run uvicorn app.presentation.api:app --reload --host 127.0.0.1 --port 8000
```

终端二：

```bash
cd frontend
npm ci
npm run dev
```

打开 **http://localhost:5173**。默认使用进程内 worker，不需要 Redis/Qdrant，检索自动走关键词。VSCode 选择 `.venv/bin/python`（Windows 为 `.venv\Scripts\python.exe`）后，可使用项目自带 F5 配置启动后端。Windows PowerShell 用 `Copy-Item .env.example .env` 代替 `cp`。

若希望本地后端连接 Compose 的 Redis/Qdrant，请自行添加仅绑定 `127.0.0.1` 的端口映射，再设置 `.env`。默认 Compose 不向宿主机暴露这两个服务。

## 3. 真正调用大模型

编辑 `.env`，例如接入 DeepSeek：

```dotenv
APP_MODE=llm
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=你的密钥
LLM_MODEL=deepseek-chat
```

或者 OpenAI 兼容 Chat Completions 服务：

```dotenv
APP_MODE=llm
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=你的密钥
LLM_MODEL=填入账户可用且支持工具调用的模型ID
```

本地运行需重启后端；Docker 运行执行：

```bash
docker compose up -d --force-recreate app worker
```

更换 demo/llm 模式后建议点击界面左侧对话区右上角的 `+` 新建会话。模型必须支持 Chat Completions 工具调用和流式响应。密钥仅在后端使用，不进入前端构建。聊天服务和 embedding 服务单独配置，不能把 DeepSeek 聊天接口当作 embedding 接口。

## 4. 开启向量检索与知识库

`.env` 填写 embedding 服务：

```dotenv
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=你的embedding服务密钥
EMBEDDING_MODEL=text-embedding-v4
```

在 Compose 环境中重建容器环境并索引：

```bash
docker compose up -d --force-recreate app worker
docker compose exec app python -m scripts.index_catalog
```

该命令会将示例商品写入商品向量集合，将 `knowledge/*.md` 经 AgentScope TextParser → ApproxTokenChunker → KnowledgeBase 写入知识集合。模型或 endpoint 改动会切换集合命名空间，需要重新索引。重排和网页检索都是可选项，配置契约见 [服务配置](docs/配置与接口.md)。未配置时明确降级，不会假装完成在线检索。

## 5. 直接试这些操作

1. 输入“帮我找一款适合通勤的降噪耳机”。
2. 点商品卡片右下角 `+` 加入购物车；右上角 `+` 选择最多三件商品进行对比。
3. 切到购物车，选择目的地与报价货币，点击“生成报价并核对”。
4. 核对确认卡片中的商品、税费、运费、合计，再点“确认下单”。
5. 到订单面板查询或取消；取消也需要确认。
6. 在偏好面板填写偏好，确认卡片后才写入长期记忆。
7. 刷新页面，聊天、购物车、订单和偏好仍然保留。

LLM 模式还可试：“分别比较通勤耳机和旅行背包，各给一个推荐理由”，观察 `task_dispatch`；“帮我做选品、对比、加入购物车的计划”，观察 Task 工具。是否派发由模型决定，但服务端校验派发原因，并禁止并行交易任务。

## 6. 代码导航

```text
globex-agent/
├── app/
│   ├── domain/                 # 纯业务模型、状态机、规则、接口
│   ├── application/
│   │   ├── usecases/commerce.py # 原子业务事务、确认、幂等
│   │   ├── tools/registry.py    # 注入 ShoppingContext
│   │   └── agents/             # 三个 Agent 的应用边界
│   ├── infrastructure/         # AgentScope、SQLAlchemy、Redis、Qdrant、HTTP
│   ├── presentation/api.py     # REST / WebSocket / 鉴权
│   ├── prompts/               # 固定 system prompt
│   ├── composition.py         # 唯一组合根
│   └── worker.py              # 独立 worker
├── frontend/src/               # React 函数组件、严格 TypeScript、统一 API 层
├── knowledge/                  # Markdown 教学资料
├── eval/                       # 检索评测
├── tests/                      # 业务、API、框架、检索、任务测试
├── scripts/                    # 索引和 SDK 检查
├── docker/                     # Python / Nginx 镜像
├── docs/                       # 架构、边界、配置、测试、设计演进
├── .vscode/                    # F5 后端调试
├── uv.lock                     # Python 依赖锁
└── docker-compose.yaml
```

建议先读 `domain/models.py` → `application/usecases/commerce.py` → `infrastructure/agentscope_runtime.py` → `presentation/api.py` → `frontend/src/App.tsx`。

## 7. 测试

```bash
uv run pytest -q
uv run python -m scripts.check_sdk
uv run python -m eval.run
cd frontend
npm run build
```

外部付费模型不参与默认测试；LLM 集成测试使用本地 OpenAI 兼容 SSE 测试服务，但确实执行 AgentScope 的模型/工具/多轮循环。

详见 [架构与边界](docs/架构与边界.md)、[配置与接口](docs/配置与接口.md)、[验证记录](docs/验证记录.md)、[设计演进记录](docs/设计演进记录.md)。



<img width="2938" height="1434" alt="8657c916d4aea3d2717acd055fdd1bf6" src="https://github.com/user-attachments/assets/92046481-69e7-4d78-9c7e-a1d50bbd3652" />

