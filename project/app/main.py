from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.agent_routes import router
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Crear la instancia de FastAPI
app = FastAPI(
    title="Proyecto Multiagentes API",
    description="API para orquestar agentes de planeación, recuperación, generación y evaluación usando Azure OpenAI + Azure Agent Framework.",
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

# Registrar rutas de agentes
app.include_router(router, prefix="/api", tags=["Agentes"])

# Endpoint raíz para verificar que el backend funciona
@app.get("/")
def root():
    return {
        "message": "Backend Multiagentes operativo 🚀",
        "status": "ok",
        "docs": "/docs",
    }