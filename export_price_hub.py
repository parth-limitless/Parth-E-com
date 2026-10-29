"""
Static Site Exporter for GitHub Pages
=====================================
Exports ONLY the main "Price Hub" dashboard to docs/index.html
so public visitors see the clean Multi-Platform Price Monitoring & Competitor Engine.

All other pages (CLV, Flipkart P&L, Meesho Tracker) remain 100% intact
and accessible when running locally (http://localhost:5000).
"""

import os
import sys

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path

# Add project root and inner directory to path
repo_root = Path(__file__).resolve().parent
inner_dir = repo_root / "spice-nest-hub"
if str(inner_dir) not in sys.path:
    sys.path.insert(0, str(inner_dir))
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

os.chdir(inner_dir)
import app

def export_price_hub_dashboard(output_dir: str = "../docs"):
    """Renders the main Price Hub dashboard and writes docs/index.html for GitHub Pages."""
    print("⏳ Rendering Price Hub dashboard from local database...")
    app.init()

    # Create test client to render exact dynamic HTML template
    client = app.app.test_client()
    resp = client.get("/")

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to render Price Hub dashboard: HTTP {resp.status_code}")

    html_content = resp.data.decode("utf-8")

    # Adapt header for pure GitHub Pages static view:
    # 1. Add "🌶️ Price Hub" active badge matching user screenshot
    # 2. Hide dead backend-only links on static GitHub Pages
    gh_header_nav = """
    <div style="display:flex; gap:10px; align-items:center;">
      <span class="btn" style="background: #1e293b; border: 1px solid #3b82f6; color: #fff; padding: 8px 16px; font-weight: 700; border-radius: 8px;">
        🌶️ Price Hub
      </span>
      <span style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: 700;">
        🟢 Live Public Snapshot
      </span>
    </div>
    """

    import re
    # Replace the local buttons block in header for GitHub Pages
    cleaned_html = re.sub(
        r'<div style="display:flex; gap:10px; align-items:center;">.*?<form method="post" action="/check".*?</form>\s*</div>',
        gh_header_nav.strip(),
        html_content,
        flags=re.DOTALL
    )

    # Disable local-only forms on GitHub Pages (Naya SKU add karna local admin feature hai)
    # Target output folder
    out_path = Path(repo_root) / "docs"
    out_path.mkdir(parents=True, exist_ok=True)

    index_file = out_path / "index.html"
    index_file.write_text(cleaned_html, encoding="utf-8")

    # Also add a .nojekyll file so GitHub Pages doesn't ignore any static assets
    (out_path / ".nojekyll").write_text("", encoding="utf-8")

    print(f"✅ Successfully exported Price Hub dashboard to: {index_file}")
    print(f"📦 File Size: {len(cleaned_html):,} bytes")
    return index_file

if __name__ == "__main__":
    export_price_hub_dashboard()
