# 小说矩阵式自动化创作工作流 — 设计文档

> 日期: 2026-05-21
> 状态: 设计完成, 待实现

---

## 概述

构建一个基于 DeepSeek V4 Pro API 的小说自动化创作流水线，包含 4 个子 Agent 协同工作，支持从原始小说文件输入到最终章节输出的全流程，通过 Web UI 进行交互式创作。

### 为什么做这个

解决网文创作中的几个核心痛点:
- 手上有多本对标书, 想拆解它们的套路/人设/文风, 手动做太慢
- 写新章节时需要参考已有的角色关系、伏笔、文风数据, 但信息分散记不住
- AI 生成的小说有浓重的 "AI 味", 需要系统化去 AI 痕迹
- 需要一个能跟用户对话协作的 AI 写手, 而不是一次性吐出一章的机器

---

## 技术选型

| 项目 | 选择 | 原因 |
|------|------|------|
| 语言 | Python 3.11+ | 文本处理生态最强, httpx/ebooklib/chromadb 都有成熟库 |
| Web 框架 | FastAPI | 原生 SSE 支持, 轻量, 适合单页应用 |
| 前端 | 原生 HTML/CSS/JS | 零依赖, FastAPI 直接渲染 |
| 向量库 | ChromaDB | 嵌入式运行, 不需要外部数据库 |
| Token 估算 | tiktoken | OpenAI 兼容 tokenizer |
| 文件解析 | ebooklib (epub) + mobi-specific | 解包 mobi 用第三方库 |
| API 调用 | httpx (async) | 支持超时/重试/流式 |

---

## 架构总览

```
文件上传 → epub/mobi/txt 解析 → 纯文本
  → Agent1: 文件处理 (清洗 + 分章切片)
  → Agent2: 拆书分析 (人设/关系/爽点/钩子/文风)  [thinking=high]
  → Agent3: 知识归档 (分类+去重+卡片入库+向量化) [thinking=standard]
  → Agent4: AI写手 (标题简介+文风克隆+去AI味+章节创作+灵感建议)
  → 最终章节输出
```

### 项目结构

```
D:\novel-pipeline\
├── main.py                    # CLI 入口
├── webui/
│   ├── app.py                 # FastAPI + SSE 端点
│   ├── templates/
│   │   └── index.html         # 前端单页
│   └── static/
│       └── style.css
├── pipeline/
│   ├── orchestrator.py        # 主控协调器 + 进度总线
│   ├── agent1_cleaner.py      # 文件处理
│   ├── agent2_deconstructor.py # 拆书分析
│   ├── agent3_kb.py           # 知识归档
│   ├── agent4_writer.py       # AI写手
│   └── api_client.py          # DeepSeek API 统一调用
├── knowledge_base/            # 持久化 JSON
│   └── [genre]/
│       ├── character_cards.json
│       ├── plot_timeline.json
│       ├── world_settings.json
│       └── style_profile.json
├── chroma_store/              # ChromaDB 持久化目录
├── config.py                  # 全局配置
├── rag.py                     # RAG 检索封装
├── requirements.txt
└── .env                       # DEEPSEEK_API_KEY
```

---

## Agent 1: 文件处理

### 功能
- 解析 epub/mobi/txt 格式 → 纯文本
- 正则剔除噪音: 防盗贴/充值广告/作者感言/目录页/无意义标点堆叠
- 段落重构: 修复断行错位, 合并被切割的段落
- 按"章"切分, 每块 ~8000 tokens, 相邻块 500 tokens 重叠
- 输出 Chunk 元数据: {chunk_id, chapter_index, overlap_prev, overlap_next}

### API 配置
```
temperature: 0.1, thinking: false, response_format: json_object
```

---

## Agent 2: 拆书分析

### 功能
- 人设拆解: 显性特征 + 隐性动机 + 核心矛盾
- 人物关系网: 关系类型(师徒/道侣/仇敌/盟友) + 亲密度(-10~+10) + 权力差 + 关系演进趋势
- 爽点曲线: 爽点类型 + 情绪值(-5~+5)
- 黄金钩子: 类型(悬念钩/利益钩) + 评分(1-10)
- 语言DNA: 成语密度 + 对白占比 + 长短句比例 + 独有句式指纹
- 伏笔追踪: 已埋伏笔 + 已回收伏笔

### API 配置
```
temperature: 0.3, thinking: enabled, reasoning_effort: high, max_tokens: 8192, response_format: json_object
```

---

## Agent 3: 知识归档

### 功能
- 题材自动检测 → 按起点中文网分类激活对应卡片模板
- 实体去重 + 演进合并 (同名角色能力升级自动更新)
- 关系网更新 (好感度/敌对度/势力归属)
- 持久化到 knowledge_base/ + 同步写入 ChromaDB
- 为 Agent4 准备检索上下文: 根据当前章节捞出相关角色卡+伏笔线, 控制在 30K tokens 以内

### 分类模板体系 (12 类)

详见设计讨论, 覆盖:
玄幻/仙侠/武侠/都市/轻小说/恋爱(跨分类叠加)/历史/军事/科幻/奇幻/游戏/悬疑/灵异/现实/体育/短篇

