"""Local backend readiness; the public Calendar callback does not expose this route."""

from fastapi import APIRouter, Response

from app.integrations.health import check_health

router = APIRouter()


@router.get("/health", tags=["Health"])
def health(response: Response):
    result = check_health()
    response.status_code = 200 if result["status"] == "ok" else 503
    response.headers["Cache-Control"] = "no-store"
    return result
