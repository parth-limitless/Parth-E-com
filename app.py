"""
Root Application Entry Point for Cloud Deployment (Render / Railway / Heroku)
Redirects execution into the inner spice-nest-hub package cleanly.
"""
import os
import sys
from pathlib import Path

# Add inner spice-nest-hub to sys.path and switch working directory
inner_dir = Path(__file__).resolve().parent / "spice-nest-hub"
if str(inner_dir) not in sys.path:
    sys.path.insert(0, str(inner_dir))

os.chdir(inner_dir)
from app import app, init

if __name__ == "__main__":
    init()
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Cloud Server starting on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
