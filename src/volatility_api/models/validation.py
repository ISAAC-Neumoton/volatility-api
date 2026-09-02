"""Model validation and backtesting utilities"""

from typing import Dict, Tuple

import numpy as np
import pandas as pd


class BacktestValidator:
    """Backtesting and validation utility for models"""

    @staticmethod
    def calculate_returns(prices: pd.Series) -> pd.Series:
        """
        Calculate log returns from price series.

        Args:
            prices: Series of prices

        Returns:
            Series of log returns
        """
        return np.log(prices / prices.shift(1)).dropna()

    @staticmethod
    def mean_absolute_error(actual: np.ndarray, predicted: np.ndarray) -> float:
        """
        Calculate Mean Absolute Error.

        Args:
            actual: Actual values
            predicted: Predicted values

        Returns:
            MAE value
        """
        return np.mean(np.abs(actual - predicted))

    @staticmethod
    def direction_accuracy(actual_returns: pd.Series, predicted_direction: np.ndarray) -> float:
        """
        Calculate direction prediction accuracy.

        Args:
            actual_returns: Actual returns
            predicted_direction: Predicted direction (1 for up, -1 for down)

        Returns:
            Accuracy score (0-1)
        """
        actual_direction = np.sign(actual_returns.values)
        correct = (actual_direction == predicted_direction).sum()
        return correct / len(actual_direction)

    @staticmethod
    def run_backtest(
        returns: pd.Series,
        model,
        test_size: float = 0.2,
    ) -> Dict[str, float]:
        """
        Run backtest on model.

        Args:
            returns: Series of returns
            model: Trained model
            test_size: Proportion of data to use for testing

        Returns:
            Dictionary with backtest metrics
        """
        split_idx = int(len(returns) * (1 - test_size))
        train_returns = returns[:split_idx]
        test_returns = returns[split_idx:]

        # Fit model on training data
        model.fit(train_returns)

        # Generate forecasts
        forecasts = []
        for i in range(len(test_returns)):
            forecast = model.forecast(horizon=1)
            forecasts.append(forecast.iloc[0, 0])

        # Calculate metrics
        mae = BacktestValidator.mean_absolute_error(
            test_returns.std(),
            np.array(forecasts),
        )

        return {"mae": mae, "test_size": len(test_returns)}
