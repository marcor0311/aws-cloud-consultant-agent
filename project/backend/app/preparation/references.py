"""Search versioned fictional briefs with inspectable lexical evidence."""

import hashlib
import re
import unicodedata
from pathlib import Path

from app.core.config import REFERENCE_DIR


def read_reference(project_id: str, root: Path = REFERENCE_DIR) -> dict:
    # IDs are selected from the catalog, never interpreted as arbitrary paths.
    projects = {
        p.parent.name: p.parent for p in (root / "projects").glob("*/project-brief.md")
    }
    if project_id not in projects:
        raise ValueError("Referencia inexistente.")
    directory = projects[project_id]
    paths = [directory / "project-brief.md", directory / "project.yaml"]
    paths.extend(sorted(directory.glob("versions/*/architecture.md")))
    return {
        "project_id": project_id,
        "is_fictitious": True,
        "documents": [
            {
                "path": p.relative_to(root.parent).as_posix(),
                "content": p.read_text(encoding="utf-8"),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in paths
        ],
    }


def tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    return set(re.findall(r"[a-z0-9]{3,}", text))


def search_references(query: str, root: Path = REFERENCE_DIR) -> list[dict]:
    terms = tokens(query)
    if not terms:
        return []
    matches = []
    for path in sorted((root / "projects").glob("*/project-brief.md")):
        body = path.read_text(encoding="utf-8")
        # Ignore the common academic notice when scoring.
        lines = [line for line in body.splitlines() if not line.startswith(">")]
        evidence = [line for line in lines if terms & tokens(line)]
        matched = sorted(terms & tokens("\n".join(lines)))
        if not matched:
            continue
        matches.append(
            {
                "project_id": path.parent.name,
                "path": path.relative_to(root.parent).as_posix(),
                "is_fictitious": True,
                "matched_terms": matched,
                "score": len(matched),
                "evidence": evidence[:5],
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
        )
    return sorted(matches, key=lambda item: (-item["score"], item["project_id"]))[:3]


class ReferenceCatalog:
    """Search and read the reference documents already indexed by the SQL store."""

    def __init__(self, store):
        self.store = store

    def search(self, query):
        terms = tokens(query) - {
            "para",
            "los",
            "las",
            "una",
            "del",
            "que",
            "con",
            "por",
            "como",
        }
        matches = []
        for doc in self.store.list("reference"):
            if not doc["path"].endswith("/project-brief.md"):
                continue
            lines = [
                line for line in doc["content"].splitlines() if not line.startswith(">")
            ]
            matched = sorted(terms & tokens("\n".join(lines)))
            if matched:
                matches.append(
                    {
                        "project_id": doc["path"].split("/")[-2],
                        "path": doc["path"],
                        "is_fictitious": True,
                        "matched_terms": matched,
                        "score": len(matched),
                        "evidence": [line for line in lines if terms & tokens(line)][
                            :5
                        ],
                        "sha256": doc["sha256"],
                        "source_commit": doc["source_commit"],
                    }
                )
        return sorted(matches, key=lambda item: (-item["score"], item["project_id"]))[
            :3
        ]

    def read_reference(self, project_id):
        if not re.fullmatch(r"[a-z0-9-]+", project_id):
            raise ValueError("Referencia inexistente.")
        prefix = f"references/projects/{project_id}/"
        documents = [
            doc
            for doc in self.store.list("reference")
            if doc["path"].startswith(prefix)
            and (
                doc["path"].endswith("project-brief.md")
                or doc["path"].endswith("architecture.md")
            )
        ]
        if not documents:
            raise ValueError("Referencia inexistente.")
        return {"project_id": project_id, "is_fictitious": True, "documents": documents}
