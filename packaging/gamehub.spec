from importlib.metadata import distribution
from os import environ, pathsep
from pathlib import Path
import sys


root = Path(SPECPATH).resolve().parent
python_home = Path(sys.base_prefix)
windows = Path(environ['SystemRoot'])
# Keep another installed application's DLLs out of the frozen Qt environment.
environ['PATH'] = pathsep.join(map(str, (python_home, windows / 'System32', windows)))

notice_dir = 'third-party'
notices = [(str(root / 'packaging' / 'THIRD_PARTY_NOTICES.txt'), notice_dir)]
for name in ('GPL-3.0.txt', 'LGPL-3.0.txt'):
    notices.append((str(root / 'packaging' / 'licenses' / name), f'{notice_dir}/Qt'))
notices.append((str(root / 'packaging' / 'licenses' / 'LGPL-2.1.txt'), f'{notice_dir}/FFmpeg'))
notices.append((str(root / 'packaging' / 'licenses' / 'PortAudio.txt'), f'{notice_dir}/PortAudio'))

python_license = python_home / 'LICENSE.txt'
if not python_license.is_file() and environ.get('GAMEHUB_CPYTHON_LICENSE'):
    python_license = Path(environ['GAMEHUB_CPYTHON_LICENSE'])
if not python_license.is_file():
    raise FileNotFoundError(f'CPython license file is missing: {python_license}')
notices.append((str(python_license), f'{notice_dir}/CPython'))

for package in (
    'PySide6-Essentials', 'PySide6-Addons', 'shiboken6', 'PyInstaller', 'psutil', 'vdf',
    'Pillow', 'numpy', 'opencv-python', 'windows-capture',
    'sounddevice', 'soundfile', 'cffi', 'pycparser', 'typing-extensions',
):
    installed = distribution(package)
    license_files = [
        file for file in installed.files or ()
        if any(part.endswith('.dist-info') for part in file.parts)
        and (
            'licenses' in file.parts
            or file.name.lower().startswith(('license', 'copying', 'notice'))
        )
        and file.name != 'LicenseRef-Qt-Commercial.txt'
        and file.locate().is_file()
    ]
    if not license_files and package == 'PyInstaller':
        raise FileNotFoundError(f'Installed wheel has no license files: {package}')
    for file in license_files:
        metadata_index = next(
            index for index, part in enumerate(file.parts) if part.endswith('.dist-info')
        )
        directory = Path(notice_dir, package, *file.parts[metadata_index + 1:-1])
        notices.append((str(file.locate()), str(directory)))

analysis = Analysis(
    [str(root / 'gamehub' / 'app.py')],
    pathex=[str(root)],
    datas=notices,
)
# The app declares a Windows x64 target and uses the Windows default input.
analysis.binaries = [
    item for item in analysis.binaries
    if not Path(item[0]).name.lower().startswith('libportaudio')
    or Path(item[0]).name.lower() == 'libportaudio64bit.dll'
]
archive = PYZ(analysis.pure)
exe = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name='GameHub',
    console=False,
    upx=False,
)
collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    name='GameHub',
    upx=False,
)