### API 配置
```
temperature: 0.2, thinking: enabled, reasoning_effort: standard, response_format: json_object
```

---

## Agent 4: AI写手

### 角色定位
协作型 AI 创作伙伴, 可与用户交互式共同创作

### 功能
- **标题与简介生成**: 根据大纲+人设+核心矛盾, 生成 3~5 个备选标题 + 200~500 字简介
- **章节创作**: 文风克隆 + 去AI味 + Show Don't Tell + 钩子收束/埋设
- **灵感建议**: 用户说"没思路"时, 从已分析小说库(ChromaDB) + 联网搜索(WebSearch)获取建议
- **大纲协作**: 用户输入简单想法, 展开为结构化章节细纲(节拍表, 6~8 个节拍)
- **交互模式**: Web UI 对话形式, 每轮可调用 DeepSeek API

### 去 AI 味处理
1. 强制禁词表: "总而言之"/"不可否认"/"随着时间的推移"/"嘴角勾起一抹玩味的笑"
2. 检测冗余风景/感官描写 (连续3句以上纯环境描写 → 压缩)
3. 检测模板式过渡句
4. 检测 AI 偏好形容词堆叠
5. 对话占比检测: 连续200字以上纯对话无打断 → 自动插入动作/心理活动

### 文风克隆
- 对标书文风样本提取: 句式节奏/修辞偏好/场景切换频率/情绪渲染方式
- 词汇频率同步: 常用词保持相同频率
- 镜头切换顺序模仿
- 对话与描写的穿插比例匹配

### API 配置
```
temperature: 0.75, frequency_penalty: 0.4, thinking: false, response_format: text
```

---

## API 调用层 (api_client.py)

- 统一入口: https://api.deepseek.com/v1/chat/completions, Model: deepseek-v4-pro
- HTTP 超时: 普通 180s, 流式 300s
- 网络重试: 指数退避 2s/4s/8s, 最多 3 次, 仅 5xx 和超时触发
- JSON 修复重试: 检测到 JSON 解析失败, 追加 "Fix JSON structure..." 指令重试, 最多 2 次
- 空响应/截断检测: 检查结尾是否正常标点, 截断则续写
- 进度汇报: 每次调用完成后向进度总线推送事件

---

## RAG 检索 (rag.py)

- 存储: ChromaDB (characters / plot_events / writing_samples 三个集合)
- 多路召回: 角色名精确匹配(0.4) + 语义相似度(0.6)
- Token 预算裁剪: tiktoken 估算, 超出 30K 从低分尾部裁剪

---

## Web UI

### 布局: 侧边栏 + 对话 (类 Gemini/ChatGPT)

```
┌──────────────────────────────────────────────────────────┐
│  ┌──────────┐                                            │
│  │侧边栏     │  主对话区                                   │
│  │          │                                            │
│  │≡ 项目列表 │  顶部: 流水进度 (四个圆点)                    │
│  │+ 新建项目 │                                            │
│  │          │  对话消息列表:                                │
│  │斗破同人   │  - AI写手 气泡: 偏白底+淡墨竖线左边框         │
│  │原创仙侠   │  - 用户 气泡: 偏暖底无边框                    │
│  │          │                                            │
│  │────────  │  底部: 输入框 + 发送按钮                       │
│  │          │                                            │
│  │◎ 项目设置 │  右下角浮动: 知识库小面板(可收起)              │
│  │ 题材 [▼] │                                            │
│  │ 对标书    │                                            │
│  │ 字数 [=] │                                            │
│  │ 联网 开关 │                                            │
│  │          │                                            │
│  │上传源文件 │                                            │
│  │[拖拽]    │                                            │
│  │          │                                            │
│  │[开始拆书] │                                            │
└──────────────┴──────────────────────────────────────────┘
```

### 视觉风格: 国风水墨

```
底色:       宣纸暖白 #f9f6f0
侧边栏底色:  #f2ede4
文字:       浓墨 #2b2b2b / 淡墨 #787878
强调色:     朱砂 #c43a31 (仅主要按钮)
分隔:       淡墨线 #d4cfc6
字体:       Noto Serif SC (思源宋体)
纸张纹理:   CSS 轻量噪点叠加
```

### 交互
- 侧边栏可折叠
- AI写手消息卡片带 [采纳] [微调] [重写] 按钮
- 加载态: 三个墨点依次明灭
- 动画仅淡入 + 微移, 干净克制

---

## 测试策略

1. 单 Agent 单元测试: mock API 返回, 验证输入输出
2. 流水线集成测试: 一本 10 章测试小说跑通全流程
3. API 容错测试: 模拟截断JSON / 超时 / token超限
4. Web UI E2E 测试: Playwright 脚本

---

## 启动方式

```bash
pip install -r requirements.txt
echo "DEEPSEEK_API_KEY=sk-xxx" > .env
python main.py --web          # Web UI, http://localhost:8866
python main.py --input novel.txt --genre 玄幻  # CLI 模式
```
