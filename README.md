# Law

一个基于多 Agent 工作流的法律咨询与案件分析 Demo。项目结合对话式前端、Flask 后端、法律条文检索、相似案例召回与长期记忆能力，面向合同纠纷、财产纠纷、婚姻家庭纠纷等常见场景，提供从普通咨询到案件研判的完整流程。

## 项目特点

- 多 Agent 协同：对话、案件分类与信息抽取、法条检索、案例研判分阶段完成
- 法律知识库检索：支持将 `law/` 目录下的法律 Markdown 文档导入 SQLite + Qdrant
- 相似案例推荐：内置示例案例，可按案件类型进行召回
- 记忆能力：支持短期对话上下文与基于向量库的长期记忆
- 前后端一体化：后端同时提供 API 和前端静态页面访问

## 系统架构

核心流程如下：

1. 用户在前端输入法律问题或案件描述
2. 后端判断是普通聊天，还是进入案件分析流程
3. `analyse_agent` 识别案件类型并补齐关键信息槽位
4. `search_rag_agent` 检索相关法律条文
5. `legal_advisory_service` 检索相似案例
6. `decision_agent` 生成中文结论、行动建议、风险提示与证据建议
7. `memory` 模块保存短期/长期记忆，支持后续追问

## 目录结构

```text
Law/
├─ backend/
│  ├─ run.py                        # 后端启动入口
│  └─ app/
│     ├─ api.py                     # Flask API 与前端静态资源入口
│     ├─ config.py                  # 环境变量与配置管理
│     ├─ agents/
│     │  ├─ agent.py                # 法律工作流总控 Agent
│     │  ├─ analyse_agent.py        # 案件分类与信息抽取
│     │  ├─ search_rag_agent.py     # 法条解析、入库与向量检索
│     │  ├─ decision_agent.py       # 法律结论生成
│     │  └─ memory.py               # 短期/长期记忆管理
│     └─ services/
│        ├─ llm_service.py          # LLM 初始化
│        └─ legal_advisory_service.py
├─ frontend/
│  ├─ analyze.html                  # 前端页面
│  ├─ analyze.css
│  └─ analyze.js
├─ law/                             # 法律知识库 Markdown / PDF
├─ law_demo.db                      # 示例 SQLite 数据库
└─ report.md                        # 相关研究记录
```

## 技术栈

- Backend: Python, Flask
- Frontend: HTML, CSS, JavaScript
- LLM: `hello_agents` 封装的模型调用
- Embedding / API Client: OpenAI SDK
- Vector DB: Qdrant
- Local Storage: SQLite

## 适用场景

- 法律咨询系统原型验证
- 多 Agent 法律分析流程演示
- 法条 RAG 检索实验
- 带记忆能力的法律对话助手 Demo

## 运行前准备

项目依赖以下运行条件：

- Python 3.10+
- 可用的 LLM/Embedding 接口
- 可访问的 Qdrant 服务

建议先创建虚拟环境并安装依赖：

```bash
pip install flask openai qdrant-client python-dotenv pydantic-settings
```

如果你的环境中没有 `hello_agents`，还需要额外安装或替换为你自己的 LLM 封装。

## 环境变量

可在项目根目录或 `backend/.env` 中配置：

```env
DEBUG=false
HOST=0.0.0.0
PORT=8000

LLM_API_KEY=your_llm_api_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_ID=gpt-4

OPENAI_API_KEY=your_openai_api_key
EMBED_API_KEY=your_embedding_api_key
EMBED_BASE_URL=https://api.openai.com/v1

QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

说明：

- `LLM_API_KEY` / `OPENAI_API_KEY` 用于大模型调用
- `EMBED_API_KEY` 用于向量嵌入
- `QDRANT_URL` 用于法律条文检索和长期记忆存储

## 启动方式

### 1. 启动后端

在项目根目录执行：

```bash
cd backend
python run.py
```

默认启动地址：

```text
http://127.0.0.1:8000
```

启动后可直接在浏览器访问首页，后端会返回前端页面。

### 2. 打开前端

浏览器访问：

```text
http://127.0.0.1:8000/
```

## API 接口

### 健康检查

`GET /api/health`

返回示例：

```json
{
  "ok": true,
  "app_name": "HelloAgents智能法律助手",
  "app_version": "1.0.0",
  "llm_enabled": true
}
```

### 法律分析

`POST /api/analyze`

请求示例：

```json
{
  "text": "对方借了我五万元一直不还，我可以起诉吗？",
  "state": null,
  "top_k": 5,
  "enable_mqe": true,
  "mqe_count": 3,
  "enable_hyde": true
}
```

接口会根据输入内容自动选择：

- 普通法律对话
- 进入案件分析流程
- 返回补充问题
- 返回法条、案例和综合结论

## 知识库说明

项目默认包含：

- `law/` 目录下的法律文本
- `law_demo.db` 示例数据库

`search_rag_agent.py` 支持把 Markdown 法律文档解析为：

- `law_catalog`
- `law_article`
- Qdrant 向量索引

如果你需要重建知识库，可以参考 [backend/app/agents/search_rag_agent.py](./backend/app/agents/search_rag_agent.py) 中的 `add_markdown_document()` 与示例主程序。

## 当前能力边界

- 当前主要覆盖合同、财产、婚姻家庭三类纠纷
- 案例库和律所库为内置示例数据，适合演示，不适合作为正式法律意见依据
- 项目依赖外部模型与向量服务，未配置时部分功能无法使用
- 后端代码中存在部分中文编码显示异常，但不影响 README 所描述的整体结构与功能定位

## 后续可扩展方向

- 增加更多法律领域分类与槽位抽取模板
- 接入真实裁判文书或案例库
- 增加用户系统与会话持久化
- 增加知识库初始化脚本与依赖清单
- 补充 Docker / requirements.txt / 部署文档

## 项目展示定位

这个项目更适合作为：

- AI + 法律场景的课程/比赛 Demo
- 多 Agent 工作流实验项目
- 法律知识库问答原型
- 智能法律助手的基础版本

## License

如需开源发布，建议你根据实际情况补充许可证，例如 `MIT`。
