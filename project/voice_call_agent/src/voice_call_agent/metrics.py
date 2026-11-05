import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import psutil


class Recorder:
    def __init__(self, directory: str, metadata: dict):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        self.directory = Path(directory) / stamp
        self.directory.mkdir(parents=True, exist_ok=False)
        self.metadata = metadata
        self.turns: list[dict] = []
        self.event_count = 0
        self.events = (self.directory / "events.jsonl").open("w")
        self.turn_file = (self.directory / "turns.jsonl").open("w")
        self.event("session_start", **metadata)

    def event(self, kind: str, **fields):
        if kind == "barge_in":
            self.event_count += 1
        self.events.write(json.dumps({"event": kind, "at": time.perf_counter(), **fields}) + "\n")
        self.events.flush()

    def turn(self, record: dict):
        self.turns.append(record)
        self.turn_file.write(json.dumps(record) + "\n")
        self.turn_file.flush()

    def finish(self, memory: dict):
        latency = [
            t["first_audio_ms"]
            for t in self.turns
            if t.get("first_audio_ms") is not None and t["status"] == "completed"
        ]
        report = {
            "metadata": self.metadata,
            "turns": len(self.turns),
            "completed": sum(t["status"] == "completed" for t in self.turns),
            "interrupted": sum(t["status"] == "interrupted" for t in self.turns),
            "errors": sum(t["status"] == "error" for t in self.turns),
            "barge_in_events": self.event_count,
            "first_audio_p50_ms": float(np.percentile(latency, 50)) if latency else None,
            "first_audio_p95_ms": float(np.percentile(latency, 95)) if latency else None,
            "memory": memory,
        }
        (self.directory / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        self.events.close()
        self.turn_file.close()
        return report


class MemorySampler:
    """RSS and system memory are separate from Ollama's model/Metal allocations."""

    def __init__(self, recorder: Recorder, url: str, interval: float):
        self.recorder, self.url, self.interval = recorder, url, interval
        self.stop_event = threading.Event()
        self.peaks = {
            "python_rss_peak_mib": 0.0,
            "ollama_rss_sum_peak_mib": 0.0,
            "ollama_model_peak_mib": 0.0,
            "ollama_metal_peak_mib": 0.0,
            "system_used_peak_mib": 0.0,
            "swap_used_peak_mib": 0.0,
        }
        self.min_available = float("inf")
        self.thread = threading.Thread(target=self._run, name="memory-sampler", daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        mib = 1024**2
        process = psutil.Process()
        with (
            httpx.Client(base_url=self.url, timeout=0.4, trust_env=False) as client,
            (self.recorder.directory / "memory.jsonl").open("w") as output,
        ):
            while not self.stop_event.is_set():
                vm = psutil.virtual_memory()
                ollama_rss = 0
                for proc in psutil.process_iter(["name", "memory_info"]):
                    try:
                        if "ollama" in (proc.info["name"] or "").lower():
                            ollama_rss += proc.info["memory_info"].rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                        continue
                model, metal = 0, 0
                try:
                    response = client.get("/api/ps")
                    response.raise_for_status()
                    for entry in response.json().get("models", []):
                        model += entry.get("size", 0)
                        metal += entry.get("size_vram", 0)
                except (httpx.HTTPError, ValueError):
                    pass
                sample = {
                    "at": time.perf_counter(),
                    "python_rss_mib": process.memory_info().rss / mib,
                    "ollama_rss_sum_mib": ollama_rss / mib,
                    "ollama_model_mib": model / mib,
                    "ollama_metal_mib": metal / mib,
                    "system_used_mib": vm.used / mib,
                    "system_available_mib": vm.available / mib,
                    "swap_used_mib": psutil.swap_memory().used / mib,
                }
                for key in self.peaks:
                    self.peaks[key] = max(self.peaks[key], sample[key.replace("_peak", "")])
                self.min_available = min(self.min_available, sample["system_available_mib"])
                output.write(json.dumps(sample) + "\n")
                output.flush()
                self.stop_event.wait(self.interval)

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=3)
        return {
            **self.peaks,
            "system_available_min_mib": (
                self.min_available if self.min_available != float("inf") else None
            ),
        }
