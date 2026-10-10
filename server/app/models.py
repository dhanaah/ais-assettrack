"""SQLAlchemy models - AIS Pallet Asset Tracking (Phase 1 + Phase 2 skeleton)."""
from datetime import datetime, timezone
import uuid
from sqlalchemy import (String, Integer, Boolean, DateTime, Text, ForeignKey, Index,
                        UniqueConstraint, Numeric)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------- masters
class Plant(Base):
    __tablename__ = "plants"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(60))
    state: Mapped[str | None] = mapped_column(String(60))
    gstin: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(250))
    pallet_prefix: Mapped[str | None] = mapped_column(String(10))
    tag_from: Mapped[int | None] = mapped_column(Integer)
    tag_to: Mapped[int | None] = mapped_column(Integer)
    challan_source: Mapped[str] = mapped_column(String(10), default="APP")      # ORACLE | APP
    app_challan_series: Mapped[str | None] = mapped_column(String(20))
    accept_other_plant_default: Mapped[bool] = mapped_column(Boolean, default=True)
    ebs_org_id: Mapped[str | None] = mapped_column(String(20))
    gcs_endpoint: Mapped[str | None] = mapped_column(String(200))
    holding_days_default: Mapped[int] = mapped_column(Integer, default=30)
    wms_stale_hours: Mapped[int | None] = mapped_column(Integer, default=4)          # block release if WMS stock older
    pdi_subinv: Mapped[str | None] = mapped_column(String(20))                       # LPNs wait here for PDI
    reject_subinv: Mapped[str | None] = mapped_column(String(20))                    # PDI rejected LPNs go here
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(String(250))


class Role(Base):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    scope: Mapped[str] = mapped_column(String(10), default="PLANT")   # PLANT | ALL
    permissions: Mapped[list["RolePermission"]] = relationship(cascade="all, delete-orphan")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_code: Mapped[str] = mapped_column(ForeignKey("roles.code"), primary_key=True)
    perm: Mapped[str] = mapped_column(String(40), primary_key=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100))
    plant_code: Mapped[str | None] = mapped_column(ForeignKey("plants.code"), index=True)  # None => all plants
    password_hash: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(120))
    mobile: Mapped[str | None] = mapped_column(String(20))
    supervisor_pin_hash: Mapped[str | None] = mapped_column(String(100))
    supervisor_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    perms_override: Mapped[str | None] = mapped_column(Text)   # central admin's per-user access list (CSV); NULL = role defaults
    device_id: Mapped[str | None] = mapped_column(String(60))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_pw: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(String(250))
    roles: Mapped[list["UserRole"]] = relationship(cascade="all, delete-orphan", lazy="selectin")

    @property
    def role_codes(self):
        return [r.role_code for r in self.roles]


class UserRole(Base):
    __tablename__ = "user_roles"
    user_pk: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_code: Mapped[str] = mapped_column(ForeignKey("roles.code"), primary_key=True)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120))
    ctype: Mapped[str | None] = mapped_column(String(5))        # OEM OES AFM
    ship_to: Mapped[str | None] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(60))
    state: Mapped[str | None] = mapped_column(String(60))
    gstin: Mapped[str | None] = mapped_column(String(20))
    plant_code: Mapped[str] = mapped_column(ForeignKey("plants.code"), index=True)
    email_to: Mapped[str | None] = mapped_column(String(300))
    email_cc: Mapped[str | None] = mapped_column(String(300))
    contact_name: Mapped[str | None] = mapped_column(String(80))
    contact_mobile: Mapped[str | None] = mapped_column(String(20))
    holding_limit_days: Mapped[int | None] = mapped_column(Integer)
    reminder_every_days: Mapped[int | None] = mapped_column(Integer)
    escalation_days: Mapped[int | None] = mapped_column(Integer)
    chargeable: Mapped[bool] = mapped_column(Boolean, default=True)
    return_mode: Mapped[str] = mapped_column(String(1), default="B")
    challan_source_override: Mapped[str | None] = mapped_column(String(10))
    api_key_hash: Mapped[str | None] = mapped_column(String(100))     # external customer API (Mode A push)
    api_key_prefix: Mapped[str | None] = mapped_column(String(12))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(String(250))
    __table_args__ = (UniqueConstraint("code", "plant_code", name="uq_customer_plant"),)


