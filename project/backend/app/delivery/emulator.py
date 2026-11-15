"""Opt-in integration checks for the pinned S3 baseline in an isolated emulator."""

import argparse
import json
import os
import ssl
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from urllib.error import URLError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener
from uuid import uuid4

from app.delivery.models import DemoRequest
from app.delivery.terraform import terraform_files

OVERRIDE = """provider "aws" {
  s3_use_path_style           = true
  skip_requesting_account_id  = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
}

module "documents" {
  kms_key_arn = aws_kms_key.test.arn
}
"""

KEY_RESOURCE = """resource "aws_kms_key" "test" {
  description = "Ephemeral PSWE-07 integration key"
}
"""


def execute(command, cwd, env):
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"{' '.join(command[:2])}: código {result.returncode}")
    return result.stdout.strip()


def require_policy(plan):
    changes = {
        change["type"]: change["change"]["after"]
        for change in plan["resource_changes"]
        if change.get("module_address") == "module.documents"
    }
    public = changes.get("aws_s3_bucket_public_access_block", {})
    encryption = changes.get("aws_s3_bucket_server_side_encryption_configuration", {})
    tags = changes.get("aws_s3_bucket", {}).get("tags") or {}
    rules = encryption.get("rule") or []
    defaults = (
        rules[0].get("apply_server_side_encryption_by_default", []) if rules else []
    )
    if (
        not all(
            public.get(key) is True
            for key in (
                "block_public_acls",
                "block_public_policy",
                "ignore_public_acls",
                "restrict_public_buckets",
            )
        )
        or not defaults
        or defaults[0].get("sse_algorithm") != "aws:kms"
        or not all(
            tags.get(key) for key in ("Project", "Environment", "Owner", "CostCenter")
        )
    ):
        raise ValueError(
            "El plan debe bloquear acceso público, usar AWS KMS y definir las cuatro etiquetas"
        )


