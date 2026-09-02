"""
Comprehensive test suite for GARCH(1,1) modeling engine and walk-forward backtester.

Tests cover:
    - GARCH model initialization, fitting, forecasting
    - Parameter validation and convergence
    - Walk-forward backtester with baseline comparison
    - Model serialization (joblib)
    - Edge cases and error handling

Author: Test Suite
Version: 1.0
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from src.volatility_api.models import GARCHModel, VolatilityForecaster, WalkForwardBacktester


class TestVolatilityForecaster:
    """Test abstract VolatilityForecaster base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Verify VolatilityForecaster is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            VolatilityForecaster("EURUSD")

    def test_instantiate_concrete_garch_model(self):
        """Verify GARCHModel can be instantiated (concrete implementation)."""
        model = GARCHModel("EURUSD")
        assert model.pair == "EURUSD"
        assert model.fitted is False
        assert model.fit_date is None

    def test_invalid_pair_raises_error(self):
        """Verify empty/None pair raises ValueError."""
        with pytest.raises(ValueError):
            GARCHModel("")
        
        with pytest.raises(ValueError):
            GARCHModel(None)


class TestGARCHModel:
    """Test GARCH(1,1) model implementation."""

    @pytest.fixture
    def sample_returns(self):
        """Generate sample log-returns (504 days ~ 2 years)."""
        np.random.seed(42)
        # Simulate realistic FX returns with heteroskedasticity
        return np.random.normal(0, 0.008, 504)

    @pytest.fixture
    def model(self):
        """Create model instance."""
        return GARCHModel("EURUSD")

    def test_model_initialization(self, model):
        """Verify model initializes with correct defaults."""
        assert model.pair == "EURUSD"
        assert model.mean == "Zero"
        assert model.fitted is False
        assert model._training_data_points == 0

    def test_fit_with_valid_returns(self, model, sample_returns):
        """Verify model fits successfully with valid returns."""
        model.fit(sample_returns, show_output=False)
        
        assert model.fitted is True
        assert model.fit_date is not None
        assert model._training_data_points == 504
        # Standard GARCH(1,1) with mean='Zero' has omega, alpha[1], beta[1]
        assert all(k in model._params for k in ["omega", "alpha[1]", "beta[1]"])

    def test_fit_validates_minimum_points(self, model):
        """Verify fit() rejects data with <10 points."""
        short_returns = np.random.normal(0, 0.01, 5)
        with pytest.raises(ValueError, match="requires ≥10 points"):
            model.fit(short_returns)

    def test_fit_validates_nan_inf(self, model):
        """Verify fit() rejects data with NaN/Inf."""
        returns_with_nan = np.random.normal(0, 0.01, 100)
        returns_with_nan[50] = np.nan
        with pytest.raises(ValueError, match="NaN or Inf"):
            model.fit(returns_with_nan)

        returns_with_inf = np.random.normal(0, 0.01, 100)
        returns_with_inf[50] = np.inf
        with pytest.raises(ValueError, match="NaN or Inf"):
            model.fit(returns_with_inf)

    def test_fit_validates_array_dimensions(self, model):
        """Verify fit() rejects non-1D arrays."""
        returns_2d = np.random.normal(0, 0.01, (100, 2))
        with pytest.raises(ValueError, match="must be 1D"):
            model.fit(returns_2d)

    def test_forecast_before_fit_raises_error(self, model):
        """Verify forecast() raises RuntimeError if model not fitted."""
        with pytest.raises(RuntimeError, match="not fitted"):
            model.forecast(horizon=5)

    def test_forecast_with_valid_horizon(self, model, sample_returns):
        """Verify forecast() returns correct shapes after fitting."""
        model.fit(sample_returns, show_output=False)
        
        forecast, ci = model.forecast(horizon=5)
        
        assert forecast.shape == (5,)
        assert ci.shape == (5, 2)
        assert np.all(forecast > 0)
        assert np.all(ci[:, 0] <= forecast)
        assert np.all(ci[:, 1] >= forecast)

    def test_forecast_horizon_validation(self, model, sample_returns):
        """Verify forecast() validates horizon parameter."""
        model.fit(sample_returns, show_output=False)
        
        with pytest.raises(ValueError, match="horizon must be int"):
            model.forecast(horizon=-1)
        
        with pytest.raises(ValueError, match="horizon must be int"):
            model.forecast(horizon=500)

    def test_forecast_annualization(self, model, sample_returns):
        """Verify forecast is annualized (scaled by sqrt(252))."""
        model.fit(sample_returns, show_output=False)
        
        forecast, _ = model.forecast(horizon=1)
        assert 5.0 < forecast[0] < 30.0

    def test_model_params_after_fit(self, model, sample_returns):
        """Verify model parameters are correctly extracted after fitting."""
        model.fit(sample_returns, show_output=False)
        
        params = model.model_params
        alpha_plus_beta = params["alpha[1]"] + params["beta[1]"]
        
        assert 0.8 < alpha_plus_beta < 1.0
        assert params["omega"] > 0

    def test_model_config_property(self, model, sample_returns):
        """Verify model_config returns complete metadata."""
        model.fit(sample_returns, show_output=False)
        
        config = model.model_config
        assert config["model_type"] == "GARCH(1,1)"
        assert config["pair"] == "EURUSD"
        assert config["fitted"] is True
        assert config["mean_model"] == "Zero"
        assert config["training_data_points"] == 504
        assert "mean_reversion_speed" in config

    def test_get_state_dict(self, model, sample_returns):
        """Verify state serialization for joblib."""
        model.fit(sample_returns, show_output=False)
        state = model.get_state_dict()
        
        assert state["pair"] == "EURUSD"
        assert state["fitted"] is True
        assert state["training_data_points"] == 504
        assert state["model_type"] == "GARCH(1,1)"
        assert state["fit_date"] is not None

    def test_set_state_dict(self, model, sample_returns):
        """Verify state reconstruction."""
        model.fit(sample_returns, show_output=False)
        state = model.get_state_dict()
        
        model2 = GARCHModel("USDJPY")
        model2.set_state_dict(state)
        
        assert model2.pair == "EURUSD"
        assert model2.fitted is True
        assert model2._training_data_points == 504

    def test_fit_with_list_input(self, model):
        """Verify fit() accepts list input."""
        returns_list = [0.001, -0.002, 0.003, -0.001] * 30
        model.fit(returns_list)
        
        assert model.fitted is True
        assert model._training_data_points == 120


