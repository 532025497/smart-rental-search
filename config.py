# -*- coding: utf-8 -*-
"""智能租房搜索系统 - 配置文件"""
import os

# 高德地图 Web 服务 API Key（必须通过环境变量配置，勿提交到仓库）
GAODE_API_KEY = os.environ.get("GAODE_API_KEY", "").strip()

# 默认城市
DEFAULT_CITY = "北京"

# 路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 通勤估算参数
TRANSIT_SPEED_KMH = 22      # 平均公交地铁速度(km/h，含步行/等车/换乘)
ROUTE_FACTOR = 1.3          # 实际路线距离 / 直线距离 的系数
PREFILTER_MULTIPLIER = 1.5  # 预筛选余量倍数(粗估时间 < 限制*此倍数 才做精确查询)

# 并发设置
MAX_CONCURRENT = 6          # 高德免费Key建议不超过6并发，避免触发限流
REQUEST_TIMEOUT = 15       # 单次请求超时(秒)

# LLM设置 (OpenAI兼容API)
# 推荐: DeepSeek (性价比高, 中文强, 注册送余额)
# 注册: https://platform.deepseek.com/
# 也可用: 通义千问/OpenAI/Ollama本地模型
LLM_API_KEY = os.environ.get("LLM_API_KEY", "") or os.environ.get("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = 30            # LLM请求超时(秒)

# Loop设置
MAX_EXTRACTION_RETRIES = 3  # 提取-验证循环最大重试次数
