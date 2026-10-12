"""Read-only access to the versioned AWS baseline catalog."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


BASELINE_ROOT = Path(__file__).resolve().parents[2] / "catalog" / "baseline-modules"
MODULE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
PROFILE_ROW_PATTERN = re.compile(
    r"^\|\s*`(?P<profile>[a-z0-9_]+)`\s*\|\s*`(?P<class>[^`]+)`\s*\|"
)
MAX_PROFILE_FILE_BYTES = 32_000
MAX_PROFILE_TOTAL_BYTES = 120_000


def list_baseline_modules() -> dict[str, Any]:
    """Return resource baselines, technical profiles, versions, and approval state."""
    modules = []
    for manifest_path in sorted(BASELINE_ROOT.glob("*/module.yaml")):
        module = _load_manifest(manifest_path.parent.name)
        modules.append(_module_summary(module))
    return {
        "catalog": "AWS resource baselines",
        "read_only": True,
        "production_use": "drafts require review and approval before production use",
        "modules": modules,
    }


def get_baseline_module(module_id: str, version: str | None = None) -> dict[str, Any]:
    """Return module metadata and version evidence; does not return executable state."""
    module = _load_manifest(module_id)
    versions = module.get("versions", [])
    selected_version = version or module.get("latest_draft")
    if selected_version not in versions:
        raise ValueError(
            f"Version {selected_version!r} is not cataloged for module {module_id!r}."
        )

    version_dir = _module_dir(module_id) / "versions" / selected_version
    result = {
        **_module_summary(module),
        "selected_version": selected_version,
        "version_status": (
            "approved" if selected_version == module.get("approved_version") else "draft"
        ),
        "profiles_document": _read_text(_module_dir(module_id) / "PROFILES.md"),
        "version_readme": _read_optional_text(version_dir / "README.md"),
        "audit_record": _read_optional_yaml(version_dir / "audit-record.yaml"),
        "production_use": (
            "Do not treat a draft snapshot as production-approved. Obtain the required "
            "engineering, security, cost, and operational review first."
        ),
    }
    return result


def get_baseline_profile(module_id: str, profile_id: str) -> dict[str, Any]:
    """Return a named profile's pinned module and Terraform inputs for review."""
    module = _load_manifest(module_id)
    if not PROFILE_ID_PATTERN.fullmatch(profile_id):
        raise ValueError("Invalid profile id.")

    profile_dir = _module_dir(module_id) / "examples" / "profiles" / profile_id
    if not profile_dir.is_dir():
        raise ValueError(f"Profile {profile_id!r} is not cataloged for {module_id!r}.")

    profile_class = _profile_class(module_id, profile_id)
    files: dict[str, str] = {}
    total_bytes = 0
    for path in sorted(profile_dir.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name != "README.md" and path.suffix not in {".tf", ".example"}:
            continue
        size = path.stat().st_size
        if size > MAX_PROFILE_FILE_BYTES or total_bytes + size > MAX_PROFILE_TOTAL_BYTES:
            raise ValueError("Profile contents exceed the MCP response size limit.")
        files[path.name] = path.read_text(encoding="utf-8")
        total_bytes += size

    return {
        "module_id": module_id,
        "module_purpose": module["purpose"],
        "profile_id": profile_id,
        "profile_class": profile_class,
        "pinned_module_version": _pinned_version(profile_dir),
        "approval_status": (
            "approved"
            if _pinned_version(profile_dir) == module.get("approved_version")
            else "draft"
        ),
        "read_only": True,
        "can_apply": False,
        "files": files,
        "usage_gate": (
            "Example only. Review workload, quotas, security, recovery, cost, remote state, "
            "and the Terraform plan; this MCP never runs terraform apply."
        ),
    }


def _module_dir(module_id: str) -> Path:
    if not MODULE_ID_PATTERN.fullmatch(module_id):
        raise ValueError("Invalid module id.")
    module_dir = BASELINE_ROOT / module_id
    if not module_dir.is_dir() or module_dir.is_symlink():
        raise ValueError(f"Unknown baseline module {module_id!r}.")
    return module_dir


def _load_manifest(module_id: str) -> dict[str, Any]:
    manifest_path = _module_dir(module_id) / "module.yaml"
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if data.get("module_id") != module_id:
        raise ValueError(f"Manifest id does not match directory {module_id!r}.")
    return data


def _module_summary(module: dict[str, Any]) -> dict[str, Any]:
    module_id = module["module_id"]
    profile_rows = []
    profile_doc = _module_dir(module_id) / "PROFILES.md"
    for line in profile_doc.read_text(encoding="utf-8").splitlines():
        match = PROFILE_ROW_PATTERN.match(line)
        if match:
            profile_rows.append(
                {"profile_id": match.group("profile"), "class": match.group("class").strip()}
            )
    approved_version = module.get("approved_version")
    return {
        "module_id": module_id,
        "purpose": module.get("purpose", ""),
        "latest_draft": module.get("latest_draft"),
        "approved_version": approved_version,
        "versions": module.get("versions", []),
        "status": "approved" if approved_version else "draft",
        "profiles": profile_rows,
    }


def _profile_class(module_id: str, profile_id: str) -> str | None:
    path = _module_dir(module_id) / "PROFILES.md"
    for line in path.read_text(encoding="utf-8").splitlines():
        match = PROFILE_ROW_PATTERN.match(line)
        if match and match.group("profile") == profile_id:
            return match.group("class").strip()
    return None


def _pinned_version(profile_dir: Path) -> str | None:
    source = (profile_dir / "main.tf").read_text(encoding="utf-8")
    match = re.search(r'source\s*=\s*"(?:\.\./)+versions/([^"/]+)"', source)
    return match.group(1) if match else None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _read_optional_yaml(path: Path) -> dict[str, Any] | None:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
