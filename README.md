# VolaCast - Volatility Forecasting as a Service

> Production-grade REST API for GARCH-based FX volatility forecasting. Zero-budget, sub-2s p95 latency, engineered for FX desks and corporate treasury teams.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## Overview

VolaCast is a production-ready volatility forecasting API built on object-oriented design principles (SOLID, Design Patterns) with strict type safety, zero hardcoded secrets, and optimized for free-tier resource constraints.

### Key Features

- **GARCH(1,1) Volatility Forecasting**: Parametric volatility models with confidence intervals
- **Multi-Source Data Ingestion**: yfinance + Alpha Vantage with automatic fallback
- **Production-Grade Security**: SHA-256 hashed API keys, request logging, audit trails
- **Structured Logging**: JSON logs with request context (duration, status, error traces)
- **Out-of-Sample Backtesting**: Walk-forward validation with baseline comparison
- **Container-Ready**: Multi-stage Docker build, free-tier optimized (~250MB)
- **Type-Safe**: 100% PEP 484 annotations, Pydantic v2 validation, mypy compatible

### Supported Currency Pairs

Major pairs: EURUSD, USDJPY, GBPUSD, USDCHF, USDCAD, AUDUSD, NZDUSD
Emerging markets: USDZAR, USDNGN, USDBRL, USDTRY, USDCNY, USDINR
Cross rates: EURGBP, EURJPY, GBPJPY, AUDJPY, and more

## Project Structure

```
volatility-api/
├── src/volatility_api/
│   ├── api/                # FastAPI routes, schemas, dependencies
│   ├── data/               # Data fetchers and SQLAlchemy repository
│   ├── models/             # Quantitative models (GARCH, backtesting)
│   ├── core/               # Security, logging, configuration
│   ├── config.py           # Environment-driven settings
│   └── main.py             # FastAPI application
├── tests/                  # Unit and integration tests
├── docker/                 # Multi-stage Dockerfile
├── notebooks/              # Jupyter for exploration
├── docs/                   # API reference and architecture
├── scripts/                # Utility scripts (backfill, demo client)
└── .github/workflows/      # CI/CD pipeline
```

## Quick Start

### Prerequisites

- Python 3.11+
- pip or conda

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/volatility-api.git
cd volatility-api

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install package in development mode
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env and set ADMIN_SECRET_KEY
```

### Running the API

```bash
# Start development server
python -m uvicorn src.volatility_api.main:app --reload --host 0.0.0.0 --port 8000

# Server runs at http://localhost:8000
# OpenAPI docs at http://localhost:8000/docs
```

### Running Tests

```bash
# Run all tests with coverage
pytest tests/ --cov=src/volatility_api --cov-report=html

# Run specific test file
pytest tests/test_api.py -v
```

## Docker Deployment

```bash
# Build multi-stage image
docker build -f docker/Dockerfile -t volatility-api:latest .

# Run container
docker run -p 8000:8000 \
  -e DATABASE_URL="sqlite:///./volatility.db" \
  -e ADMIN_SECRET_KEY="your-secret-key" \
  volatility-api:latest

# Check health
curl http://localhost:8000/v1/health
```

## API Usage

### Authentication

All endpoints require an `X-API-Key` header:

```bash
curl -H "X-API-Key: your_api_key_here" \
  http://localhost:8000/v1/forecast/EURUSD?horizon=5
```

### Get Volatility Forecast

```bash
curl -X GET \
  -H "X-API-Key: vca_xxxxx" \
  "http://localhost:8000/v1/forecast/EURUSD?horizon=5"
```

**Response:**

```json
{
  "pair": "EURUSD",
  "horizon": 5,
  "forecasts": [0.245, 0.248, 0.251, 0.249, 0.246],
  "confidence_intervals": [
    {"lower": 0.195, "upper": 0.295, "confidence_level": 95.0},
    {"lower": 0.198, "upper": 0.298, "confidence_level": 95.0},
    {"lower": 0.201, "upper": 0.301, "confidence_level": 95.0},
    {"lower": 0.199, "upper": 0.299, "confidence_level": 95.0},
    {"lower": 0.196, "upper": 0.296, "confidence_level": 95.0}
  ],
  "model_version": "1.0.0",
  "generated_at": "2024-01-15T10:30:45.123Z",
  "valid_until": "2024-01-15T16:30:45.123Z"
}
```

### Get Health Status

```bash
curl http://localhost:8000/v1/health
```

### Get Backtest Metrics

```bash
curl -H "X-API-Key: vca_xxxxx" \
  http://localhost:8000/v1/backtest/EURUSD