def run(request, image, output):
    started = datetime.now(UTC)
    checks = []
    versions = {}
    resources = []
    run_url = (
        os.getenv("GITHUB_SERVER_URL", "") + "/" + os.getenv("GITHUB_REPOSITORY", "")
    )
    run_id = os.getenv("GITHUB_RUN_ID")
    container = "pswe07-" + uuid4().hex
    container_started = False
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    def check(name, action, category):
        try:
            value = action()
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            print(f"{name}: {error}", flush=True)
            checks.append({"name": name, "status": "failed", "category": category})
            return False, None
        print(f"{name}: correcto", flush=True)
        checks.append({"name": name, "status": "passed", "category": category})
        return True, value

    with TemporaryDirectory(prefix="pswe07-terraform-") as temp:
        work = Path(temp)
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith(("AWS_", "TF_"))
        }
        env.update(
            TF_IN_AUTOMATION="true",
            TF_INPUT="false",
            TF_CLI_CONFIG_FILE=str(work / "terraform.rc"),
        )
        (work / "terraform.rc").touch()
        for name, content in terraform_files(request).items():
            (work / name).write_bytes(content)
        (work / "emulator_override.tf").write_text(OVERRIDE, encoding="utf-8")
        (work / "emulator_kms.tf").write_text(KEY_RESOURCE, encoding="utf-8")
        (work / "terraform.tfvars").write_bytes(
            (work / "terraform.tfvars.example").read_bytes()
        )

        def docker(*args):
            return execute(["docker", *args], work, env)

        def terraform(*args):
            return execute(["terraform", *args], work, env)

        def start_emulator():
            nonlocal container_started
            docker(
                "run",
                "-d",
                "--name",
                container,
                "--memory=2g",
                "--memory-swap=2g",
                "-p",
                "127.0.0.1::9297",
                image,
            )
            container_started = True
            endpoint = "https://" + docker("port", container, "9297/tcp")
            prefix = f"{container}:/home/emulator/.aws/emulator/9297"
            for _ in range(30):
                try:
                    for name in ("ca.pem", "emulator_credentials"):
                        docker("cp", f"{prefix}/{name}", str(work / name))
                    client = build_opener(
                        ProxyHandler({}),
                        HTTPSHandler(
                            context=ssl.create_default_context(
                                cafile=str(work / "ca.pem")
                            )
                        ),
                    )
                    with client.open(
                        endpoint + "/__admin/health", timeout=2
                    ) as response:
                        if response.read().strip() == b"ok":
                            break
                except (RuntimeError, OSError, URLError):
                    pass
                sleep(1)
            else:
                raise RuntimeError("El endpoint TLS local no respondió")
            (work / "aws-config").touch()
            env.update(
                AWS_ENDPOINT_URL=endpoint,
                AWS_ENDPOINT_URL_S3=endpoint,
                AWS_ENDPOINT_URL_KMS=endpoint,
                AWS_ENDPOINT_URL_STS=endpoint,
                AWS_SHARED_CREDENTIALS_FILE=str(work / "emulator_credentials"),
                AWS_CONFIG_FILE=str(work / "aws-config"),
                AWS_CA_BUNDLE=str(work / "ca.pem"),
                AWS_EC2_METADATA_DISABLED="true",
                AWS_DISABLE_HOST_PREFIX_INJECTION="true",
                NO_PROXY="127.0.0.1,localhost",
            )
            versions["aws_emulator"] = docker(
                "exec", container, "aws-emulator", "--version"
            )

        def plan():
            terraform("plan", "-no-color", "-out=integration.tfplan")
            return json.loads(terraform("show", "-json", "integration.tfplan"))

        def scan():
            manifest = json.loads(
                (work / ".terraform/modules/modules.json").read_text(encoding="utf-8")
            )
            module = next(
                item for item in manifest["Modules"] if item["Key"] == "documents"
            )
            result = execute(
                [
                    "trivy",
                    "config",
                    "--severity",
                    "HIGH,CRITICAL",
                    "--exit-code",
                    "1",
                    module["Dir"],
                ],
                work,
                env,
            )
            versions["trivy"] = execute(["trivy", "--version"], work, env).splitlines()[
                0
            ]
            print(result)

        def verify():
            if (
                terraform("output", "-raw", "bucket_id")
                != request.architecture.bucket_name
            ):
                raise ValueError("El identificador del bucket difiere del esperado")
            terraform("plan", "-no-color", "-detailed-exitcode")

        try:
            formatted, _ = check(
                "terraform fmt",
                lambda: (terraform("fmt"), terraform("fmt", "-check")),
                "terraform",
            )
            initialized, _ = (
                check(
                    "terraform init",
                    lambda: terraform("init", "-no-color"),
                    "terraform",
                )
                if formatted
                else (False, None)
            )
            if initialized:
                versions.update(json.loads(terraform("version", "-json")))
                validated, _ = check(
                    "terraform validate",
                    lambda: terraform("validate", "-no-color"),
                    "terraform",
                )
                check("Trivy", scan, "security")
                ready, _ = check("AWS Emulator TLS", start_emulator, "emulator")
                if ready and validated:
                    planned, planned_values = check(
                        "terraform plan", plan, "integration"
                    )
                    if planned:
                        resources = sorted(
                            change["address"]
                            for change in planned_values["resource_changes"]
                        )
                        allowed, _ = check(
                            "Políticas del plan",
                            lambda: require_policy(planned_values),
                            "policy",
                        )
                        if allowed:
                            try:
                                applied, _ = check(
                                    "terraform apply",
                                    lambda: terraform(
                                        "apply", "-no-color", "integration.tfplan"
                                    ),
                                    "integration",
                                )
                                if applied:
                                    check(
                                        "Verificación después de apply",
                                        verify,
                                        "integration",
                                    )
                            finally:
                                check(
                                    "terraform destroy",
                                    lambda: terraform(
                                        "destroy", "-no-color", "-auto-approve"
                                    ),
                                    "integration",
                                )
        finally:
            if container_started:
                check(
                    "Eliminar contenedor",
                    lambda: docker("rm", "-f", container),
                    "cleanup",
                )
            names = (
                ("terraform fmt", "terraform"),
                ("terraform init", "terraform"),
                ("terraform validate", "terraform"),
                ("Trivy", "security"),
                ("AWS Emulator TLS", "emulator"),
                ("terraform plan", "integration"),
                ("Políticas del plan", "policy"),
                ("terraform apply", "integration"),
                ("Verificación después de apply", "integration"),
                ("terraform destroy", "integration"),
                ("Eliminar contenedor", "cleanup"),
            )
            existing = {item["name"]: item for item in checks}
            checks = [
                existing.get(
                    name, {"name": name, "status": "not_run", "category": category}
                )
                for name, category in names
            ]
            evidence = {
                "schema_version": "1.0",
                "scope": "aws-emulator-s3-demo",
                "baseline_commit": request.architecture.baseline.commit,
                "bucket_name": request.architecture.bucket_name,
                "region": request.architecture.region,
                "started_at": started.isoformat(),
                "ended_at": datetime.now(UTC).isoformat(),
                "versions": versions,
                "resources": resources,
                "checks": checks,
                "run_url": f"{run_url}/actions/runs/{run_id}" if run_id else None,
            }
            output.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return all(item["status"] == "passed" for item in checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("fixtures/delivery-1.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("../generated/emulator/evidence.json")
    )
    parser.add_argument("--image", default="pswe07-aws-emulator")
    args = parser.parse_args()
    request = DemoRequest.model_validate_json(args.input.read_bytes())
    raise SystemExit(0 if run(request, args.image, args.output) else 1)


if __name__ == "__main__":
    main()
