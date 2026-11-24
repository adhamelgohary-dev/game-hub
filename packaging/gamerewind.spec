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
    'PySide6-Essentials', 'PySide6-Addons', 'shiboken6', 'PyInstaller', 'vdf',
    'Pillow', 'numpy', 'windows-capture',
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

_EXCLUDED_MODULES = [
    'psutil',
    'cv2',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtQuick3D',
    'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtSql',
    'PySide6.QtTest',
    'PySide6.QtWebChannel',
    'PySide6.QtWebSockets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.Qt3DCore',
    'PySide6.QtDesigner',
    'PySide6.QtHelp',
    'PySide6.QtPrintSupport',
    'PySide6.QtXml',
    'PySide6.QtDBus',
    'PySide6.QtPositioning',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtSpatialAudio',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtGraphs',
    'PySide6.QtHttpServer',
    'PySide6.QtNfc',
    'PySide6.QtRemoteObjects',
    'PySide6.QtScxml',
    'PySide6.QtStateMachine',
    'PySide6.QtTextToSpeech',
    'PySide6.QtUiTools',
    'PIL.AvifImagePlugin',
]

analysis = Analysis(
    [str(root / 'gamehub' / 'app.py')],
    pathex=[str(root)],
    excludes=_EXCLUDED_MODULES,
    datas=[
        *notices,
        (
            str(root / 'gamehub' / 'core' / 'protection' / 'protected_games.json'),
            'gamehub/core/protection',
        ),
        (str(root / 'packaging' / 'assets' / 'GameRewind.png'), 'assets'),
        (str(root / 'packaging' / 'assets' / 'GameRewind.ico'), 'assets'),
    ],
)

_ALLOWED_QT_PLUGINS = {
    'platforms/qwindows.dll',
    'platforms/qoffscreen.dll',
    'styles/qmodernwindowsstyle.dll',
    'imageformats/qjpeg.dll',
    'imageformats/qwebp.dll',
    'imageformats/qico.dll',
    'multimedia/ffmpegmediaplugin.dll',
    'multimedia/windowsmediaplugin.dll',
}
_DROPPED_QT_PREFIXES = (
    'opengl32sw',
    'qt6quick',
    'qt6qml',
    'qt6opengl',
    'qt6virtualkeyboard',
    'qt6svg',
    'qt6multimediawidgets',
    'qt6pdf',
    'qt6shadertools',
    'qt6spatialaudio',
    'qt6web',
    'qt6designer',
    'qt6sql',
    'qt6printsupport',
    'qt6dbus',
    'qt6xml',
    'qt6test',
)
_ALLOWED_QT_TRANSLATIONS = {'qtbase_ar.qm', 'qtbase_en.qm'}


def _keep_bundle_item(item) -> bool:
    dest = Path(item[0]).as_posix().lower()
    name = Path(item[0]).name.lower()
    # Keep only 64-bit PortAudio for our x64 Windows build.
    if name.startswith('libportaudio') and name != 'libportaudio64bit.dll':
        return False
    # Never ship OpenCV or unused AVIF codec (~133 MiB combined).
    if dest.startswith('cv2/') or name.startswith('opencv_') or name == 'cv2.pyd':
        return False
    if dest.startswith('pil/_avif') or name.startswith('_avif.'):
        return False
    # Trim unused PySide6 DLLs, plugins, QML, and translations while keeping QtCore/Gui/Widgets/Network/Multimedia.
    if dest.startswith('pyside6/'):
        rel = dest.removeprefix('pyside6/')
        if rel.startswith('qml/') or rel.startswith('resources/'):
            return False
        if rel.startswith('translations/'):
            return name in _ALLOWED_QT_TRANSLATIONS
        if rel.startswith('plugins/'):
            return rel.removeprefix('plugins/') in _ALLOWED_QT_PLUGINS
        if name.startswith(_DROPPED_QT_PREFIXES):
            return False
    return True


analysis.binaries = [item for item in analysis.binaries if _keep_bundle_item(item)]
analysis.datas = [item for item in analysis.datas if _keep_bundle_item(item)]
archive = PYZ(analysis.pure)
exe = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name='GameRewind',
    console=False,
    upx=False,
    icon=str(root / 'packaging' / 'assets' / 'GameRewind.ico'),
    version=str(root / 'packaging' / 'version_info.txt'),
    manifest=str(root / 'packaging' / 'GameRewind.manifest'),
)
collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    name='GameRewind',
    upx=False,
)
