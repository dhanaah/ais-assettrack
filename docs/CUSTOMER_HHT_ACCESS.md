# Customer HHT (Option A return slips) - network access
AIS AssetTrack · Developed by DT

## How the customer HHT connects
The HHT at the customer site is paired once by QR (web: Masters › Customers › 📱 HHT). On every call it:
1. tries the **AIS network** addresses (server name / PC name / IPs) - all at once, 2.5 s wait. Used when the HHT is on AIS Wi-Fi or AIS VPN (sister plants, customers on the AIS network): **direct to the AIS server**.
2. otherwise uses the **internet address** of the customer API (below).
3. with no network at all, the slip is kept on the HHT and sent automatically later (never doubled).

Only the customer API is used: `/api/ext/v1/...` with the device key in the `X-API-Key` header. The customer sees only its own pallets and can only create Option A return slips.

## Recommended setup for outside access (for AIS IT)
**Publish only `/api/ext/` through the company reverse proxy / WAF in the DMZ, over HTTPS.** The AssetTrack server itself stays inside the AIS network.

| Item | Setting |
|---|---|
| Public name | e.g. `https://assettrack.aisglass.com` (company TLS certificate) |
| Forward | `https://assettrack.aisglass.com/api/ext/*` → `http://<AssetTrack server>:8001/api/ext/*` |
| Block | every other path (`/`, `/api/v1/*`, `/print/*`, `/static/*`) - not reachable from the internet |
| Firewall | inbound 443 to the proxy only; proxy → AssetTrack server port 8001 inside |
| Limits | rate limit (e.g. 60 requests/min per IP), request size 1 MB |
| Logging | proxy access log kept 90 days |

Then put the address in `server\settings.env`:
```
PALLET_PUBLIC_API_URL=https://assettrack.aisglass.com
```
and restart the server. New pairing QRs carry it; HHTs paired before can take it in Settings › AIS connection.

Why this way: the server is never exposed (only two read / one create endpoints are), every customer HHT has its own key that AIS can remove at once (web: Customers › 📱 HHT › Remove), and the same HHT works on AIS Wi-Fi without the internet.

Alternatives if the reverse proxy is not available yet:
- **AIS VPN / APN SIM** on the customer HHT: it then counts as "AIS network" and talks to the server directly.
- **Until then**: customers without AIS network use Option B (slip made by AIS Security at the IN gate). A customer HHT without any network keeps its slips and sends them later, but the slip with the AIS-signed QR prints only after it has reached AIS.
