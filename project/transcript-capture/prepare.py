"""Build a private local extension from pinned TranscripTonic MIT source."""

import argparse
import hashlib
import io
import json
import os
import secrets
import shutil
import urllib.request
import zipfile
from pathlib import Path

from dotenv import dotenv_values, set_key

COMMIT = "1e38252610b2d6ab2347e3a15a5d1d1da325505c"
ARCHIVE_SHA256 = "926bf79f459f49380e10fa1fbe4dcc9e87f8c62ca901d988647c56d6f738ab67"
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TARGET = ROOT / "project/generated/transcriptonic"
CACHE = ROOT / "project/generated" / f"transcriptonic-{COMMIT}.zip"
URL = "http://127.0.0.1:8000/api/workflow/events/transcript"


def replace(path, before, after):
    content = path.read_text()
    if content.count(before) != 1:
        raise ValueError(f"La versión fijada cambió: {path.name}")
    path.write_text(content.replace(before, after))


def build(archive, token, destination):
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Checksum de TranscripTonic inválido.")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        prefix = f"transcriptonic-{COMMIT}/"
        wanted = [
            "LICENSE",
            "extension/icon.png",
            "extension/content-scripts/common-config.js",
            "extension/content-scripts/common-utils.js",
        ]
        wanted += [
            f"extension/content-scripts/google-meet/{name}.js"
            for name in ("config", "utils", "index")
        ]
        for name in wanted:
            target = destination / name.removeprefix("extension/")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_bytes(source.read(prefix + name))
    common = destination / "content-scripts/common-utils.js"
    replace(
        common,
        "meetingSoftware: meetingSoftware,",
        "captureId: crypto.randomUUID(),\n        meetingUrl: location.origin + location.pathname,\n        captureClosed: false,\n        meetingSoftware: meetingSoftware,",
    )
    replace(
        common,
        "const objectToSave = {}",
        """const objectToSave = {
        captureId: state.captureId, meetingUrl: state.meetingUrl,
        reporterName: state.userName, captureClosed: sendDownloadMessage === true
    }""",
    )
    content = common.read_text()
    start, end = (
        content.index("function checkExtensionStatus(state) {"),
        content.index("\n/**\n * @description Overwrite state"),
    )
    common.write_text(
        content[:start]
        + "function checkExtensionStatus(state) { return Promise.resolve(); }\n"
        + content[end:]
    )
    replace(
        common,
        "function logError(state, code, err) {",
        "function logError(state, code, err) { return; // No remote telemetry in the local integration.\n",
    )
    replace(
        common,
        "function renderFab() {",
        "function renderFab() { return; // Use the extension popup.\n",
    )
    replace(
        common,
        'state.stateTranscriptBlock.personName === "You"',
        "/^(you|tú|tu|usted)$/i.test(state.stateTranscriptBlock.personName.trim())",
    )
    index = destination / "content-scripts/google-meet/index.js"
    replace(
        index,
        "initGoogleMeet()\n",
        """let captureRouteWatcher;
let captureInitializationStarted = false;
function startCaptureOnMeetingRoute() {
    if (captureInitializationStarted || !/^\\/(?:meet\\/)?[a-z]{3}-[a-z]{4}-[a-z]{3}$/.test(location.pathname)) return;
    captureInitializationStarted = true;
    clearInterval(captureRouteWatcher);
    chrome.runtime.sendMessage({type: "consulting_preflight"}, result => {
        if (result?.success) initGoogleMeet();
        else console.warn("Ya existe una captura activa; cerrá esa pestaña antes de iniciar otra.");
    });
}
captureRouteWatcher = setInterval(startCaptureOnMeetingRoute, 500);
startCaptureOnMeetingRoute();
""",
    )
    content = index.read_text()
    start, end = (
        content.index("        // REGISTER CHAT MESSAGES LISTENER"),
        content.index("        //*********** MEETING END ROUTINES"),
    )
    index.write_text(content[:start] + content[end:])
    utils = destination / "content-scripts/google-meet/utils.js"
    replace(
        utils,
        "function showNotificationGoogleMeet(extensionStatusJSON) {",
        "function showNotificationGoogleMeet(extensionStatusJSON) { return; // Status lives in the popup.\n",
    )
    config = destination / "content-scripts/common-config.js"
    replace(
        config,
        'const LOGO_URL = "https://ejnana.github.io/transcripto-status/icon.png"',
        'const LOGO_URL = ""',
    )
    for name in ("background.mjs", "popup.html", "popup.mjs"):
        shutil.copyfile(HERE / name, destination / name)
    manifest = {
        "manifest_version": 3,
        "name": "Consultoría — captura de Meet (TranscripTonic)",
        "version": "1.0.1",
        "description": "Captura local de subtítulos para el backend de desarrollo.",
        "permissions": ["storage", "alarms", "downloads"],
        "host_permissions": ["http://127.0.0.1/*"],
        "background": {"service_worker": "background.mjs", "type": "module"},
        "action": {"default_popup": "popup.html", "default_icon": "icon.png"},
        "content_scripts": [
            {
                "matches": ["https://meet.google.com/*"],
                "js": [
                    "content-scripts/common-config.js",
                    "content-scripts/common-utils.js",
                    "content-scripts/google-meet/config.js",
                    "content-scripts/google-meet/utils.js",
                    "content-scripts/google-meet/index.js",
                ],
                "run_at": "document_idle",
            }
        ],
        "content_security_policy": {
            "extension_pages": "script-src 'self'; object-src 'self'; connect-src 'self' http://127.0.0.1:8000"
        },
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    private = destination / "backend-config.json"
    private.write_text(json.dumps({"url": URL, "token": token}))
    private.chmod(0o600)
    (destination / "UPSTREAM.json").write_text(
        json.dumps(
            {
                "repository": "https://github.com/vivek-nexus/transcriptonic",
                "commit": COMMIT,
                "archive_sha256": ARCHIVE_SHA256,
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, help="Archivo fijado, para reconstruir sin red"
    )
    args = parser.parse_args()
    if args.archive:
        archive = args.archive.read_bytes()
    elif CACHE.is_file():
        archive = CACHE.read_bytes()
    else:
        with urllib.request.urlopen(
            f"https://codeload.github.com/vivek-nexus/transcriptonic/zip/{COMMIT}",
            timeout=30,
        ) as response:
            archive = response.read()
    # Verify before touching local configuration.
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise SystemExit("Checksum de TranscripTonic inválido.")
    CACHE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    CACHE.write_bytes(archive)
    env_file = ROOT / "project/.env"
    token = os.getenv("WORKFLOW_TRANSCRIPT_TOKEN") or dotenv_values(env_file).get(
        "WORKFLOW_TRANSCRIPT_TOKEN", ""
    )
    if not token:
        token = secrets.token_urlsafe(40)
        set_key(str(env_file), "WORKFLOW_TRANSCRIPT_TOKEN", token, quote_mode="always")
    if len(token) < 32:
        raise SystemExit("WORKFLOW_TRANSCRIPT_TOKEN debe tener al menos 32 caracteres.")
    if token in {
        dotenv_values(env_file).get(name)
        for name in ("CALENDAR_ACCESS_SERVICE_KEY", "WORKFLOW_MANAGER_TOKEN")
    }:
        raise SystemExit(
            "La credencial de captura debe ser independiente de las demás."
        )
    build(archive, token, TARGET)
    print(f"Extensión lista para cargar desde: {TARGET}")
    print(
        "La credencial queda en archivos locales ignorados por Git; no compartir la carpeta generada."
    )


if __name__ == "__main__":
    main()
