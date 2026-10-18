from fastapi import FastAPI

app = FastAPI(
    title="Sophikron API",
    description="API for the Sophikron educational platform.",
    version="0.1.0",
)


@app.get("/")
async def read_root() -> dict[str, str]:
    """Return basic API information."""
    return {"message": "Welcome to Sophikron API"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Return the API health status."""
    return {"status": "ok"}