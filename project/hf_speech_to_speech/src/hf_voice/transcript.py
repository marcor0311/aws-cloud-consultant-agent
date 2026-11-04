"""Replaceable live hypotheses and streamed assistant text, without duplicate finals."""

from collections import OrderedDict

from rich.console import Console
from rich.live import Live
from rich.text import Text


class TranscriptDisplay:
    def __init__(self, console=None):
        self.console = console or Console(highlight=False)
        self.inline = self.console.is_terminal and not self.console.is_dumb_terminal
        self.texts = OrderedDict()
        self.finished = set()
        self.active = None
        self.live = None

    def update(self, speaker, item, text, *, final=False, append=False):
        key = (speaker, item)
        if key in self.finished:
            return
        previous = self.texts.get(key, "")
        text = previous + text if append else text
        if not text.strip():
            return
        self.texts[key] = text
        self.texts.move_to_end(key)
        while len(self.texts) > 128:
            old, _ = self.texts.popitem(last=False)
            self.finished.discard(old)
        line = Text(f"{speaker}: ", style="bold cyan" if speaker == "Tú" else "bold green")
        line.append(text, style="default")
        if final:
            self._stop_live()
            if self.inline or text != previous:
                self.console.print(line, soft_wrap=True)
            self.finished.add(key)
            self.active = None
        elif text != previous:
            self.active = key
            if self.inline:
                if self.live is None:
                    self.live = Live(line, console=self.console, auto_refresh=False, transient=True)
                    self.live.start()
                self.live.update(line, refresh=True)
            else:
                # IDE output panes need an actual write for every revised hypothesis.
                self.console.print(line, soft_wrap=True)

    def interrupt(self):
        if self.active and self.active[0] == "Agente":
            key = self.active
            self.update(*key, self.texts[key] + " (interrumpido)", final=True)

    def _stop_live(self):
        if self.live:
            self.live.stop()
            self.live = None

    def close(self):
        self._stop_live()