```

## Configuration

All configuration is environment-driven via `.env` file:

```bash
# Application
APP_NAME=VolaCast
DEBUG=false
LOG_LEVEL=INFO

# Database (supports SQLite, PostgreSQL, MySQL)
DATABASE_URL=sqlite:///./volatility.db

# Security
ADMIN_SECRET_KEY=<generate-random-secret>

# Model
MAX_FORECAST_HORIZON=10
MIN_DATA_POINTS=504
DEFAULT_CACHE_HOURS=6
MAX_API_KEY_AGE_DAYS=365

# Observability
SENTRY_DSN=<optional-sentry-dsn>

# Data Sources
ALPHA_VANTAGE_KEY=<optional-alpha-vantage-key>
```

## Architecture & Design Patterns

### SOLID Principles

- **Single Responsibility**: Each class has one reason to change (RepositoryService, GARCHModel, etc.)
- **Open/Closed**: Abstract base classes (DataFetcher, VolatilityForecaster) for extension
- **Liskov Substitution**: Concrete fetchers and models are substitutable for their bases
- **Interface Segregation**: Focused interfaces for API dependencies
- **Dependency Inversion**: Injected dependencies, no hardcoded instantiation

### Design Patterns

- **Repository Pattern**: RepositoryService encapsulates all DB operations
- **Factory Pattern**: FetcherFactory selects data source with fallback
- **Strategy Pattern**: Pluggable volatility forecasters (GARCH, etc.)
- **Adapter Pattern**: Unified interface for multiple data sources
- **Middleware**: Request logging, CORS, error handling

### Type Safety

- 100% PEP 484 type annotations across all public APIs
- Pydantic v2 for runtime validation of requests/responses
- mypy for static type checking (configuration in pyproject.toml)
- Custom validators for domain constraints (FX pairs, horizons)

## Development Workflow

### Agile Milestones

- **Sprint 1**: Configuration, schemas, DB models, repository layer ✅
- **Sprint 2**: Data ingestion (fetchers, fallback logic), backfill script
- **Sprint 3**: GARCH modeling, joblib persistence, walk-forward backtesting
- **Sprint 4**: FastAPI endpoints, security, error handling, request logging
- **Sprint 5**: Full test suite, Docker, GitHub Actions CI

### Code Quality

```bash
# Format code
black src/ tests/

# Lint code
ruff check src/ tests/

# Type check
mypy src/

# Run tests with coverage
pytest tests/ --cov=src/volatility_api --cov-report=html

# Coverage gate (>= 70%)
```

### Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

## Performance Targets

- **Latency**: < 2s p95 for forecast endpoints
- **Memory**: <= 512MB RAM (free-tier optimized)
- **Storage**: Ephemeral filesystem with SQLite (configurable)
- **Throughput**: Support for typical FX desk workloads

## Security Considerations

- **API Keys**: SHA-256 hashed, never logged plaintext
- **Environment Variables**: No secrets in code, .env file excluded from git
- **Database**: Unique constraints, foreign key integrity
- **Request Logging**: Audit trail with request context and status codes
- **CORS**: Configurable for production deployments

## Troubleshooting

### Database Locked

If SQLite reports "database is locked", ensure only one process writes at a time. For production, use PostgreSQL.

```bash
# Use PostgreSQL instead
DATABASE_URL=postgresql://user:pass@localhost/volatility
```

### Model Not Found

If backfilling data for the first time, models need training data. Ensure >= 504 historical data points exist.

```bash
# Backfill EURUSD data
python scripts/backfill_data.py EURUSD --start-date 2021-01-01 --end-date 2024-01-15
```

### Auth Failures

Verify API key hash matches in database and is not expired.

```bash
# List all active keys
sqlite3 volatility.db "SELECT key_hash, owner, is_active FROM api_keys WHERE is_active=1;"
```

## Contributing

Contributions are welcome! Please follow:

1. Fork the repository
2. Create feature branch: `git checkout -b feature/my-feature`
3. Commit changes with clear messages
4. Submit pull request against `develop` branch
5. Ensure CI passes (tests, linting, coverage)

## License

MIT License - see LICENSE file for details

## Support

For issues, questions, or suggestions:

- Open a GitHub Issue
- Check existing discussions
- Review [API Reference](docs/api_reference.md)

## Roadmap

- [ ] WebSocket streaming forecasts
- [ ] Multi-horizon ensemble models
- [ ] Historical forecast accuracy reports
- [ ] Rate limiting per API key
- [ ] GraphQL endpoint
- [ ] Kubernetes Helm charts

