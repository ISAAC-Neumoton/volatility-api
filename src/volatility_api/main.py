"""Main application entry point"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.volatility_api.config import settings
from src.volatility_api.api import routes
from src.volatility_api.data.repository import RepositoryService
from src.volatility_api.core.logging import RequestLoggingMiddleware, logger


# Initialize DB tables cleanly on startup without blocking requests
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events: initialize tables on startup."""
    try:
        repo = RepositoryService(settings.database_url)
        repo.initialize()
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization warning: {e}")
    yield


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Request Logging & Audit Middleware (Sprint 4)
repo_instance = RepositoryService(settings.database_url)
app.add_middleware(RequestLoggingMiddleware, repo_service=repo_instance)

# Include routers
app.include_router(routes.router)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Volatility API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)