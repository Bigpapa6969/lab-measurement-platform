"""
dependencies.py — FastAPI dependency providers
===============================================
These are injected via ``Depends()`` in route handlers.
Centralising them here means route handlers never reach into ``request.app``
directly — their signatures stay clean and easy to test.

Usage in a route::

    from app.api.dependencies import get_store
    from app.api.store import InMemoryStore

    @router.get("/measurements/{mid}")
    def get_measurement(mid: str, store: InMemoryStore = Depends(get_store)):
        ...
"""
from fastapi import Request

from app.api.store import InMemoryStore


def get_store(request: Request) -> InMemoryStore:
    """
    Return the application-scoped in-memory store.

    The store is initialised in ``app.main`` during the FastAPI lifespan
    and attached to ``app.state.store``.
    """
    return request.app.state.store
