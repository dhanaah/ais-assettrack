# Customer HHT (Option A return slips) - network access
AIS AssetTrack · Developed by DT

**AIS rule: nothing is published to the internet.** Customer HHTs reach the AssetTrack server only through the AIS SSL-VPN.

## How the customer HHT connects
The HHT at the customer site is paired once by QR (web: Masters › Customers › 📱 HHT). On every call it:
1. tries the **AIS network** addresses from the pairing QR (server name / PC name / IPs) - all at once, short wait. These are reachable when the HHT is on AIS Wi-Fi or connected to the **AIS VPN (FortiClient)**.
2. with no connection, the slip is kept on the HHT and sent automatically later (never doubled).

Only the customer API is used: `/api/ext/v1/...` with the device key in the `X-API-Key` header. The customer sees only its own pallets and can only create Option A return slips and, where enabled, customer receipts.
Customer staff sign in on the HHT with their own user; a sign-in that is no longer valid (expired, password reset by AIS, server replaced) is signed out automatically with the reason.

## Setup for AIS IT
| Item | Setting |
|---|---|
| VPN | FortiClient SSL-VPN account per customer site (or per HHT) |
| Access | that VPN account may reach **only** the AssetTrack server, TCP port 8001 (or 443 if IIS is used) |
| Other AIS systems | not reachable from the customer VPN account |
| Logging | VPN connection log kept 90 days |

On the HHT: install FortiClient, sign in to the VPN, then open AssetTrack. Nothing else is configured on the HHT; the addresses come from the pairing QR.

## Security
- Every customer HHT has its own key; AIS can remove it at once (web: Customers › 📱 HHT › Remove).
- Return-slip QR codes are signed by the AssetTrack server and checked at the AIS IN gate.
- Customers without VPN use Option B (slip made by AIS Security at the IN gate).