class Transporter(Base):
    __tablename__ = "transporters"
    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    gstin: Mapped[str | None] = mapped_column(String(20))
    contact_name: Mapped[str | None] = mapped_column(String(80))
    contact_mobile: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(120))
    plant_codes: Mapped[str | None] = mapped_column(String(200))   # ; separated
    vehicles: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(String(250))


class TagBatch(Base):
    __tablename__ = "tag_batches"
    batch_no: Mapped[str] = mapped_column(String(30), primary_key=True)
    plant_code: Mapped[str] = mapped_column(ForeignKey("plants.code"), index=True)
    tag_from: Mapped[int] = mapped_column(Integer)
    tag_to: Mapped[int] = mapped_column(Integer)
    vendor: Mapped[str | None] = mapped_column(String(80))
    received_date: Mapped[datetime | None] = mapped_column(DateTime)
    received_by: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="IN_STOCK")
    notes: Mapped[str | None] = mapped_column(String(250))


class Tag(Base):
    """One row per physical barcode tag. tag_no is the scanned value."""
    __tablename__ = "tags"
    tag_no: Mapped[str] = mapped_column(String(30), primary_key=True)
    plant_code: Mapped[str] = mapped_column(ForeignKey("plants.code"), index=True)
    batch_no: Mapped[str | None] = mapped_column(ForeignKey("tag_batches.batch_no"))
    status: Mapped[str] = mapped_column(String(15), default="IN_STOCK")   # IN_STOCK ASSIGNED RETIRED
    pallet_no: Mapped[str | None] = mapped_column(ForeignKey("pallets.pallet_no"), index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime)


class Pallet(Base):
    __tablename__ = "pallets"
    pallet_no: Mapped[str] = mapped_column(String(30), primary_key=True)
    home_plant: Mapped[str] = mapped_column(ForeignKey("plants.code"), index=True)
    pallet_type: Mapped[str | None] = mapped_column(String(30))
    size: Mapped[str | None] = mapped_column(String(40))
    tare_kg: Mapped[float | None] = mapped_column(Numeric(8, 2))
    current_tag: Mapped[str | None] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(15), default="AVAILABLE", index=True)
    # AVAILABLE ALLOCATED AT_CUSTOMER IN_RETURN HELD DAMAGED UNDER_REPAIR DISCONTINUED
    location_plant: Mapped[str | None] = mapped_column(String(10), index=True)  # plant physically holding it
    customer_code: Mapped[str | None] = mapped_column(String(20), index=True)
    dispatch_date: Mapped[datetime | None] = mapped_column(DateTime)
    challan_ref: Mapped[str | None] = mapped_column(String(40))
    picklist_no: Mapped[str | None] = mapped_column(String(40))
    load_state: Mapped[str | None] = mapped_column(String(6), default="EMPTY", index=True)    # LOADED | EMPTY
    load_ref: Mapped[str | None] = mapped_column(String(60))      # what it carries: part / LPN count / source doc
    load_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    zone: Mapped[str | None] = mapped_column(String(12), default="YARD", index=True)   # YARD PRODUCTION FGWH PACKING (in-plant)
    zone_at: Mapped[datetime | None] = mapped_column(DateTime)
    purchase_date: Mapped[datetime | None] = mapped_column(DateTime)
    discontinued_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    notes: Mapped[str | None] = mapped_column(String(250))


class PalletHistory(Base):
    __tablename__ = "pallet_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pallet_no: Mapped[str] = mapped_column(String(30), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    from_status: Mapped[str | None] = mapped_column(String(15))
    to_status: Mapped[str | None] = mapped_column(String(15))
    plant_code: Mapped[str | None] = mapped_column(String(10))
    customer_code: Mapped[str | None] = mapped_column(String(20))
    ref_doc: Mapped[str | None] = mapped_column(String(40))
    user_id: Mapped[str | None] = mapped_column(String(40))
    device_id: Mapped[str | None] = mapped_column(String(60))
    event_id: Mapped[str | None] = mapped_column(String(36))
    remarks: Mapped[str | None] = mapped_column(String(250))


class TagHistory(Base):
    __tablename__ = "tag_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pallet_no: Mapped[str] = mapped_column(String(30), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    old_tag: Mapped[str | None] = mapped_column(String(30))
    new_tag: Mapped[str | None] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(String(120))
    user_id: Mapped[str | None] = mapped_column(String(40))


