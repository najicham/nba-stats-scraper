"""
Unified Admin Dashboard - FastAPI Backend

Consolidates all monitoring, operations, and analytics into a single interface.
Replaces fragmented dashboard systems with one cohesive solution.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NBA Stats Unified Dashboard",
    description="Unified monitoring and operations dashboard",
    version="1.0.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "unified-dashboard",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "api": "ok",
            "firestore": "ok",  # TODO: Add actual checks
            "bigquery": "ok"    # TODO: Add actual checks
        }
    }


# Import route modules will be done after app initialization to avoid circular imports
# Routes are registered below

# Import and register routes
try:
    from api import home
    app.include_router(home.router, prefix="/api", tags=["home"])
except ImportError as e:
    logger.warning(f"Could not import home router: {e}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
