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
DEFAULT_CHAPTER_WORDS = 3000

# --- 15 分类模板名 ---
GENRE_TEMPLATES = [
    "玄幻", "仙侠", "武侠", "都市", "轻小说", "恋爱",
    "历史", "军事", "科幻", "奇幻", "游戏", "悬疑",
    "现实", "体育", "短篇",
]

ANTI_AI_CLICHES = [
    "总而言之", "不可否认", "随着时间的推移",
    "嘴角勾起一抹玩味的笑", "与此同时，他心中涌起一股",
    "深邃而神秘", "不可名状", "宛若", "仿佛一切都在",
]


def load_api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set. Create .env file or set environment variable.")
    return key
