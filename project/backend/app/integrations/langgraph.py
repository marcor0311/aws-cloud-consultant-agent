"""Translate the application's execution contract to the existing LangGraph API."""

from langgraph.types import Command

from app.workflow.ports import WorkflowSnapshot


class LangGraphExecution:
    def __init__(self, graph):
        self._graph = graph

    @staticmethod
    def _config(thread_id):
        return {"configurable": {"thread_id": thread_id}}

    def inspect(self, thread_id):
        snapshot = self._graph.get_state(self._config(thread_id))
        pending = [i.value for task in snapshot.tasks for i in task.interrupts]
        return WorkflowSnapshot(
            state=dict(snapshot.values),
            pending=pending,
            runnable=bool(snapshot.next) and not pending,
            checkpoint_id=(snapshot.config or {})
            .get("configurable", {})
            .get("checkpoint_id"),
        )

    def start(self, thread_id, state):
        self._graph.invoke(state, self._config(thread_id))

    def resume(self, thread_id, value):
        self._graph.invoke(Command(resume=value), self._config(thread_id))

    def continue_run(self, thread_id):
        self._graph.invoke(None, self._config(thread_id))

    def update(self, thread_id, state, *, after_step):
        self._graph.update_state(self._config(thread_id), state, as_node=after_step)
