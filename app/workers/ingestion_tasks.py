from .celery_worker import celery_app
from app.core.redis import get_redis
import json

@celery_app.task(name="save_to_cache")
def save_to_cache(key:str, value:dict, expire:int = 3600):
    """
    salva i dati in redis come cache con TTL(time to live)
    """
    redis = get_redis()
    redis.set(key=json.dumps(value), ex=expire)
    return True


