from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.api.dependencies import clear_runtime
from app.core.config import load_environment

load_environment()


@asynccontextmanager
async def lifespan(_app):
    try:
        yield
    finally:
        clear_runtime()


# Crear la instancia de FastAPI
app = FastAPI(
    lifespan=lifespan,
    title="Calendar Assistant API",
    description="Registro de clientes y verificación OTP para Calendar Assistant.",
    version="1.0.0",
)

# Permitir solicitudes cross-origin a la API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En prod esto se cambia
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


# Endpoint raíz para verificar que el backend funciona
@app.get("/")
def root():
    return {
        "message": "Calendar Assistant operativo",
        "status": "ok",
        "docs": "/docs",
    }
