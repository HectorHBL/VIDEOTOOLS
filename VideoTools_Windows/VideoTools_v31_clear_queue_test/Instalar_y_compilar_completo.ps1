param(
    [string]$Destino = (Join-Path $PSScriptRoot 'Distribucion_completa'),
    [switch]$OmitirModelosWhisper
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$project = $PSScriptRoot
$python = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $python) {
    throw "Instala Python 3.11 y vuelve a ejecutar este script. Puedes usar: winget install Python.Python.3.11"
}

Push-Location $project
try {
    & py -3.11 -m pip install --upgrade pip
    & py -3.11 -m pip install -r requirements.txt pyinstaller

    $models = Join-Path $project 'models'
    $argos = Join-Path $project 'argos_models'
    New-Item -ItemType Directory -Force -Path $models,$argos | Out-Null
    $prepareModels = Join-Path $env:TEMP 'videotools_prepare_models.py'
    @"
from pathlib import Path
import sys, urllib.request, zipfile
import argostranslate.package, argostranslate.settings
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
root = Path(r'$project')
models = root / 'models'
argos = root / 'argos_models'
models.mkdir(exist_ok=True); argos.mkdir(exist_ok=True)
name = 'Helsinki-NLP/opus-mt-es-en'
target = models / 'es_en_hf'
if not target.is_dir():
    AutoTokenizer.from_pretrained(name).save_pretrained(target)
    AutoModelForSeq2SeqLM.from_pretrained(name).save_pretrained(target)
argostranslate.settings.package_data_dir = str(argos)
argostranslate.package.update_package_index()
available = argostranslate.package.get_available_packages()
for package in available:
    if package.from_code == 'en' and package.to_code == 'es':
        argostranslate.package.install_from_path(package.download())
        break
else: raise RuntimeError('No se encontró el paquete Argos en-es')
for language, name in [('es','vosk-model-small-es-0.42'),('en','vosk-model-small-en-us-0.15')]:
    target = models / 'vosk' / name
    if not target.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        archive = target.parent / (name + '.zip')
        urllib.request.urlretrieve(f'https://alphacephei.com/vosk/models/{name}.zip', archive)
        with zipfile.ZipFile(archive) as z: z.extractall(target.parent)
        archive.unlink()
if '--whisper' in sys.argv:
    from faster_whisper import WhisperModel
    for name in ('small','medium','large-v3'):
        WhisperModel(name, device='cpu', compute_type='int8', download_root=str(models))
"@ | Set-Content -LiteralPath $prepareModels -Encoding UTF8
    $modelArgs = @($prepareModels)
    if (-not $OmitirModelosWhisper) { $modelArgs += '--whisper' }
    & py -3.11 @modelArgs
    Remove-Item -LiteralPath $prepareModels -Force

    $ffmpegZip = Join-Path $env:TEMP 'ffmpeg-release-essentials.zip'
    Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $ffmpegZip
    $ffmpegTemp = Join-Path $env:TEMP 'videotools_ffmpeg'
    Remove-Item -LiteralPath $ffmpegTemp -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -LiteralPath $ffmpegZip -DestinationPath $ffmpegTemp -Force
    Copy-Item (Get-ChildItem $ffmpegTemp -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName (Join-Path $project 'ffmpeg.exe') -Force
    Copy-Item (Get-ChildItem $ffmpegTemp -Recurse -Filter ffprobe.exe | Select-Object -First 1).FullName (Join-Path $project 'ffprobe.exe') -Force

    & py -3.11 -m PyInstaller --noconfirm --clean --onefile --windowed --icon VideoTools.ico --add-data 'VideoTools.ico;.' --collect-all faster_whisper --collect-all ctranslate2 --collect-all vosk --collect-all argostranslate --collect-all pymupdf --collect-all reportlab --collect-all transformers --collect-all tokenizers --collect-all tkinterdnd2 --hidden-import av --name VideoTools VideoTools.py

    Remove-Item -LiteralPath $Destino -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $Destino,(Join-Path $Destino 'Proyecto') | Out-Null
    Copy-Item 'dist\VideoTools.exe','ffmpeg.exe','ffprobe.exe' -Destination $Destino
    Copy-Item 'models','argos_models' -Destination $Destino -Recurse
    Copy-Item 'VideoTools.py','VideoTools.ico','VideoTools_film_reel.png','build.bat','README.txt','requirements.txt','Instalar_y_compilar_completo.ps1' -Destination (Join-Path $Destino 'Proyecto')
    Write-Host "Listo. Ejecuta: $(Join-Path $Destino 'VideoTools.exe')" -ForegroundColor Green
}
finally { Pop-Location }
