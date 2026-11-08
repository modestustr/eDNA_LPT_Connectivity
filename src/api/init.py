"""
API Initialization & Bootstrap
==============================
Initializes the simulation service and API client for the application.
This module wires together the business logic with the client interface.

Supports two modes:
- LOCAL: Direct in-process calls (default for app.py)
- HTTP: Remote calls to FastAPI server (for production/scaling)
"""

from typing import Optional
from .service import SimulationService
from .client import SimulationAPIClient


# Global singleton instances (initialized once at app startup)
_simulation_service: Optional[SimulationService] = None
_api_client: Optional[SimulationAPIClient] = None


def initialize_simulation_api(
    simulation_runner,
    http_server_url: Optional[str] = None,
):
    """
    Bootstrap the simulation API with the actual simulation runner.

    Args:
        simulation_runner: Callable(SimRunConfig, progress_callback) -> RunResult
                          This is the core simulation executor (e.g., from OceanParcels)
        http_server_url: Optional URL to remote FastAPI server (e.g., "http://localhost:8000")
                        If provided and accessible, will use HTTP mode instead of local.

    Returns:
        Initialized SimulationAPIClient
    """
    global _simulation_service, _api_client

    _simulation_service = SimulationService(simulation_runner)
    _api_client = SimulationAPIClient(_simulation_service, http_base_url=http_server_url)

    mode = _api_client.mode
    if http_server_url:
        print(f"[WEB] API Client initialized in {mode.upper()} mode (server: {http_server_url})")
    else:
        print(f"[LOCAL] API Client initialized in {mode.upper()} mode (local process)")

    return _api_client


def get_api_client() -> SimulationAPIClient:
    """
    Get the initialized API client.
    Must call initialize_simulation_api() first.
    """
    global _api_client
    if _api_client is None:
        raise RuntimeError(
            "API client not initialized. Call initialize_simulation_api() at app startup."
        )
    return _api_client


def get_service() -> SimulationService:
    """
    Get the initialized simulation service (for direct access if needed).
    """
    global _simulation_service
    if _simulation_service is None:
        raise RuntimeError(
            "Simulation service not initialized. Call initialize_simulation_api() at app startup."
        )
    return _simulation_service
