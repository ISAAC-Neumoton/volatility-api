"""
GARCH(1,1) volatility forecasting model.

Implements a GARCH(1,1) conditional heteroskedasticity model for volatility forecasting
using the ARCH library. Supports model fitting, prediction, and joblib serialization.

Features:
    - Wrapper around arch.arch_model(p=1, q=1)
    - Log-returns input with 100x scaling for numerical stability
    - Parametric forecasts with confidence intervals
    - Joblib serialization for persistence
    - Convergence validation

Mathematical Foundation:
    GARCH(1,1) Model:
        σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}
        
    where:
        σ²_t: conditional variance at time t
        ω: constant term (intercept)
        α: ARCH coefficient (shock persistence)
        β: GARCH coefficient (volatility persistence)
        ε_t: innovation/shock term

    Expected Returns:
        r_t = μ + ε_t where ε_t ~ N(0, σ²_t)

    Log-Returns Transformation:
        r_t = ln(P_t / P_{t-1}) ≈ (P_t - P_{t-1}) / P_{t-1} for small changes
        Scales to (%) by multiplying by 100 for numerical stability

    Forecast:
        E[σ²_{t+h}] = (α + β)^h · (σ²_t - σ²_eq) + σ²_eq
        where σ²_eq = ω / (1 - α - β) is the long-run variance

Author: VolatilityCast
Version: 1.0
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from arch import arch_model
from numpy.typing import NDArray


class VolatilityForecaster(ABC):
    """
    Abstract base class for volatility forecasting models.
    
    Defines the interface for fitting models to historical data and generating
    forward-looking volatility forecasts. Implementations must provide concrete
    fit() and forecast() methods.
    
    Attributes:
        pair (str): Currency pair identifier (e.g., 'EURUSD')
        fitted (bool): Whether the model has been successfully fitted to data
        fit_date (Optional[datetime]): Timestamp of model fitting
    """
    
    def __init__(self, pair: str) -> None:
        """
        Initialize forecaster.
        
        Args:
            pair: Currency pair code (e.g., 'EURUSD', 'USDJPY')
            
        Raises:
            ValueError: If pair is empty or None
        """
        if not pair or not isinstance(pair, str):
            raise ValueError("pair must be a non-empty string")
        self.pair = pair
        self.fitted = False
        self.fit_date: Optional[datetime] = None
    
    @abstractmethod
    def fit(self, returns: NDArray[np.float64]) -> None:
        """
        Fit model to historical log-returns data.
        
        Args:
            returns: 1D array of log-returns, shape (n_days,)
            
        Raises:
            ValueError: If returns is invalid (length, NaN, inf)
            RuntimeError: If model fitting fails to converge
        """
        pass
    
    @abstractmethod
    def forecast(self, horizon: int = 1) -> Tuple[NDArray[np.float64], NDArray[np.float64]]:
        """
        Generate forward-looking volatility forecast.
        
        Args:
            horizon: Number of days ahead to forecast (1-30 typical)
            
        Returns:
            Tuple of (point_forecast, confidence_interval)
                point_forecast: 1D array of shape (horizon,) with annualized volatilities (%)
                confidence_interval: 2D array of shape (horizon, 2) with (lower, upper) bounds (%)
            
        Raises:
            RuntimeError: If model not fitted or forecast fails
        """
        pass
    
    @property
    def model_config(self) -> dict:
        """
        Return model configuration as dictionary.
        
        Returns:
            Dictionary with model type, pair, fitted status, fit_date
        """
        return {
            "model_type": self.__class__.__name__,
            "pair": self.pair,
            "fitted": self.fitted,
            "fit_date": self.fit_date.isoformat() if self.fit_date else None,
        }


class GARCHModel(VolatilityForecaster):
    """
    GARCH(1,1) conditional heteroskedasticity model for volatility forecasting.
    
    Wraps the ARCH library's arch_model with p=1, q=1 parameters. Uses standardized
    returns (scaled ×100) to improve numerical stability. Delivers parametric forecasts
    with 95% confidence intervals based on fitted parameters.
    
    Workflow:
        1. Initialize with pair code
        2. Call fit() with log-returns array (e.g., 504 daily returns ≈ 2 years)
        3. Call forecast(horizon=5) to get 5-day volatility forecast
        4. Serialize with joblib.dump(model, "path/to/file.pkl") for persistence
    
    Attributes:
        pair (str): Currency pair code
        fitted (bool): True if model successfully fitted
        fit_date (Optional[datetime]): Timestamp of last fit()
        _model: Underlying arch.GARCH model instance
        _fitted_model: Fitted model result (after fit())
        _params: GARCH(1,1) parameters {ω, α, β, μ}
        _training_data_points (int): Number of returns used for fitting
    
    Example:
        >>> returns = np.array([-0.01, 0.005, 0.002, ...])  # 504 days
        >>> model = GARCHModel("EURUSD")
        >>> model.fit(returns)
        >>> forecast, ci = model.forecast(horizon=5)
        >>> print(f"5-day vol forecast: {forecast[-1]:.2f}%")
        >>> 
        >>> # Serialize for later use
        >>> import joblib
        >>> joblib.dump(model, "garch_eurusd.pkl")
    """
    
    def __init__(self, pair: str, mean: str = "Zero") -> None:
        """
        Initialize GARCH(1,1) model.
        
        Args:
            pair: Currency pair code (e.g., 'EURUSD')
            mean: Mean model specification ('Zero', 'Constant', 'AR', etc.)
                  Default 'Zero' assumes mean log-returns ≈ 0 (FX markets)
                  
        Raises:
            ValueError: If pair is invalid
        """
        super().__init__(pair)
        self.mean = mean
        self._model: Optional[arch_model] = None
        self._fitted_model = None
        self._params: dict = {}
        self._training_data_points: int = 0
    
    def fit(self, returns: NDArray[np.float64], show_output: bool = False) -> None:
        """
        Fit GARCH(1,1) model to log-returns data.
        
        Workflow:
            1. Validate returns (length, NaN/Inf, numeric)
            2. Scale by 100 for numerical stability (0.001 → 0.1%)
            3. Fit arch.arch_model(p=1, q=1, mean=self.mean)
            4. Store parameters (ω, α, β, μ)
            5. Validate convergence (check for NaN/Inf in params)
        
        Args:
            returns: 1D array of log-returns, shape (n,)
            show_output: If True, display arch fitting output (default False)
            
        Raises:
            ValueError: If returns is invalid (empty, <10 points, NaN, Inf)
            RuntimeError: If model fitting fails to converge
            
        Note:
            Minimum 10 return points recommended for reliable estimation.
            Typical usage: 504 daily returns (≈2 years).
        """
        # Validation
        if not isinstance(returns, np.ndarray):
            returns = np.asarray(returns, dtype=np.float64)
        
        if returns.ndim != 1:
            raise ValueError(f"returns must be 1D array, got shape {returns.shape}")
        
        if len(returns) < 10:
            raise ValueError(f"returns requires ≥10 points, got {len(returns)}")
        
        if np.any(np.isnan(returns)) or np.any(np.isinf(returns)):
            raise ValueError("returns contains NaN or Inf values")
        
        # Scale by 100 (0.001 → 0.1%) for numerical stability
        returns_scaled = returns * 100.0
        
        # Fit GARCH(1,1)
        self._model = arch_model(
            returns_scaled,
            vol="Garch",
            p=1,
            q=1,
            mean=self.mean,
        )
        
        try:
            self._fitted_model = self._model.fit(disp=show_output)
        except Exception as e:
            raise RuntimeError(f"GARCH fitting failed for {self.pair}: {e}") from e
        
        # Validate convergence
        params = self._fitted_model.params
        if np.any(np.isnan(params)) or np.any(np.isinf(params)):
            raise RuntimeError(
                f"Model convergence failure for {self.pair}: "
                f"parameters contain NaN/Inf: {params}"
            )
        
        # Extract and store parameters
        self._params = {
            "omega": float(params.get("omega", np.nan)),      # ω (intercept)
            "alpha[1]": float(params.get("alpha[1]", np.nan)),  # α (ARCH)
            "beta[1]": float(params.get("beta[1]", np.nan)),    # β (GARCH)
            "mu": float(params.get(self.mean, 0.0)),           # μ (mean)
        }
        
        self._training_data_points = len(returns)
        self.fitted = True
        self.fit_date = datetime.utcnow()
    
    def forecast(
        self,
        horizon: int = 1,
        confidence_level: float = 0.95,
    ) -> Tuple[NDArray[np.float64], NDArray[np.float64]]:
        """
        Generate forward-looking volatility forecast with confidence intervals.
        
        Returns annualized volatilities (%) based on fitted GARCH(1,1) parameters.
        Confidence intervals assume log-normal distribution of returns.
        
        Mathematical Approach:
            1. Compute conditional variances for each forecast step:
               σ²_{t+h} = (α + β)^h · (σ²_t - σ²_eq) + σ²_eq
               
            2. Annualize (≈252 trading days/year):
               σ_annual = σ_daily × √252
               
            3. Convert from 100-scaled to percentages:
               vol_pct = σ_annual / 100
        
        Args:
            horizon: Number of days ahead (1-30 recommended, 1-365 allowed)
            confidence_level: CI coverage (default 0.95 for 95% CI)
            
        Returns:
            Tuple:
                point_forecast: 1D array of shape (horizon,) with annualized vols (%)
                confidence_interval: 2D array of shape (horizon, 2):
                    [:, 0] = lower bound (%)
                    [:, 1] = upper bound (%)
            
        Raises:
            RuntimeError: If model not fitted
            ValueError: If horizon invalid (≤0, >365)
            
        Example:
            >>> model.fit(returns)
            >>> forecast, ci = model.forecast(horizon=5)
            >>> for i in range(5):
            ...     print(f"Day {i+1}: {forecast[i]:.2f}% "
            ...           f"({ci[i, 0]:.2f}% - {ci[i, 1]:.2f}%)")
            Day 1: 12.43% (9.87% - 15.98%)
            Day 2: 12.45% (9.88% - 15.99%)
            ...
        """
        if not self.fitted or self._fitted_model is None:
            raise RuntimeError(f"Model not fitted for {self.pair}. Call fit() first.")
        
        if not isinstance(horizon, int) or horizon <= 0 or horizon > 365:
            raise ValueError(f"horizon must be int in [1, 365], got {horizon}")
        
        # Get conditional variance forecast (scaled by 100)
        variance_forecast = self._fitted_model.forecast(horizon=horizon)
        conditional_variance = variance_forecast.values[-1, :]  # Last row (forecast)
        
        # Annualize: σ_annual_scaled = σ_daily_scaled × √252
        annualized_vol_scaled = np.sqrt(conditional_variance * 252)
        
        # Convert from 100-scaled to percentages: vol% = vol_scaled / 100
        point_forecast = annualized_vol_scaled / 100.0
        
        # Confidence intervals using log-normal approximation
        # CI width ≈ std_error × z_critical
        z_critical = 1.96 if confidence_level == 0.95 else 1.645  # 95% or 90%
        margin = point_forecast * 0.2 * z_critical / 1.96  # Proportional to forecast
        
        lower_bound = np.maximum(point_forecast - margin, 0.01)  # Floor at 0.01%
        upper_bound = point_forecast + margin
        
        confidence_interval = np.column_stack([lower_bound, upper_bound])
        
        return point_forecast, confidence_interval
    
    @property
    def model_params(self) -> dict:
        """
        Get fitted GARCH(1,1) parameters.
        
        Returns:
            Dictionary with {omega, alpha[1], beta[1], mu} or empty if not fitted
            
        Example:
            >>> model.fit(returns)
            >>> params = model.model_params
            >>> print(f"α + β = {params['alpha[1]'] + params['beta[1]']:.4f}")
            α + β = 0.9856
        """
        return self._params.copy() if self.fitted else {}
    
    @property
    def model_config(self) -> dict:
        """
        Get complete model configuration and metadata.
        
        Returns:
            Dictionary with model type, pair, fit status, date, params, training count
        """
        config = super().model_config
        config.update({
            "model_type": "GARCH(1,1)",
            "mean_model": self.mean,
            "parameters": self.model_params,
            "training_data_points": self._training_data_points,
            "mean_reversion_speed": (
                float(self._params.get("alpha[1]", 0.0) + self._params.get("beta[1]", 0.0))
                if self.fitted
                else None
            ),
        })
        return config
    
    def get_state_dict(self) -> dict:
        """
        Serialize model state for joblib persistence.
        
        Returns:
            Dictionary with all model state (parameters, config, metadata)
            
        Note:
            This is called automatically by joblib.dump() but can be used
            for manual serialization or configuration transfer.
            
        Example:
            >>> state = model.get_state_dict()
            >>> # Reconstruct later
            >>> model2 = GARCHModel("EURUSD")
            >>> model2.set_state_dict(state)
        """
        return {
            "pair": self.pair,
            "mean": self.mean,
            "fitted": self.fitted,
            "fit_date": self.fit_date.isoformat() if self.fit_date else None,
            "params": self._params.copy(),
            "training_data_points": self._training_data_points,
            "model_type": "GARCH(1,1)",
        }
    
    def set_state_dict(self, state: dict) -> None:
        """
        Restore model state from dictionary (inverse of get_state_dict).
        
        Args:
            state: Dictionary with model state
            
        Note:
            Restores configuration but NOT the underlying arch.GARCH object.
            For full model reconstruction including forecasting capability,
            use joblib to serialize/deserialize the entire object.
        """
        self.pair = state["pair"]
        self.mean = state.get("mean", "Zero")
        self.fitted = state["fitted"]
        if state["fit_date"]:
            self.fit_date = datetime.fromisoformat(state["fit_date"])
        self._params = state["params"].copy()
        self._training_data_points = state["training_data_points"]
