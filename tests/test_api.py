"""Tests for API endpoints"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from src.volatility_api.main import app
from src.volatility_api.data.repository import BacktestResult, ModelRegistry

client = TestClient(app)


# --- Existing Original Tests ---

def test_health_check():
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_endpoint():
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()


# --- Additional Endpoint & Authentication Tests ---

def test_v1_health_check():
    """Test system health check endpoint"""
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database_connected" in data
    assert "disk_free_mb" in data


def test_get_pairs():
    """Test retrieving supported currency pairs"""
    response = client.get("/v1/pairs")
    assert response.status_code == 200
    pairs = response.json()
    assert isinstance(pairs, list)
    assert "EURUSD" in pairs
    assert "USDJPY" in pairs


def test_auth_missing_api_key():
    """Test forecast endpoint fails without X-API-Key header"""
    response = client.get("/v1/forecast/EURUSD?horizon=5")
    assert response.status_code == 401
    assert response.json()["error_code"] == "MISSING_API_KEY"


def test_auth_invalid_api_key():
    """Test forecast endpoint fails with an invalid X-API-Key"""
    response = client.get(
        "/v1/forecast/EURUSD?horizon=5",
        headers={"X-API-Key": "vca_invalid_key_value"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_API_KEY"


def test_invalid_pair_validation():
    """Test validation failure for unsupported pair"""
    response = client.get(
        "/v1/forecast/INVALIDPAIR?horizon=5",
        headers={"X-API-Key": "vca_test_key"},
    )
    # Auth or input validation returns 4xx
    assert response.status_code in (400, 401, 422)


@patch("src.volatility_api.api.dependencies.RepositoryService.validate_api_key", return_value=True)
@patch("src.volatility_api.api.dependencies.RepositoryService.get_latest_model")
@patch("src.volatility_api.api.dependencies.RepositoryService.load_model_with_joblib")
def test_forecast_success(mock_load_model, mock_get_model, mock_val_key):
    """Test successful forecast generation with mock forecaster"""
    mock_get_model.return_value = ModelRegistry(
        id=1,
        pair="EURUSD",
        model_version="1.0.0",
        params_path="./models/EURUSD_test.pkl",
        training_data_points=504,
    )

    mock_forecaster = MagicMock()
    mock_forecaster.forecast.return_value = (
        [0.007, 0.0072, 0.0071, 0.0073, 0.0075],
        [(0.006, 0.008), (0.0061, 0.0082), (0.006, 0.0081), (0.0062, 0.0083), (0.0064, 0.0085)],
    )
    mock_load_model.return_value = mock_forecaster

    response = client.get(
        "/v1/forecast/EURUSD?horizon=5",
        headers={"X-API-Key": "vca_valid_key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["pair"] == "EURUSD"
    assert data["horizon"] == 5
    assert len(data["forecasts"]) == 5
    assert len(data["confidence_intervals"]) == 5
    assert data["model_version"] == "1.0.0"


@patch("src.volatility_api.api.dependencies.RepositoryService.validate_api_key", return_value=True)
@patch("src.volatility_api.api.dependencies.RepositoryService.get_backtest_results")
def test_get_backtest_success(mock_backtest_results, mock_val_key):
    """Test retrieving backtest performance metrics"""
    mock_backtest_results.return_value = [
        BacktestResult(
            pair="EURUSD",
            run_date="2026-09-02T12:00:00",
            horizon=5,
            data_points=504,
            mae=0.002,
            rmse=0.0025,
            baseline_mae=0.0023,
            baseline_rmse=0.0028,
            outperformance_pct=13.04,
        )
    ]

    response = client.get(
        "/v1/backtest/EURUSD",
        headers={"X-API-Key": "vca_valid_key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["pair"] == "EURUSD"
    assert data[0]["outperformance_pct"] == 13.04