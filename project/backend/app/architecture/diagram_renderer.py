"""Strict adapter for the pinned awslabs/diagram-as-code CLI."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.architecture.topology import AWSDAC_VERSION


class AwsDacRenderer:
    def __init__(self, executable: str | None = None):
        bundled = (
            Path(__file__).resolve().parents[2]
            / "tools"
            / "awsdac"
            / f"v{AWSDAC_VERSION}"
            / "dist"
            / f"awsdac-v{AWSDAC_VERSION}_windows-amd64"
            / "awsdac.exe"
        )
        self.executable = (
            executable
            or os.environ.get("AWSDAC_EXECUTABLE")
            or (str(bundled) if bundled.is_file() else "awsdac")
        )

    def _resolved_executable(self) -> str:
        resolved = shutil.which(self.executable)
        if not resolved:
            raise RuntimeError(
                f"awsdac v{AWSDAC_VERSION} no está instalado o no está en PATH."
            )
        return resolved

    def verify_version(self) -> str:
        result = subprocess.run(
            [self._resolved_executable(), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        match = re.search(r"(?:v)?([0-9]+\.[0-9]+(?:\.[0-9]+)?)", result.stdout)
        if not match or match.group(1) != AWSDAC_VERSION:
            actual = match.group(1) if match else "desconocida"
            raise RuntimeError(
                f"Versión awsdac incompatible: {actual}; se requiere {AWSDAC_VERSION}."
            )
        return match.group(1)

    def render(self, source: Path, output: Path) -> Path:
        self.verify_version()
        source = source.resolve()
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [self._resolved_executable(), str(source), "-o", str(output), "--force"],
            check=True,
            capture_output=True,
            text=True,
        )
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("awsdac no produjo un PNG válido.")
        return output

    def render_bytes(self, source_yaml: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix="architecture-awsdac-") as directory:
            root = Path(directory)
            source = root / "architecture.aws-dac.yaml"
            output = root / "architecture.png"
            source.write_text(source_yaml, encoding="utf-8", newline="\n")
            self.render(source, output)
            return output.read_bytes()
