"""
Demo client for testing VolaCast API endpoints.

Provides a simple CLI for interacting with the VolaCast API, including:
    - Health checks
    - Forecast retrieval
    - Backtest metrics
    - Admin refresh operations

Useful for development and integration testing.

Usage:
    python scripts/demo_client.py health --url http://localhost:8000

    python scripts/demo_client.py forecast --url http://localhost:8000 \
        --api-key vca_xxxxx --pair EURUSD --horizon 5

    python scripts/demo_client.py backtest --url http://localhost:8000 \
        --api-key vca_xxxxx --pair EURUSD

Examples:
    # Check API health (no auth required)
    python scripts/demo_client.py health

    # Get forecast with API key
    python scripts/demo_client.py forecast --api-key vca_xxxxx --pair USDJPY

    # Show all available pairs
    python scripts/demo_client.py pairs --api-key vca_xxxxx
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import httpx

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from volatility_api.api.schemas import SUPPORTED_PAIRS


class VolaCastClient:
    """
    HTTP client for VolaCast API.

    Methods:
        health: Check API health status.
        pairs: Get supported currency pairs.
        forecast: Request volatility forecast.
        backtest: Get backtest metrics.
        refresh_pair: Admin operation to refresh data and refit model.
    """

    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None):
        """
        Initialize VolaCast client.

        Args:
            base_url: API base URL (default: http://localhost:8000).
            api_key: Optional API key for authenticated endpoints.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _get_headers(self, include_auth: bool = False) -> dict:
        """Get request headers."""
        headers = {"Accept": "application/json"}
        if include_auth and self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def health(self) -> dict:
        """
        Check API health status.

        Returns:
            Health check response as dictionary.

        Raises:
            httpx.HTTPError: On HTTP error.
        """
        with httpx.Client() as client:
            response = client.get(f"{self.base_url}/v1/health")
            response.raise_for_status()
            return response.json()

    def pairs(self) -> dict:
        """
        Get supported currency pairs.

        Returns:
            Dictionary with supported pairs.

        Raises:
            httpx.HTTPError: On HTTP error.
        """
        with httpx.Client() as client:
            response = client.get(
                f"{self.base_url}/v1/pairs",
                headers=self._get_headers(include_auth=True),
            )
            response.raise_for_status()
            return response.json()

    def forecast(self, pair: str, horizon: int = 5) -> dict:
        """
        Request volatility forecast.

        Args:
            pair: FX pair code (e.g., "EURUSD").
            horizon: Forecast horizon in days (1-10).

        Returns:
            Forecast response as dictionary.

        Raises:
            httpx.HTTPError: On HTTP error.
            ValueError: If API key not configured.
        """
        if not self.api_key:
            raise ValueError("API key required for forecast endpoint")

        with httpx.Client() as client:
            response = client.get(
                f"{self.base_url}/v1/forecast/{pair}",
                params={"horizon": horizon},
                headers=self._get_headers(include_auth=True),
            )
            response.raise_for_status()
            return response.json()

    def backtest(self, pair: str) -> dict:
        """
        Get backtest metrics for a pair.

        Args:
            pair: FX pair code.

        Returns:
            Backtest results as dictionary.

        Raises:
            httpx.HTTPError: On HTTP error.
            ValueError: If API key not configured.
        """
        if not self.api_key:
            raise ValueError("API key required for backtest endpoint")

        with httpx.Client() as client:
            response = client.get(
                f"{self.base_url}/v1/backtest/{pair}",
                headers=self._get_headers(include_auth=True),
            )
            response.raise_for_status()
            return response.json()

    def refresh_pair(self, pair: str, admin_secret: str) -> dict:
        """
        Admin operation: refresh data and refit model for a pair.

        Args:
            pair: FX pair code.
            admin_secret: Admin secret key from X-Admin-Secret header.

        Returns:
            Response as dictionary.

        Raises:
            httpx.HTTPError: On HTTP error.
        """
        headers = {"X-Admin-Secret": admin_secret}

        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}/v1/admin/refresh/{pair}",
                headers=headers,
            )
            response.raise_for_status()
            return response.json()


def format_output(data: dict) -> str:
    """Format output as pretty JSON."""
    return json.dumps(data, indent=2, default=str)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="VolaCast API demo client",
        epilog="Example: python scripts/demo_client.py forecast --pair EURUSD --api-key vca_xxxxx",
    )

    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )

    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key for authenticated endpoints",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Health command
    subparsers.add_parser("health", help="Check API health status")

    # Pairs command
    subparsers.add_parser("pairs", help="Get supported currency pairs")

    # Forecast command
    forecast_parser = subparsers.add_parser("forecast", help="Request volatility forecast")
    forecast_parser.add_argument("--pair", type=str, default="EURUSD", help="FX pair (default: EURUSD)")
    forecast_parser.add_argument("--horizon", type=int, default=5, help="Forecast horizon in days (default: 5)")

    # Backtest command
    backtest_parser = subparsers.add_parser("backtest", help="Get backtest metrics")
    backtest_parser.add_argument("--pair", type=str, default="EURUSD", help="FX pair (default: EURUSD)")

    # Refresh command (admin)
    refresh_parser = subparsers.add_parser("refresh", help="Admin: refresh data and refit model")
    refresh_parser.add_argument("--pair", type=str, default="EURUSD", help="FX pair (default: EURUSD)")
    refresh_parser.add_argument("--admin-secret", type=str, required=True, help="Admin secret key")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Create client
    client = VolaCastClient(base_url=args.url, api_key=args.api_key)

    try:
        if args.command == "health":
            print("🏥 Checking API health...")
            result = client.health()
            print(format_output(result))

        elif args.command == "pairs":
            print("📊 Supported currency pairs:")
            pairs_list = sorted(SUPPORTED_PAIRS)
            for i, pair in enumerate(pairs_list, 1):
                print(f"  {i:2d}. {pair}")
            print(f"\nTotal: {len(pairs_list)} pairs")

        elif args.command == "forecast":
            print(f"📈 Requesting forecast for {args.pair} (horizon={args.horizon} days)...")
            result = client.forecast(args.pair, args.horizon)
            print(format_output(result))

        elif args.command == "backtest":
            print(f"🧪 Retrieving backtest metrics for {args.pair}...")
            result = client.backtest(args.pair)
            print(format_output(result))

        elif args.command == "refresh":
            print(f"🔄 Admin refresh for {args.pair}...")
            result = client.refresh_pair(args.pair, args.admin_secret)
            print(format_output(result))

        return 0

    except ValueError as e:
        print(f"❌ Error: {str(e)}", file=sys.stderr)
        return 1

    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP Error {e.response.status_code}: {e.response.text}", file=sys.stderr)
        return 1

    except httpx.ConnectError as e:
        print(f"❌ Connection error: {str(e)}", file=sys.stderr)
        print(f"   Is the API running at {args.url}?", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
