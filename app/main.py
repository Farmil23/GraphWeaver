import uvicorn
from app.api.v1.endpoints import app  # noqa: F401  (re-exported for uvicorn)

if __name__ == "__main__":
    uvicorn.run(
        "app.api.v1.endpoints:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
