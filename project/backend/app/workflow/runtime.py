"""Dispatch persisted workflow tasks using dependencies composed at the entry point."""

import base64
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime

from app.integrations.errors import ConfigurationError, ProviderError
from app.persistence.locking import Busy
from app.project_opening.decisions import BoardDecisionBlocked

logger = logging.getLogger(__name__)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("La fecha debe incluir zona horaria.")
    return parsed.timestamp()


class WorkflowRuntime:
    def __init__(
        self,
        settings,
        *,
        store,
        process,
        board_rejections,
        service,
        google,
        notifier,
        drafter,
        references,
        worker_lock,
        resources,
        mock_clock=None,
        client_lookup=None,
    ):
        self.settings, self.store = settings, store
        self.process, self.service = process, service
        self.board_rejections = board_rejections
        self.google, self.notifier, self.drafter = google, notifier, drafter
        self.search, self.read_reference = references.search, references.read_reference
        self.worker_lock, self.stack = worker_lock, resources
        self.mock_clock, self.client_lookup = mock_clock, client_lookup

    def close(self):
        self.stack.close()

    def submit_preparation(self, case_id, operation, **payload):
        """Queue operations that may call a model; HTTP/MCP never generate inline."""
        self.service._owned(case_id)
        if operation == "review":
            current = self.service.get(case_id)
            if (
                current["state"].get("revision") != payload["revision"]
                or current["state"].get("status") != "awaiting_review"
            ):
                raise ValueError("La revisión cambió; consultar el borrador actual.")
            if payload["decision"] != "revise" or not payload["feedback"].strip():
                raise ValueError("Indicar los ajustes solicitados.")
        elif operation == "continue":
            self.service.get(case_id)
        elif operation != "start":
            raise ValueError("Operación de preparación inválida.")
        body = {"case_id": case_id, "operation": operation, "arguments": payload}
        if operation == "continue":
            body["checkpoint"] = self.service.checkpoint_id(case_id)
        identity = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        key = f"preparation-command:{identity}"
        self.store.receive(key, "preparation_command", body)
        return {
            "status": self.store.job(key)["status"],
            "task_id": key,
            "case_id": case_id,
        }

    def _preparation_command(self, payload):
        operation, args = payload["operation"], payload["arguments"]
        if operation == "start":
            self.service.start(payload["case_id"], **args)
        elif operation == "review":
            state = self.service.get(payload["case_id"])["state"]
            if state.get("revision", 0) > args["revision"]:
                # The draft checkpoint committed before the command receipt did.
                return
            if (
                state.get("status") == "awaiting_draft"
                and state.get("feedback") == args["feedback"]
            ):
                self.service.continue_preparation(payload["case_id"])
            else:
                self.service.review(payload["case_id"], **args)
        elif operation == "continue":
            self.service.continue_preparation(payload["case_id"])
        else:
            raise ValueError("Operación de preparación inválida.")

    def _cancel_process(self, case_id):
        state = self.process.graph.inspect(self.process.thread_id(case_id)).state
        if state.get("status") in {
            "awaiting_meeting",
            "awaiting_transcript",
            "cancelled",
        }:
            self.process.internal(case_id, "meeting.cancelled", "meeting.cancelled")

    def register_meeting(self, payload, client_id):
        identity = f"{payload['calendar_id']}:{payload['calendar_event_id']}"
        case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        if not self.store.get(f"meeting:{case_id}"):
            self.store.put(
                f"meeting:{case_id}",
                "meeting",
                {
                    **payload,
                    "case_id": case_id,
                    "client_id": client_id,
                    "manager_id": self.settings.manager_id,
                    "status": "pending_calendar_sync",
                },
            )
        self.store.put(
            f"owner:{case_id}",
            "owner",
            {"case_id": case_id, "manager_id": self.settings.manager_id},
        )
        self.store.receive(
            f"calendar:{fingerprint}", "calendar", {**payload, "case_id": case_id}
        )
        if payload.get("started_at") and payload.get("completed_at"):
            self.store.record_calendar_work(
                fingerprint,
                case_id,
                timestamp(payload["started_at"]),
                timestamp(payload["completed_at"]),
                self.settings.manager_id,
            )
        return {"status": "registered", "case_id": case_id}

    def receive_message(self, message):
        attributes = message.get("attributes", {})
        raw = message.get("data", "")
        if len(raw) > 1_000_000:
            raise ValueError("Evento demasiado grande.")
        try:
            body = json.loads(base64.b64decode(raw, validate=True))
        except (ValueError, TypeError):
            raise ValueError("Evento Pub/Sub inválido.") from None
        kind = attributes.get("ce-type", body.get("type", ""))
        event_id = attributes.get("ce-id", body.get("id", message.get("messageId", "")))
        source = attributes.get("ce-source", body.get("source", ""))
        if not event_id or len(event_id) > 200:
            raise ValueError("El evento requiere un ID estable.")
        data = body.get("data", body)
        if kind == "google.workspace.meet.transcript.v2.fileGenerated":
            name = data.get("transcript", {}).get("name", "")
            if not re.fullmatch(
                r"conferenceRecords/[A-Za-z0-9_-]+/transcripts/[A-Za-z0-9_-]+", name
            ):
                raise ValueError("Referencia de transcripción inválida.")
            job_kind = "meet_transcript"
            payload = {"transcript": name, "source": source}
        elif kind == "google.workspace.events.subscription.v1.expirationReminder":
            job_kind, payload = "renew", {"source": source}
        else:
            return {"status": "ignored"}
        received = self.store.receive(f"google:{event_id}", job_kind, payload)
        return {"status": "accepted" if received else "duplicate"}

    def ensure_subscription(self, space):
        with self.store.lock(f"subscription:{space}"):
            return self._ensure_subscription(space)

    def _ensure_subscription(self, space):
        if not self.settings.pubsub_topic:
            raise ConfigurationError("configure_workflow_pubsub_topic")
        key = f"subscription:{space}"
        current = self.store.get(key)
        if current and current.get("operation"):
            result = self.google.operation(current["operation"])
        elif current and timestamp(current["expireTime"]) > self.store.clock() + 3600:
            return current
        elif current:
            result = self.google.renew(current)
        else:
            existing = [
                s
                for s in self.google.find_subscriptions(space)
                if s.get("notificationEndpoint", {}).get("pubsubTopic")
                == self.settings.pubsub_topic
            ]
            if len(existing) > 1:
                raise ConfigurationError(
                    "multiple_workspace_subscriptions_require_reconciliation"
                )
            if existing:
                self.store.put(key, "subscription", {**existing[0], "space": space})
                if timestamp(existing[0]["expireTime"]) > self.store.clock() + 3600:
                    return existing[0]
                result = self.google.renew(existing[0])
            else:
                result = self.google.subscribe(space, self.settings.pubsub_topic)
        if result.get("error"):
            raise ConfigurationError("workspace_subscription_failed")
        if result.get("name", "").startswith("operations/") and not result.get(
            "done", False
        ):
            self.store.put(
                key, "subscription", {"space": space, "operation": result["name"]}
            )
            raise ProviderError("workspace_subscription_pending", retry_after=5)
        subscription = result.get("response", result)
        if not subscription.get("name") or not subscription.get("expireTime"):
            raise ProviderError("workspace_subscription_incomplete")
        self.store.put(key, "subscription", {**subscription, "space": space})
        return subscription

    def _source_subscription(self, source):
        subscriptions = self.store.list("subscription")
        matches = [
            s
            for s in subscriptions
            if s.get("name")
            and source == f"//workspaceevents.googleapis.com/{s['name']}"
        ]
        if len(matches) != 1:
            raise ProviderError("subscription_source_not_registered")
        return matches[0]

    def _calendar(self, payload):
        case_id = payload["case_id"]
        with self.store.lock(f"meeting:{case_id}"):
            meeting = self.store.get(f"meeting:{case_id}")
            if meeting.get("status") == "cancelled":
                return
            if payload.get("operation") == "cancelled":
                self.store.put(
                    f"meeting:{case_id}", "meeting", {**meeting, "status": "cancelled"}
                )
                self.service.cancel_waiting_meeting(case_id)
                self.process.ensure(case_id, meeting["client_id"])
                self._cancel_process(case_id)
                return
            event = self.google.calendar_event(
                payload["calendar_id"], payload["calendar_event_id"]
            )
            if event.get("status") == "cancelled":
                self.store.put(
                    f"meeting:{case_id}", "meeting", {**meeting, "status": "cancelled"}
                )
                self.service.cancel_waiting_meeting(case_id)
                self.process.ensure(case_id, meeting["client_id"])
                self._cancel_process(case_id)
                return
            if (
                event.get("extendedProperties", {})
                .get("private", {})
                .get("calendar_assistant")
                != "stuart"
            ):
                raise ConfigurationError("calendar_event_not_owned_by_agent")
            if self.client_lookup:
                client_code = (
                    event.get("extendedProperties", {})
                    .get("private", {})
                    .get("workflow_client_code", "")
                )
                client = self.client_lookup(client_code)
                if (
                    not client
                    or not client.enabled
                    or client.client_id != meeting["client_id"]
                    or not any(
                        a.get("email", "").casefold() == client.company_email.casefold()
                        for a in event.get("attendees", [])
                    )
                ):
                    raise ConfigurationError("calendar_event_client_mismatch")
            conference = event.get("conferenceData", {})
            code = conference.get("conferenceId", "")
            if not code:
                raise ProviderError("calendar_meet_pending")
            # Calendar tracking is usable before the Meet/PubSub integration is configured.
            space = (
                self.google.space(code)["name"] if self.settings.pubsub_topic else ""
            )
            updated = {
                **meeting,
                "status": "scheduled",
                "meet_code": code,
                "space": space,
                "start": event["start"]["dateTime"],
                "end": event["end"]["dateTime"],
            }
            self.store.put(f"meeting:{case_id}", "meeting", updated)
            # Live tracking records the same first delivery that demos used to create manually.
            handoff_id = f"{case_id}:calendar:meeting"
            if not self.store.handoff(handoff_id):
                self.store.create_handoff(
                    handoff_id,
                    case_id,
                    "calendar-assistant",
                    self.settings.manager_id,
                    "scheduling",
                    "initial_meeting",
                    revision=1,
                    artifact_sha256=hashlib.sha256(
                        json.dumps(
                            {
                                k: updated[k]
                                for k in ("calendar_event_id", "start", "end")
                            },
                            sort_keys=True,
                        ).encode()
                    ).hexdigest(),
                )
            self.service.wait_for_meeting(case_id, payload["calendar_event_id"])
            self.process.ensure(case_id, meeting["client_id"])
            if not self.store.project_list(self.settings.manager_id) or not any(
                p["case_id"] == case_id
                for p in self.store.project_list(self.settings.manager_id)
            ):
                self.store.register_project(
                    case_id,
                    case_id,
                    event.get("summary", "Reunión inicial"),
                    "Cliente registrado",
                    self.settings.manager_id,
                )
            if self.settings.pubsub_topic:
                self.ensure_subscription(space)

    def _transcript(self, payload, job_id):
        subscription = self._source_subscription(payload["source"])
        transcript = self.google.transcript(payload["transcript"])
        conference = transcript["conference"]
        if not conference.get("endTime") or not transcript.get("text", "").strip():
            raise ProviderError("completed_meeting_transcript_required")
        if conference.get("space") != subscription["space"]:
            raise ConfigurationError("conference_subscription_mismatch")
        began = timestamp(conference["startTime"])
        meetings = [
            m
            for m in self.store.list("meeting")
            if m.get("space") == conference["space"]
            and m["status"] == "scheduled"
            and timestamp(m["start"]) - 3600 <= began <= timestamp(m["end"]) + 3600
        ]
        if len(meetings) != 1:
            raise ProviderError("conference_requires_unambiguous_meeting")
        meeting = meetings[0]
        case_id = meeting["case_id"]
        self.store.put(
            f"transcript:{case_id}",
            "transcript",
            {
                "case_id": case_id,
                "text": transcript["text"],
                "sources": transcript["sources"],
                "conference_record": conference["name"],
            },
        )
        # Stable conference identity deduplicates notifications for multiple segments/events.
        self.process.ensure(case_id, meeting["client_id"])
        self.process.internal(
            case_id,
            f"transcript.available:{conference['name']}",
            "transcript.available",
        )
        self.service.start(
            case_id, conference["name"], transcript["text"], transcript["text"]
        )
        self.store.event(
            f"processed:{job_id}",
            case_id,
            "transcript.processed",
            {
                "conference_record": conference["name"],
                "source_resources": transcript["sources"],
            },
        )

    def run_once(self):
        with self.worker_lock.hold():
            return self._run_once()

    def _run_once(self):
        job = self.store.claim()
        if not job:
            return False
        try:
            if job["kind"] == "calendar":
                self._calendar(job["payload"])
            elif job["kind"] == "calendar_sync":
                from app.workflow.calendar_sync import CalendarSync

                CalendarSync(self).sync(job["payload"]["calendar_id"])
            elif job["kind"] == "meet_transcript":
                self._transcript(job["payload"], job["id"])
            elif job["kind"] == "captured_transcript":
                from app.workflow.transcripts import process_capture

                process_capture(self, job["payload"], job["id"])
            elif job["kind"] == "process_event":
                self.process.apply(job["payload"]["case_id"], job["payload"]["event"])
            elif job["kind"] == "board_rejection":
                receipt = self.board_rejections.deliver(job["payload"])
                self.store.finish_job(job["id"], receipt=receipt)
                return True
            elif job["kind"] == "preparation_command":
                self._preparation_command(job["payload"])
            elif job["kind"] == "renew":
                self.ensure_subscription(
                    self._source_subscription(job["payload"]["source"])["space"]
                )
            elif job["kind"] == "slack":
                notice = job["payload"]
                if notice["manager_id"] != self.settings.manager_id:
                    raise ConfigurationError("notification_manager_mismatch")
                current = self.store.get(f"status:{notice['case_id']}")
                if current != notice:
                    self.store.finish_job(job["id"], status="superseded")
                    return True
                receipt = self.notifier.send(
                    notice, str(uuid.uuid5(uuid.NAMESPACE_URL, job["id"]))
                )
                self.store.finish_job(job["id"], receipt=receipt)
                self.store.event(
                    f"sent:{job['id']}", notice["case_id"], "notification.sent", receipt
                )
                return True
            else:
                raise ValueError("Tipo de tarea desconocido.")
            self.store.finish_job(job["id"])
        except BoardDecisionBlocked as error:
            self.store.finish_job(
                job["id"],
                status="failed",
                error=str(error)[:120],
                receipt={"status": "blocked", "reason": str(error)},
            )
        except ConfigurationError as error:
            self.store.finish_job(job["id"], status="failed", error=str(error))
        except ProviderError as error:
            status = (
                "uncertain"
                if error.ambiguous
                else ("failed" if job["attempts"] >= 20 else "pending")
            )
            self.store.finish_job(
                job["id"],
                status=status,
                delay=max(error.retry_after, min(300, 2 ** job["attempts"])),
                error=str(error),
            )
        except Busy:
            self.store.finish_job(
                job["id"], status="pending", delay=5, error="case_busy"
            )
        except Exception as error:
            # Retain the event, but never log provider bodies, tokens or transcripts.
            self.store.finish_job(
                job["id"], status="failed", error=type(error).__name__
            )
            logger.warning("Workflow job failed: %s", type(error).__name__)
        return True

    def poll_google(self):
        if not self.settings.pubsub_subscription:
            return
        messages = self.google.pull(self.settings.pubsub_subscription)
        for received in messages:
            try:
                self.receive_message(received["message"])
            except (ValueError, TypeError, KeyError):
                message_id = received["message"].get("messageId", uuid.uuid4().hex)
                self.store.event(f"invalid:{message_id}", None, "pubsub.quarantined")
            self.google.acknowledge(
                self.settings.pubsub_subscription, [received["ackId"]]
            )

    def maintenance(self):
        self.deliver_post_calls()
        if self.settings.calendar_webhook_url:
            from app.workflow.calendar_sync import CalendarSync

            CalendarSync(self).subscribe()
        # Legacy offline demo reconciliation; live Calendar changes use events.watch.
        if (
            self.settings.mode == "mock"
            and self.client_lookup
            and self.settings.google_token_file
        ):
            for event in self.google.calendar_events(self.settings.calendar_id):
                properties = event.get("extendedProperties", {}).get("private", {})
                code = properties.get("workflow_client_code")
                if not code or event.get("status") == "cancelled":
                    continue
                client = self.client_lookup(code)
                if (
                    not client
                    or not client.enabled
                    or not any(
                        a.get("email", "").casefold() == client.company_email.casefold()
                        for a in event.get("attendees", [])
                    )
                ):
                    continue
                self.register_meeting(
                    {
                        "calendar_id": self.settings.calendar_id,
                        "calendar_event_id": event["id"],
                        "operation": "scheduled",
                        "version": event.get("etag", ""),
                    },
                    client.client_id,
                )
        for subscription in self.store.list("subscription"):
            active = any(
                m.get("space") == subscription["space"] and m["status"] == "scheduled"
                for m in self.store.list("meeting")
            )
            if active:
                try:
                    self.ensure_subscription(subscription["space"])
                    self.reconcile_conferences(subscription["space"])
                except ProviderError:
                    logger.warning("Workspace subscription needs retry")

    def deliver_post_calls(self):
        if not self.settings.post_call_dir or not self.client_lookup:
            return
        import os

        from app.workflow.receipts import accept_call_receipt

        for path in self.settings.post_call_dir.glob("*.json"):
            try:
                receipt = json.loads(path.read_text())
                accept_call_receipt(
                    self,
                    receipt,
                    os.getenv("CALENDAR_ACCESS_SERVICE_KEY", ""),
                    self.client_lookup,
                )
                path.unlink(missing_ok=True)
            except (FileNotFoundError, Busy):
                # HTTP delivery and the worker may acknowledge the same receipt concurrently.
                continue
            except (ValueError, KeyError, TypeError):
                try:
                    path.rename(path.with_suffix(".invalid"))
                except FileNotFoundError:
                    pass
                logger.warning("Invalid post-call receipt quarantined for inspection")

    def reconcile_conferences(self, space):
        for conference in self.google.conferences(space):
            if not conference.get("endTime"):
                continue
            current = self.store.get(f"subscription:{space}")
            if not current or not current.get("name"):
                continue
            if any(
                t.get("conference_record") == conference["name"]
                for t in self.store.list("transcript")
            ):
                continue
            transcripts = self.google.transcripts(conference["name"])
            if transcripts:
                self.store.receive(
                    f"reconcile:{conference['name']}",
                    "meet_transcript",
                    {
                        "transcript": transcripts[0]["name"],
                        "source": f"//workspaceevents.googleapis.com/{current['name']}",
                    },
                )

    def owned_cases(self):
        visible = {
            m["case_id"]: {
                "case_id": m["case_id"],
                "status": m["status"],
                "revision": 0,
            }
            for m in self.store.list("meeting")
            if m["manager_id"] == self.settings.manager_id
        }
        visible.update(
            {
                s["case_id"]: s
                for s in self.store.list("status")
                if s["manager_id"] == self.settings.manager_id
            }
        )
        for project in self.store.project_list(self.settings.manager_id):
            visible[project["case_id"]] = {
                **visible.get(project["case_id"], {}),
                **project,
            }
        for process in self.store.list("process"):
            if process["case_id"] in visible:
                visible[process["case_id"]]["process"] = process
        return list(visible.values())

    def open_preparation(self, project_id=""):
        cases = self.owned_cases()
        if not project_id:
            return {
                "mode": self.settings.mode,
                "status": "project_selection_required" if cases else "no_projects",
                "question": "¿Con cuál proyecto querés trabajar?"
                if cases
                else "Todavía no hay proyectos preparados.",
                "projects": cases,
            }
        selected = [
            c for c in cases if project_id in {c.get("project_id"), c["case_id"]}
        ]
        if len(selected) != 1:
            raise ValueError("Elegir uno de los proyectos de la lista.")
        project = selected[0]
        if project.get("status") not in {"awaiting_review", "ready_for_stage_2"}:
            return {
                "status": project.get("status"),
                "project": project,
                "message": "Los insumos todavía no están listos; la preparación continúa de forma autónoma.",
            }
        state = self.service.get(project["case_id"])["state"]
        artifact = self.store.get(f"artifact:{project['case_id']}:{state['revision']}")
        return {
            "status": state["status"],
            "mode": self.settings.mode,
            "project": project,
            "revision": state["revision"],
            "review_subject": state.get("review_subject", "presentation"),
            "pending": self.service.get(project["case_id"])["pending"],
            "package": state.get("package"),
            "documents": artifact["documents"] if artifact else {},
            "comments": self.store.case_notes(project["case_id"]),
            "handoffs": self.store.case_handoffs(project["case_id"]),
        }

    def artifact(self, case_id, name, revision):
        self.service._owned(case_id)
        artifact = self.store.get(f"artifact:{case_id}:{revision}")
        if not artifact or name not in artifact["documents"]:
            raise ValueError("Insumo inexistente para esa revisión.")
        return {
            "case_id": case_id,
            "revision": revision,
            "name": name,
            "content": artifact["documents"][name],
            "package": artifact["package"],
        }
