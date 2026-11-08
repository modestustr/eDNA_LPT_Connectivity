#!/usr/bin/env python
"""
Standalone FastAPI Server Launcher
===================================
Run the simulation service as a standalone HTTP server.

Usage:
    python run_api_server.py                    # Local server on :8000
    python run_api_server.py --host 0.0.0.0 --port 9000

Requires:
    pip install fastapi uvicorn

Then connect from app.py with:
    from api_init import initialize_simulation_api
    api_client = initialize_simulation_api(
        simulation_runner,
        http_server_url="http://localhost:8000"
    )
"""

import argparse
import sys
import traceback
from pathlib import Path

# Add project root to path so imports work
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import uvicorn
except ImportError:
    print("ERROR: FastAPI dependencies not installed.")
    print("Install with: pip install fastapi uvicorn")
    sys.exit(1)

from src.api.server import app, initialize_service
from src.api.service import SimulationService
from src.core import simulation_service


def main():
    parser = argparse.ArgumentParser(
        description="Launch eDNA LPT Simulation Service HTTP API"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server port (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reload on code changes (development only)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging level (default: info)",
    )

    args = parser.parse_args()

    # Initialize service with the simulation runner
    try:
        service = SimulationService(simulation_service.run_simulation_with_result)
        initialize_service(service)
        print("[OK] Simulation service initialized")
    except Exception as e:
        print(f"[ERROR] Failed to initialize service: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Print startup banner
    print("\n" + "=" * 70)
    print("eDNA LPT Simulation Service - FastAPI HTTP Server")
    print("=" * 70)
    print(f"[START] Server on http://{args.host}:{args.port}")
    print(f"[DOCS] API Documentation: http://{args.host}:{args.port}/docs")
    print(f"[REDOC] ReDoc: http://{args.host}:{args.port}/redoc")
    print("=" * 70 + "\n")

    # Start server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
