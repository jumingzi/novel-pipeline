# 小说矩阵工坊 (Novel Pipeline)

基于 DeepSeek V4 Pro API 的小说自动化创作流水线。支持拆书分析、知识库构建、仿生创作、编辑对话，国风水墨 Web UI。

## 功能

### 拆书分析
- 上传 .txt / .epub / .mobi → 自动清洗分章
- AI 深度拆解人设、人物关系、爽点曲线、黄金钩子、文风 DNA、伏笔追踪
- 支持按章节范围选择性拆解（如 1-20 章、50-100 章）
- 批量并行处理（默认 10 并发），快速模式 5-8 分钟拆完 100 章

### 知识库
- 角色卡、剧情时间线、世界观设定、文风档案按项目独立存储
- ChromaDB 向量检索，支持语义搜索和关键词混合搜索
- 断点续跑：Agent2 完成后自动保存检查点，崩溃可从断点继续
- 项目导出为 JSON（含角色、剧情、已采纳章节）

### 章节创作
- 根据细纲 + 知识库上下文 + 对标书文风生成章节
- 流式输出：文字实时出现在界面
- AI 味检测报告：自动评分 + 标记禁用词 + 句式雷同检测
- 重写、微调、采纳保存
- 批量章节生成：节拍表驱动，自动串联钩子
- 角色一致性检查

### 创作工具
- **大纲规划器**：输入想法 → AI 生成 6-8 节拍表（起承转合），可逐个微调
- **角色关系图**：环形布局展示角色网络
- **对比分析**：两本书文风差异对比（对白占比、成语密度、句长）
- **标题生成**：根据概要生成 3-5 个备选书名
- **灵感建议**：卡文时 AI 给 3 个创作方向

### AI 写手对话
- 专属网文编辑助手，讨论剧情、人物、爽点设计
- 50 轮对话记忆
- 自动引用知识库角色列表和文风数据
- `/` 命令菜单（/灵感 /书名 /细纲 /角色 /分析 /续写 /大纲）

### Web UI
- 国风水墨主题 + 深色模式
- 侧边栏可折叠/拖拽宽度
- 浏览器式多标签页
- 步骤条进度显示
- 通知中心 + 快捷键
- 实时字数统计

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/jumingzi/novel-pipeline.git
cd novel-pipeline

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 4. 启动
python main.py --web
# 打开 http://127.0.0.1:8866
```

## CLI 模式

```bash
# 拆书分析（仅分析不生成章节）
python main.py --input 斗破苍穹.epub --genre 玄幻 --analyze-only

# 分析 + 生成章节
python main.py --input 小说.txt --genre 都市 --outline "主角重生归来..." --words 2000
```

## 项目结构

```
novel-pipeline/
├── main.py                     # CLI & Web 入口
├── config.py                   # 全局配置 (Agent参数矩阵、禁用词表)
├── rag.py                      # ChromaDB 向量检索
├── pipeline/
│   ├── api_client.py           # DeepSeek API 统一调用 (重试/JSON修复/流式)
│   ├── agent1_cleaner.py       # 文件处理 (解析/清洗/分章)
│   ├── agent2_deconstructor.py # 拆书分析 (人设/关系/爽点/钩子/文风)
│   ├── agent3_kb.py            # 知识归档 (去重/入库/向量化)
│   ├── agent4_writer.py        # AI写手 (创作/去AI味/检测)
│   └── orchestrator.py         # 主控协调 (进度总线/流水线/批处理)
├── webui/
│   ├── app.py                  # FastAPI (8+ 端点 / SSE)
│   ├── templates/index.html    # 前端单页
│   └── static/style.css        # 国风水墨设计系统
├── knowledge_base/              # 知识库持久化 (自动生成)
├── chroma_store/               # ChromaDB 向量数据
└── tests/                      # 59 个测试用例
```

## 技术栈

| 层 | 技术 |
|---|------|
| 语言 | Python 3.11+ |
| Web | FastAPI + Jinja2 + SSE |
| 前端 | 原生 HTML/CSS/JS (零框架) |
| API | DeepSeek V4 Pro (OpenAI 兼容) |
| 向量库 | ChromaDB (嵌入式) |
| 文件解析 | ebooklib + mobi + tiktoken |
| 测试 | pytest (59 cases) |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | 模型名 |
| `DEEPSEEK_API_KEY` | (必填) | API Key |

## License

MIT
