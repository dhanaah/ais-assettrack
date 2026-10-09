# AIS AssetTrack — Customer Return Slip API (v1)
*For customer-end IT teams outside the AIS network. Developed by DT.*

## 1. What it does
When empty AIS pallets are loaded on a vehicle at your plant, your system (or a simple web form / script) sends AIS:
the **pallets**, the **vehicle number** and your **delivery challan**. AIS returns a **Return Slip number** and a
printable **Return Slip with QR**. Print it and hand it to the driver. At the AIS IN gate, security scans the QR — the vehicle is
checked in automatically and the pallets are reconciled against your list.

## 2. Access
| Item | Value |
|---|---|
| Base URL | `https://<AIS public host>/api/ext/v1` (given by AIS IT) |
| Auth | Header `X-API-Key: <your key>` — one key per customer plant, issued by AIS Master Maintenance |
| Format | JSON, UTF-8 |
| Scope | You see and act on **your own** pallets only |

Keep the key secret. If it leaks, AIS revokes it and issues a new one.

## 3. Endpoints
### 3.1 Pallets currently with you — `GET /holding`
Returns every AIS pallet at your site, with days held and overdue flag. Use it to plan returns.

### 3.2 Check pallets before loading (optional) — `POST /validate`
```json
{ "tags": ["CHN-P00012", "100345", "100346"] }
```
Each tag comes back `ok: true` or with a reason (unknown tag, not at your site). Nothing is changed.

### 3.3 Create the return slip — `POST /return-slip`
```json
{
  "pallets": ["CHN-P00012", "100345", "100346"],
  "vehicle_no": "TN 09 AB 1234",
  "customer_challan_no": "DC/24-25/0871",
  "customer_challan_date": "2026-10-10T09:30:00",
  "driver_name": "R. Kumar",
  "driver_mobile": "98xxxxxx10",
  "transporter": "ABC Logistics",
  "client_ref": "YOURSYS-RET-000871"
}
```
* `pallets`: scanned pallet tag numbers or pallet numbers (max 500).
* `client_ref`: your own unique reference. Sending the same request again returns the same slip (safe to retry).

Response:
```json
{
  "slip_no": "CHN-RTS-000245",
  "status": "OPEN",
  "vehicle_no": "TN09AB1234",
  "declared_qty": 3,
  "qr_payload": "AIS1|RS|CHN-RTS-000245|CHN|HMIL|TN09AB1234|3|2610100930|72CF7FAC",
  "label_url": "/api/ext/v1/return-slip/CHN-RTS-000245/label?t=....",
  "pallets": [{"pallet_no": "CHN-P00012", "received": false, "exception": null}],
  "warnings": []
}
```
`warnings` lists tags AIS does not show at your site — the slip is still created; AIS reconciles at receipt.

### 3.4 Print the Return Slip — `GET {label_url}`
Open `label_url` (prefix the base host) in a browser and press **Print / Save PDF**. You get the standard A4
AIS Pallet Return Slip (AIS logo, slip no / date, customer, vehicle / driver, your challan, pallet list,
signature boxes) with the signed QR at top right. No API key is needed for this link; the link itself is unguessable.
If you prefer printing from your own system, encode `qr_payload` as a QR code (error correction M).

### 3.5 Track the slip — `GET /return-slip/{slip_no}`
Status `OPEN` → `IN_GATE` (vehicle reached AIS) → `RECEIVING` → `CLOSED`, with per-pallet `received` / `exception`.

## 4. QR code content
```
AIS1|RS|<slip no>|<AIS plant>|<customer code>|<vehicle no>|<pallet qty>|<yyMMddHHmm>|<check code>
```
| Field | Example | Purpose |
|---|---|---|
| AIS1 | AIS1 | format version (future changes stay readable) |
| RS | RS | document type: Return Slip |
| slip no | CHN-RTS-000245 | key to the full pallet list on the AIS server |
| AIS plant | CHN | receiving plant — wrong-plant arrival is flagged |
| customer | HMIL | sender |
| vehicle | TN09AB1234 | security compares with the actual vehicle |
| qty | 3 | quick count check at the gate |
| date-time | 2610100930 | slip creation time |
| check code | 72CF7FAC | signed by the AIS server; any edit to the label makes it invalid |

Pallet numbers are **not** inside the QR (keeps it small and fast to scan); the HHT reads them from the slip.

## 5. Errors
| HTTP | Meaning |
|---|---|
| 401 | missing / wrong API key |
| 404 | slip not found or not yours |
| 422 | field missing or wrong type (details in response) |

Interactive documentation (try it): `https://<AIS public host>/docs` → section *external-customer*.
