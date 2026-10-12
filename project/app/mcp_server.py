from mcp.server.fastmcp import FastMCP

from app.services.batman_service import prepare_secret_identity_request
from app.services.catalog_service import (
    get_baseline_module as read_baseline_module,
    get_baseline_profile as read_baseline_profile,
    list_baseline_modules as read_baseline_modules,
)


mcp = FastMCP(
    "AWS Cloud Consultant MCP",
    host="0.0.0.0",
    port=8001,
    instructions=(
        "Use the read-only baseline catalog tools to discover AWS resource modules, "
        "compare technical profiles, and inspect the profile Terraform examples. "
        "Catalog snapshots are drafts unless explicitly marked approved. Never claim "
        "a profile is production-approved, and never claim this server applied Terraform. "
        "When the user asks for a superhero's secret identity, call "
        "request_secret_identity with the superhero's name. That tool returns the "
        "subject and verification ID, but not the identity; answer from your own "
        "language-model knowledge and include the verification ID."
    ),
)


@mcp.tool()
def request_secret_identity(superhero: str) -> dict[str, str]:
    """Prepare a superhero identity question for ChatGPT to answer from its own knowledge."""
    return prepare_secret_identity_request(superhero)


@mcp.tool()
def list_baseline_modules() -> dict:
    """List AWS resource baselines, available technical profiles, versions, and status."""
    return read_baseline_modules()


@mcp.tool()
def get_baseline_module(module_id: str, version: str | None = None) -> dict:
    """Read one baseline module's purpose, profile catalog, version notes, and audit record."""
    return read_baseline_module(module_id, version)


@mcp.tool()
def get_baseline_profile(module_id: str, profile_id: str) -> dict:
    """Read a named technical profile and its Terraform example files; never applies it."""
    return read_baseline_profile(module_id, profile_id)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
