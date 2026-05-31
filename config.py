"""全局配置：模型、检索阈值、路径。全部可用环境变量覆盖。"""
import os

# ---------- 大模型（OpenAI 兼容接口）----------
# 默认 360 智脑（本项目核查底座）。若要换 DeepSeek 等，改这三个环境变量即可，代码无需改动。
#   360 智脑：LLM_BASE_URL=https://api.360.cn/v1   LLM_MODEL=360gpt-pro   LLM_AUTH_PREFIX=""
#   DeepSeek：LLM_BASE_URL=https://api.deepseek.com/v1  LLM_MODEL=deepseek-chat  LLM_AUTH_PREFIX="Bearer "
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.360.cn/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "360gpt-pro")
# 鉴权头前缀：360 智脑与 DeepSeek/OpenAI 一致，都用 "Bearer "（官方文档示例 Authorization: Bearer <key>）。
LLM_AUTH_PREFIX = os.getenv("LLM_AUTH_PREFIX", "Bearer ")

# ---------- 检索 ----------
TOP_K = int(os.getenv("TOP_K", "3"))
# 命中阈值：score >= 该值视为知识库命中，可走"数据复用"快路径
KB_HIT_THRESHOLD = float(os.getenv("KB_HIT_THRESHOLD", "0.45"))
# 中文向量模型（FAISS 路径用）。国内下载慢可设 HF_ENDPOINT=https://hf-mirror.com
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")

# ---------- 路径 ----------
_HERE = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(_HERE, "seed_data.json")
CACHE_PATH = os.path.join(_HERE, "kb_cache.json")  # 自动扩库写到这里
