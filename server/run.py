"""AIS AssetTrack server - single-process runner. Developed by DT
  python run.py                  -> http://127.0.0.1:8001 (development / console)
  IIS (HttpPlatformHandler or ASP.NET Core Module): IIS starts this file and gives the port in HTTP_PLATFORM_PORT /
  ASPNETCORE_PORT; IIS itself listens on 80 / 443 and passes the requests on (see iis\\Setup_IIS.ps1).
The tray app (tray_app.py) is the other way to run the same server, without IIS."""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PALLET_PORT") or os.getenv("HTTP_PLATFORM_PORT") or os.getenv("ASPNETCORE_PORT") or "8001")
    uvicorn.run("app.main:app", host=os.getenv("PALLET_HOST", "127.0.0.1"), port=port, workers=1, log_level="info",
                proxy_headers=True, forwarded_allow_ips="127.0.0.1")
