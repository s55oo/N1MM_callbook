# -*- mode: python ; coding: utf-8 -*-
import os
import re

# Windows version information (company, product, description, version) is
# generated from __version__ in Callbooker.py on every build. An exe that
# carries it looks far less suspicious to antivirus heuristics than one
# without (Trojan:Win32/Wacatac.B!ml false positives on unsigned exes).
_HERE = os.path.dirname(os.path.abspath(SPEC))
_VERSION = re.search(
    r'^__version__\s*=\s*"([^"]+)"',
    open(os.path.join(_HERE, 'Callbooker.py'), encoding='utf-8').read(),
    re.M,
).group(1)
_NUMS = tuple(([int(p) for p in _VERSION.split('.') if p.isdigit()] + [0, 0, 0, 0])[:4])
os.makedirs(os.path.join(_HERE, 'build'), exist_ok=True)
_VERSION_FILE = os.path.join(_HERE, 'build', 'version_Callbooker.txt')
with open(_VERSION_FILE, 'w', encoding='utf-8') as _fh:
    _fh.write('''VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'S55OO'),
      StringStruct('FileDescription', 'Callbooker - callbook lookup for N1MM Logger+ and VHFCtest4WIN'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'Callbooker'),
      StringStruct('LegalCopyright', 'S55OO - https://github.com/s55oo/N1MM_callbook'),
      StringStruct('OriginalFilename', 'Callbooker.exe'),
      StringStruct('ProductName', 'Callbooker'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''.format(nums=_NUMS, ver=_VERSION))


a = Analysis(
    ['Callbooker.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['paho.mqtt.client'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Callbooker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest='manifest.xml',
    version=_VERSION_FILE,
    icon=os.path.join(_HERE, 'callbooker.ico'),
)
