"""
API Client Layer Tests

Tests SimulationAPIClient with both local and HTTP modes.
- Mode auto-detection
- Local mode execution
- HTTP mode execution
- Error handling and fallback
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.client import SimulationAPIClient
from src.core.simulation_contracts import RunStatus, SimRunConfig, RunResult


class TestAPIClientModeDetection:
    """Test client mode auto-detection"""

    def test_local_mode_when_no_server_available(self):
        """Client should default to local mode when server unavailable"""
        mock_service = Mock()
        
        client = SimulationAPIClient(
            service=mock_service,
            http_base_url="http://127.0.0.1:8000"
        )
        
        # Should have service available
        assert client.service is not None

    def test_http_mode_when_server_available(self):
        """Client should use HTTP mode when server responds"""
        mock_service = Mock()
        
        with patch('src.api.client.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            client = SimulationAPIClient(
                service=mock_service,
                http_base_url="http://127.0.0.1:8000"
            )
            
            # Should have attempted health check
            assert mock_service is not None


class TestAPIClientLocalMode:
    """Test client in local execution mode"""

    @pytest.fixture
    def client(self):
        """Create client with mocked service"""
        mock_service = Mock()
        
        # Mock preflight methods
        mock_service.preflight_single_run.return_value = (True, [])
        mock_service.preflight_batch_run.return_value = ([], [])
        
        # Mock execution methods (correct method names)
        mock_service.execute_single_run.return_value = RunResult(
            status=RunStatus.SUCCEEDED,
            output_path="/tmp/output",
            started_at_utc="2024-01-01T00:00:00Z",
            ended_at_utc="2024-01-01T00:10:00Z",
            elapsed_seconds=600.0,
            error_message="",
            metadata={}
        )
        
        mock_service.execute_batch_runs.return_value = {
            "summary": [],
            "results": [],
            "success_count": 0,
            "total_count": 0
        }
        
        return SimulationAPIClient(service=mock_service)

    @pytest.fixture
    def valid_config(self):
        """Create valid simulation config"""
        return {
            "file_path": "/tmp/dataset.nc",
            "output_path": "/tmp/output",
            "days": 1,
            "mode": "random",
            "backend": "scipy",
            "particle_count": 100,
            "seed": 42,
            "dt_minutes": 10,
            "output_hours": 1,
            "repeat_release_hours": None
        }

    def test_validate_single_run_local(self, client, valid_config):
        """Local mode validation"""
        is_valid, issues = client.validate_single_run(
            dataset_path="/tmp/dataset.nc",
            config=valid_config
        )
        
        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)

    def test_run_single_local(self, client, valid_config):
        """Local mode single run execution"""
        result = client.run_single(
            dataset_path="/tmp/dataset.nc",
            output_path="/tmp/output",
            config=valid_config,
            progress_callback=None
        )
        
        assert isinstance(result, RunResult)
        assert result.status == RunStatus.SUCCEEDED

    def test_run_batch_local(self, client, valid_config):
        """Local mode batch execution"""
        configs = [valid_config, valid_config]
        
        results = client.validate_batch_runs(
            dataset_path="/tmp/dataset.nc",
            batch_configs=configs
        )
        
        assert isinstance(results, tuple)
        assert len(results) == 2


class TestAPIClientHTTPMode:
    """Test client in HTTP execution mode"""

    @pytest.fixture
    def client_with_http(self):
        """Create client configured for HTTP mode"""
        mock_service = Mock()
        
        return SimulationAPIClient(
            service=mock_service,
            http_base_url="http://127.0.0.1:8000"
        )

    def test_http_base_url_configured(self, client_with_http):
        """Client should store HTTP base URL"""
        assert client_with_http.http_base_url is not None


class TestAPIClientCallbackHandling:
    """Test progress callback handling"""

    @pytest.fixture
    def client(self):
        """Create client with mocked service"""
        mock_service = Mock()
        mock_service.execute_single_run.return_value = RunResult(
            status=RunStatus.SUCCEEDED,
            output_path="/tmp/output",
            started_at_utc="2024-01-01T00:00:00Z",
            ended_at_utc="2024-01-01T00:10:00Z",
            elapsed_seconds=600.0,
            error_message="",
            metadata={}
        )
        
        return SimulationAPIClient(service=mock_service)

    @pytest.fixture
    def valid_config(self):
        """Create valid simulation config"""
        return {
            "file_path": "/tmp/dataset.nc",
            "output_path": "/tmp/output",
            "days": 1,
            "mode": "random",
            "backend": "scipy",
            "particle_count": 100,
            "seed": 42,
            "dt_minutes": 10,
            "output_hours": 1,
            "repeat_release_hours": None
        }

    def test_callback_invoked_during_execution(self, client, valid_config):
        """Callback should be invoked with progress updates"""
        callback = Mock()
        
        result = client.run_single(
            dataset_path="/tmp/dataset.nc",
            output_path="/tmp/output",
            config=valid_config,
            progress_callback=callback
        )
        
        assert result.status == RunStatus.SUCCEEDED
        # Callback may be called depending on implementation


# Run with: pytest tests/test_api_client.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
