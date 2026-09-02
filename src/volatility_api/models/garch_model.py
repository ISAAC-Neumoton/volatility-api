"""GARCH volatility model implementation"""

from typing import Optional, Tuple

import numpy as np
import pandas as pd
from arch import arch_model


class GARCHModel:
    """GARCH(1,1) volatility forecast model"""

    def __init__(self, p: int = 1, q: int = 1):
        """
        Initialize GARCH model.

        Args:
            p: Order of ARCH (lagged volatility terms)
            q: Order of GARCH (lagged squared residual terms)
        """
        self.p = p
        self.q = q
        self.model = None
        self.fitted_model = None

    def fit(self, returns: pd.Series) -> None:
        """
        Fit GARCH model to return series.

        Args:
            returns: Series of log returns
        """
        self.model = arch_model(returns, vol="Garch", p=self.p, q=self.q)
        self.fitted_model = self.model.fit(disp="off")

    def forecast(self, horizon: int = 1) -> pd.DataFrame:
        """
        Forecast volatility.

        Args:
            horizon: Number of periods to forecast

        Returns:
            DataFrame with volatility forecasts
        """
        if self.fitted_model is None:
            raise RuntimeError("Model must be fitted before forecasting")

        forecast = self.fitted_model.forecast(horizon=horizon)
        variance_forecast = forecast.variance.iloc[-1, :]
        volatility_forecast = np.sqrt(variance_forecast)

        return pd.DataFrame(
            {"volatility": volatility_forecast},
            index=pd.RangeIndex(1, horizon + 1),
        )

    def get_parameters(self) -> dict:
        """Get model parameters"""
        if self.fitted_model is None:
            raise RuntimeError("Model must be fitted first")

        return self.fitted_model.params.to_dict()
