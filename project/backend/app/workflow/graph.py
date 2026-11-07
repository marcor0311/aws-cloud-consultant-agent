"""Six-stage custom workflow using StateGraph, edges and durable interrupts."""

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.workflow.state import STAGES, TERMINAL, ProcessState
from app.workflow.transitions import transition


def wait_for_event(state):
    # No side effects before interrupt: LangGraph restarts this node on resume.
    event = interrupt(
        {
            "action": "await_process_event",
            "stage": state["stage"],
            "stage_name": STAGES[state["stage"]],
            "iteration": state["iteration"],
            "status": state["status"],
            "revision": state["revision"],
        }
    )
    return transition(state, event)


def destination(state):
    return END if state["status"] in TERMINAL else STAGES[state["stage"]]


def build_process_graph(checkpointer):
    graph = StateGraph(ProcessState)
    destinations = {name: name for name in STAGES.values()} | {END: END}
    for name in STAGES.values():
        graph.add_node(name, wait_for_event)
        graph.add_conditional_edges(name, destination, destinations)
    graph.add_edge(START, STAGES[1])
    return graph.compile(checkpointer=checkpointer)
