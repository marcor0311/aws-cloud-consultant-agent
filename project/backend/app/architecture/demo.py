"""Visible, offline demonstration of the Cloud Architecture Agent."""

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app.architecture.catalog import BaselineCatalog
from app.architecture.graph import build_graph
from app.architecture.service import ArchitectureService
from app.integrations.langgraph import LangGraphExecution

BACKEND = Path(__file__).resolve().parents[2]
WORKSPACE = Path(__file__).resolve().parents[5]
DEFAULT_INPUT = BACKEND / "examples" / "architecture-1.json"
DEFAULT_OUTPUT = BACKEND / "data" / "architecture-demo"
BASELINES = WORKSPACE / "aws-cloud-consultant-baseline-modules"


def run(input_path: Path, output: Path) -> dict:
    package = json.loads(input_path.read_text(encoding="utf-8"))
    catalog = BaselineCatalog(BASELINES)
    with tempfile.TemporaryDirectory(prefix="architecture-demo-") as temporary:
        connection = sqlite3.connect(
            Path(temporary) / "checkpoints.sqlite3", check_same_thread=False
        )
        try:
            service = ArchitectureService(
                LangGraphExecution(build_graph(SqliteSaver(connection), catalog)),
                catalog,
            )
            pending = service.start("demo-issue-19", "architecture-demo-v1", package)
            state = pending["state"]
            approved = service.review(
                "demo-issue-19",
                state["revision"],
                state["artifact_sha256"],
                "approve",
            )["state"]
        finally:
            connection.close()

    output.mkdir(parents=True, exist_ok=True)
    for filename, content in approved["documents"].items():
        (output / filename).write_text(content, encoding="utf-8")
    handoff = approved["handoff"]
    (output / "handoff-finops.json").write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result = {
        "agent": "cloud-architecture-agent",
        "status": approved["status"],
        "revision": approved["revision"],
        "artifact_sha256": approved["artifact_sha256"],
        "selected_baselines": [item["module_id"] for item in package["baselines"]],
        "files": sorted([*approved["documents"], "handoff-finops.json"]),
        "output": str(output.resolve()),
        "terraform_generated": False,
        "aws_credentials_used": False,
    }
    (output / "demo-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Ejecuta una demostración local y segura del agente 3."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
