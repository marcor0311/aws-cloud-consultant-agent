"""Move legacy local credentials outside Git, with private backups and offline checks."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project"
AGENT = PROJECT / "agents/1. calendar assistant"
FILES = {
    "GOOGLE_OAUTH_CLIENT_FILE": (AGENT, "google/oauth-client.json"),
    "GOOGLE_OAUTH_TOKEN_FILE": (AGENT, "google/calendar-token.json"),
    "CALENDAR_GMAIL_CLIENT_FILE": (PROJECT, "google/oauth-client.json"),
    "CALENDAR_GMAIL_TOKEN_FILE": (PROJECT, "google/gmail-token.json"),
    "WORKFLOW_GOOGLE_CLIENT_FILE": (PROJECT, "google/oauth-client.json"),
    "WORKFLOW_GOOGLE_TOKEN_FILE": (PROJECT, "google/workflow-token.json"),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def env_bytes(values):
    # dotenv supports quoted multiline values; ensure round-trip equality before writing.
    content = "".join(
        key
        + ("=" + json.dumps(value, ensure_ascii=False) if value is not None else "")
        + "\n"
        for key, value in values.items()
    )
    from io import StringIO

    if dict(dotenv_values(stream=StringIO(content), interpolate=False)) != values:
        raise ValueError("No se pudo conservar exactamente la configuración.")
    return content.encode()


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Destino simbólico no permitido.")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("El destino ya tiene otro contenido; no se sobrescribe.")
        path.chmod(0o600)
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)


def replace_env(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verify_loaders(destination, secret_keys):
    clean = {key: value for key, value in os.environ.items() if key not in secret_keys}
    clean.pop("CALENDAR_ASSISTANT_MODE", None)
    clean["CLOUD_CONSULTANT_SECRETS_DIR"] = str(destination)
    backend = """
import os
from dotenv import dotenv_values
from app.core.config import load_environment, secrets_directory, SECRET_FILES
load_environment()
private = dotenv_values(secrets_directory() / 'secrets.env', interpolate=False)
assert all(os.environ.get(k) == v for k,v in private.items() if v is not None)
assert all(os.path.isabs(os.environ[k]) for k in SECRET_FILES)
"""
    agent = """
