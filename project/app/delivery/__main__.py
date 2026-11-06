"""Initialize explicitly, execute and export a persisted local demonstration."""

import argparse
import json
import os
from pathlib import Path

from app.delivery.models import DemoRequest
from app.delivery.repository import PostgresRepository
from app.delivery.workflow import DeliveryWorkflow


def main():
    parser = argparse.ArgumentParser(
        description="Entrega 1 local; no utiliza APIs cloud"
    )
    parser.add_argument("command", choices=["init-db", "run"])
    parser.add_argument("--input", type=Path, default=Path("examples/delivery-1.json"))
    parser.add_argument("--output", type=Path, default=Path("data/delivery-demo"))
    args = parser.parse_args()
    dsn = os.getenv("DELIVERY_DATABASE_URL")
    if not dsn:
        parser.error("Configurar DELIVERY_DATABASE_URL para una base PostgreSQL local")
    repository = PostgresRepository(dsn)
    if args.command == "init-db":
        repository.initialize()
        print("Esquema de entrega inicializado.")
        return
    request = DemoRequest.model_validate_json(args.input.read_text(encoding="utf-8"))
    result = DeliveryWorkflow(repository).run(request)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "delivery.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    refs = list(result["handoff"]["artifacts"]) if result["handoff"] else []
    if result["report"]:
        refs.append(result["report"]["artifact"])
    for ref in refs:
        artifact = repository.artifact(request.delivery_id, ref["artifact_id"])
        (args.output / artifact["filename"]).write_bytes(bytes(artifact["content"]))
    print(
        json.dumps(
            {
                "delivery_id": result["delivery_id"],
                "status": result["status"],
                "files_exported": len(refs),
            },
            ensure_ascii=False,
        )
    )
    if result["status"] != "draft_ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
