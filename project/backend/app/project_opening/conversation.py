"""Durable, one-question-at-a-time MCP conversation for opening a project."""

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.preparation.processing import CORPORATE_FILENAMES
from app.project_opening.models import OpeningRequest


class ConversationState(TypedDict, total=False):
    session_id: str
    case_id: str
    approved: bool
    queue_position: int
    budget_total: str
    architect: str
    status: str
    result: dict[str, Any]


def _yes_no(answer):
    normalized = str(answer).strip().casefold()
    if normalized in {"sí", "si", "s", "yes", "y", "aprobado", "aprobada"}:
        return True
    if normalized in {"no", "n", "rechazado", "rechazada"}:
        return False
    raise ValueError("Responde sí o no.")


class OpeningConversation:
    """Collect the explicit direction decision and confirm GitHub writes."""

    def __init__(self, service, checkpointer, *, owner="aws-cloud-consulting-group"):
        self.service = service
        self.repository = service.repository
        self.store = self.repository.store
        self.owner = owner
        graph = StateGraph(ConversationState)
        graph.add_node("project", self._project)
        graph.add_node("decision", self._decision)
        graph.add_node("priority", self._priority)
        graph.add_node("budget", self._budget)
        graph.add_node("architect", self._architect)
        graph.add_node("confirm", self._confirm)
        graph.add_node("reject", self._reject)
        graph.add_node("cancel", self._cancel)
        graph.add_node("open", self._open)
        graph.add_edge(START, "project")
        graph.add_conditional_edges(
            "project",
            lambda state: "decision" if state.get("case_id") else END,
        )
        graph.add_conditional_edges(
            "decision", lambda state: "priority" if state["approved"] else "reject"
        )
        graph.add_edge("priority", "budget")
        graph.add_edge("budget", "architect")
        graph.add_edge("architect", "confirm")
        graph.add_conditional_edges(
            "confirm",
            lambda state: "open" if state["status"] == "confirmed" else "cancel",
        )
        graph.add_edge("reject", END)
        graph.add_edge("cancel", END)
        graph.add_edge("open", END)
        self.graph = graph.compile(checkpointer=checkpointer)

    def start(self):
        session_id = uuid.uuid4().hex
        config = self._config(session_id)
        self.graph.invoke({"session_id": session_id}, config)
        return self._response(session_id)

    def respond(self, session_id, answer):
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("La sesión de apertura no es válida.")
        snapshot = self.graph.get_state(self._config(session_id))
        if not snapshot.values or not any(task.interrupts for task in snapshot.tasks):
            raise ValueError("La conversación no está esperando una respuesta.")
        self.graph.invoke(Command(resume=answer), self._config(session_id))
        return self._response(session_id)

    def resume(self, session_id):
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("La sesión de apertura no es válida.")
        snapshot = self.graph.get_state(self._config(session_id))
        if (
            not snapshot.values
            or not snapshot.next
            or any(task.interrupts for task in snapshot.tasks)
        ):
            raise ValueError(
                "La apertura no tiene un paso fallido que se pueda reanudar."
            )
        self.graph.invoke(None, self._config(session_id))
        return self._response(session_id)

    def _response(self, session_id):
        snapshot = self.graph.get_state(self._config(session_id))
        pending = [
            interrupt.value for task in snapshot.tasks for interrupt in task.interrupts
        ]
        if pending:
            return {
                "session_id": session_id,
                "status": "waiting_for_answer",
                **pending[0],
            }
        return {
            "session_id": session_id,
            "status": snapshot.values.get("status", "completed"),
            **snapshot.values.get("result", {}),
        }

    @staticmethod
    def _config(session_id):
        return {"configurable": {"thread_id": "opening-conversation:" + session_id}}

    def _prepared(self):
        ready = []
        for project in self.store.project_list(None):
            case_id = project["case_id"]
            status = self.store.get(f"status:{case_id}") or {}
            revision = status.get("revision")
            manifest = self.store.get(f"artifact-files:{case_id}:{revision}")
            if (
                status.get("status") == "ready_for_stage_2"
                and manifest
                and (
                    len(manifest.get("files", [])) in {3, 6}
                    or {f["name"] for f in manifest.get("files", [])}
                    == set(CORPORATE_FILENAMES)
                )
                and not self.store.get(f"opening:{case_id}")
            ):
                ready.append(
                    {
                        "case_id": case_id,
                        "project": project["title"],
                        "company": project["company"],
                        "revision": revision,
                        "is_fictitious": bool(project["is_fictitious"]),
                    }
                )
        return ready

    def _project(self, state):
        choices = self._prepared()
        if not choices:
            return {"status": "no_prepared_projects"}
        while True:
            selected = interrupt(
                {
                    "field": "project",
                    "question": "¿Cuál proyecto quieres gestionar? Puedes decir el nombre o usar su case_id.",
                    "projects": choices,
                }
            )
            answer = str(selected).strip().casefold()
            matches = [
                project
                for project in choices
                if answer
                in {project["case_id"].casefold(), project["project"].casefold()}
            ]
            if len(matches) == 1:
                return {"case_id": matches[0]["case_id"]}

    def _decision(self, state):
        while True:
            answer = interrupt(
                {
                    "field": "approved",
                    "question": f"¿Dirección aprobó que continúe el proyecto {state['case_id']}? Responde sí o no.",
                }
            )
            try:
                return {"approved": _yes_no(answer)}
            except ValueError:
                continue

    def _priority(self, state):
        choices = self.repository.queue()
        while True:
            answer = interrupt(
                {
                    "field": "queue_position",
                    "question": "¿En qué posición debe quedar el proyecto en la cola actual?",
                    "current_queue": [
                        {
                            "case_id": item["case_id"],
                            "title": item["title"],
                            "position": item["queue_position"],
                        }
                        for item in choices
                    ],
                }
            )
            try:
                position = int(str(answer).strip())
                if 1 <= position <= len(choices) + 1:
                    return {"queue_position": position}
            except (TypeError, ValueError):
                continue

    def _budget(self, state):
        while True:
            answer = interrupt(
                {
                    "field": "budget",
                    "question": "¿Cuál es el presupuesto total aprobado? Indica el monto en USD.",
                }
            )
            try:
                amount = Decimal(
                    str(answer)
                    .strip()
                    .replace("$", "")
                    .replace(",", "")
                    .replace("USD", "")
                    .strip()
                )
                if amount > 0 and amount.as_tuple().exponent >= -2:
                    return {"budget_total": str(amount.quantize(Decimal("0.01")))}
            except (InvalidOperation, ValueError):
                continue

    def _architect(self, state):
        while True:
            answer = interrupt(
                {
                    "field": "architect",
                    "question": "¿Qué usuario de GitHub será el arquitecto asignado?",
                }
            )
            architect = str(answer).strip().removeprefix("@").strip()
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", architect):
                return {"architect": architect}

    def _confirm(self, state):
        project = next(
            item for item in self._prepared() if item["case_id"] == state["case_id"]
        )
        status = self.store.get(f"status:{state['case_id']}")
        manifest = self.store.get(
            f"artifact-files:{state['case_id']}:{status['revision']}"
        )
        while True:
            answer = interrupt(
                {
                    "field": "confirm_creation",
                    "question": "Confirma que registre la aprobación y estos datos, cree el repositorio desde el template, publique los documentos aprobados y cree el issue de arquitectura asignado al arquitecto? Responde sí o no.",
                    "summary": {
                        "project": project["project"],
                        "approved": True,
                        "queue_position": state["queue_position"],
                        "budget_usd": state["budget_total"],
                        "architect": state["architect"],
                        "repository_template": "marcor0311/aws-cloud-consulting-project-template",
                        "files_to_publish": len(manifest["files"]),
                    },
                }
            )
            try:
                confirmed = _yes_no(answer)
                return {"status": "confirmed" if confirmed else "cancelled"}
            except ValueError:
                continue

    def _reject(self, state):
        record = {
            "case_id": state["case_id"],
            "decision": "rejected",
            "actor": "Stuart",
            "recorded_at": self.store.clock(),
            "session_id": state["session_id"],
        }
        key = "opening-decision:" + state["case_id"]
        previous = self.store.get(key)
        if previous and previous.get("decision") != "rejected":
            raise ValueError("El proyecto ya tiene una decisión de apertura distinta.")
        self.store.put(key, "opening-decision", record)
        self.store.event(
            "opening-rejected:" + state["case_id"],
            state["case_id"],
            "opening.rejected",
            {"actor": "Stuart", "session_id": state["session_id"]},
        )
        return {"status": "rejected", "case_id": state["case_id"]}

    def _cancel(self, state):
        self.store.event(
            "opening-cancelled:" + state["session_id"],
            state["case_id"],
            "opening.confirmation_cancelled",
            {"actor": "Stuart"},
        )
        return {"status": "cancelled", "case_id": state["case_id"]}

    def _open(self, state):
        opening = self.store.get(f"opening:{state['case_id']}")
        project = opening or next(
            item for item in self._prepared() if item["case_id"] == state["case_id"]
        )
        status = self.store.get(f"status:{state['case_id']}")
        manifest = self.store.get(
            f"artifact-files:{state['case_id']}:{status['revision']}"
        )
        artifact = self.store.get(f"artifact:{state['case_id']}:{status['revision']}")
        package = artifact["package"]
        amount = Decimal(state["budget_total"])

        def texts(key):
            return [
                item if isinstance(item, str) else item["text"]
                for item in package.get(key, [])
            ]

        needs = texts("needs")
        requirements = texts("requirements")
        risks = texts("risks") + texts("restrictions")
        questions = package.get("open_questions", [])
        request = {
            "case_id": state["case_id"],
            "company": project["company"],
            "project_name": project.get("project", project.get("project_name")),
            "owner": self.owner,
            "private": False,
            "queue_position": state["queue_position"],
            "architect": state["architect"],
            "issue_assignee": state["architect"],
            "budget": {
                "currency": "USD",
                "total": str(amount),
                "accepted": True,
                "lines": [
                    {
                        "name": "Presupuesto aprobado por dirección",
                        "amount": str(amount),
                    }
                ],
                "conditions": "Monto total aprobado por dirección y confirmado por Stuart en el chat MCP.",
            },
            "work": {
                "context": package["summary"],
                "scope": "\n".join(needs + requirements) or package["summary"],
                "restrictions": "\n".join(risks + questions)
                or "Documentar supuestos y validar restricciones con el cliente.",
                "deliverables": "Diseño de arquitectura AWS, diagrama, decisiones, supuestos y criterios para revisión de FinOps.",
                "acceptance": "El diseño responde a las necesidades y requisitos incluidos en los insumos aprobados, documenta supuestos y queda asignado para revisión del arquitecto.",
            },
            "approved_by": "Stuart",
            "approval_reference": "Aprobación de dirección confirmada por Stuart en la sesión MCP "
            + state["session_id"],
            "comments": "",
            "files": manifest["files"],
            "is_fictitious": bool(project.get("is_fictitious", False)),
        }
        record = self.service.register(
            OpeningRequest.model_validate(request).model_dump(mode="json")
        )
        result = self.service.run(record["case_id"])
        self.store.put(
            "opening-decision:" + state["case_id"],
            "opening-decision",
            {
                "case_id": state["case_id"],
                "decision": "approved",
                "actor": "Stuart",
                "session_id": state["session_id"],
                "request_sha256": record["request_sha256"],
                "confirmed_at": self.store.clock(),
            },
        )
        return {"status": result["status"], "result": result}
