-- Run once on SQL Server (tables are created by the app on first start)
CREATE DATABASE PalletDB;
GO
ALTER DATABASE PalletDB SET READ_COMMITTED_SNAPSHOT ON;   -- scans never block reports
ALTER DATABASE PalletDB SET ALLOW_SNAPSHOT_ISOLATION ON;
GO
-- Service login (or use Windows auth of the IIS app pool identity)
CREATE LOGIN pallet_app WITH PASSWORD = 'ChangeMe#2026';
USE PalletDB; CREATE USER pallet_app FOR LOGIN pallet_app; ALTER ROLE db_owner ADD MEMBER pallet_app;
GO
