import redis
import os
from dotenv import load_dotenv
load_dotenv()

REDIS_CACHE_URL = os.getenv("REDIS_CACHE_URL")
_redis_client = None

def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_CACHE_URL)
    return _redis_client

