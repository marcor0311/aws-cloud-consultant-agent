"""A real model tool call inside LangGraph, followed by an actual MCP exchange."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class LiveOpeningState(TypedDict, total=False):
    case_id: str
    execution_id: str
    model: str
    mock_board: bool
    preflight: dict
    inference: dict
    delivery: dict


def build_live_opening_graph(checkpointer, mcp, infer):
    def preflight(state):
        return {"preflight": mcp.preflight(state["case_id"])}

    def model(state):
        return {"inference": infer(state)}

    def execute(state):
        call = state["inference"]
        expected = {
            "expediente_id": state["case_id"],
            "decision_sha256": state["preflight"]["result"]["request_sha256"],
        }
        if call["name"] != "ejecutar_apertura" or call["arguments"] != expected:
            raise ValueError("El modelo intentó ejecutar otra decisión o expediente.")
        return {"delivery": mcp.execute(call["name"], call["arguments"])}

    graph = StateGraph(LiveOpeningState)
    graph.add_node("mcp_preflight", preflight)
    graph.add_node("chatgpt_oauth", model)
    graph.add_node("mcp_github_opening", execute)
    graph.add_edge(START, "mcp_preflight")
    graph.add_edge("mcp_preflight", "chatgpt_oauth")
    graph.add_edge("chatgpt_oauth", "mcp_github_opening")
    graph.add_edge("mcp_github_opening", END)
    return graph.compile(checkpointer=checkpointer)
