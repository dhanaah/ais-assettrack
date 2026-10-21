# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec - AIS AssetTrack Server (Windows tray EXE). Built by GitHub Actions (job server-exe). Developed by DT
from PyInstaller.utils.hooks import collect_submodules
import re
from PyInstaller.utils.win32.versioninfo import (VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
                                                 VarFileInfo, VarStruct)
# Windows file details (right-click > Properties > Details): an EXE with no maker / version scores as suspicious in
# antivirus machine-learning checks (Trend Micro Apex One "Predictive Machine Learning").
APP_V = re.search(r'APP_VERSION = "([^"]+)"', open('app/config.py', encoding='utf-8').read()).group(1)
_n = tuple(int(x) for x in (APP_V.split('.') + ['0', '0', '0'])[:4])
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_n, prodvers=_n, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
        StringStruct('CompanyName', 'Asahi India Glass Ltd. (AIS Glass)'),
        StringStruct('FileDescription', 'AIS AssetTrack Server - returnable pallet tracking (internal)'),
        StringStruct('FileVersion', APP_V), StringStruct('InternalName', 'AssetTrack_Server'),
        StringStruct('LegalCopyright', 'AIS Glass - internal use. Developed by DT'),
        StringStruct('OriginalFilename', 'AssetTrack_Server.exe'), StringStruct('ProductName', 'AIS AssetTrack'),
        StringStruct('ProductVersion', APP_V), StringStruct('Comments', 'Developed by DT')])]),
          VarFileInfo([VarStruct('Translation', [0x0409, 1200])])])
hidden = (collect_submodules('uvicorn') + collect_submodules('app') + collect_submodules('sqlalchemy.dialects') +
          ['anyio._backends._asyncio', 'multipart', 'python_multipart', 'segno', 'openpyxl', 'bcrypt', 'jwt', 'httpx',
           'pystray._win32', 'PIL._tkinter_finder', 'pyodbc', 'reportlab', 'reportlab.pdfgen', 'reportlab.lib', 'pypdf', 'email.mime.text', 'email.mime.multipart'])
a = Analysis(['tray_app.py'], pathex=['.'], binaries=[], datas=[('app/static', 'app/static')], hiddenimports=hidden,
             hookspath=[], runtime_hooks=[], excludes=['matplotlib', 'numpy', 'pandas', 'test'], noarchive=False)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AssetTrack_Server', debug=False, strip=False, upx=False,
          console=False, icon='assettrack.ico', version=version_info)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name='AssetTrack_Server')
