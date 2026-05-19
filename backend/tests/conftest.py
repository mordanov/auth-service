"""Shared pytest configuration for backend tests.

The async loop is managed by pytest-asyncio. Integration modules that touch the
shared async SQLAlchemy engine opt into a session-scoped asyncio loop via an
explicit module-level marker.
"""

import pytest_asyncio


@pytest_asyncio.fixture(scope="session", autouse=True)
async def cleanup_async_resources():
	"""Close shared async resources after the test session finishes."""
	yield

	try:
		from src.middleware.rate_limit import close_redis

		await close_redis()
	except Exception:
		pass

	try:
		from src.db.base import engine

		await engine.dispose()
	except Exception:
		pass
