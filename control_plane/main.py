"""
MCP Container Control Plane - FastAPI Main Application
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from control_plane.api import api_router
from control_plane.services.registry_client import RegistryClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時の初期化 / 終了時のクリーンアップ"""
    logger.info("Control Plane starting …")
    # Registry ヘルスチェック（起動確認のみ、失敗しても続行）
    registry = RegistryClient()
    if await registry.health():
        logger.info("Registry connection OK")
    else:
        logger.warning("Registry not reachable — will retry when needed")
    yield
    logger.info("Control Plane shutting down …")


app = FastAPI(
    title="MCP Container Control Plane",
    description="MCPサーバーコンテナの作成・管理システム",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files and templates
BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# API routers
app.include_router(api_router)


@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """メインUI"""
    return templates.TemplateResponse("index.html", {"request": request})
