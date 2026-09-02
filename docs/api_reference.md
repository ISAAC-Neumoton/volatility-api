# API Reference

## Volatility API Documentation

### Base URL
```
http://localhost:8000/api
```

### Authentication
All endpoints require an `X-API-Key` header with a valid API key.

```
X-API-Key: your_api_key_here
```

## Endpoints

### GET /volatility/{symbol}
Get volatility forecast for a given stock symbol.

**Parameters:**
- `symbol` (path): Stock ticker symbol (e.g., "AAPL")

**Response:**
```json
{
  "symbol": "AAPL",
  "volatility": 0.25,
  "timestamp": "2024-01-15T10:30:00",
  "confidence": 0.85
}
```

### POST /backtest
Run backtesting on a volatility model.

**Request Body:**
```json
{
  "symbol": "AAPL",
  "start_date": "2023-01-01",
  "end_date": "2024-01-01",
  "model_type": "garch"
}
```

**Response:**
```json
{
  "symbol": "AAPL",
  "score": 0.85,
  "results": {}
}
```

## Status Codes
- `200`: Success
- `400`: Bad Request
- `401`: Unauthorized
- `500`: Internal Server Error

## Error Handling
All errors return a JSON response with an error message:

```json
{
  "detail": "Error message here"
}
```
