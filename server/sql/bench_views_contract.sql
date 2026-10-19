/* =====================================================================================================================
   AIS AssetTrack  <->  AIS Dispatch Planning Bench : SQL read contract                              Developed by DT
   ---------------------------------------------------------------------------------------------------------------------
   When the Dispatch Planning Bench runs on SQL Server, AssetTrack can read it straight from SQL Server (setting
   "Read the Bench from" = SQL on the web page Integrations > Dispatch Planning Bench). It reads ONLY these two views,
   READ ONLY. The Bench may change its own tables at any time - it only has to keep these two views, with these column
   names and meanings. AssetTrack never writes into the Bench database.

   Bench database and AssetTrack database are separate databases (e.g. BenchDB and PalletDB), on the same SQL Server.

   PART 1 - the Bench creates the two views (in the Bench database). The SELECT part is the Bench's own: map its
            tables to these columns. Extra columns are allowed and ignored.
   PART 2 - the DBA gives the AssetTrack login read rights on the two views only.
   ===================================================================================================================== */

/* ---------------------------------------------------------------------------------------------------------------------
   VIEW dbo.assettrack_trips  - one row per Bench trip (dispatch)
   column            type             meaning
   trip_id           NVARCHAR(40)     unique, never re-used Bench dispatch id (AssetTrack trip = DB-<plant>-<trip_id>)
   trip_no           NVARCHAR(40)     trip number people see in the Bench
   plant_code        NVARCHAR(20)     AIS plant (CHN, TLJ ...; or a Bench code translated by the plant map)
   section           NVARCHAR(20)     MAIN / PACKING
   customer_code     NVARCHAR(40)     customer (site) code
   segment           NVARCHAR(20)     OEM / OES / AFM / EXP
   shift_name        NVARCHAR(40)     optional
   vehicle_no        NVARCHAR(20)     vehicle number
   trip_status       NVARCHAR(20)     PLANNED / PICKING / PDI_DONE / DISPATCHED / CANCELLED  (CANCELLED releases the trip)
   pdi_by            NVARCHAR(80)     PDI inspector name           pdi_login        NVARCHAR(40)  his login
   supervisor        NVARCHAR(80)     shift supervisor name        supervisor_login NVARCHAR(40)  his login
   so_no             NVARCHAR(40)     Oracle sales order no (after PDI), optional
   planned_at        DATETIME2        trip date / time (local time); trips older than the look-back days are not read
   updated_at        DATETIME2        last change of the trip row (local time) - REQUIRED, AssetTrack reads changed trips
   --------------------------------------------------------------------------------------------------------------------- */

/* ---------------------------------------------------------------------------------------------------------------------
   VIEW dbo.assettrack_trip_cards  - one row per part card (LPN) on a trip = the PDI check sheet
   column            type             meaning
   trip_id           NVARCHAR(40)     the trip (same as in assettrack_trips)
   lpn_no            NVARCHAR(40)     part card / LPN number
   part_no           NVARCHAR(40)     AIS item code
   qty               INT              quantity on the card
   sub_inv           NVARCHAR(20)     sub-inventory, optional
   pdi_status        NVARCHAR(10)     OK      = PDI passed, goes on the vehicle
                                      HOLD    = on hold for rework, stays on the trip, NOT loadable until it becomes OK
                                      REJECT  = rejected, final: off the trip (keep the row! AssetTrack stops a scan of it)
   pdi_reason        NVARCHAR(200)    reject / hold reason, optional
   updated_at        DATETIME2        last change of the card row (local time) - REQUIRED
   A rejected card's alternate is simply a new row (pdi_status OK) on the same trip.
   A card the Bench deletes from the view is treated as removed (same as REJECT, without a reason).
   --------------------------------------------------------------------------------------------------------------------- */

-- PART 1 - example only: replace the FROM / column parts with the Bench's real tables.
/*
USE BenchDB;
GO
CREATE OR ALTER VIEW dbo.assettrack_trips AS
SELECT CAST(d.id AS NVARCHAR(40)) AS trip_id, d.trip_no, d.plant_code, d.section, d.customer_code, d.segment, d.shift_name,
       d.vehicle_no, d.status AS trip_status, d.pdi_by, d.pdi_login, d.supervisor, d.supervisor_login, d.so_no,
       d.planned_at, d.updated_at
FROM dbo.dispatches d;
GO
CREATE OR ALTER VIEW dbo.assettrack_trip_cards AS
SELECT CAST(p.dispatch_id AS NVARCHAR(40)) AS trip_id, p.lpn_no, p.item_code AS part_no, p.qty, p.sub_inv,
       p.pdi_status, p.pdi_reason, p.updated_at
FROM dbo.picks p;
GO
-- recommended for speed: indexes on the Bench tables behind updated_at and trip_id
*/

-- PART 2 - read rights for AssetTrack (run in the Bench database; use the login AssetTrack already uses for PalletDB:
--          the IIS app pool  [IIS APPPOOL\AssetTrack]  (or [AIS\IISSERVER$] when SQL Server is on another server),
--          or the SQL login  [pallet_app]).
/*
USE BenchDB;
GO
CREATE USER [IIS APPPOOL\AssetTrack] FOR LOGIN [IIS APPPOOL\AssetTrack];      -- or: FOR LOGIN [pallet_app]
GRANT SELECT ON dbo.assettrack_trips      TO [IIS APPPOOL\AssetTrack];
GRANT SELECT ON dbo.assettrack_trip_cards TO [IIS APPPOOL\AssetTrack];
-- nothing else: no table rights, no write rights. The views read the Bench tables by ownership chaining.
GO
*/

-- Check (as the AssetTrack login):  SELECT TOP 5 * FROM BenchDB.dbo.assettrack_trips ORDER BY updated_at DESC;
-- Then on the AssetTrack web page: Integrations > Dispatch Planning Bench > Read the Bench from = SQL,
-- Bench SQL database = BenchDB, Save, "Test SQL read", "Pull now".
