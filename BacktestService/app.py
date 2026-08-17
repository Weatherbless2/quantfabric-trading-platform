"""ASGI entry point for the QuantFabric read-only backtest service."""

from .service import create_app

app = create_app()
