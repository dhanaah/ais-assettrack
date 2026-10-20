/* =====================================================================================================================
   AIS AssetTrack -> AIS Dispatch Planning Bench : read rights on the Bench tables                     Developed by DT
   ---------------------------------------------------------------------------------------------------------------------
   AssetTrack ("Read the Bench from" = SQL) reads these Bench tables directly, READ ONLY:
       picklist_dispatch   one row per pick list (trip)          pick_log          one row per picked LPN
       pdi_inspections     every PDI decision                     part_master       customer part -> AIS code
   One database per plant: AIS_DPB_MASTER (Bench default plant) and AIS_DPB_<PLANT> (e.g. AIS_DPB_ASP).

   Run once in SSMS as sysadmin. Then run it again whenever a new plant database is added in the Bench.
   By default it gives AssetTrack's OWN login (the IIS app pool) read rights, so nothing has to be typed on the AssetTrack
   page. The login gets db_datareader (read every table) in each Bench database - no write rights anywhere.
   ===================================================================================================================== */

-- 1) OPTIONAL - only if IT wants a separate SQL login instead of AssetTrack's own (then also set @login below to it, and
--    enter it under Advanced settings on the AssetTrack Bench page):
-- CREATE LOGIN [ais_assettrack_reader] WITH PASSWORD = N'<strong password>', CHECK_POLICY = ON, DEFAULT_DATABASE = [master];
-- GO

-- 2) Read rights in EVERY Bench plant database (AIS_DPB_*), found automatically.
--    @login = the login AssetTrack uses for PalletDB: N'IIS APPPOOL\AssetTrack' (SQL Server on the IIS server itself),
--    N'AIS\<IIS-SERVER-NAME>$' (SQL Server on another server), N'pallet_app' (SQL login), or N'ais_assettrack_reader' (step 1).
DECLARE @login sysname = N'IIS APPPOOL\AssetTrack';
DECLARE @db sysname, @sql nvarchar(max);
DECLARE dbs CURSOR LOCAL FAST_FORWARD FOR
    SELECT name FROM sys.databases WHERE name LIKE N'AIS[_]DPB[_]%' AND state_desc = N'ONLINE';
OPEN dbs; FETCH NEXT FROM dbs INTO @db;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @sql = N'USE ' + QUOTENAME(@db) + N';
        DECLARE @q nvarchar(600) = N''CREATE USER '' + QUOTENAME(@l) + N'' FOR LOGIN '' + QUOTENAME(@l);
        IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @l) EXEC (@q);
        EXEC sp_addrolemember N''db_datareader'', @l;';
    EXEC sp_executesql @sql, N'@l sysname', @l = @login;
    PRINT N'read rights in ' + @db;
    FETCH NEXT FROM dbs INTO @db;
END
CLOSE dbs; DEALLOCATE dbs;
GO

-- 3) Check (as that login):
--    SELECT TOP 5 id, trip_id, vehicle, dispatch_status, sent_at FROM AIS_DPB_MASTER.dbo.picklist_dispatch ORDER BY id DESC;
--    UPDATE AIS_DPB_MASTER.dbo.picklist_dispatch SET notes = notes WHERE 1 = 0;    -- must FAIL (no write rights)
-- Then on the AssetTrack web page: Masters > Dispatch Bench link > Auto pull ON, Read the Bench from = Automatic,
-- Save, "Test SQL read", "Pull now". Nothing else to fill in.