# ---------------------------------------------------------------- phase 2 documents (skeleton)
class PickList(Base):
    __tablename__ = "picklists"
    picklist_no: Mapped[str] = mapped_column(String(40), primary_key=True)
    plant_code: Mapped[str] = mapped_column(ForeignKey("plants.code"), index=True)
    customer_code: Mapped[str] = mapped_column(String(20))
    transporter_code: Mapped[str | None] = mapped_column(String(20))
    pallet_type: Mapped[str | None] = mapped_column(String(30))
    qty: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    # OPEN -> (scan) -> PDI_PENDING -> PDI_TXN_PENDING -> SO_PENDING -> READY -> CHALLANED -> APPROVED -> DISPATCHED | CANCELLED
    # EMPTY_RETURN: OPEN -> READY -> CHALLANED -> APPROVED -> DISPATCHED (no PDI / SO); Yard loading: challan made at "Finish loading"
    source: Mapped[str | None] = mapped_column(String(15), default="APP")   # APP | DISPATCH_BENCH (old: HMIL_BENCH)
    load_point: Mapped[str | None] = mapped_column(String(10))            # YARD = empty return loaded at the Pallet Yard
    ext_ref: Mapped[str | None] = mapped_column(String(40), index=True)    # e.g. Bench dispatch id
    dispatch_type: Mapped[str] = mapped_column(String(15), default="PALLET_ONLY")   # CUSTOMER STOCK_TRANSFER EMPTY_RETURN PALLET_ONLY
    to_plant: Mapped[str | None] = mapped_column(String(10))           # stock transfer / empty return destination
    blanket_id: Mapped[int | None] = mapped_column(Integer)
    part_no: Mapped[str | None] = mapped_column(String(40))
    part_qty: Mapped[int | None] = mapped_column(Integer)
    po_number: Mapped[str | None] = mapped_column(String(40))
    invoice_no: Mapped[str | None] = mapped_column(String(40))
    invoice_date: Mapped[datetime | None] = mapped_column(DateTime)
    ewaybill_no: Mapped[str | None] = mapped_column(String(20))
    pdi_by: Mapped[str | None] = mapped_column(String(40))
    pdi_at: Mapped[datetime | None] = mapped_column(DateTime)
    so_number: Mapped[str | None] = mapped_column(String(40))
    challan_no: Mapped[str | None] = mapped_column(String(40))
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    gcs_no: Mapped[str | None] = mapped_column(String(40))
    created_by: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    remarks: Mapped[str | None] = mapped_column(String(250))


class PickListLine(Base):
    __tablename__ = "picklist_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    picklist_no: Mapped[str] = mapped_column(ForeignKey("picklists.picklist_no"), index=True)
    pallet_no: Mapped[str] = mapped_column(String(30), index=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_id: Mapped[str | None] = mapped_column(String(40))
    device_id: Mapped[str | None] = mapped_column(String(60))
    __table_args__ = (UniqueConstraint("picklist_no", "pallet_no", name="uq_pl_pallet"),)


class ReturnSlip(Base):
    __tablename__ = "return_slips"
    slip_no: Mapped[str] = mapped_column(String(40), primary_key=True)
    plant_code: Mapped[str] = mapped_column(ForeignKey("plants.code"), index=True)
    customer_code: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(2))               # A B1 B2
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    customer_challan_no: Mapped[str | None] = mapped_column(String(40))   # customer's own challan / DC number
    customer_challan_date: Mapped[datetime | None] = mapped_column(DateTime)
    driver_name: Mapped[str | None] = mapped_column(String(80))
    driver_mobile: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(10), default="HHT")      # HHT WEB EXT_API
    declared_qty: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(25), default="OPEN", index=True)
    # OPEN PENDING_VERIFICATION IN_GATE RECEIVING CLOSED
    gcs_in_no: Mapped[str | None] = mapped_column(String(40))
    created_by: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    remarks: Mapped[str | None] = mapped_column(String(250))


