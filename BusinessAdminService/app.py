"""ASGI entrypoint for the business administration service."""

from .service import create_app

app = create_app()
