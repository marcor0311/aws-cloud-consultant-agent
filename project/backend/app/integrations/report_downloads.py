"""Short-lived, hash-bound PDF links for MCP clients without resource downloads."""

import hashlib
import hmac
import time
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from starlette.responses import Response

from app.delivery.report import require_report_owner


class ReportDownloads:
    lifetime_seconds = 300
    media_types = {"application/pdf": "pdf", "application/json": "json"}

    def __init__(self, repository, operator, public_url, key, *, clock=time.time):
        parsed = urlsplit(public_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError(
                "DELIVERY_DOWNLOAD_BASE_URL requiere un origen HTTPS sin ruta ni credenciales"
            )
        if len(key) < 32:
            raise ValueError(
                "La firma de descargas requiere el token Bearer de al menos 32 caracteres"
            )
        self.repository, self.operator = repository, operator
        self.public_url, self.key, self.clock = (
            public_url.rstrip("/"),
            key.encode(),
            clock,
        )

    def _artifact(self, delivery_id, artifact_id):
        row = self.repository.get(delivery_id)
        if not row:
            raise LookupError("Informe inexistente")
        require_report_owner(row, self.operator)
        artifact = self.repository.artifact(delivery_id, artifact_id)
        if not artifact or artifact["media_type"] not in self.media_types:
            raise LookupError("Documento inexistente en este informe")
        raw = bytes(artifact["content"])
        if hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
            raise ValueError("El documento no coincide con su SHA-256")
        return artifact, raw

    def _signature(self, delivery_id, artifact_id, sha256, expires):
        message = f"report-download-v1\n{self.operator}\n{delivery_id}\n{artifact_id}\n{sha256}\n{expires}"
        return hmac.new(self.key, message.encode(), hashlib.sha256).hexdigest()

    def prepare(self, delivery_id, artifact_id):
        delivery_id, artifact_id = UUID(str(delivery_id)), UUID(str(artifact_id))
        artifact, raw = self._artifact(delivery_id, artifact_id)
        expires = int(self.clock()) + self.lifetime_seconds
        sha = artifact["sha256"]
        query = urlencode(
            {
                "expires": expires,
                "sha256": sha,
                "signature": self._signature(delivery_id, artifact_id, sha, expires),
            }
        )
        return {
            "delivery_id": str(delivery_id),
            "artifact_id": str(artifact_id),
            "filename": self.filename(delivery_id, artifact_id, artifact["media_type"]),
            "media_type": artifact["media_type"],
            "sha256": sha,
            "size_bytes": len(raw),
            "expires_at": expires,
            "expires_in_seconds": self.lifetime_seconds,
            "download_url": f"{self.public_url}/downloads/{delivery_id}/{artifact_id}?{query}",
        }

    def filename(self, delivery_id, artifact_id, media_type):
        extension = self.media_types[media_type]
        return f"informe-{delivery_id}-{artifact_id}.{extension}"

    async def download(self, request):
        headers = {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        }
        try:
            delivery_id = UUID(request.path_params["delivery_id"])
            artifact_id = UUID(request.path_params["artifact_id"])
            expires = int(request.query_params["expires"])
            sha = request.query_params["sha256"]
            signature = request.query_params["signature"]
            if (
                not self.clock() < expires <= self.clock() + self.lifetime_seconds
                or not hmac.compare_digest(
                    signature, self._signature(delivery_id, artifact_id, sha, expires)
                )
            ):
                raise ValueError("Enlace inválido o vencido")
            artifact, raw = self._artifact(delivery_id, artifact_id)
            if artifact["sha256"] != sha:
                raise ValueError("Archivo distinto al autorizado")
        except (ValueError, LookupError, KeyError):
            return Response(
                "Enlace inválido o vencido", status_code=404, headers=headers
            )
        headers["Content-Disposition"] = (
            f'attachment; filename="{self.filename(delivery_id, artifact_id, artifact["media_type"])}"'
        )
        return Response(raw, media_type=artifact["media_type"], headers=headers)
