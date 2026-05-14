from celery import Celery
import os
from dotenv import load_dotenv
load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")
celery_app = Celery(
    "workers",
    broker=REDIS_URL,
    backend=REDIS_URL   #se vuoi usare redis anche come backend
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)


