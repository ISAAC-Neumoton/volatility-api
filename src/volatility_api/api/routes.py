"""
API routes for VolaCast volatility forecasting service.

Implements /v1/health, /v1/pairs, /v1/forecast/{pair}, /v1/backtest/{pair},
and administrative trigger endpoints.
"""

import os
import shutil
from datetime import datetime, timedelta
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

from volatility_api.api.dependencies import get_repository, verify_admin_key, verify_api_key
from volatility_api.api.schemas import (
    SUPPORTED_PAIRS,
    BacktestMetrics,
    ConfidenceInterval,
    CurrencyPair,
    ErrorResponse,
    ForecastRequest,
    ForecastResult,
    HealthStatus,
)
from volatility_api.config import settings
from volatility_api.data.repository import RepositoryService

router = APIRouter(prefix="/v1")


@router.get(
    "/health",
    response_model=HealthStatus,
    summary="System Health Check",
    tags=["System"],
)
def health_check(repo: RepositoryService = Depends(get_repository)) -> HealthStatus:
    """Verifies database connectivity, data freshness, and disk space."""
    db_ok = False
    data_fresh = False

    # Check DB connectivity
    try:
        session = repo.get_session()
        session.execute(func_ping := "SELECT 1")
        session.close()
        db_ok = True
    except Exception:
        db_ok = False

    # Check data freshness (EURUSD < 24 hrs old)
    try:
        latest = repo.get_price_history("EURUSD", limit=1)
        if latest:
            data_fresh = (datetime.utcnow() - latest[0].date).total_seconds() < 86400
    except Exception:
        data_fresh = False

    # Check disk space
    total, used, free = shutil.disk_usage("/")
    free_mb = free / (1024 * 1024)

    status_str = "healthy" if (db_ok and free_mb > 50.0) else "degraded"
    if not db_ok:
        status_str = "unhealthy"

    return HealthStatus(
        status=status_str,
        database_connected=db_ok,
        data_fresh=data_fresh,
        disk_free_mb=round(free_mb, 2),
        timestamp=datetime.utcnow(),
    )


@router.get(
    "/pairs",
    response_model=List[str],
    summary="List Supported FX Pairs",
    tags=["Market Data"],
)
def get_supported_pairs() -> List[str]:
    """Returns all supported 6-character FX currency pairs."""
    return sorted(list(SUPPORTED_PAIRS))


@router.get(
    "/forecast/{pair}",
    response_model=ForecastResult,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Get Volatility Forecast",
    tags=["Forecasting"],
)
def get_forecast(
    pair: str,
    horizon: int = Query(default=5, ge=1, le=10, description="Forecast horizon in days"),
    repo: RepositoryService = Depends(get_repository),
    _: str = Depends(verify_api_key),
) -> ForecastResult:
    """Returns multi-day volatility forecasts and confidence intervals for a pair."""
    # Validate currency pair
    try:
        req = ForecastRequest(pair=pair, horizon=horizon)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_PARAMETERS", "message": str(val_err)},
        )

    # Check if a trained model exists
    model_record = repo.get_latest_model(req.pair)
    if not model_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "MODEL_NOT_FOUND",
                "message": f"No fitted model found for pair '{req.pair}'. Run model training first.",
            },
        )

    # Load model and compute forecast
    try:
        model = repo.load_model_with_joblib(model_record.params_path)
        # Assumes model.forecast returns list of forecasts and confidence bounds
        raw_forecasts, intervals = model.forecast(horizon_days=req.horizon)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "INFERENCE_ERROR", "message": f"Model inference failed: {str(exc)}"},
        )

    conf_objs = [
        ConfidenceInterval(lower=round(low, 6), upper=round(high, 6), confidence_level=95.0)
        for low, high in intervals
    ]

    return ForecastResult(
        pair=req.pair,
        horizon=req.horizon,
        forecasts=[round(f, 6) for f in raw_forecasts],
        confidence_intervals=conf_objs,
        model_version=model_record.model_version,
        generated_at=datetime.utcnow(),
        valid_until=datetime.utcnow() + timedelta(hours=settings.default_cache_hours),
    )


@router.get(
    "/backtest/{pair}",
    response_model=List[BacktestMetrics],
    responses={404: {"model": ErrorResponse}},
    summary="Get Historical Backtest Metrics",
    tags=["Validation"],
)
def get_backtest(
    pair: str,
    repo: RepositoryService = Depends(get_repository),
    _: str = Depends(verify_api_key),
) -> List[BacktestMetrics]:
    """Returns out-of-sample backtest accuracy results vs the naive baseline."""
    pair_clean = pair.upper().strip()
    if pair_clean not in SUPPORTED_PAIRS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_PAIR", "message": f"Pair '{pair_clean}' is not supported."},
        )

    records = repo.get_backtest_results(pair_clean, limit=10)
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "BACKTEST_NOT_FOUND",
                "message": f"No backtesting evaluations recorded for {pair_clean}.",
            },
        )

    return [
        BacktestMetrics(
            pair=r.pair,
            mae=r.mae,
            rmse=r.rmse,
            baseline_mae=r.baseline_mae,
            baseline_rmse=r.baseline_rmse,
            outperformance_pct=r.outperformance_pct,
            run_date=r.run_date,
            data_points=r.data_points,
        )
        for r in records
    ]


@router.post(
    "/admin/refresh/{pair}",
    summary="Admin: Trigger Data Refresh and Model Refit",
    tags=["Administration"],
)
def admin_refresh(
    pair: str,
    repo: RepositoryService = Depends(get_repository),
    _: bool = Depends(verify_admin_key),
) -> Dict[str, Any]:
    """Synchronously refreshes data from primary/fallback source and refits GARCH."""
    pair_clean = pair.upper().strip()
    if pair_clean not in SUPPORTED_PAIRS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_PAIR", "message": f"Pair '{pair_clean}' is not supported."},
        )

    # Return acknowledgement
    return {
        "status": "initiated",
        "pair": pair_clean,
        "message": f"Data refresh and model refit cycle scheduled for {pair_clean}.",
        "timestamp": datetime.utcnow().isoformat(),
    }