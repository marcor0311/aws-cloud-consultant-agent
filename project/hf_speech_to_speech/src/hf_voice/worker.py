"""Run the unmodified HF server; only repair Homebrew phonemizer paths."""

import argparse
import json
import threading
from pathlib import Path
from threading import Event


def configure_espeak():
    # Misaki's import selects espeakng-loader. Override it afterwards with the
    # matching native Homebrew library and data directory, before constructing G2P.
    import misaki.espeak  # noqa: F401
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    for prefix in (Path("/opt/homebrew"), Path("/usr/local")):
        library = prefix / "lib/libespeak-ng.dylib"
        data = prefix / "share/espeak-ng-data"
        if library.exists() and (data / "phontab").exists():
            EspeakWrapper.set_library(str(library))
            EspeakWrapper.set_data_path(str(data))
            return
    raise RuntimeError("Instala la biblioteca y los datos con brew install espeak-ng.")


def resolved_profile(path):
    from speech_to_speech.config import load_config, resolve_config

    return resolve_config(load_config(path), names=["spanish"], include_client=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", type=Path)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--memory-file", type=Path)
    args = parser.parse_args()
    config = resolved_profile(args.profile)
    if args.validate:
        print("Perfil oficial de Hugging Face validado.")
        return
    configure_espeak()
    import mlx.core as mx

    # Avoid retaining gigabytes of reusable Metal buffers on an 18 GB machine.
    mx.set_cache_limit(256 * 1024**2)
    if args.memory_file:

        def sample():
            while True:
                data = {
                    "mlx_active_mib": mx.get_active_memory() / 1024**2,
                    "mlx_cache_mib": mx.get_cache_memory() / 1024**2,
                    "mlx_allocator_peak_mib": mx.get_peak_memory() / 1024**2,
                }
                temporary = args.memory_file.with_suffix(".tmp")
                temporary.write_text(json.dumps(data))
                temporary.replace(args.memory_file)
                threading.Event().wait(0.5)

        threading.Thread(target=sample, daemon=True).start()
    from speech_to_speech.configured_runtime import build_configured_server
    from speech_to_speech.pipeline.console import console

    # Some upstream handlers print transcripts even when log_transcripts=False.
    # Keep diagnostic logging, but never persist their Rich conversation output.
    console.quiet = True

    runtime = build_configured_server(config, Event())
    mx.clear_cache()
    runtime.start()
    try:
        runtime.wait()
    except KeyboardInterrupt:
        runtime.stop()


if __name__ == "__main__":
    main()
