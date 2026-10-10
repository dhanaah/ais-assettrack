# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec - AIS AssetTrack Server (Windows tray EXE). Built by GitHub Actions (job server-exe). Developed by DT
from PyInstaller.utils.hooks import collect_submodules
hidden = (collect_submodules('uvicorn') + collect_submodules('app') + collect_submodules('sqlalchemy.dialects') +
          ['anyio._backends._asyncio', 'multipart', 'python_multipart', 'segno', 'openpyxl', 'bcrypt', 'jwt', 'httpx',
           'pystray._win32', 'PIL._tkinter_finder', 'pyodbc', 'email.mime.text', 'email.mime.multipart'])
a = Analysis(['tray_app.py'], pathex=['.'], binaries=[], datas=[('app/static', 'app/static')], hiddenimports=hidden,
             hookspath=[], runtime_hooks=[], excludes=['matplotlib', 'numpy', 'pandas', 'test'], noarchive=False)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AssetTrack_Server', debug=False, strip=False, upx=False,
          console=False, icon='assettrack.ico')
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name='AssetTrack_Server')