import os
from dotenv import dotenv_values
from src.config import load_environment, secrets_directory, AGENT_KEYS
load_environment()
private = dotenv_values(secrets_directory() / 'secrets.env', interpolate=False)
allowed = lambda k: k in AGENT_KEYS or k.startswith('LIVEKIT_')
assert all(os.environ.get(k) == v for k,v in private.items() if v is not None and allowed(k))
assert all(k not in os.environ for k in private if not allowed(k))
assert os.path.isabs(os.environ['GOOGLE_OAUTH_TOKEN_FILE'])
"""
    for cwd, code in ((PROJECT / "backend", backend), (AGENT, agent)):
        subprocess.run([sys.executable, "-c", code], cwd=cwd, env=clean, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path.home() / ".config/aws-cloud-consultant-agent/dev",
    )
    args = parser.parse_args()
    destination = args.destination.expanduser()
    if not destination.is_absolute() or destination.resolve().is_relative_to(ROOT):
        raise ValueError(
            "El directorio privado debe ser absoluto y estar fuera del repo."
        )
    for path in (destination, *destination.parents):
        if path.is_symlink():
            raise ValueError("La ruta privada no puede contener enlaces simbólicos.")
    env_path = PROJECT / ".env"
    if env_path.is_symlink():
        raise ValueError("La configuración no puede ser un enlace simbólico.")
    local = dict(dotenv_values(env_path, interpolate=False))
    if local.get("CLOUD_CONSULTANT_SECRETS_DIR"):
        print("La configuración ya usa un directorio externo; no se vuelve a migrar.")
        return
    if any("${" in value for value in local.values() if value):
        raise ValueError(
            "Resolver primero las referencias ${...} de la configuración local."
        )
    defaults = {
        AGENT / "secrets/google_oauth_client.json": "google/oauth-client.json",
        AGENT / "secrets/google_calendar_token.json": "google/calendar-token.json",
        PROJECT / "secrets/gmail_token.json": "google/gmail-token.json",
        PROJECT / "secrets/workflow_google_token.json": "google/workflow-token.json",
    }
    migrations = {}
    configured_sources = {}
    for key, (base, target) in FILES.items():
        value = local.get(key)
        if value:
            source = Path(value).expanduser()
            source = source if source.is_absolute() else base / source
            if source.is_file():
                migrations.setdefault(
                    source, destination / defaults.get(source, target)
                )
                configured_sources[key] = source
    for folder in (PROJECT / "secrets", AGENT / "secrets", PROJECT / "backend/secrets"):
        for source in folder.rglob("*") if folder.exists() else ():
            if source.is_symlink():
                raise ValueError("Origen simbólico no permitido.")
            if not source.is_file() or source.name == ".gitkeep":
                continue
            target = defaults.get(source)
            if not target:
                relative = (
                    source.relative_to(PROJECT / "secrets")
                    if source.is_relative_to(PROJECT / "secrets")
                    else None
                )
                if (
                    relative
                    and relative.parts[0] == "meeting-assistant"
                    and source.name in {"registration.json", "session.json"}
                ):
                    target = "chatgpt/meeting-assistant/" + source.name
                elif relative and relative.parts[0] == "chatgpt-plan-demo":
                    target = "chatgpt/plan-demo/" + "/".join(relative.parts[1:])
                else:
                    target = "backups/legacy/" + str(source.relative_to(ROOT))
            migrations.setdefault(source, destination / target)
    private, public = {}, {}
    for key, value in local.items():
        if key in FILES:
            continue
        sensitive = (
            key.endswith("_KEY")
            or any(
                word in key
                for word in (
                    "SECRET",
                    "PASSWORD",
                    "TOKEN",
                    "API_KEY",
                    "DATABASE_URL",
                    "CHECKPOINT_URL",
                )
            )
            or key
            in {
                "GOOGLE_ACCOUNT_EMAIL",
                "LIVEKIT_URL",
                "CALENDAR_SMTP_USERNAME",
                "CALENDAR_SMTP_FROM",
            }
        )
        (private if sensitive else public)[key] = value
    public["CLOUD_CONSULTANT_SECRETS_DIR"] = str(destination)
    public.update({key: value[1] for key, value in FILES.items()})
    # Preserve aliases: Calendar and workflow may deliberately use the same token.
    for key, source in configured_sources.items():
        public[key] = str(migrations[source].relative_to(destination))
    for source, relative in defaults.items():
        if source.is_file():
            for key, (_, target) in FILES.items():
                if key not in configured_sources and target == relative:
                    public[key] = str(migrations[source].relative_to(destination))
    payloads = {destination / "secrets.env": env_bytes(private)}
    snapshots = {}
    for source, target in migrations.items():
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise ValueError("Solo se migran archivos regulares del repositorio.")
        data = source.read_bytes()
        if target in payloads and payloads[target] != data:
            raise ValueError(
                "Dos credenciales distintas usan el mismo destino; conciliar primero."
            )
        payloads[target] = data
        snapshots[source] = data
    for path, data in payloads.items():
        if path.is_symlink() or (path.exists() and path.read_bytes() != data):
            raise ValueError(
                "El directorio destino contiene otro secreto; no se sobrescribe."
            )
    print(
        f"Plan: {len(snapshots)} archivos privados y {len(private)} variables → {destination}"
    )
    if not args.apply:
        print("Revisado sin cambios. Detener componentes y ejecutar con --apply.")
        return
    backup = destination / "backups" / str(time.time_ns())
    old_env = env_path.read_bytes()
    private_write(backup / "project.env", old_env)
    for source, data in snapshots.items():
        private_write(backup / "files" / source.relative_to(ROOT), data)
    for path, data in payloads.items():
        private_write(path, data)
        if digest(path.read_bytes()) != digest(data):
            raise ValueError("Falló la verificación de integridad.")
    for directory in (destination, *[p for p in destination.rglob("*") if p.is_dir()]):
        directory.chmod(0o700)
    replace_env(env_path, env_bytes(public))
    try:
        verify_loaders(destination, set(private))
        for key, source in configured_sources.items():
            if digest((destination / public[key]).read_bytes()) != digest(
                snapshots[source]
            ):
                raise ValueError("Una ruta configurada perdió su credencial original.")
        for source, relative in defaults.items():
            if source in snapshots and digest(
                (destination / relative).read_bytes()
            ) != digest(snapshots[source]):
                raise ValueError(
                    "Falta una credencial predeterminada después de migrar."
                )
        if any(source.read_bytes() != data for source, data in snapshots.items()):
            raise ValueError(
                "Un archivo cambió durante la migración; detener componentes."
            )
    except Exception:
        replace_env(env_path, old_env)
        raise
    private_write(
        backup / "manifest.json",
        json.dumps(
            {
                str(source.relative_to(ROOT)): {
                    "destination": str(migrations[source]),
                    "sha256": digest(data),
                }
                for source, data in snapshots.items()
            },
            indent=2,
        ).encode(),
    )
    for source in snapshots:
        source.unlink()
    print(f"Migración verificada. Respaldo privado: {backup}")
    print("Reiniciar los componentes abiertos. No se hicieron llamadas a proveedores.")


if __name__ == "__main__":
    main()
