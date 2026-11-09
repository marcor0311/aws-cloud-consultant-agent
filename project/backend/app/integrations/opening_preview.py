"""GitHub simulator writes reviewable artifacts; the actual agent graph is unchanged."""

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

from app.integrations.slack_board import SlackBoardActions


def simulate_board_approval(board, case_id, choices=None):
    """Four placeholder members; never emits a real Slack message or approval."""
    ballot = board.prepare(
        case_id,
        {
            "team_id": "TPREVIEW",
            "app_id": "APREVIEW",
            "channel_id": "CPREVIEW",
            "members": [
                {"slack_id": f"UBOARD{i}", "name": f"Board Member {i}"}
                for i in range(1, 5)
            ],
            "is_simulated": True,
        },
    )
    if ballot["status"] in {"approved", "not_approved"}:
        return board.repository.save(ballot)
    ballot = board.repository.save(
        {
            **ballot,
            "status": "open",
            "receipt": {"channel": "CPREVIEW", "ts": f"{ballot['opened_at']:.6f}"},
        }
    )
    secret = "local-preview-only-not-a-slack-secret"
    for i, member in enumerate(ballot["members"]):
        now = time.time()
        payload = {
            "type": "block_actions",
            "api_app_id": "APREVIEW",
            "team": {"id": "TPREVIEW"},
            "channel": {"id": "CPREVIEW"},
            "container": {"message_ts": ballot["receipt"]["ts"]},
            "user": {"id": member["slack_id"]},
            "actions": [
                {
                    "action_id": "board_" + (choices[i] if choices else "approve"),
                    "value": ballot["id"],
                    "action_ts": str(now),
                }
            ],
        }
        raw = urlencode({"payload": json.dumps(payload)}).encode()
        timestamp = str(int(now))
        signature = (
            "v0="
            + hmac.new(
                secret.encode(),
                b"v0:" + timestamp.encode() + b":" + raw,
                hashlib.sha256,
            ).hexdigest()
        )
        SlackBoardActions(board, secret, clock=lambda: now).handle(
            raw, timestamp, signature
        )
    return board.get(ballot["id"])


class PreviewGitHub:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.calls = []

    def save(self, name, value):
        (self.directory / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2)
        )

    def ensure_repository(self, record):
        self.calls.append("repository")
        result = {
            "id": 0,
            "url": "https://github.invalid/"
            + record["owner"]
            + "/"
            + record["repository_name"],
            "full_name": record["owner"] + "/" + record["repository_name"],
            "default_branch": "main",
        }
        self.save(
            "repository-preview.json",
            {
                "mode": "preview",
                "template": record["template_repository"],
                "title": record["title"],
                "private": record["private"],
                **result,
            },
        )
        return result

    def publish(self, record, files):
        self.calls.append("documents")
        hashes = {}
        for name, data in files.items():
            path = self.directory / "repository" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        sha = hashlib.sha1(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        self.save("files-preview.json", hashes)
        return {"sha": sha, "url": record["repository"]["url"] + "/commit/" + sha}

    def merge_initial_structure(self, record):
        self.calls.append("initial_structure_pr")
        result = {
            "number": 1,
            "url": record["repository"]["url"] + "/pull/1",
            "branch": "docs/initial-structure",
            "merged": True,
            "merge_sha": record["commit"]["sha"],
        }
        self.save("pull-request-preview.json", {"mode": "preview", **result})
        return result

    def assign_architecture(self, record, body, template):
        self.calls.append("architect")
        (self.directory / "architecture-issue.md").write_text(body)
        result = {
            "number": 1,
            "url": record["repository"]["url"] + "/issues/1",
            "assignee": record.get("issue_assignee") or record["architect"],
            "assignment_pending": False,
            "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
        }
        self.save("issue-preview.json", {"mode": "preview", **result})
        return result
