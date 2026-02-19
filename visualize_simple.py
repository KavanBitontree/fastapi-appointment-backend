"""
Simple Graph Visualizer - Workaround for LangGraph Bug
=======================================================
Creates a manual Mermaid diagram and converts to PNG using Python.

HOW TO RUN:
  python visualize_simple.py

REQUIREMENTS:
  pip install playwright
  playwright install chromium

OUTPUT:
  aarogya_graph_manual.png - PNG image
  aarogya_graph_detailed.png - Detailed PNG image
"""

from pathlib import Path
import sys

# Manual Mermaid diagram of your actual graph structure
MERMAID_DIAGRAM = """%%{init: {'theme':'base', 'themeVariables': { 'primaryColor':'#e3f2fd','primaryTextColor':'#000','primaryBorderColor':'#1976d2','lineColor':'#1976d2','secondaryColor':'#fff3e0','tertiaryColor':'#f3e5f5'}}}%%

graph TD
    START([START])
    END([END])
    
    START --> trim_messages[trim_messages<br/>Keep last 20 messages]
    trim_messages --> supervisor{supervisor<br/>Route by intent}
    
    supervisor -->|appointment intent| appointment_node[appointment_node<br/>ReAct Agent<br/>Max 10 iterations]
    supervisor -->|doctor search| doctor_node[doctor_node<br/>ReAct Agent<br/>Max 6 iterations]
    supervisor -->|nearby search| nearby_node[nearby_node<br/>ReAct Agent<br/>Max 4 iterations]
    supervisor -->|profile update| profile_node[profile_node<br/>ReAct Agent<br/>Max 4 iterations]
    supervisor -->|greeting/help/finish| END
    
    appointment_node --> supervisor
    doctor_node --> supervisor
    nearby_node --> supervisor
    profile_node --> supervisor
    
    style START fill:#4caf50,stroke:#2e7d32,color:#fff
    style END fill:#f44336,stroke:#c62828,color:#fff
    style trim_messages fill:#e3f2fd,stroke:#1976d2
    style supervisor fill:#fff3e0,stroke:#f57c00
    style appointment_node fill:#f3e5f5,stroke:#7b1fa2
    style doctor_node fill:#f3e5f5,stroke:#7b1fa2
    style nearby_node fill:#f3e5f5,stroke:#7b1fa2
    style profile_node fill:#f3e5f5,stroke:#7b1fa2
"""

DETAILED_DIAGRAM = """%%{init: {'theme':'base', 'themeVariables': { 'primaryColor':'#e3f2fd'}}}%%

graph TD
    START([START])
    END([END])
    
    START --> trim_messages[trim_messages]
    trim_messages --> supervisor{supervisor}
    
    supervisor -->|appointment| appointment_node[appointment_node]
    supervisor -->|doctor| doctor_node[doctor_node]
    supervisor -->|nearby| nearby_node[nearby_node]
    supervisor -->|profile| profile_node[profile_node]
    supervisor -->|finish| END
    
    appointment_node --> supervisor
    doctor_node --> supervisor
    nearby_node --> supervisor
    profile_node --> supervisor
    
    subgraph "Appointment Tools"
        apt1[check_can_book_on_date]
        apt2[search_doctor_by_name]
        apt3[get_free_slots]
        apt4[book_slot]
        apt5[get_my_appointments]
    end
    
    subgraph "Doctor Tools"
        doc1[search_doctor_by_name]
        doc2[search_doctor_by_speciality]
        doc3[list_all_specialities]
        doc4[list_all_doctors]
        doc5[get_doctor_by_id]
    end
    
    subgraph "Nearby Tools"
        near1[find_nearby_doctors]
        near2[list_all_specialities]
    end
    
    subgraph "Profile Tools"
        prof1[get_patient_profile]
        prof2[update_patient_name]
        prof3[update_patient_dob]
    end
    
    appointment_node -.-> apt1
    appointment_node -.-> apt2
    appointment_node -.-> apt3
    appointment_node -.-> apt4
    appointment_node -.-> apt5
    
    doctor_node -.-> doc1
    doctor_node -.-> doc2
    doctor_node -.-> doc3
    doctor_node -.-> doc4
    doctor_node -.-> doc5
    
    nearby_node -.-> near1
    nearby_node -.-> near2
    
    profile_node -.-> prof1
    profile_node -.-> prof2
    profile_node -.-> prof3
"""

def mermaid_to_png_builtin(mermaid_code: str, output_path: Path) -> bool:
    """Convert Mermaid code to PNG using Python's built-in mermaid renderer."""
    try:
        from playwright.sync_api import sync_playwright
        
        print(f"  Using Playwright to render PNG...")
        
        # HTML template with Mermaid
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ startOnLoad: true, theme: 'base' }});
    </script>
</head>
<body>
    <div class="mermaid">
{mermaid_code}
    </div>
</body>
</html>
"""
        
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            
            # Load HTML with Mermaid
            page.set_content(html_content)
            
            # Wait for Mermaid to render
            page.wait_for_timeout(2000)
            
            # Find the SVG element
            svg_element = page.locator("svg").first
            
            # Take screenshot
            svg_element.screenshot(path=str(output_path))
            
            browser.close()
        
        return True
        
    except ImportError:
        print("  ❌ Playwright not installed")
        print("     Install with: pip install playwright && playwright install chromium")
        return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_diagrams():
    """Generate Mermaid diagrams and convert to PNG."""
    out = Path(".")
    
    print("="*70)
    print("GENERATING GRAPH VISUALIZATIONS")
    print("="*70)
    
    diagrams = [
        ("manual", MERMAID_DIAGRAM, "Clean topology"),
        ("detailed", DETAILED_DIAGRAM, "With all tools"),
    ]
    
    png_generated = False
    
    for name, mermaid_code, description in diagrams:
        print(f"\n[{name}] {description}")
        
        # Save Mermaid source
        mmd_path = out / f"aarogya_graph_{name}.mmd"
        mmd_path.write_text(mermaid_code)
        print(f"  ✅ Mermaid source: {mmd_path}")
        
        # Convert to PNG
        png_path = out / f"aarogya_graph_{name}.png"
        print(f"  Converting to PNG...")
        
        if mermaid_to_png_builtin(mermaid_code, png_path):
            print(f"  ✅ PNG saved: {png_path}")
            png_generated = True
        else:
            print(f"  ❌ PNG conversion failed")
    
    # Summary
    print("\n" + "="*70)
    print("VISUALIZATION COMPLETE")
    print("="*70)
    
    if png_generated:
        print("\n✅ PNG files generated successfully!")
        print("\nGenerated files:")
        print("  📄 aarogya_graph_manual.mmd (Mermaid source)")
        print("  🖼️  aarogya_graph_manual.png (PNG image)")
        print("  📄 aarogya_graph_detailed.mmd (Mermaid source)")
        print("  🖼️  aarogya_graph_detailed.png (PNG image)")
    else:
        print("\n⚠️  PNG conversion failed")
        print("\nTo enable PNG generation:")
        print("  pip install playwright")
        print("  playwright install chromium")
        print("\nAlternative: Use online converter")
        print("  1. Go to: https://mermaid.live")
        print("  2. Paste content from .mmd files")
        print("  3. Click 'Download PNG'")
    
    print("\n" + "="*70)

if __name__ == "__main__":
    generate_diagrams()
