#!/usr/bin/env python
"""
Launcher for eDNA LPT Connectivity Dashboard
Starts API server + Streamlit app together with live logging
"""

import subprocess
import sys
import time
# import requests
import threading
from pathlib import Path


def read_output_stream(process, startup_event=None):
    """Read and print output from a process, optionally signal on startup."""
    try:
        for line in iter(process.stdout.readline, ''):
            if line:
                print(line, end='', flush=True)
                if startup_event and ("Application startup complete" in line or "Uvicorn running on" in line):
                    startup_event.set()
    except Exception:
        pass


if __name__ == "__main__":
    project_root = Path(__file__).parent
    sys.path.insert(0, str(project_root))
    
    # Start API server in background
    print("[START] Starting API server...")
    api_launcher = project_root / "src" / "api" / "launcher.py"
    startup_event = threading.Event()
    
    api_process = subprocess.Popen(
        [sys.executable, str(api_launcher)],
        cwd=str(project_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
    )
    
    # Start a thread to read and display API server output
    output_thread = threading.Thread(
        target=read_output_stream,
        args=(api_process, startup_event),
        daemon=True,
    )
    output_thread.start()
    
    # Wait for API startup signal or timeout
    print("[WAIT] Waiting for API full initialization...")
    if startup_event.wait(timeout=120):
        print("[OK] API fully initialized!")
        time.sleep(1)
    else:
        print("[!] API startup timeout, but continuing...")
    
    try:
        # Run Streamlit with app.py
        print("[START] Starting Streamlit app...")
        app_path = project_root / "src" / "ui" / "app.py"
        
        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.headless",
            "true",
            "--server.address",
            "localhost",
        ]
        
        # Add port if provided via command line (from workspace launcher)
        # Otherwise let Streamlit pick automatically
        cmd.extend(sys.argv[1:])
        
        # Execute streamlit (blocks until user closes it)
        subprocess.run(cmd, cwd=str(project_root))
        
    finally:
        # Cleanup: Kill API server when Streamlit closes
        print("\n[STOP] Shutting down API server...")
        api_process.terminate()
        try:
            api_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            api_process.kill()
        print("[OK] All services stopped")
