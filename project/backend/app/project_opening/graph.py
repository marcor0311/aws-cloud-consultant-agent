"""LangGraph executes approved work; every remote step reconciles before retrying."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.project_opening.ports import ProjectGitHub


class OpeningState(TypedDict, total=False):
    case_id: str
    repository: dict
    commit: dict
    pull_request: dict
    issue: dict
    status: str
    board_approval: dict


def build_opening_graph(
    checkpointer,
    repository,
    github: ProjectGitHub,
    documents,
    issue_renderer,
    board_approval,
):
    def approve_board(state):
        certificate = board_approval(state["case_id"])
        repository.accept_board(state["case_id"], certificate)
        repository.update(
            state["case_id"], board_approval=certificate, status="board_approved"
        )
        return {"board_approval": certificate}

    def create_repo(state):
        record = repository.get(state["case_id"])
        result = github.ensure_repository(record)
        repository.update(
            state["case_id"], repository=result, status="repository_ready"
        )
        return {"repository": result}

    def upload(state):
        record = repository.get(state["case_id"])
        result = github.publish(record, documents(record))
        repository.update(state["case_id"], commit=result, status="documents_ready")
        return {"commit": result}

    def merge(state):
        record = repository.get(state["case_id"])
        result = github.merge_initial_structure(record)
        repository.update(
            state["case_id"],
            pull_request=result,
            status="initial_structure_merged"
            if result["merged"]
            else "awaiting_initial_structure_merge",
        )
        if not result["merged"]:
            raise ValueError("initial_structure_merge_pending")
        return {"pull_request": result}

    def assign(state):
        record = repository.get(state["case_id"])
        if not record.get("pull_request", {}).get("merged"):
            raise ValueError("initial_structure_pr_requires_reconciliation")
        body, template = issue_renderer(record)
        result = github.assign_architecture(record, body, template)
        if result.get("assignment_pending"):
            repository.update(
                state["case_id"], issue=result, status="awaiting_architect_access"
            )
            raise ValueError("architect_invitation_pending")
        repository.update(state["case_id"], issue=result, status="issue_ready")
        return {"issue": result}

    def deliver(state):
        record = repository.get(state["case_id"])
        repository.deliver(record)
        repository.update(state["case_id"], status="delivered")
        return {"status": "delivered"}

    graph = StateGraph(OpeningState)
    for name, node in [
        ("board_approval", approve_board),
        ("repository", create_repo),
        ("documents", upload),
        ("initial_structure_pr", merge),
        ("architect", assign),
        ("handoff", deliver),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "board_approval")
    graph.add_edge("board_approval", "repository")
    graph.add_edge("repository", "documents")
    graph.add_edge("documents", "initial_structure_pr")
    graph.add_edge("initial_structure_pr", "architect")
    graph.add_edge("architect", "handoff")
    graph.add_edge("handoff", END)
    return graph.compile(checkpointer=checkpointer)