class ReturnSlipLine(Base):
    __tablename__ = "return_slip_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slip_no: Mapped[str] = mapped_column(ForeignKey("return_slips.slip_no"), index=True)
    pallet_no: Mapped[str] = mapped_column(String(30), index=True)
    declared: Mapped[bool] = mapped_column(Boolean, default=True)   # on slip
    received: Mapped[bool] = mapped_column(Boolean, default=False)  # scanned at yard
    exception: Mapped[str | None] = mapped_column(String(20))       # SHORT EXCESS CROSS_CUSTOMER UNKNOWN DAMAGED FOREIGN
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("slip_no", "pallet_no", name="uq_rs_pallet"),)


# ---------------------------------------------------------------- parts: blanket, LPN, WMS stock, sub-inventory
class BlanketOrder(Base):
    """Customer blanket PO = master data for SO: controls PO number and schedule qty per part."""
    __tablename__ = "blanket_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plant_code: Mapped[str] = mapped_column(ForeignKey("plants.code"), index=True)
    customer_code: Mapped[str] = mapped_column(String(20), index=True)
    part_no: Mapped[str] = mapped_column(String(40), index=True)
    customer_part_no: Mapped[str | None] = mapped_column(String(40))
    blanket_no: Mapped[str] = mapped_column(String(40))
    po_number: Mapped[str] = mapped_column(String(40))
    schedule_qty: Mapped[int] = mapped_column(Integer, default=0)
    released_qty: Mapped[int] = mapped_column(Integer, default=0)       # qty on SOs pushed to EBS
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    dispatch_type: Mapped[str] = mapped_column(String(15), default="CUSTOMER")   # CUSTOMER | STOCK_TRANSFER
    to_plant: Mapped[str | None] = mapped_column(String(10))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(String(250))
    __table_args__ = (UniqueConstraint("plant_code", "customer_code", "part_no", "po_number", name="uq_blanket"),)


class SubInvRule(Base):
    """After PDI OK, LPN moves to the sub-inventory set for customer + part (blank = any)."""
    __tablename__ = "subinv_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plant_code: Mapped[str] = mapped_column(ForeignKey("plants.code"), index=True)
    customer_code: Mapped[str | None] = mapped_column(String(20))
    part_no: Mapped[str | None] = mapped_column(String(40))
    ok_subinv: Mapped[str] = mapped_column(String(20))
    ok_locator: Mapped[str | None] = mapped_column(String(40))
    reject_subinv: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Lpn(Base):
    """FG LPN from WMS. Status is owned by AssetTrack once picked; WMS upload never overrides an in-process LPN."""
    __tablename__ = "lpns"
    lpn_no: Mapped[str] = mapped_column(String(40), primary_key=True)
    plant_code: Mapped[str] = mapped_column(ForeignKey("plants.code"), index=True)
    part_no: Mapped[str] = mapped_column(String(40), index=True)
    part_desc: Mapped[str | None] = mapped_column(String(120))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    subinventory: Mapped[str | None] = mapped_column(String(20))
    locator: Mapped[str | None] = mapped_column(String(40))
    pallet_no: Mapped[str | None] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(15), default="AVAILABLE", index=True)
    # AVAILABLE RESERVED PICKED PDI_OK REJECTED DISPATCHED MISSING
    reserved_for: Mapped[str | None] = mapped_column(String(40), index=True)    # pick list no
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime)
    picklist_no: Mapped[str | None] = mapped_column(String(40), index=True)
    txn_state: Mapped[str | None] = mapped_column(String(12))                 # PENDING SENT CONFIRMED FAILED
    wms_batch: Mapped[str | None] = mapped_column(String(30))
    wms_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    wms_missing: Mapped[bool] = mapped_column(Boolean, default=False)        # in-process LPN absent from latest WMS stock
    wms_subinv: Mapped[str | None] = mapped_column(String(20))                # sub-inv as per latest WMS upload
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PickListLpn(Base):
    __tablename__ = "picklist_lpns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    picklist_no: Mapped[str] = mapped_column(ForeignKey("picklists.picklist_no"), index=True)
    lpn_no: Mapped[str] = mapped_column(String(40), index=True)
    pallet_no: Mapped[str | None] = mapped_column(String(30))
    part_no: Mapped[str | None] = mapped_column(String(40))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    pdi_result: Mapped[str | None] = mapped_column(String(10))                # OK REJECT
    pdi_remarks: Mapped[str | None] = mapped_column(String(200))
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_id: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("picklist_no", "lpn_no", name="uq_pl_lpn"),)


