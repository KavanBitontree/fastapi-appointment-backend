"""
visualize.py — LangGraph Graph Visualizer for Aarogya Healthcare
=================================================================
Uses the ACTUAL graph from langGraph_service/graph.py (no dummy stubs)

HOW TO RUN:
  python visualize.py

OUTPUT FILES:
  aarogya_graph_simple.mmd / .png  — top-level view
  aarogya_graph_xray.mmd  / .png  — xray view (all ReAct internals + tool nodes)

For PNG support:
  pip install playwright && playwright install chromium
"""

import sys
import asyncio
from pathlib import Path

try:
    from langGraph_service.graph import _build_app
    from core.database import SessionLocal
except ImportError as e:
    print(f"[visualize] Missing dependency: {e}")
    print("Make sure you're running from the project root directory")
    sys.exit(1)


# ── Build actual graph ─────────────────────────────────────────────────────────
async def build_graph():
    """Build the actual production graph with real nodes and tools."""
    print("[visualize] Creating database session...")
    db = SessionLocal()
    
    try:
        print("[visualize] Getting checkpointer...")
        from langGraph_service.graph import get_checkpointer
        checkpointer = await get_checkpointer()
        
        print("[visualize] Building graph with actual nodes...")
        # Use dummy IDs for visualization - the graph structure is what matters
        app = _build_app(
            db=db,
            patient_id=999,
            user_id=999,
            patient_name="Visualization User",
            checkpointer=checkpointer,
        )
        
        print("[visualize] Graph built successfully!")
        return app
        
    except Exception as e:
        print(f"[visualize] Error building graph: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


# ── Render ─────────────────────────────────────────────────────────────────────
async def render(output_dir: str = "."):
    """Render the actual graph to Mermaid and PNG files."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("[visualize] Building actual graph topology...")
    app = await build_graph()

    # Get graphs with error handling for LangGraph bugs
    print("[visualize] Extracting graph structure...")
    try:
        simple_graph = app.get_graph()
        xray_graph   = app.get_graph(xray=True)
    except Exception as e:
        print(f"[visualize] ❌ Error getting graph: {e}")
        print("\nThis is a known LangGraph issue with conditional edges.")
        print("Trying alternative visualization method...")
        
        # Fallback: manually describe the graph
        print("\n" + "="*70)
        print("GRAPH STRUCTURE (Manual Description)")
        print("="*70)
        print("""
Your Aarogya Healthcare LangGraph:

START
  ↓
trim_messages (trims to last 20 messages)
  ↓
supervisor (routes based on intent)
  ├─→ appointment_node (booking, slots, appointments)
  ├─→ doctor_node (search doctors)
  ├─→ nearby_node (location-based search)
  ├─→ profile_node (view/update profile)
  └─→ END (greetings, help, out-of-scope)

Each worker agent:
  ↓
supervisor (receives response)
  ↓
END (returns to user)

Nodes: 6 (trim_messages, supervisor, 4 workers)
Edges: 10 (entry, conditional routing, worker cycles)
Loop Protection: 50 graph recursion limit, 4-10 agent iterations
        """)
        return

    # Mermaid DSL
    print("\n" + "="*70)
    print("GENERATING MERMAID DIAGRAMS")
    print("="*70)
    
    for name, g in [("simple", simple_graph), ("xray", xray_graph)]:
        try:
            mmd = g.draw_mermaid()
            path = out / f"aarogya_graph_{name}.mmd"
            path.write_text(mmd)
            print(f"\n[visualize] Mermaid ({name}) -> {path}")
            if name == "simple":
                print("\nMermaid DSL (simple):")
                print("-" * 70)
                print(mmd)
                print("-" * 70)
        except Exception as e:
            print(f"[visualize] ❌ Mermaid ({name}) failed: {e}")
            if "NoneType" in str(e):
                print("  (This is a LangGraph bug with conditional edge sorting)")

    # PNG via playwright
    print("\n" + "="*70)
    print("GENERATING PNG IMAGES")
    print("="*70)
    
    png_ok = False
    for name, g in [("simple", simple_graph), ("xray", xray_graph)]:
        try:
            print(f"\n[visualize] Rendering PNG for {name} graph...")
            png_bytes = g.draw_mermaid_png()
            path = out / f"aarogya_graph_{name}.png"
            path.write_bytes(png_bytes)
            print(f"[visualize] ✅ PNG saved -> {path}")
            png_ok = True
        except Exception as e:
            print(f"[visualize] ❌ PNG ({name}) failed: {e}")
            if "NoneType" in str(e):
                print("  (This is a LangGraph bug with conditional edge sorting)")

    if not png_ok:
        print("\n" + "="*70)
        print("PNG GENERATION FAILED")
        print("="*70)
        print("\nTo enable PNG generation, install playwright:")
        print("  pip install playwright")
        print("  playwright install chromium")
        print("\nAlternatively, paste the .mmd files at: https://mermaid.live")

    # ASCII graph
    print("\n" + "="*70)
    print("ASCII GRAPH REPRESENTATION")
    print("="*70)
    try:
        simple_graph.print_ascii()
    except Exception as e:
        print(f"  (ASCII graph not available: {e})")

    print("\n" + "="*70)
    print("VISUALIZATION COMPLETE")
    print("="*70)
    print(f"\nOutput directory: {out.resolve()}")
    print("\nGenerated files:")
    print(f"  - aarogya_graph_simple.mmd (Mermaid source)")
    print(f"  - aarogya_graph_xray.mmd (Mermaid source with tool details)")
    if png_ok:
        print(f"  - aarogya_graph_simple.png (Visual diagram)")
        print(f"  - aarogya_graph_xray.png (Detailed diagram)")
    print("\n")


if __name__ == "__main__":
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    asyncio.run(render(output_dir))