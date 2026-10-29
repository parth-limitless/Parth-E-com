"""
Spice Nest Hub - 24-Hour Automated Sync & GitHub Pages Publisher
================================================================
1. Runs local headless price & stock check (genuine Indian IP, no ScrapingBee)
2. Updates SQLite database
3. Exports fresh 'docs/index.html' Price Hub dashboard
4. Pushes changes automatically to GitHub
"""

import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

repo_root = Path(__file__).resolve().parent
inner_dir = repo_root / "spice-nest-hub"
python_exe = inner_dir / "venv" / "Scripts" / "python.exe"

def run_cmd(cmd, desc):
    print(f"\n▶ {desc}...")
    res = subprocess.run(cmd, cwd=repo_root, shell=True)
    if res.returncode != 0:
        print(f"⚠️ Warning during {desc} (code {res.returncode})")
    return res.returncode

def main():
    print("=" * 65)
    print(f"🌶️ SPICE NEST HUB - 24H DAILY AUTO SYNC STARTED AT {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 65)

    # 1. Run local price & competitor check
    run_cmd(f'"{python_exe}" spice-nest-hub/check_runner.py', "Running Price & Stock Check")

    # 2. Export updated Price Hub HTML for GitHub Pages
    run_cmd(f'"{python_exe}" export_price_hub.py', "Exporting Price Hub to docs/index.html")

    # 3. Check git changes and auto push to GitHub
    print("\n▶ Checking Git Status & Auto-Pushing to GitHub...")
    subprocess.run("git add docs/ spicenest.db spice-nest-hub/spicenest.db", cwd=repo_root, shell=True)
    
    commit_msg = f"Auto-sync: Daily Price Hub Snapshot [{datetime.now():%Y-%m-%d %H:%M}] [skip ci]"
    res = subprocess.run(f'git commit -m "{commit_msg}"', cwd=repo_root, shell=True)
    if res.returncode == 0:
        print("🚀 Pushing updated dashboard to GitHub...")
        subprocess.run("git push origin main", cwd=repo_root, shell=True)
        print("✅ GitHub Pages updated successfully!")
    else:
        print("ℹ️ No new price changes detected today. Repository is already up to date.")

    print("\n" + "=" * 65)
    print("🏁 24H AUTO SYNC CYCLE FINISHED!")
    print("=" * 65)

if __name__ == "__main__":
    main()
