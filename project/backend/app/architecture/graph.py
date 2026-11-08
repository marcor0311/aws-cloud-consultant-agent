"""LangGraph workflow for Cloud Architecture Agent review."""

from langgraph.graph import END, START, StateGraph

from app.architecture.nodes import ArchitectureNodes
from app.architecture.state import ArchitectureState


def build_graph(checkpointer, catalog):
    nodes = ArchitectureNodes(catalog)
    graph = StateGraph(ArchitectureState)
    graph.add_node("validate_architecture", nodes.validate)
    graph.add_node("architect_review", nodes.review)
    graph.add_node("handoff_finops", nodes.handoff)
    graph.add_edge(START, "validate_architecture")
    graph.add_edge("validate_architecture", "architect_review")
    graph.add_conditional_edges(
        "architect_review",
        lambda state: state["decision"],
        {"approve": "handoff_finops", "revise": END},
    )
    graph.add_edge("handoff_finops", END)
    return graph.compile(checkpointer=checkpointer)
