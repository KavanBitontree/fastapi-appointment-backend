"""
visualize.py
============
Generates a PNG of the LangGraph chatbot graph INCLUDING RUNTIME JUMPS.

Why runtime jumps aren't shown by default:
  LangGraph's draw_mermaid_png() only renders *declared* edges (add_edge /
  add_conditional_edges). Runtime Command(goto=...) jumps are invisible to it.
  We fix this by:
    1. Getting the raw Mermaid string from the compiled graph.
    2. Injecting the runtime jump edges manually with a distinct orange style.
    3. Rendering the patched Mermaid string to PNG.

Runtime jumps in this graph:
  doctor_handler ──► appointment_handler
    (triggered when doctor found AND date already in context)

Usage:
    # From project root:
    python tests/visualize.py

Output:
    graph.png  — saved next to this file.

Requirements:
    pip install playwright
    playwright install chromium
"""

import sys
import asyncio
from pathlib import Path

# ── Make project root importable ─────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiosqlite
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from langGraph_service.schemas.state import ChatbotState


# ── Runtime jumps to inject ───────────────────────────────────────────────────
# These are Command(goto=...) jumps inside nodes — not declared as graph edges.
# Format: (from_node, to_node, label)
RUNTIME_JUMPS = [
    ("doctor_handler", "appointment_handler", "runtime: doctor found + date in ctx"),
]


# ── Intent router (mirrors main_graph._route_intent exactly) ─────────────────

def _route_intent(state: ChatbotState) -> str:
    classification = state.get("classification")
    intent = classification.intent if classification else "out_of_scope"
    return {
        "appointment":    "appointment_handler",
        "doctor_search":  "doctor_handler",
        "nearby_doctors": "nearby_doctor_handler",
        "profile":        "profile_handler",
        "greeting":       "response_handler",
        "help":           "response_handler",
        "out_of_scope":   "response_handler",
    }.get(intent, "response_handler")


# ── Graph builder (stub version — no real DB needed) ─────────────────────────

def _build_visualization_graph(checkpointer: AsyncSqliteSaver):
    """
    Mirrors main_graph._build_app() exactly but uses lambda stubs
    instead of real DB-dependent handlers — no DB session required.
    """
    workflow = StateGraph(ChatbotState)

    # Nodes
    workflow.add_node("classify_intent",       lambda s: s)
    workflow.add_node("appointment_handler",   lambda s: s)
    workflow.add_node("doctor_handler",        lambda s: s)
    workflow.add_node("nearby_doctor_handler", lambda s: s)
    workflow.add_node("profile_handler",       lambda s: s)
    workflow.add_node("response_handler",      lambda s: s)

    # Edges — exact mirror of main_graph._build_app()
    workflow.add_edge(START, "classify_intent")

    workflow.add_conditional_edges(
        "classify_intent",
        _route_intent,
        {
            "appointment_handler":   "appointment_handler",
            "doctor_handler":        "doctor_handler",
            "nearby_doctor_handler": "nearby_doctor_handler",
            "profile_handler":       "profile_handler",
            "response_handler":      "response_handler",
        },
    )

    for handler in [
        "appointment_handler",
        "doctor_handler",
        "nearby_doctor_handler",
        "profile_handler",
    ]:
        workflow.add_edge(handler, "response_handler")

    workflow.add_edge("response_handler", END)

    return workflow.compile(checkpointer=checkpointer)


# ── Mermaid patcher ───────────────────────────────────────────────────────────

