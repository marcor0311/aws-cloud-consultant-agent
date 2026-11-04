import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psutil

LATENCY_KEY = "speech_to_speech.turn_latency"


class Measurements:
    def __init__(self, root="outputs", mode="chat"):
        self.path = Path(root) / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path.mkdir(parents=True)
        self.mode = mode
        self.turns, self.errors = [], 0
        self.first_chunks, self.response_stops = {}, {}
        self.last_stopped = None
        self.memory = {
            "rss_process_tree_peak_mib": 0.0,
            "ollama_model_peak_mib": 0.0,
            "ollama_metal_peak_mib": 0.0,
            "available_min_mib": None,
            "swap_peak_mib": 0.0,
            "swap_start_mib": None,
        }
        self.turn_file = (self.path / "turns.jsonl").open("w")
        self.memory.update(
            mlx_active_peak_mib=0.0, mlx_cache_peak_mib=0.0, mlx_allocator_peak_mib=0.0
        )

    def observe(self, event):
        kind, now = event.get("type"), time.perf_counter()
        if kind == "input_audio_buffer.speech_stopped":
            self.last_stopped = now
        elif kind == "response.created":
            key = event["response"]["id"]
            self.response_stops[key] = self.last_stopped
        elif kind == "response.output_audio.delta":
            key = event.get("response_id")
            self.first_chunks.setdefault(key, now)
        elif kind == "error":
            self.errors += 1
        elif kind == "response.done":
            response = event["response"]
            key = response["id"]
            timing = response.get("metadata", {}).get(LATENCY_KEY)
            if isinstance(timing, str):
                timing = json.loads(timing)
            start = self.response_stops.pop(key, None)
            first = self.first_chunks.pop(key, None)
            item = {
                "response_id": key,
                "status": response.get("status"),
                "hf_server_latency": timing,
                "client_speech_stopped_to_audio_ms": (
                    (first - start) * 1000 if first is not None and start is not None else None
                ),
            }
            self.turns.append(item)
            self.turn_file.write(json.dumps(item) + "\n")
            self.turn_file.flush()

    async def sample_memory(self, child_pid, ollama_base, stop):
        mib = 1024**2
        with (self.path / "memory.jsonl").open("w") as output:
            async with httpx.AsyncClient(timeout=0.5, trust_env=False) as client:
                while not stop.is_set():
                    total = psutil.Process().memory_info().rss
                    try:
                        parent = psutil.Process(child_pid)
                        for process in [parent, *parent.children(recursive=True)]:
                            total += process.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    vm = psutil.virtual_memory()
                    model = metal = 0
                    try:
                        response = await client.get(ollama_base + "/api/ps")
                        response.raise_for_status()
                        for entry in response.json().get("models", []):
                            model += entry.get("size", 0)
                            metal += entry.get("size_vram", 0)
                    except (httpx.HTTPError, ValueError):
                        pass
                    values = {
                        "at": time.perf_counter(),
                        "rss_process_tree_mib": total / mib,
                        "ollama_model_mib": model / mib,
                        "ollama_metal_mib": metal / mib,
                        "available_mib": vm.available / mib,
                        "swap_mib": psutil.swap_memory().used / mib,
                    }
                    if self.memory["swap_start_mib"] is None:
                        self.memory["swap_start_mib"] = values["swap_mib"]
                    try:
                        values.update(json.loads((self.path / "mlx-memory.json").read_text()))
                    except (OSError, ValueError):
                        pass
                    for key in ("mlx_active", "mlx_cache"):
                        self.memory[key + "_peak_mib"] = max(
                            self.memory[key + "_peak_mib"], values.get(key + "_mib", 0)
                        )
                    self.memory["mlx_allocator_peak_mib"] = max(
                        self.memory["mlx_allocator_peak_mib"],
                        values.get("mlx_allocator_peak_mib", 0),
                    )
                    for key in ("rss_process_tree", "ollama_model", "ollama_metal", "swap"):
                        self.memory[key + "_peak_mib"] = max(
                            self.memory[key + "_peak_mib"], values[key + "_mib"]
                        )
                    minimum = self.memory["available_min_mib"]
                    self.memory["available_min_mib"] = min(
                        minimum if minimum is not None else float("inf"), values["available_mib"]
                    )
                    output.write(json.dumps(values) + "\n")
                    output.flush()
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=0.5)
                    except TimeoutError:
                        pass

    def finish(self):
        times = [
            (item.get("hf_server_latency") or {}).get("e2e_s")
            for item in self.turns
            if item["status"] == "completed"
        ]
        times = [value * 1000 for value in times if value is not None]
        result = {
            "engine": "huggingface/speech-to-speech",
            "version": "1.1.0",
            "mode": self.mode,
            "responses": len(self.turns),
            "completed": sum(item["status"] == "completed" for item in self.turns),
            "cancelled": sum(item["status"] == "cancelled" for item in self.turns),
            "failed": sum(item["status"] == "failed" for item in self.turns),
            "incomplete": sum(item["status"] == "incomplete" for item in self.turns),
            "protocol_errors": self.errors,
            "server_speech_end_to_audio_median_ms": statistics.median(times) if times else None,
            "memory": self.memory,
        }
        result["stage_median_ms"] = {}
        for stage in ("stt_s", "llm_s", "tts_ttfa_s"):
            values = [
                (item.get("hf_server_latency") or {}).get(stage)
                for item in self.turns
                if item["status"] == "completed"
            ]
            values = [value * 1000 for value in values if value is not None]
            result["stage_median_ms"][stage.removesuffix("_s")] = (
                statistics.median(values) if values else None
            )
        (self.path / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        self.turn_file.close()
        return result
