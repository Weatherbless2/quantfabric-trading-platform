"""ASGI entry point for historical minute bars."""

from .service import create_app

app = create_app()
