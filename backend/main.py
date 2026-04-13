# Vercel entry point — re-exports the FastAPI app from the app package.
# Vercel's Python service runner looks for `app` in backend/main.py.
from app.main import app  # noqa: F401

__all__ = ["app"]
