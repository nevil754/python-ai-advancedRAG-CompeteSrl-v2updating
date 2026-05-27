
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.observability import setup_all
from app.core.settings import get_settings
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from __future__ import annotations

settings = get_settings()




