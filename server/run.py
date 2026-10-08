"""Dev / single-process runner.  python run.py  ->  http://localhost:8001
Production on IIS: see web.config + README (one worker per app pool, 4 pools on 8001-8004)."""
import os, uvicorn
if __name__ == "__main__":
    port = int(os.getenv("PALLET_PORT", os.getenv("HTTP_PLATFORM_PORT", "8001")))
    uvicorn.run("app.main:app", host=os.getenv("PALLET_HOST", "127.0.0.1"), port=port, workers=1, log_level="info")
