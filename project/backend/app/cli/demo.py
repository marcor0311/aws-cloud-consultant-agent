"""Run the offline demo; no account credentials or external APIs are required."""

import argparse
import json
import uuid

from app.core.config import PROJECT_DIR
from app.demos.workflow import run_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory", help="New directory; an existing run is never reset."
    )
    parser.add_argument(
        "--collaborate",
        action="store_true",
        help="Also simulate Stuart editing/approving and the next agent accepting.",
    )
    args = parser.parse_args()
    directory = (
        args.directory
        or PROJECT_DIR / "generated/mock-workflow" / uuid.uuid4().hex[:10]
    )
    report = run_demo(directory, collaborate=args.collaborate, activate=True)
    print(
        json.dumps(
            {
                "mode": "mock",
                "directory": str(directory),
                "projects": [
                    {
                        "project": p["title"],
                        "status": p["status"],
                        "revision": p["revision"],
                    }
                    for p in report["projects"]
                ],
                "slack_notifications": len(report["slack_outbox"]),
                "external_connections": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
