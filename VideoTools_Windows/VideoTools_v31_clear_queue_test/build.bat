@echo off
py -3.11 -m pip install pyinstaller faster-whisper vosk argostranslate pymupdf reportlab transformers tkinterdnd2
py -3.11 -m PyInstaller --noconfirm --clean --onefile --windowed --icon VideoTools.ico --add-data "VideoTools.ico;." --collect-all faster_whisper --collect-all ctranslate2 --collect-all vosk --collect-all argostranslate --collect-all pymupdf --collect-all reportlab --collect-all transformers --collect-all tokenizers --collect-all tkinterdnd2 --hidden-import av --name VideoTools_v36 VideoTools.py
echo Generado: dist\VideoTools_v36.exe
pause
