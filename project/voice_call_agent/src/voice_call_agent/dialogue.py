import re


class History:
    def __init__(self, system: str, max_turns: int, max_characters: int):
        self.system = system
        self.max_turns = max_turns
        self.max_characters = max_characters
        self.items: list[dict[str, str]] = []

    def add(self, role: str, content: str):
        if not content.strip():
            return
        self.items.append({"role": role, "content": content[-self.max_characters :]})
        self._trim()

    def _trim(self):
        while len(self.items) > 1 and (
            len(self.items) > self.max_turns * 2
            or sum(len(item["content"]) for item in self.items) > self.max_characters
        ):
            self.items.pop(0)
        # Do not start the context with an orphaned assistant answer.
        while self.items and self.items[0]["role"] == "assistant":
            self.items.pop(0)

    def messages(self):
        return [{"role": "system", "content": self.system}, *[dict(m) for m in self.items]]


class PhraseBuffer:
    def __init__(self, minimum: int = 35, maximum: int = 160):
        self.minimum, self.maximum, self.buffer = minimum, maximum, ""

    def feed(self, text: str) -> list[str]:
        self.buffer += text
        phrases = []
        while self.buffer:
            boundary = next(
                (
                    m.end()
                    for m in re.finditer(r"[.!?;:](?:\s+|$)", self.buffer)
                    if self.minimum <= m.end() <= self.maximum
                ),
                None,
            )
            if boundary is None and len(self.buffer) >= self.maximum:
                boundary = self.buffer.rfind(" ", 0, self.maximum + 1)
                if boundary < self.minimum:
                    boundary = self.maximum
            if boundary is None:
                break
            phrase, self.buffer = self.buffer[:boundary].strip(), self.buffer[boundary:].lstrip()
            if phrase:
                phrases.append(phrase)
        return phrases

    def flush(self) -> str:
        result, self.buffer = self.buffer.strip(), ""
        return result
