"""Build preparation with LangGraph's documented custom-workflow pattern."""

from langgraph.graph import END, START, StateGraph

from app.preparation.nodes import PreparationNodes
from app.preparation.references import search_references
from app.preparation.state import PreparationState


def after_review(state):
    subject = state.get("review_subject", "presentation")
    if state["decision"] == "revise":
        return "revise_speaker_notes" if subject == "speaker_notes" else "revise"
    return subject


def build_graph(checkpointer, search=search_references, drafter=None, store=None):
    nodes = PreparationNodes(search, drafter, store)
    graph = StateGraph(PreparationState)
    graph.add_node("wait_for_meeting", nodes.wait_for_meeting)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("draft", nodes.draft)
    graph.add_node("review", nodes.review)
    graph.add_node("generate_speaker_notes", nodes.generate_speaker_notes)
    graph.add_node("revise_speaker_notes", nodes.revise_speaker_notes)
    graph.add_node("handoff", nodes.handoff)
    graph.add_conditional_edges(
        START,
        lambda state: (
            "meeting"
            if state.get("calendar_event_id") and not state.get("transcript")
            else "prepare"
        ),
        {"meeting": "wait_for_meeting", "prepare": "retrieve"},
    )
    graph.add_conditional_edges(
        "wait_for_meeting",
        lambda state: state.get("status") == "meeting_cancelled",
        {True: END, False: "retrieve"},
    )
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", "review")
    graph.add_conditional_edges(
        "review",
        after_review,
        {
            "presentation": "generate_speaker_notes",
            "speaker_notes": "handoff",
            "revise": "draft",
            "revise_speaker_notes": "revise_speaker_notes",
        },
    )
    graph.add_edge("generate_speaker_notes", "review")
    graph.add_edge("revise_speaker_notes", "review")
    graph.add_edge("handoff", END)
    return graph.compile(checkpointer=checkpointer)
