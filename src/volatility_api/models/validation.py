"""
Walk-forward backtesting and model validation engine.

Implements walk-forward analysis (rolling-window out-of-sample validation) for
forecast evaluation. Models are trained on historical data and tested on forward-looking
out-of-sample data, simulating real-world deployment conditions.

Features:
    - Rolling-window retraining on expanding or fixed windows
    - Out-of-sample performance metrics (MAE, RMSE, outperformance %)
    - Baseline comparison (rolling standard deviation)
    - Per-period forecast storage for analysis
    - Validation of model superiority (≥10% outperformance gate)

Mathematical Foundation:
    Walk-Forward Backtest:
        For each test period:
            1. Fit model on training window (e.g., last 252 days)
            2. Forecast 1-day horizon volatility
            3. Compare forecast to realized volatility
            4. Step forward 1 day
            5. Repeat until end of data
    
    Performance Metrics:
        MAE = (1/N) Σ|y_t - ŷ_t|           (Mean Absolute Error)
        RMSE = √((1/N) Σ(y_t - ŷ_t)²)     (Root Mean Squared Error)
        MAPE = (1/N) Σ|y_t - ŷ_t| / |y_t|  (Mean Absolute Percentage Error)
        
    Outperformance:
        baseline = rolling std(returns, window=100)
        model_error = MAE(forecast, realized_vol)
        outperformance = 100 * (baseline_error - model_error) / baseline_error
        
        Model validated if outperformance ≥ 10% (beats rolling std by 10%)

Author: VolatilityCast
Version: 1.0
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from numpy.typing import NDArray


class WalkForwardBacktester:
    """
    Walk-forward backtester for out-of-sample model validation.
    
    Implements rolling-window evaluation: train on historical window, forecast next period,
    step forward. Compares model to baseline (rolling std) and computes performance metrics.
    
    Workflow:
        1. Initialize with returns data and train/test windows
        2. Call backtest(model) which:
           a. Iterates through data with rolling windows
           b. Fits model on each training window
           c. Generates 1-day forecast
           d. Compares to realized volatility (absolute daily return)
           e. Steps forward 1 day
        3. Returns DataFrame with forecast history and metrics
        4. Validates model outperformance ≥ 10% vs baseline
    
    Attributes:
        returns: Log-returns array (1D), shape (n,)
        train_window: Size of training window (days), default 252 (1 year)
        test_window: Size of test window (days), default 100
        baseline_window: Size of rolling window for baseline std (days), default 100
        min_outperformance_pct: Validation gate for model superiority (default 10%)
    
    Example:
        >>> returns = np.array([-0.01, 0.005, ...])  # 1000 days
        >>> backtester = WalkForwardBacktester(
        ...     returns,
        ...     train_window=252,
        ...     test_window=100,
        ... )
        >>> model = GARCHModel("EURUSD")
        >>> results = backtester.backtest(model)
        >>> print(f"MAE: {results['mae']:.4f}")
        >>> print(f"Outperformance: {results['outperformance_pct']:.1f}%")
        >>> if results['is_valid']:
        ...     print("Model validated (outperformance ≥ 10%)")
    """
    
    def __init__(
        self,
        returns: NDArray[np.float64],
        train_window: int = 252,
        test_window: Optional[int] = None,
        baseline_window: int = 100,
        min_outperformance_pct: float = 10.0,
    ) -> None:
        """
        Initialize walk-forward backtester.
        
        Args:
            returns: 1D array of log-returns
            train_window: Training window size in days (default 252 ≈ 1 year)
            test_window: Test window size in days (default auto-calculated)
            baseline_window: Rolling window for baseline std (default 100)
            min_outperformance_pct: Validation threshold (%)
            
        Raises:
            ValueError: If returns is invalid or windows are misconfigured
        """
        if not isinstance(returns, np.ndarray) or returns.ndim != 1:
            raise ValueError("returns must be 1D numpy array")
        
        if len(returns) < train_window + 100:
            raise ValueError(
                f"returns requires ≥{train_window + 100} points, got {len(returns)}"
            )
        
        if train_window < 50:
            raise ValueError(f"train_window must be ≥50, got {train_window}")
        
        self.returns = returns
        self.train_window = train_window
        self.test_window = test_window or (len(returns) - train_window) // 2
        self.baseline_window = baseline_window
        self.min_outperformance_pct = min_outperformance_pct
        
        if self.test_window < 10:
            raise ValueError(f"test_window must be ≥10, got {self.test_window}")
    
    def _calculate_realized_volatility(
        self,
        returns: NDArray[np.float64],
        window: int = 1,
    ) -> NDArray[np.float64]:
        """
        Calculate realized (historical) volatility.
        
        Args:
            returns: Log-returns array
            window: Number of days to aggregate (default 1 for daily)
            
        Returns:
            1D array of rolling volatilities (annualized %)
        """
        if window == 1:
            # Daily volatility = |return| (approximation)
            return np.abs(returns)
        else:
            # Rolling window volatility
            realized_vol = pd.Series(returns).rolling(window=window).std()
            return realized_vol.values * np.sqrt(252) * 100
    
    def _calculate_baseline_forecast(
        self,
        returns: NDArray[np.float64],
        window: int = 100,
    ) -> NDArray[np.float64]:
        """
        Calculate baseline forecast (rolling standard deviation).
        
        Args:
            returns: Log-returns array
            window: Rolling window size (default 100 days)
            
        Returns:
            1D array of rolling std forecasts (annualized %)
        """
        rolling_vol = pd.Series(returns).rolling(window=window).std()
        return rolling_vol.values * np.sqrt(252) * 100
    
    def backtest(self, model) -> dict:
        """
        Run walk-forward backtest on model.
        
        Workflow:
            1. Initialize at start of train window
            2. For each test period:
               a. Extract training data (indices i to i+train_window)
               b. Fit model on training data
               c. Forecast 1-day volatility (horizon=1)
               d. Take point forecast (not confidence interval)
               e. Compare to realized volatility (|return| on next day)
               f. Store forecast, realized, error
               g. Step forward 1 day
            3. Calculate metrics:
               - MAE = mean(|forecast - realized|)
               - RMSE = sqrt(mean((forecast - realized)²))
               - Baseline MAE = mean(|baseline - realized|)
               - Outperformance % = (baseline_mae - model_mae) / baseline_mae × 100
            4. Validate model (is_valid = outperformance ≥ threshold)
        
        Args:
            model: VolatilityForecaster instance (must have fit() and forecast())
            
        Returns:
            Dictionary with keys:
                mae (float): Mean absolute error of forecast
                rmse (float): Root mean squared error
                baseline_mae (float): Baseline (rolling std) MAE
                mape (float): Mean absolute percentage error
                outperformance_pct (float): Model vs baseline, %
                is_valid (bool): True if outperformance ≥ min_outperformance_pct
                test_periods (int): Number of forecast periods
                forecasts (np.ndarray): 1D array of forecasts
                realized_vols (np.ndarray): 1D array of realized vols
                baseline_forecasts (np.ndarray): 1D array of baseline forecasts
                errors (np.ndarray): Forecast errors (forecast - realized)
            
        Raises:
            ValueError: If model not fitted or forecast fails
            RuntimeError: If backtest encounters unexpected data issues
        """
        forecasts: List[float] = []
        realized_vols: List[float] = []
        baseline_forecasts: List[float] = []
        errors: List[float] = []
        
        # Walk forward through test window
        start_idx = self.train_window
        end_idx = start_idx + self.test_window
        
        for t in range(start_idx, end_idx):
            # Extract training window
            train_data = self.returns[t - self.train_window : t]
            
            # Fit model on training data
            try:
                model.fit(train_data)
            except Exception as e:
                raise RuntimeError(
                    f"Model fit failed at test period {t - start_idx}: {e}"
                ) from e
            
            # Generate 1-day forecast
            try:
                forecast_point, _ = model.forecast(horizon=1)
                forecast = float(forecast_point[0])
            except Exception as e:
                raise RuntimeError(
                    f"Model forecast failed at test period {t - start_idx}: {e}"
                ) from e
            
            # Calculate realized volatility (next day absolute return)
            realized_vol = abs(self.returns[t]) * np.sqrt(252) * 100  # Annualized %
            
            # Calculate baseline forecast (rolling std at t-1)
            baseline = self._calculate_baseline_forecast(
                self.returns[t - self.baseline_window : t],
                window=self.baseline_window,
            )[-1]
            
            forecasts.append(forecast)
            realized_vols.append(realized_vol)
            baseline_forecasts.append(baseline)
            errors.append(forecast - realized_vol)
        
        # Convert to arrays
        forecasts_arr = np.array(forecasts)
        realized_arr = np.array(realized_vols)
        baseline_arr = np.array(baseline_forecasts)
        errors_arr = np.array(errors)
        
        # Calculate metrics
        mae = np.mean(np.abs(errors_arr))
        rmse = np.sqrt(np.mean(errors_arr ** 2))
        baseline_errors = baseline_arr - realized_arr
        baseline_mae = np.mean(np.abs(baseline_errors))
        mape = np.mean(np.abs(errors_arr) / np.maximum(realized_arr, 0.001)) * 100
        
        # Calculate outperformance
        if baseline_mae > 0:
            outperformance_pct = 100 * (baseline_mae - mae) / baseline_mae
        else:
            outperformance_pct = 0.0
        
        is_valid = outperformance_pct >= self.min_outperformance_pct
        
        return {
            "mae": float(mae),
            "rmse": float(rmse),
            "baseline_mae": float(baseline_mae),
            "mape": float(mape),
            "outperformance_pct": float(outperformance_pct),
            "is_valid": bool(is_valid),
            "test_periods": len(forecasts),
            "forecasts": forecasts_arr,
            "realized_vols": realized_arr,
            "baseline_forecasts": baseline_arr,
            "errors": errors_arr,
        }
    
    def summary(self, backtest_results: dict) -> str:
        """
        Generate human-readable backtest summary.
        
        Args:
            backtest_results: Dictionary returned by backtest()
            
        Returns:
            Formatted string with metrics and validation status
        """
        return (
            f"\n== Walk-Forward Backtest Results ==\n"
            f"Test Periods: {backtest_results['test_periods']}\n"
            f"\nModel Performance:\n"
            f"  MAE:  {backtest_results['mae']:.4f}\n"
            f"  RMSE: {backtest_results['rmse']:.4f}\n"
            f"  MAPE: {backtest_results['mape']:.2f}%\n"
            f"\nBaseline (Rolling Std):\n"
            f"  MAE:  {backtest_results['baseline_mae']:.4f}\n"
            f"\nComparative Performance:\n"
            f"  Outperformance: {backtest_results['outperformance_pct']:+.1f}%\n"
            f"  Validation: {'✓ PASS' if backtest_results['is_valid'] else '✗ FAIL'} "
            f"(≥{self.min_outperformance_pct}% required)\n"
        )
