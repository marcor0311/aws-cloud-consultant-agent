"""Generate three local meeting deliverables from source-bound preparation."""

import argparse
import json
from pathlib import Path

from app.core.config import PROJECT_DIR
from app.demos.insumos import prepare_mock
from app.integrations.insumos_export import export_insumos
from app.preparation.insumos import MeetingInsumos, MeetingTranscript


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_DIR.parent / "insumos")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--mock",
        action="store_true",
        help="Run the scripted Nike fixture through LangGraph.",
    )
    source.add_argument("--transcript", type=Path)
    parser.add_argument(
        "--content",
        type=Path,
        help="Validated preparation JSON; required with --transcript.",
    )
    args = parser.parse_args()
    if args.mock:
        transcript, content, result = prepare_mock()
        status = result["state"]["status"]
    else:
        if not args.content:
            parser.error(
                "--transcript requiere --content; no se inventa un resumen automático."
            )
        transcript = MeetingTranscript.model_validate_json(args.transcript.read_text())
        content = MeetingInsumos.model_validate_json(args.content.read_text())
        status = "awaiting_review"
    manifest = export_insumos(transcript, content, args.output, status=status)
    print(
        json.dumps(
            {"directory": str(args.output.resolve()), **manifest},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
