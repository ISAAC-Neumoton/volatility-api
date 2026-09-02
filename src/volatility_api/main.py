"""Main application entry point"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.volatility_api.config import settings
from src.volatility_api.api import routes


app = FastAPI(title=settings.app_name, debug=settings.debug)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
