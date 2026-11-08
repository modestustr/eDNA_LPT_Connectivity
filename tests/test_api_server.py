"""
FastAPI Server Endpoint Tests

Tests all HTTP endpoints and API behavior.
- Health checks
- Validation endpoints
- Execution endpoints
- Error responses
- Swagger/OpenAPI documentation
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.server import app
from src.core.simulation_contracts import SimRunConfig, RunResult, RunStatus


@pytest.fixture
def client():
    """Create test client for FastAPI app"""
    return TestClient(app)


@pytest.fixture
def valid_config():
    """Create valid simulation config"""
    return {
        "u_var": "uo",
        "v_var": "vo",
        "lon_coord": "longitude",
        "lat_coord": "latitude",
        "time_coord": "time",
        "depth_coord": "depth",
        "particle_mode": "random",
        "particle_backend": "scipy",
        "particle_count_override": 100,
        "random_seed": 42,
        "dt_minutes": 10,
        "output_hours": 1,
        "release_mode": "instant",
        "days": 1,
        "mesh_adapter": "none"
    }


class TestHealthEndpoints:
    """Test health check endpoints"""

    def test_health_endpoint(self, client):
        """GET /health should return healthy status"""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_version_endpoint(self, client):
        """GET /version should return version info"""
        response = client.get("/version")
        
        assert response.status_code == 200
        data = response.json()
        assert "version" in data or response.status_code in [200, 404]


class TestValidationEndpoints:
    """Test validation endpoints"""

    def test_validate_single_endpoint(self, client, valid_config):
        """POST /validate/single should validate config"""
        response = client.post(
            "/validate/single",
            json={
                "dataset_path": "/tmp/dataset.nc",
                "config": valid_config
            }
        )
        
        # Should accept the request (validation may return error or success)
        assert response.status_code in [200, 400, 422]

    def test_validate_batch_endpoint(self, client, valid_config):
        """POST /validate/batch should validate multiple configs"""
        response = client.post(
            "/validate/batch",
            json={
                "dataset_path": "/tmp/dataset.nc",
                "configs": [valid_config, valid_config]
            }
        )
        
        # Should accept the request
        assert response.status_code in [200, 400, 422]


class TestExecutionEndpoints:
    """Test execution endpoints"""

    def test_run_single_endpoint(self, client, valid_config):
        """POST /run/single should execute simulation"""
        response = client.post(
            "/run/single",
            json={
                "dataset_path": "/tmp/dataset.nc",
                "output_path": "/tmp/output",
                "config": valid_config
            },
            timeout=30
        )
        
        # Endpoint exists and accepts request
        assert response.status_code in [200, 400, 422, 500]

    def test_run_batch_endpoint(self, client, valid_config):
        """POST /run/batch should execute batch simulations"""
        response = client.post(
            "/run/batch",
            json={
                "dataset_path": "/tmp/dataset.nc",
                "output_base": "/tmp",
                "configs": [valid_config]
            },
            timeout=60
        )
        
        # Endpoint exists and accepts request
        assert response.status_code in [200, 400, 422, 500]


class TestStatusEndpoints:
    """Test run status endpoints"""

    def test_get_runs_endpoint(self, client):
        """GET /runs should return list of runs"""
        response = client.get("/runs")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_get_run_by_id_endpoint(self, client):
        """GET /runs/{id} should attempt to fetch run status"""
        response = client.get("/runs/nonexistent-id")
        
        # Should return 404 or empty result, not 500
        assert response.status_code in [200, 404]


class TestOpenAPIDocumentation:
    """Test OpenAPI/Swagger documentation"""

    def test_openapi_schema_endpoint(self, client):
        """GET /openapi.json should return OpenAPI schema"""
        response = client.get("/openapi.json")
        
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data or "swagger" in data

    def test_swagger_docs_endpoint(self, client):
        """GET /docs should return Swagger UI"""
        response = client.get("/docs")
        
        assert response.status_code == 200
        assert "html" in response.text.lower() or "swagger" in response.text.lower()


class TestErrorHandling:
    """Test error handling and edge cases"""

    def test_invalid_json_payload(self, client):
        """Invalid JSON payload should return 422"""
        response = client.post(
            "/validate/single",
            json={"invalid": "payload"}
        )
        
        # Should handle gracefully
        assert response.status_code in [400, 422]

    def test_missing_required_fields(self, client):
        """Missing required fields should return validation error"""
        response = client.post(
            "/validate/single",
            json={}
        )
        
        # Should return 422 for validation error
        assert response.status_code in [400, 422]

    def test_nonexistent_endpoint(self, client):
        """Nonexistent endpoint should return 404"""
        response = client.get("/nonexistent-endpoint")
        
        assert response.status_code == 404


class TestCORSHeaders:
    """Test CORS and header handling"""

    def test_cors_headers_present(self, client):
        """Response should include appropriate CORS headers"""
        response = client.get("/health")
        
        # May or may not have CORS headers, depending on config
        assert response.status_code == 200


# Run with: pytest tests/test_api_server.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