class LpnTxn(Base):
    """Sub-inventory transfer sent to EBS. CONFIRMED only after (1) EBS accepted AND (2) EBS on-hand verified."""
    __tablename__ = "lpn_txns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lpn_no: Mapped[str] = mapped_column(String(40), index=True)
    plant_code: Mapped[str] = mapped_column(String(10), index=True)
    picklist_no: Mapped[str | None] = mapped_column(String(40), index=True)
    reason: Mapped[str] = mapped_column(String(15))                           # PDI_OK PDI_REJECT
    from_subinv: Mapped[str | None] = mapped_column(String(20))
    to_subinv: Mapped[str] = mapped_column(String(20))
    to_locator: Mapped[str | None] = mapped_column(String(40))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="PENDING", index=True)   # PENDING SENT CONFIRMED FAILED
    ebs_txn_id: Mapped[str | None] = mapped_column(String(40))
    ack_at: Mapped[datetime | None] = mapped_column(DateTime)                # confirmation 1: EBS accepted
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)           # confirmation 2: EBS on-hand shows LPN in to_subinv
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScanMiss(Base):
    """A scan point was skipped; detected at the next scan point. Alert + record (+ safe auto-correct)."""
    __tablename__ = "scan_misses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    plant_code: Mapped[str | None] = mapped_column(String(10), index=True)
    pallet_no: Mapped[str | None] = mapped_column(String(30), index=True)
    lpn_no: Mapped[str | None] = mapped_column(String(40))
    detected_at: Mapped[str] = mapped_column(String(20))           # scan point that found it: DOCK YARD RETURN_SLIP PDI EMPTY_RETURN
    missed_point: Mapped[str] = mapped_column(String(30))          # e.g. YARD_IN, RETURN_SLIP, OUT_GATE, DOCK_SCAN
    found_status: Mapped[str | None] = mapped_column(String(15))
    expected_status: Mapped[str | None] = mapped_column(String(40))
    last_ref: Mapped[str | None] = mapped_column(String(40))       # last known document
    current_ref: Mapped[str | None] = mapped_column(String(40))    # document at the detecting scan
    action: Mapped[str] = mapped_column(String(15))                # AUTO_CORRECTED | BLOCKED | ALERT
    message: Mapped[str | None] = mapped_column(String(300))
    user_id: Mapped[str | None] = mapped_column(String(40), index=True)
    device_id: Mapped[str | None] = mapped_column(String(60))
    responsible_role: Mapped[str | None] = mapped_column(String(10))   # who should have scanned
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(40))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution: Mapped[str | None] = mapped_column(String(250))


class WmsUpload(Base):
    __tablename__ = "wms_uploads"
    batch_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    plant_code: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(10))                           # EXCEL API
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    new_lpns: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    missing: Mapped[int] = mapped_column(Integer, default=0)
    protected: Mapped[int] = mapped_column(Integer, default=0)               # in-process LPNs left untouched
    user_id: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- sync / events / audit
class Event(Base):
    """Inbox of HHT events. event_id is client generated UUID => idempotent."""
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(60), index=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    plant_code: Mapped[str] = mapped_column(String(10), index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    payload: Mapped[str] = mapped_column(Text)              # JSON
    local_ts: Mapped[datetime] = mapped_column(DateTime)
    received_ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    app_version: Mapped[str | None] = mapped_column(String(15))
    offline: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(12), default="APPLIED", index=True)  # APPLIED REJECTED EXCEPTION
    result: Mapped[str | None] = mapped_column(String(300))


class Device(Base):
    __tablename__ = "devices"
    device_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    plant_code: Mapped[str | None] = mapped_column(String(10), index=True)
    model: Mapped[str | None] = mapped_column(String(60))
    app_version: Mapped[str | None] = mapped_column(String(15))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    last_user: Mapped[str | None] = mapped_column(String(40))
    pending_reported: Mapped[int] = mapped_column(Integer, default=0)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(String(40), index=True)
    plant_code: Mapped[str | None] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(40), index=True)
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(45))


class Setting(Base):
    """Key/value settings editable on the web (integrations)."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Sequence(Base):
    """Per plant document series (challan, picklist, slip)."""
    __tablename__ = "sequences"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)   # e.g. CHN:PL
    value: Mapped[int] = mapped_column(Integer, default=0)