class TestWalkForwardBacktester:
    """Test walk-forward backtesting engine."""

    @pytest.fixture
    def sample_returns(self):
        """Generate sample log-returns (600 days)."""
        np.random.seed(42)
        return np.random.normal(0, 0.008, 600)

    @pytest.fixture
    def backtester(self, sample_returns):
        """Create backtester instance."""
        return WalkForwardBacktester(
            sample_returns,
            train_window=252,
            test_window=100,
            baseline_window=100,
        )

    def test_backtester_initialization(self, backtester):
        """Verify backtester initializes with correct parameters."""
        assert backtester.train_window == 252
        assert backtester.test_window == 100
        assert backtester.baseline_window == 100
        assert len(backtester.returns) == 600

    def test_backtester_validates_minimum_data(self):
        """Verify backtester requires sufficient data."""
        short_returns = np.random.normal(0, 0.01, 100)
        with pytest.raises(ValueError):
            WalkForwardBacktester(short_returns, train_window=252)

    def test_backtester_validates_window_sizes(self, sample_returns):
        """Verify backtester validates window configuration."""
        with pytest.raises(ValueError, match="train_window must be"):
            WalkForwardBacktester(sample_returns, train_window=10)
        
        with pytest.raises(ValueError, match="test_window must be"):
            WalkForwardBacktester(
                sample_returns,
                train_window=100,
                test_window=5,
            )

    def test_backtest_execution(self, backtester):
        """Verify backtest() runs and returns valid results dictionary."""
        model = GARCHModel("EURUSD")
        results = backtester.backtest(model)
        
        required_keys = [
            "mae", "rmse", "baseline_mae", "mape",
            "outperformance_pct", "is_valid", "test_periods",
            "forecasts", "realized_vols", "baseline_forecasts", "errors",
        ]
        assert all(k in results for k in required_keys)

    def test_backtest_metrics_are_numeric(self, backtester):
        """Verify backtest metrics are numeric and non-negative."""
        model = GARCHModel("EURUSD")
        results = backtester.backtest(model)
        
        assert isinstance(results["mae"], float)
        assert isinstance(results["rmse"], float)
        assert isinstance(results["mape"], float)
        assert results["mae"] >= 0
        assert results["rmse"] >= 0
        assert results["mape"] >= 0

    def test_backtest_arrays_have_correct_length(self, backtester):
        """Verify backtest output arrays match test_window."""
        model = GARCHModel("EURUSD")
        results = backtester.backtest(model)
        
        test_periods = backtester.test_window
        assert len(results["forecasts"]) == test_periods
        assert len(results["realized_vols"]) == test_periods
        assert len(results["baseline_forecasts"]) == test_periods
        assert len(results["errors"]) == test_periods

    def test_backtest_outperformance_calculation(self, backtester):
        """Verify outperformance percentage bounds."""
        model = GARCHModel("EURUSD")
        results = backtester.backtest(model)
        assert -100 <= results["outperformance_pct"] <= 200

    def test_backtest_validation_gate(self, backtester):
        """Verify validation gate against minimum outperformance threshold."""
        model = GARCHModel("EURUSD")
        results = backtester.backtest(model)
        
        # Uses either class attribute or default 10% KPI target
        threshold = getattr(backtester, "min_outperformance_pct", 10.0)
        assert results["is_valid"] == (results["outperformance_pct"] >= threshold)

    def test_backtest_summary_output(self, backtester):
        """Verify summary() generates readable output."""
        model = GARCHModel("EURUSD")
        results = backtester.backtest(model)
        summary = backtester.summary(results)
        
        for term in ["Walk-Forward Backtest Results", "Test Periods", "MAE", "RMSE", "Outperformance", "Validation"]:
            assert term in summary

    def test_realized_volatility_calculation(self, backtester):
        """Verify realized volatility is correctly computed."""
        realized = backtester._calculate_realized_volatility(
            backtester.returns[:100],
            window=1,
        )
        assert len(realized) == 100
        assert np.all(realized >= 0)


