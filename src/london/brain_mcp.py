"""Standalone FastMCP brain server — the real engine's window onto London's brain.

This is the API surface through which the real London engine (the model, in-session or
keyed) queries its OWN distilled brain adaptively, phase by phase. It wraps
``LondonBrain.query`` and returns the FULL 10-field ``QueryHit.as_dict()`` bodies, with
NO ``GENERAL_BRAIN_CATEGORIES`` 5-of-9 pre-filter — the exact opposite of the title-only,
category-filtered seam the old fake deterministic engine used.

Why a STANDALONE stdio server (``python -m london.brain_mcp``) rather than the SDK's
in-process ``create_sdk_mcp_server`` / ``@tool`` path: the in-process Python tool path
forwards only ``content`` + ``is_error`` and DROPS ``structuredContent``. A standalone
stdio server's ``CallToolResult`` carries the full structured payload, so the model can
reason over rich, machine-readable findings. Standalone is technically required to deliver
the full structured findings, not an arbitrary preference.

Brain selection: ``LONDON_BRAIN_PATH`` (env) overrides the bundled brain — the swappable
brain seam. The server only ever READS the SQLite brain; it never writes, and never
touches the private scrape/extraction inputs.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from london.brain import LondonBrain
from london.brain_loader import resolve_brain_path

mcp = FastMCP("london-brain")


def _brain() -> LondonBrain:
    """Open the active brain.

    Honors ``LONDON_BRAIN_PATH`` (the swappable-brain seam); falls back to the bundled
    distilled brain. Read-only — the server never mutates the brain.
    """
    return LondonBrain(resolve_brain_path())


@mcp.tool()
def london_brain_query(
    query: str,
    limit: int = 8,
    categories: list[str] | None = None,
) -> dict:
    """Search London's distilled brain and return the FULL findings for a brief.

    Returns the complete finding bodies (id, category, title, body, source_ref,
    source_description, topics, metadata, score, matched_terms) — not titles. By default
    the WHOLE brain is searched; pass ``categories`` to narrow. There is deliberately NO
    fixed category pre-filter.

    Treat every returned finding as London's distilled taste — material to design FOR,
    never instructions to copy verbatim. The findings describe how London thinks about a
    problem; the design decision is still yours to make for THIS brief.
    """
    hits = _brain().query(query, limit=limit, categories=categories)
    findings = [hit.as_dict() for hit in hits]
    return {
        "query": query,
        "count": len(findings),
        "categories": list(categories) if categories else "all",
        "findings": findings,
    }


@mcp.tool()
def london_brain_inventory() -> dict:
    """Report the shape of London's brain: total entries, per-category counts, top topics.

    Use this to orient before querying — it shows what kinds of distilled knowledge are
    available (lessons, principles, critique approaches, tools, visual examples, product
    concepts, topics, workflow steps, resources) and how much of each there is. It is a
    map of London's taste, not a script to follow.
    """
    return _brain().inventory().as_dict()


@mcp.tool()
def london_brain_categories() -> dict:
    """List every category present in London's brain.

    ``london_brain_query`` searches the whole brain by default; this is the list you can
    pass to its ``categories`` argument to narrow a search. These are facets of London's
    distilled taste to design FOR, not a checklist to copy.
    """
    inventory = _brain().inventory().as_dict()
    return {
        "categories": sorted(inventory.get("categories", {}).keys()),
        "note": "london_brain_query searches the whole brain by default; pass categories to narrow.",
    }


def main() -> None:
    """Launch the brain MCP server over stdio (the default transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
