"""GitHub lifecycle for an existing tested commit, without running infrastructure."""

import base64
import re
from hashlib import sha256
from urllib.parse import quote

from app.integrations.project_github import ProjectGitHub
from app.persistence.delivery import DeliveryConflict


class EngineeringGitHub(ProjectGitHub):
    def pages(self, path, *, key=None, params=None):
        result, page = [], 1
        while True:
            value = self.request(
                "GET", path, params={**(params or {}), "per_page": 100, "page": page}
            )
            items = value[key] if key else value
            result.extend(items)
            if len(items) < 100:
                return result
            page += 1

    def tree(self, repository, commit):
        value = self.request(
            "GET", f"/repos/{repository}/git/trees/{commit}", params={"recursive": "1"}
        )
        if value.get("truncated"):
            raise DeliveryConflict(
                "El árbol remoto está truncado; requiere conciliación"
            )
        return {item["path"]: item for item in value["tree"]}

    def verify_files(self, repository, commit, files):
        tree = self.tree(repository, commit)
        for file in files:
            entry = tree.get(file["path"])
            if (
                not entry
                or entry["type"] != "blob"
                or entry["mode"] not in ("100644", "100755")
            ):
                raise DeliveryConflict(
                    "Falta un archivo regular de implementación en el commit remoto"
                )
            blob = self.request("GET", f"/repos/{repository}/git/blobs/{entry['sha']}")
            if (
                blob.get("encoding") != "base64"
                or sha256(base64.b64decode(blob["content"])).hexdigest()
                != file["sha256"]
            ):
                raise DeliveryConflict(
                    "El código remoto no coincide con los bytes probados"
                )

    def approval(self, repository, number, architect, commit):
        reviews = self.pages(f"/repos/{repository}/pulls/{number}/reviews")
        decisive = [
            r
            for r in reviews
            if r["user"]["login"].casefold() == architect.casefold()
            and r["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}
        ]
        review = decisive[-1] if decisive else None
        if not review or review["state"] != "APPROVED" or review["commit_id"] != commit:
            raise DeliveryConflict(
                "Falta la aprobación vigente del arquitecto sobre el commit exacto"
            )
        return review

    def protection(self, repository):
        value = self.request(
            "GET", f"/repos/{repository}/branches/main/protection", missing=True
        )
        reviews = (value or {}).get("required_pull_request_reviews") or {}
        checks = (value or {}).get("required_status_checks") or {}
        if (
            not value
            or not value.get("enforce_admins", {}).get("enabled")
            or reviews.get("required_approving_review_count", 0) < 1
            or not reviews.get("dismiss_stale_reviews")
            or not checks.get("strict")
            or not (checks.get("contexts") or checks.get("checks"))
            or value.get("allow_force_pushes", {}).get("enabled")
        ):
            raise DeliveryConflict(
                "main requiere protección con revisión, invalidación de aprobaciones antiguas, checks estrictos y aplicación a administradores"
            )
        return value

    def verify_baselines(self, modules):
        receipts = []
        for module in modules:
            match = re.fullmatch(
                r"https://github\.com/([^/]+/[^/]+)/pull/([1-9][0-9]*)(?:#pullrequestreview-[0-9]+)?",
                module["approval_reference"],
            )
            if not match or match[1] != module["repository"]:
                raise DeliveryConflict(
                    "El baseline debe referenciar su PR de aprobación en GitHub"
                )
            pull = self.request("GET", f"/repos/{match[1]}/pulls/{match[2]}")
            if not pull.get("merged") or module["commit"] not in {
                pull["head"]["sha"],
                pull["merge_commit_sha"],
            }:
                raise DeliveryConflict(
                    "El baseline fijado no corresponde al PR aprobado e integrado"
                )
            review = self.approval(
                match[1], match[2], module["approved_by"], pull["head"]["sha"]
            )
            pinned = self.tree(match[1], module["commit"]).get(module["path"])
            reviewed = self.tree(match[1], pull["head"]["sha"]).get(module["path"])
            if (
                not pinned
                or not reviewed
                or pinned["type"] != "tree"
                or pinned["sha"] != reviewed["sha"]
            ):
                raise DeliveryConflict(
                    "El módulo fijado no coincide con el módulo revisado"
                )
            receipts.append(
                {"module": module, "verification_reference": review["html_url"]}
            )
        return receipts

    def publish(self, repository, request, evidence, inputs):
        prefix = f"/repos/{repository}"
        commit = evidence["implementation_commit"]
        marker = f"<!-- engineering:{request['intake_id']}:{commit} -->"
        ref = self.request(
            "GET",
            prefix + "/git/ref/heads/" + quote(request["branch"], safe="/"),
            missing=True,
        )
        if ref is None:
            self.request(
                "POST",
                prefix + "/git/refs",
                json={"ref": "refs/heads/" + request["branch"], "sha": commit},
            )
        elif ref["object"]["sha"] != commit:
            raise DeliveryConflict(
                "La rama remota contiene otro commit; no se sobrescribe"
            )
        pulls = self.pages(
            prefix + "/pulls",
            params={
                "state": "all",
                "head": repository.split("/")[0] + ":" + request["branch"],
                "base": "main",
            },
        )
        if len(pulls) > 1:
            raise DeliveryConflict(
                "Hay varios PRs para la rama; conciliar antes de continuar"
            )
        if pulls:
            pull = self.request("GET", prefix + f"/pulls/{pulls[0]['number']}")
        else:
            files = "\n".join(
                f"- {f['role']}: {f['reference']} (SHA-256 {f['sha256']})"
                for f in [
                    *inputs["architecture"]["files"],
                    *inputs["finops"]["files"],
                    *evidence["files"],
                ]
            )
            pull = self.request(
                "POST",
                prefix + "/pulls",
                json={
                    "title": "feat: entrega de ingeniería validada localmente",
                    "head": request["branch"],
                    "base": "main",
                    "body": f"Implementación probada: {commit}.\n\nInsumos aprobados y evidencias:\n{files}\n\nCorrida local: {evidence['run_reference']}.\nRequiere CI y aprobación del arquitecto sobre este commit.\n\n{marker}",
                },
            )
        if (
            marker not in (pull.get("body") or "")
            or pull["head"]["sha"] != commit
            or pull["head"]["repo"]["full_name"].casefold() != repository.casefold()
            or pull["base"]["ref"] != "main"
        ):
            raise DeliveryConflict("El PR remoto cambió o pertenece a otra entrega")
        if not pull.get("merged"):
            if pull["state"] != "open":
                raise DeliveryConflict("El PR se cerró sin integración")
            reviewer = inputs["architecture"]["approval"]["actor"]
            try:
                self.approval(repository, pull["number"], reviewer, commit)
            except DeliveryConflict:
                requested = {
                    r["login"].casefold() for r in pull.get("requested_reviewers", [])
                }
                if reviewer.casefold() not in requested:
                    self.request(
                        "POST",
                        prefix + f"/pulls/{pull['number']}/requested_reviewers",
                        json={"reviewers": [reviewer]},
                    )
        return {
            "number": pull["number"],
            "url": pull["html_url"],
            "head": commit,
            "marker": marker,
        }

    def verify_ci(self, repository, evidence):
        match = re.fullmatch(
            re.escape(f"https://github.com/{repository}/actions/runs/")
            + r"([1-9][0-9]*)",
            evidence["run_reference"],
        )
        if not match:
            raise DeliveryConflict(
                "La corrida CI no referencia GitHub Actions del proyecto"
            )
        run = self.request("GET", f"/repos/{repository}/actions/runs/{match[1]}")
        if (
            run["head_sha"] != evidence["implementation_commit"]
            or run["status"] != "completed"
            or run["conclusion"] != "success"
            or run["repository"]["full_name"].casefold() != repository.casefold()
        ):
            raise DeliveryConflict(
                "GitHub Actions no acredita una ejecución exitosa del commit probado"
            )
        protection = self.protection(repository)
        required = protection["required_status_checks"]
        checks = self.pages(
            f"/repos/{repository}/commits/{run['head_sha']}/check-runs",
            key="check_runs",
        )
        statuses = self.pages(f"/repos/{repository}/commits/{run['head_sha']}/statuses")
        requirements = required.get("checks") or [
            {"context": n, "app_id": None} for n in required.get("contexts", [])
        ]
        for need in requirements:
            candidates = [
                c
                for c in checks
                if c["name"] == need["context"]
                and (
                    need.get("app_id") in (None, -1) or c["app"]["id"] == need["app_id"]
                )
            ]
            latest = max(candidates, key=lambda c: c["id"], default=None)
            status = next(
                (s for s in statuses if s["context"] == need["context"]), None
            )
            if not (
                latest
                and latest["status"] == "completed"
                and latest["conclusion"] == "success"
            ) and not (
                need.get("app_id") in (None, -1)
                and not latest
                and status
                and status["state"] == "success"
            ):
                raise DeliveryConflict(
                    "Faltan comprobaciones obligatorias exitosas sobre el commit exacto"
                )
        return {
            "id": run["id"],
            "head_sha": run["head_sha"],
            "conclusion": run["conclusion"],
            "url": run["html_url"],
        }

    def verify_change_scope(self, repository, pull, evidence):
        files = self.pages(f"/repos/{repository}/pulls/{pull['number']}/files")
        expected = {
            f["path"] for f in evidence["files"] if f["role"] == "implementation"
        }
        if len(files) != pull["changed_files"] or any(
            f["filename"] not in expected or f["status"] == "removed" for f in files
        ):
            raise DeliveryConflict(
                "El PR contiene cambios sin respaldo en el manifiesto probado"
            )

    def integrate(self, repository, publication, evidence, architect):
        path = f"/repos/{repository}/pulls/{publication['number']}"
        pull = self.request("GET", path)
        if (
            pull["head"]["sha"] != publication["head"]
            or pull["base"]["ref"] != "main"
            or pull["head"]["repo"]["full_name"].casefold() != repository.casefold()
            or publication["marker"] not in (pull.get("body") or "")
        ):
            raise DeliveryConflict("El PR cambió desde la publicación")
        review = self.approval(
            repository, publication["number"], architect, publication["head"]
        )
        self.verify_change_scope(repository, pull, evidence)
        if not pull.get("merged"):
            if pull["state"] != "open" or pull.get("draft"):
                raise DeliveryConflict("El PR no está abierto para integración")
            if not pull.get("merge_commit_sha"):
                raise DeliveryConflict(
                    "GitHub todavía no calculó el merge; reintentar tras sus comprobaciones"
                )
            self.verify_files(
                repository,
                pull["merge_commit_sha"],
                [f for f in evidence["files"] if f["role"] == "implementation"],
            )
            result = self.request(
                "PUT",
                path + "/merge",
                json={"sha": publication["head"], "merge_method": "merge"},
            )
            if not result.get("merged"):
                raise DeliveryConflict("GitHub no confirmó la integración del PR")
            pull = self.request("GET", path)
        if not pull.get("merged"):
            raise DeliveryConflict("La integración requiere conciliación")
        self.verify_files(
            repository,
            pull["merge_commit_sha"],
            [f for f in evidence["files"] if f["role"] == "implementation"],
        )
        return {
            "merge_commit": pull["merge_commit_sha"],
            "review_reference": review["html_url"],
            "review_commit": review["commit_id"],
        }
