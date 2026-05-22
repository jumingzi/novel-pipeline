import os
from dotenv import load_dotenv

load_dotenv()

# Suppress ChromaDB telemetry errors
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

# --- API (可从环境变量覆盖) ---
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

# --- Agent 参数矩阵 ---
AGENT_CONFIG = {
    "agent1": {
        "thinking": False,
        "temperature": 0.1,
        "response_format": "json_object",
    },
    "agent2": {
        "thinking": True,
        "reasoning_effort": "standard",
        "temperature": 0.3,
        "max_tokens": 8192,
        "response_format": "json_object",
    },
    "agent3": {
        "thinking": True,
        "reasoning_effort": "standard",
        "temperature": 0.2,
        "response_format": "json_object",
    },
    "agent4": {
        "thinking": False,
        "temperature": 0.75,
        "frequency_penalty": 0.4,
    },
}

# --- Chunk 参数 ---
CHUNK_SIZE_TOKENS = 8000
CHUNK_OVERLAP_TOKENS = 500

# --- Agent4 上下文限制 ---
AGENT4_MAX_CONTEXT_TOKENS = 30000

# --- 重试 ---
MAX_RETRIES = 3
RETRY_BACKOFF = (2, 4, 8)
JSON_FIX_MAX_RETRIES = 2

# --- HTTP ---
HTTP_TIMEOUT = 180
HTTP_TIMEOUT_STREAMING = 300

# --- 章节 ---
DEFAULT_CHAPTER_WORDS = 1500

# --- 15 分类模板名 ---
GENRE_TEMPLATES = [
    "玄幻", "仙侠", "武侠", "都市", "轻小说", "恋爱",
    "历史", "军事", "科幻", "奇幻", "游戏", "悬疑",
    "现实", "体育", "短篇",
]

ANTI_AI_CLICHES = [
    # 开头/过渡废话
    "总而言之", "不可否认", "随着时间的推移", "与此同时", "在这一刻",
    "此时此刻", "在这千钧一发之际", "随着", "紧接着", "不一会",
    "此时此刻他心中涌起一股", "不知过了多久", "转眼间",
    # AI 形容词堆叠套路
    "深邃而神秘", "不可名状", "宛若", "仿佛一切都在",
    "令人窒息的", "无与伦比的", "难以言喻的", "前所未有",
    # 面部表情AI体
    "嘴角勾起一抹", "嘴角勾起一丝", "嘴角微微上扬",
    "眼眸中闪过", "眼中闪过一抹", "眼底深处",
    "眼神中透着", "目光中带着", "脸上浮现出",
    # 情绪直述（违背Show Don't Tell）
    "他心中充满了", "他感到一阵", "他心中涌起一股",
    "一股强烈的", "内心深处", "他不由得",
    # 被动语态AI体
    "被一股", "被一种", "让人感到", "给人一种",
    # 冗余修饰
    "显得格外", "显得异常", "愈发显得", "堪称",
    "可以说是", "不得不说", "无不是",
    # 武侠/玄幻AI套路词
    "一股前所未有的力量", "化作一道", "爆发出",
    "眼中精光一闪", "冷哼一声", "倒吸一口凉气",
    "浑身一震", "瞳孔一缩", "面色一变", "身形一动",
    # 结尾AI套路
    "一切都在", "一切似乎都", "这场", "这场战斗",
    "而这仅仅只是开始", "而这只是", "等待着他们的",
]


def load_api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set. Create .env file or set environment variable.")
    return key
