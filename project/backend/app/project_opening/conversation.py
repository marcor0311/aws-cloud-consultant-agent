"""Durable, one-question-at-a-time MCP conversation for opening a project."""

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.integrations.errors import ProviderError
from app.preparation.processing import CORPORATE_FILENAMES
from app.project_opening.models import OpeningRequest, project_identity, slug


class ConversationState(TypedDict, total=False):
    session_id: str
    choices: list[dict[str, Any]]
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


def _ask(question, error=None):
    """Pause for Stuart; a repeated question explains why the last answer failed."""
    return interrupt({**question, "error": error} if error else question)


class OpeningConversation:
    """Collect the explicit direction decision and confirm GitHub writes."""

    def __init__(
        self,
        service,
        checkpointer,
        *,
        owner="aws-cloud-consulting-group",
        find_user=None,
    ):
        self.service = service
        self.repository = service.repository
        self.store = self.repository.store
        self.owner = owner
        # Optional read-only GitHub lookup; it never writes before confirmation.
        self.find_user = find_user
        graph = StateGraph(ConversationState)
        graph.add_node("choices", self._choices)
        graph.add_node("project", self._project)
        graph.add_node("decision", self._decision)
        graph.add_node("confirm_rejection", self._confirm_rejection)
        graph.add_node("priority", self._priority)
        graph.add_node("budget", self._budget)
        graph.add_node("architect", self._architect)
        graph.add_node("confirm", self._confirm)
        graph.add_node("reject", self._reject)
        graph.add_node("cancel", self._cancel)
        graph.add_node("open", self._open)
        graph.add_edge(START, "choices")
        graph.add_conditional_edges(
            "choices",
            lambda state: "project" if state.get("choices") else END,
        )
        graph.add_edge("project", "decision")
        graph.add_conditional_edges(
            "decision",
            lambda state: "priority" if state["approved"] else "confirm_rejection",
        )
        graph.add_conditional_edges(
            "confirm_rejection",
            lambda state: "reject" if state["status"] == "confirmed" else "cancel",
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
                # A rejection ends the flow; the Engagement Manager takes over.
                and not self.repository.direction_decision(case_id)
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

    def _numbered(self):
        return [
            {"option": index, **project}
            for index, project in enumerate(self._prepared(), 1)
        ]

    def _choices(self, state):
        # Fixed in the checkpoint so replays and numbered answers stay stable.
        choices = self._numbered()
        if not choices:
            return {"choices": [], "status": "no_prepared_projects"}
        return {"choices": choices}

    def _selected(self, state):
        # Sessions checkpointed before choices were stored fall back to a fresh list.
        return next(
            p
            for p in state.get("choices") or self._numbered()
            if p["case_id"] == state["case_id"]
        )

    def _project(self, state):
        choices = state.get("choices") or self._numbered()
        error = None
        while True:
            selected = _ask(
                {
                    "field": "project",
                    "question": "¿Cuál proyecto quieres gestionar? Puedes decir su número, nombre o case_id.",
                    "projects": choices,
                },
                error,
            )
            answer = str(selected).strip().casefold()
            matches = [
                project
                for project in choices
                if answer
                in {
                    str(project["option"]),
                    project["case_id"].casefold(),
                    project["project"].casefold(),
                }
            ]
            if len(matches) == 1:
                self.repository.start_direction(matches[0]["case_id"])
                return {"case_id": matches[0]["case_id"]}
            error = (
                "Hay más de un proyecto con ese nombre; usa su número o case_id."
                if matches
                else f"No encontré «{str(selected)[:80]}» entre los proyectos preparados."
            )

    def _decision(self, state):
        project = self._selected(state)
        error = None
        while True:
            answer = _ask(
                {
                    "field": "approved",
                    "question": f"¿Dirección aprobó que continúe el proyecto {project['project']} ({state['case_id']})? Responde sí o no.",
                },
                error,
            )
            try:
                return {"approved": _yes_no(answer)}
            except ValueError as invalid:
                error = str(invalid)

    def _confirm_rejection(self, state):
        project = self._selected(state)
        error = None
        while True:
            answer = _ask(
                {
                    "field": "confirm_rejection",
                    "question": f"¿Confirmas que Dirección rechazó {project['project']}? Se registrará el rechazo, el proyecto saldrá de la lista y no se creará repositorio ni issue. Responde sí o no.",
                },
                error,
            )
            try:
                confirmed = _yes_no(answer)
                return {"status": "confirmed" if confirmed else "cancelled"}
            except ValueError as invalid:
                error = str(invalid)

    def _priority(self, state):
        choices = self.repository.queue()
        error = None
        while True:
            answer = _ask(
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
                },
                error,
            )
            try:
                position = int(str(answer).strip().removeprefix("#"))
                if 1 <= position <= len(choices) + 1:
                    return {"queue_position": position}
            except (TypeError, ValueError):
                pass
            error = f"Indica un número entero entre 1 y {len(choices) + 1}."

    def _budget(self, state):
        error = None
        while True:
            answer = _ask(
                {
                    "field": "budget",
                    "question": "¿Cuál es el presupuesto total aprobado? Indica el monto en USD.",
                },
                error,
            )
            text = re.sub(r"(?i)usd|\$|,|\s", "", str(answer))
            try:
                amount = Decimal(text)
                if (
                    amount.is_finite()
                    and amount > 0
                    and amount.as_tuple().exponent >= -2
                    and amount < Decimal("1e12")
                ):
                    return {"budget_total": str(amount.quantize(Decimal("0.01")))}
            except (InvalidOperation, ValueError):
                pass
            error = "Indica un monto positivo en USD, con dos decimales como máximo; por ejemplo 180000 o 180,000.50."

    def _architect(self, state):
        error = None
        while True:
            answer = _ask(
                {
                    "field": "architect",
                    "question": "¿Qué usuario de GitHub será el arquitecto asignado?",
                },
                error,
            )
            architect = str(answer).strip().removeprefix("@").strip()
            if not re.fullmatch(r"[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}", architect):
                error = "Indica un usuario de GitHub válido: letras, números y guiones."
                continue
            if self.find_user is None:
                return {"architect": architect}
            try:
                login = self.find_user(architect)
            except ProviderError:
                error = "No pude verificar el usuario en GitHub; vuelve a indicarlo."
                continue
            if login:
                return {"architect": login}
            error = f"No encontré el usuario {architect} en GitHub."

    def _confirm(self, state):
        project = self._selected(state)
        status = self.store.get(f"status:{state['case_id']}")
        manifest = self.store.get(
            f"artifact-files:{state['case_id']}:{status['revision']}"
        )
        counter = self.store.get(f"opening-number:{slug(project['company'])}") or {}
        identity = project_identity(
            project["company"], counter.get("last", 0) + 1, project["project"]
        )
        error = None
        while True:
            answer = _ask(
                {
                    "field": "confirm_creation",
                    "question": "¿Confirmas que registre la aprobación y estos datos, cree el repositorio desde el template, publique los documentos aprobados y cree el issue de arquitectura asignado al arquitecto? Responde sí o no.",
                    "summary": {
                        "project": project["project"],
                        "company": project["company"],
                        "approved": True,
                        "queue_position": state["queue_position"],
                        "budget_usd": state["budget_total"],
                        "architect": state["architect"],
                        "repository_template": OpeningRequest.model_fields[
                            "template_repository"
                        ].default,
                        "repository_title": identity["title"],
                        "repository": f"{self.owner}/{identity['repository_name']}",
                        "repository_number_note": "El número por compañía se reserva al confirmar.",
                        "files_to_publish": len(manifest["files"]),
                        "files": [file["name"] for file in manifest["files"]],
                        "publication_path": "docs/01-discovery/",
                        "architecture_issue": {
                            "title": "[Arquitectura] " + identity["title"],
                            "assignee": state["architect"],
                        },
                    },
                },
                error,
            )
            try:
                confirmed = _yes_no(answer)
                return {"status": "confirmed" if confirmed else "cancelled"}
            except ValueError as invalid:
                error = str(invalid)

    def _reject(self, state):
        self.repository.reject(state["case_id"], "Stuart", state["session_id"])
        return {"status": "rejected", "case_id": state["case_id"]}

    def _cancel(self, state):
        self.store.event(
            "opening-cancelled:" + state["session_id"],
            state["case_id"],
            "opening.confirmation_cancelled",
            {
                "actor": "Stuart",
                "step": "creation" if state.get("approved") else "rejection",
            },
        )
        return {"status": "cancelled", "case_id": state["case_id"]}

    def _open(self, state):
        opening = self.store.get(f"opening:{state['case_id']}")
        project = opening or self._selected(state)
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
        # Direction's stage ends with the registered approval; execution is timed
        # separately in the project-opening phase until the architecture handoff.
        self.repository.finish_direction(record["case_id"])
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
