"""GitHub operations exposed through the agent's MCP tools, with reconciliation."""

import base64
import hashlib
import os
import subprocess
import time
from urllib.parse import quote

import httpx

from app.integrations.errors import ConfigurationError, ProviderError


def github_token():
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", "github.com"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise ConfigurationError("github_sign_in_required")


class ProjectGitHub:
    def __init__(self, client=None, token_provider=github_token, *, wait=time.sleep):
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)
        self.token_provider = token_provider
        self.wait = wait

    def request(self, method, path, *, missing=False, initializing=False, **kwargs):
        try:
            response = self.client.request(
                method,
                "https://api.github.com" + path,
                headers={
                    "Authorization": "Bearer " + self.token_provider(),
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
                **kwargs,
            )
        except httpx.HTTPError:
            raise ProviderError(
                "github_transport_error", ambiguous=method != "GET"
            ) from None
        if missing and response.status_code == 404:
            return None
        if initializing and method == "GET" and response.status_code in {404, 409}:
            return None
        if response.status_code not in {200, 201, 202, 204}:
            raise ProviderError(
                f"github_http_{response.status_code}",
                ambiguous=method != "GET" and response.status_code >= 500,
            )
        return response.json() if response.content else {}

    @staticmethod
    def repo_path(record):
        return f"/repos/{record['owner']}/{record['repository_name']}"

    @staticmethod
    def marker(record):
        return "meeting-assistant:" + record["case_id"] + ":" + record["request_sha256"]

    def ensure_repository(self, record):
        path = self.repo_path(record)
        description = record["title"] + " [" + self.marker(record) + "]"
        existing = self.request("GET", path, missing=True)
        if existing is None:
            template = self.request("GET", f"/repos/{record['template_repository']}")
            if not template.get("is_template"):
                raise ValueError(
                    "El repositorio de origen no está habilitado como template."
                )
            self.request(
                "POST",
                f"/repos/{record['template_repository']}/generate",
                json={
                    "owner": record["owner"],
                    "name": record["repository_name"],
                    "description": description,
                    "private": record["private"],
                    "include_all_branches": False,
                },
            )
            existing = self.request("GET", path)
        if (
            existing.get("description") != description
            or bool(existing.get("private")) != record["private"]
        ):
            raise ValueError(
                "El nombre ya pertenece a otro repositorio; no se modificó."
            )
        origin = existing.get("template_repository", {}).get("full_name")
        if origin and origin.casefold() != record["template_repository"].casefold():
            raise ValueError("El repositorio existente proviene de otro template.")
        return {
            "url": existing["html_url"],
            "full_name": existing["full_name"],
            "default_branch": existing["default_branch"],
            "id": existing["id"],
        }

    def wait_for_head(self, record):
        path = self.repo_path(record)
        for attempt in range(7):
            # Template generation may expose repository metadata before its Git refs.
            metadata = self.request("GET", path)
            branch = quote(metadata["default_branch"], safe="")
            reference = self.request(
                "GET", path + "/git/ref/heads/" + branch, initializing=True
            )
            if reference:
                return branch, reference["object"]["sha"]
            if attempt < 6:
                self.wait(min(attempt + 1, 5))
        raise ProviderError(
            "github_default_branch_not_ready_retry_same_execution", retry_after=5
        )

    def publish(self, record, files):
        path = self.repo_path(record)
        _, base_head = self.wait_for_head(record)
        branch = "docs/initial-structure"
        ref_path = path + "/git/ref/heads/" + branch
        reference = self.request("GET", ref_path, missing=True)
        if reference is None:
            self.request(
                "POST",
                path + "/git/refs",
                json={
                    "ref": "refs/heads/" + branch,
                    "sha": base_head,
                },
            )
            reference = self.request("GET", ref_path)
        head = reference["object"]["sha"]
        commit = self.request("GET", path + "/git/commits/" + head)
        # Binary files use Git blob base64; the whole package is one atomic commit.
        tree = self.request(
            "GET", path + "/git/trees/" + commit["tree"]["sha"] + "?recursive=1"
        )
        if tree.get("truncated"):
            raise ProviderError("github_tree_truncated")
        present = {item["path"]: item["sha"] for item in tree["tree"]}
        expected = {
            name: hashlib.sha1(
                b"blob " + str(len(data)).encode() + b"\0" + data
            ).hexdigest()
            for name, data in files.items()
        }
        if all(present.get(name) == digest for name, digest in expected.items()):
            return {"sha": head, "url": record["repository"]["url"] + "/commit/" + head}
        entries = []
        for name, data in files.items():
            if name in present and present[name] != expected[name]:
                original = (
                    self.request(
                        "GET",
                        f"/repos/{record['template_repository']}/contents/{name}",
                        missing=True,
                    )
                    if name == "README.md"
                    else None
                )
                if not original or original["sha"] != present[name]:
                    raise ValueError(
                        "Ya existe un insumo distinto en el destino; conciliar antes de sobrescribir."
                    )
            blob = self.request(
                "POST",
                path + "/git/blobs",
                json={"content": base64.b64encode(data).decode(), "encoding": "base64"},
            )
            entries.append(
                {"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]}
            )
        created_tree = self.request(
            "POST",
            path + "/git/trees",
            json={"base_tree": commit["tree"]["sha"], "tree": entries},
        )
        created = self.request(
            "POST",
            path + "/git/commits",
            json={
                "message": "docs: entregar insumos aprobados\n\n" + self.marker(record),
                "tree": created_tree["sha"],
                "parents": [head],
            },
        )
        # force:false refuses to overwrite a concurrently advanced branch.
        self.request(
            "PATCH",
            path + "/git/refs/heads/" + branch,
            json={"sha": created["sha"], "force": False},
        )
        return {
            "sha": created["sha"],
            "url": record["repository"]["url"] + "/commit/" + created["sha"],
        }

    def merge_initial_structure(self, record):
        path = self.repo_path(record)
        marker = "<!-- " + self.marker(record) + " -->"
        pulls = self.request(
            "GET",
            path + "/pulls",
            params={
                "state": "all",
                "head": record["owner"] + ":docs/initial-structure",
                "base": record["repository"]["default_branch"],
                "per_page": 100,
            },
        )
        if len(pulls) > 1:
            raise ValueError("initial_structure_pr_requires_reconciliation")
        if pulls:
            pull = self.request("GET", path + f"/pulls/{pulls[0]['number']}")
        else:
            pull = self.request(
                "POST",
                path + "/pulls",
                json={
                    "title": "docs: estructura inicial e insumos aprobados",
                    "head": "docs/initial-structure",
                    "base": record["repository"]["default_branch"],
                    "body": "Insumos aprobados y acta de apertura.\n\n" + marker,
                },
            )
        if (
            marker not in (pull.get("body") or "")
            or pull["head"]["sha"] != record["commit"]["sha"]
        ):
            raise ValueError("initial_structure_pr_changed_requires_reconciliation")
        if not pull.get("merged"):
            if pull["state"] != "open":
                raise ValueError("initial_structure_pr_closed_without_merge")
            try:
                self.request(
                    "PUT",
                    path + f"/pulls/{pull['number']}/merge",
                    json={
                        "sha": record["commit"]["sha"],
                        "merge_method": "merge",
                    },
                )
            except ProviderError as exc:
                if str(exc) not in {
                    "github_http_403",
                    "github_http_405",
                    "github_http_409",
                }:
                    raise
            # A lost merge response is reconciled by reading the PR on retry.
            pull = self.request("GET", path + f"/pulls/{pull['number']}")
        return {
            "number": pull["number"],
            "url": pull["html_url"],
            "merged": bool(pull.get("merged")),
            "merge_sha": pull.get("merge_commit_sha") if pull.get("merged") else None,
        }

    def assign_architecture(self, record, issue_body, template):
        path = self.repo_path(record)
        assignee_login = record.get("issue_assignee") or record["architect"]
        marker = "<!-- " + self.marker(record) + " -->"
        matches = []
        page = 1
        while True:
            issues = self.request(
                "GET", path + f"/issues?state=all&per_page=100&page={page}"
            )
            matches.extend(
                i
                for i in issues
                if "pull_request" not in i and marker in (i.get("body") or "")
            )
            if len(issues) < 100:
                break
            page += 1
        if len(matches) > 1:
            raise ValueError(
                "Hay más de un issue para la entrega; requiere conciliación."
            )
        if matches:
            issue = matches[0]
            if issue["body"] != issue_body:
                raise ValueError(
                    "El issue existente cambió; no se sobrescribe su trabajo."
                )
        else:
            # A new repository does not automatically grant the architect access.
            assignee = quote(assignee_login, safe="")
            assigned = self.request(
                "GET", path + "/assignees/" + assignee, missing=True
            )
            if assigned is None:
                self.request(
                    "PUT",
                    path + "/collaborators/" + assignee,
                    json={"permission": "push"},
                )
            issue = self.request(
                "POST",
                path + "/issues",
                json={
                    "title": "[Arquitectura] " + record["title"],
                    "body": issue_body,
                    "assignees": [assignee_login] if assigned is not None else [],
                },
            )
        if assignee_login.casefold() not in {
            a["login"].casefold() for a in issue["assignees"]
        }:
            assignee = quote(assignee_login, safe="")
            if (
                self.request("GET", path + "/assignees/" + assignee, missing=True)
                is not None
            ):
                issue = self.request(
                    "POST",
                    path + f"/issues/{issue['number']}/assignees",
                    json={"assignees": [assignee_login]},
                )
        pending = assignee_login.casefold() not in {
            a["login"].casefold() for a in issue["assignees"]
        }
        return {
            "url": issue["html_url"],
            "number": issue["number"],
            "assignee": None if pending else assignee_login,
            "assignment_pending": pending,
            "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
        }