class TestModelJobLibSerialization:
    """Test model serialization and persistence."""

    @pytest.fixture
    def fitted_model(self):
        """Create and fit a model."""
        np.random.seed(42)
        returns = np.random.normal(0, 0.008, 504)
        model = GARCHModel("EURUSD")
        model.fit(returns, show_output=False)
        return model

    @pytest.fixture
    def temp_model_dir(self):
        """Create temporary directory for model files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_save_and_load_with_joblib(self, fitted_model, temp_model_dir):
        """Verify model can be saved and loaded with joblib."""
        try:
            import joblib
        except ImportError:
            pytest.skip("joblib not installed")

        file_path = os.path.join(temp_model_dir, "test_model.pkl")
        joblib.dump(fitted_model, file_path)
        assert os.path.exists(file_path)
        
        loaded_model = joblib.load(file_path)
        assert loaded_model.pair == fitted_model.pair
        assert loaded_model.fitted == fitted_model.fitted
        assert loaded_model._training_data_points == fitted_model._training_data_points

    def test_forecast_after_deserialization(self, fitted_model, temp_model_dir):
        """Verify deserialized model can still forecast."""
        try:
            import joblib
        except ImportError:
            pytest.skip("joblib not installed")

        file_path = os.path.join(temp_model_dir, "test_model.pkl")
        forecast_orig, ci_orig = fitted_model.forecast(horizon=5)
        
        joblib.dump(fitted_model, file_path)
        loaded_model = joblib.load(file_path)
        
        forecast_loaded, ci_loaded = loaded_model.forecast(horizon=5)
        np.testing.assert_array_almost_equal(forecast_orig, forecast_loaded)
        np.testing.assert_array_almost_equal(ci_orig, ci_loaded)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])