def _inject_runtime_jumps(mermaid_str: str, jumps: list[tuple[str, str, str]]) -> str:
    """
    Injects runtime jump edges into the raw Mermaid diagram string.

    - Uses dashed orange arrows  (-.->) to distinguish from declared edges.
    - linkStyle overrides color them orange so they stand out visually.

    Args:
        mermaid_str : Raw Mermaid string from app.get_graph().draw_mermaid()
        jumps       : List of (from_node, to_node, label) tuples

    Returns:
        Patched Mermaid string.
    """
    if not jumps:
        return mermaid_str

    lines = mermaid_str.strip().splitlines()

    # Count existing edge lines to know linkStyle indices for our injected edges
    existing_edge_count = sum(
        1 for line in lines
        if ("-->" in line or "-.->" in line or "==>" in line)
        and not line.strip().startswith("%%")
    )

    # Build jump edge lines (dashed arrow with label)
    jump_lines = [
        "",
        "    %% ── Runtime Jumps (Command-based) — shown in orange ──────────────────",
    ]
    for from_node, to_node, label in jumps:
        jump_lines.append(f'    {from_node} -.->|"{label}"| {to_node}')

    # Build linkStyle overrides to color runtime jump edges orange
    style_lines = []
    for i in range(len(jumps)):
        edge_idx = existing_edge_count + i
        style_lines.append(
            f"    linkStyle {edge_idx} stroke:#ff6b00,stroke-width:2.5px,stroke-dasharray:8"
        )

    # Find insertion point: just before classDef lines or at end
    insert_at = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith("classDef") or line.strip().startswith("class "):
            insert_at = i
            break

    patched = lines[:insert_at] + jump_lines + [""] + style_lines + [""] + lines[insert_at:]
    return "\n".join(patched)


# ── PNG renderer ──────────────────────────────────────────────────────────────

async def _render_mermaid_to_png(mermaid_str: str) -> bytes:
    """
    Renders a Mermaid diagram string to PNG bytes using Playwright.
    Falls back to LangGraph's built-in renderer if Playwright unavailable.
    """
    try:
        from playwright.async_api import async_playwright

        html = f"""<!DOCTYPE html>
<html>
<head>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    body {{ margin: 20px; background: white; }}
    .mermaid {{ font-family: sans-serif; }}
  </style>
</head>
<body>
  <div class="mermaid">{mermaid_str}</div>
  <script>
    mermaid.initialize({{
      startOnLoad: true,
      theme: 'default',
      flowchart: {{ curve: 'basis', padding: 20 }},
    }});
  </script>
</body>
</html>"""

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": 1400, "height": 900})
            await page.set_content(html)
            await page.wait_for_timeout(2500)  # let Mermaid render

            # Try to screenshot just the SVG element for a tight crop
            svg = await page.query_selector(".mermaid svg")
            if svg:
                png_bytes = await svg.screenshot(type="png")
            else:
                png_bytes = await page.screenshot(full_page=True, type="png")

            await browser.close()
            return png_bytes

    except ImportError:
        print("⚠️  Playwright not found. Install with:")
        print("    pip install playwright && playwright install chromium")
        print("⚠️  Falling back to LangGraph's built-in renderer (no runtime jumps in PNG)...")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    output_path = Path(__file__).parent / "graph.png"

    # Build graph
    db_path = Path(__file__).parent.parent / "chat_checkpoints.db"
    conn = await aiosqlite.connect(str(db_path))
    checkpointer = AsyncSqliteSaver(conn)
    app = _build_visualization_graph(checkpointer)

    graph_obj = app.get_graph()

    # Get raw Mermaid string
    raw_mermaid = graph_obj.draw_mermaid()
    print("── Raw Mermaid ─────────────────────────────────────────────────────")
    print(raw_mermaid)

    # Inject runtime jumps
    patched_mermaid = _inject_runtime_jumps(raw_mermaid, RUNTIME_JUMPS)
    print("\n── Patched Mermaid (with runtime jumps) ────────────────────────────")
    print(patched_mermaid)

    # Render to PNG
    png_bytes = await _render_mermaid_to_png(patched_mermaid)

    if png_bytes is None:
        # Playwright unavailable — fall back to LangGraph's own renderer (no jumps)
        png_bytes = graph_obj.draw_mermaid_png()

    output_path.write_bytes(png_bytes)

    print(f"\n✅ Graph saved → {output_path.resolve()}")
    print(
        "\n📌 Legend:\n"
        "  Solid arrows   (──►)  = declared graph edges\n"
        "  Dashed arrows  (-.-►) = conditional routing from classify_intent\n"
        "  Orange dashed  (-.-►) = runtime Command jumps\n"
        "                          e.g. doctor_handler → appointment_handler\n"
        "                          when doctor found + date already in context\n"
    )

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())