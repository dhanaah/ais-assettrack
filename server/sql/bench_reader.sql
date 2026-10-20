/* =====================================================================================================================
   AIS AssetTrack -> AIS Dispatch Planning Bench : read rights on the Bench tables                     Developed by DT
   ---------------------------------------------------------------------------------------------------------------------
   AssetTrack ("Read the Bench from" = SQL) reads these Bench tables directly, READ ONLY:
       picklist_dispatch   one row per pick list (trip)          pick_log          one row per picked LPN
       pdi_inspections     every PDI decision                     part_master       customer part -> AIS code
   One database per plant: AIS_DPB_MASTER (Bench default plant) and AIS_DPB_<PLANT> (e.g. AIS_DPB_ASP).

   Run once in SSMS as sysadmin. Then run it again whenever a new plant database is added in the Bench.
   The login gets db_datareader (read every table) in each Bench database - no write rights anywhere.
   ===================================================================================================================== */

-- 1) Login used by AssetTrack for the Bench (skip if AssetTrack's own login is used - see step 2)
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'ais_assettrack_reader')
    CREATE LOGIN [ais_assettrack_reader] WITH PASSWORD = N'<strong password>', CHECK_POLICY = ON, DEFAULT_DATABASE = [master];
GO

-- 2) Read rights in EVERY Bench plant database (AIS_DPB_*), found automatically.
--    AssetTrack's own login instead (IIS app pool):  SET @login = N'IIS APPPOOL\AssetTrack'  (or N'AIS\IISSERVER$', N'pallet_app')
DECLARE @login sysname = N'ais_assettrack_reader';
DECLARE @db sysname, @sql nvarchar(max);
DECLARE dbs CURSOR LOCAL FAST_FORWARD FOR
    SELECT name FROM sys.databases WHERE name LIKE N'AIS[_]DPB[_]%' AND state_desc = N'ONLINE';
OPEN dbs; FETCH NEXT FROM dbs INTO @db;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @sql = N'USE ' + QUOTENAME(@db) + N';
        IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @l) EXEC(N''CREATE USER '' + QUOTENAME(@l) + N'' FOR LOGIN '' + QUOTENAME(@l));
        EXEC sp_addrolemember N''db_datareader'', @l;';
    EXEC sp_executesql @sql, N'@l sysname', @l = @login;
    PRINT N'read rights in ' + @db;
    FETCH NEXT FROM dbs INTO @db;
END
CLOSE dbs; DEALLOCATE dbs;
GO

-- 3) Check (log in as ais_assettrack_reader):
--    SELECT TOP 5 id, trip_id, vehicle, dispatch_status, sent_at FROM AIS_DPB_MASTER.dbo.picklist_dispatch ORDER BY id DESC;
--    UPDATE AIS_DPB_MASTER.dbo.picklist_dispatch SET notes = notes WHERE 1 = 0;    -- must FAIL (no write rights)
-- Then on the AssetTrack web page: Masters > Dispatch Bench link > Read the Bench from = SQL, Bench SQL databases = AIS_DPB_*,
-- SQL login / password, Save, "Test SQL read", "Pull now".
