"""
FastAPI Document Automation Backend
Main application entry point
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent))

from config import settings
from routers import documents
from models.schemas import HealthResponse, ErrorResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Document Automation System - AI-powered document classification and OCR"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)


@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint - health check"""
    try:
        # Check service availability
        services = {
            'anthropic': settings.anthropic_api_key_configured,
            'gcs': settings.gcs_configured
        }
        
        status = "healthy" if all(services.values()) else "degraded"
        
        return HealthResponse(
            status=status,
            version=settings.VERSION,
            services=services
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return HealthResponse(
            status="unhealthy",
            version=settings.VERSION,
            services={}
        )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for Cloud Run"""
    return await root()


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "timestamp": datetime.now().isoformat()
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )

