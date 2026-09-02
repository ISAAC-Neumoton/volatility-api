"""Tests for volatility models"""

import numpy as np
import pandas as pd
import pytest

from src.volatility_api.models.garch_model import GARCHModel


def test_garch_model_initialization():
    """Test GARCH model initialization"""
    model = GARCHModel(p=1, q=1)
    assert model.p == 1
    assert model.q == 1


def test_garch_model_fit():
    """Test GARCH model fitting"""
    # Generate synthetic returns
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0, 0.01, 100))

    model = GARCHModel()
    model.fit(returns)

    assert model.fitted_model is not None


def test_garch_model_forecast():
    """Test GARCH model forecasting"""
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0, 0.01, 100))

    model = GARCHModel()
    model.fit(returns)

    forecast = model.forecast(horizon=5)
    assert len(forecast) == 5
    assert "volatility" in forecast.columns
