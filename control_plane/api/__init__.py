"""MCP Container Control Plane - API Routers"""
from fastapi import APIRouter
from control_plane.api.containers import router as containers_router
from control_plane.api.build import router as build_router
from control_plane.api.chat import router as chat_router
from control_plane.api.container_chat import router as container_chat_router
from control_plane.api.test import router as test_router

api_router = APIRouter(prefix="/api")
api_router.include_router(containers_router)
api_router.include_router(build_router)
api_router.include_router(chat_router)
api_router.include_router(container_chat_router)
api_router.include_router(test_router)
