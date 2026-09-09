"""Servicios reutilizables para PDF, voz, sincronía SRT y vídeo de audiolibro."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, re, shutil, subprocess, tempfile, urllib.error, urllib.request
import pymupdf as fitz

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

class AudiobookError(RuntimeError): pass

@dataclass(frozen=True)
class Segment:
    text: str
    page: int
    start: int
    end: int

@dataclass(frozen=True)
class AudiobookResult:
    audio: Path
    video: Path
    srt: Path
    original_srt: Path
    translation_srt: Path | None

PIPER_VOICES={
    "Español mexicano - es_MX-ald": ("es_MX-ald-medium.onnx", "es"),
    "English US - en_US": ("en_US-lessac-medium.onnx", "en"),
}

def detect_language(text: str) -> str:
    words=re.findall(r"[a-záéíóúüñ]+",text.casefold())
    es={"el","la","de","que","y","en","para","con","una","por","los","las","del","es"}
    en={"the","of","and","to","in","for","with","is","this","that","a","an","are"}
    return "es" if sum(w in es for w in words)+3*len(re.findall(r"[áéíóúüñ¿¡]",text.casefold())) >= sum(w in en for w in words) else "en"

def extract_pdf(path: Path, work: Path) -> tuple[list[tuple[int,str]],list[Path]]:
    try: doc=fitz.open(path)
    except Exception as error: raise AudiobookError(f"PDF inválido o ilegible: {error}")
    pages=[];images=[];work.mkdir(parents=True,exist_ok=True)
    try:
        for index,page in enumerate(doc):
            text=page.get_text("text",sort=True).strip()
            if text: pages.append((index,text))
            image=work/f"pagina_{index+1:04d}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.35,1.35),alpha=False).save(image)
            images.append(image)
    finally: doc.close()
    if not pages: raise AudiobookError("El PDF no tiene texto seleccionable. Aplica OCR antes de generar el audiolibro.")
    return pages,images

def split_text(pages: list[tuple[int,str]], max_chars: int=170) -> list[tuple[int,str]]:
    result=[]
    for page,text in pages:
        units=re.split(r"(?<=[.!?…])\s+|\n{2,}",text)
        current=""
        for unit in units:
            unit=re.sub(r"\s+"," ",unit).strip()
            while unit:
                room=max_chars-len(current)-(1 if current else 0)
                if room<=0:
                    result.append((page,current));current="";room=max_chars
                if len(unit)<=room:
                    current=(current+" "+unit).strip();unit=""
                else:
                    cut=unit.rfind(" ",0,room)
                    cut=cut if cut>25 else room
                    part=unit[:cut].strip();unit=unit[cut:].strip()
                    current=(current+" "+part).strip();result.append((page,current));current=""
        if current:result.append((page,current))
    return result

def find_piper(base: Path) -> str:
    for candidate in (base/"piper.exe",base/"tools"/"piper.exe"):
        if candidate.is_file(): return str(candidate)
    found=shutil.which("piper") or shutil.which("piper.exe")
    if not found: raise AudiobookError("Piper no está instalado. Ejecuta el instalador completo o coloca piper.exe junto a VideoTools.")
    return found

def piper_model(base: Path, voice: str) -> Path:
    filename,_=PIPER_VOICES.get(voice,next(iter(PIPER_VOICES.values())))
    for path in (base/"models"/"piper"/filename,base/"voices"/filename):
        if path.is_file(): return path
    raise AudiobookError(f"No se encontró la voz Piper {filename}. Ejecuta el instalador completo con conexión a Internet.")

def piper_tts(exe: str, model: Path, text: str, output: Path, speed: float) -> None:
    command=[exe,"--model",str(model),"--output_file",str(output),"--length_scale",f"{1/max(0.2,speed):.3f}"]
    result=subprocess.run(command,input=text,encoding="utf-8",capture_output=True,creationflags=NO_WINDOW)
    if result.returncode: raise AudiobookError("Piper no pudo generar el audio: "+result.stderr.decode("utf-8","replace")[-500:])

def elevenlabs_tts(key: str, voice_id: str, text: str, output: Path, speed: float) -> None:
    data=json.dumps({"text":text,"model_id":"eleven_multilingual_v2","voice_settings":{"stability":0.5,"similarity_boost":0.75,"speed":speed}}).encode("utf-8")
    request=urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",data=data,headers={"xi-api-key":key,"Content-Type":"application/json","Accept":"audio/mpeg"},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=90) as response: output.write_bytes(response.read())
    except urllib.error.HTTPError as error: raise AudiobookError(f"ElevenLabs rechazó la solicitud ({error.code}). Verifica la API Key o cambia a Piper.")
    except urllib.error.URLError as error: raise AudiobookError(f"ElevenLabs no está disponible: {error.reason}. Puedes cambiar a Piper.")

def elevenlabs_voices(key: str) -> list[tuple[str,str]]:
    request=urllib.request.Request("https://api.elevenlabs.io/v1/voices",headers={"xi-api-key":key})
    try:
        with urllib.request.urlopen(request,timeout=20) as response: data=json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error: raise AudiobookError(f"No se pudieron consultar voces ElevenLabs: {error.reason}. Puedes cambiar a Piper.")
    return [(voice.get("name",voice.get("voice_id","Voz")),voice["voice_id"]) for voice in data.get("voices",[])]

def media_duration(ffprobe: str, path: Path) -> float:
    result=subprocess.run([ffprobe,"-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],capture_output=True,text=True,creationflags=NO_WINDOW)
    if result.returncode: raise AudiobookError("FFprobe no pudo leer la duración del audio generado.")
    return float(result.stdout.strip())

def write_srt(path: Path, segments: list[Segment]) -> None:
    def stamp(ms:int):
        h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000);return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    path.write_text("\n".join(f"{n}\n{stamp(item.start)} --> {stamp(item.end)}\n{item.text}\n" for n,item in enumerate(segments,1)),encoding="utf-8")

def _concat_escape(path: Path) -> str: return path.resolve().as_posix().replace("'","'\\''")

def _run(command: list[str], message: str) -> None:
    result=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",errors="replace",creationflags=NO_WINDOW)
    if result.returncode: raise AudiobookError(message+": "+result.stderr[-900:])

def build_audiobook(pdf: Path, destination: Path, provider: str, voice: str, speed: float, language: str, bilingual: bool, keep_pauses: bool, ffmpeg: str, ffprobe: str, app_root: Path, translate, get_key, cancelled=lambda:False, progress=lambda _text,_done,_total:None) -> AudiobookResult:
    """Genera audio, SRT(s) y MP4; el llamador aporta traductor/cancelación reutilizables."""
    if cancelled(): raise AudiobookError("Proceso cancelado por el usuario.")
    destination.mkdir(parents=True,exist_ok=True)
    stem=pdf.stem;audio=destination/f"{stem}_audiolibro.mp3";video=destination/f"{stem}_subtitulado.mp4";srt=destination/f"{stem}.srt";original_srt=destination/f"{stem}_original.srt";translation_srt=destination/f"{stem}_traduccion.srt" if bilingual else None
    if any(path.exists() for path in (audio,video,srt,original_srt,translation_srt) if path): raise AudiobookError("Ya existe una salida de audiolibro. Elige otra carpeta o renombra el PDF; nunca se sobrescribe el original.")
    with tempfile.TemporaryDirectory(prefix="videotools_audiolibro_") as raw:
        work=Path(raw);pages,images=extract_pdf(pdf,work/"paginas");pieces=split_text(pages)
        full="\n".join(text for _,text in pages);source_lang=detect_language(full) if language=="Automático" else language
        if not pieces: raise AudiobookError("No se encontraron frases utilizables en el PDF.")
        piper=None;model=None;key=None
        if provider=="Piper (offline)": piper=find_piper(app_root);model=piper_model(app_root,voice)
        else:
            key=get_key()
            if not key: raise AudiobookError("Falta la API Key de ElevenLabs. Ábrela en Configuración o cambia a Piper.")
        audio_parts=[];segments=[];offset=0;total=len(pieces)
        for number,(page,text) in enumerate(pieces,1):
            if cancelled(): raise AudiobookError("Proceso cancelado por el usuario.")
            part=work/f"audio_{number:05d}.{ 'wav' if piper else 'mp3'}"
            if piper: piper_tts(piper,model,text,part,speed)
            else: elevenlabs_tts(key,voice,text,part,speed)
            length=max(0.05,media_duration(ffprobe,part));start=round(offset*1000);offset+=length;segments.append(Segment(text,page,start,round(offset*1000)));audio_parts.append(part)
            progress("Generando voz",number,total)
            if keep_pauses and number<total:
                silence=work/f"pausa_{number:05d}.wav";_run([ffmpeg,"-y","-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t","0.55",str(silence)],"No se pudo crear la pausa")
                offset+=0.55;audio_parts.append(silence)
        list_audio=work/"audio.txt";list_audio.write_text("".join(f"file '{_concat_escape(item)}'\n" for item in audio_parts),encoding="utf-8")
        _run([ffmpeg,"-y","-f","concat","-safe","0","-i",str(list_audio),"-c:a","libmp3lame","-b:a","128k",str(audio)],"No se pudo unir el audiolibro")
        write_srt(srt,segments);write_srt(original_srt,segments)
        translated=None
        if bilingual:
            translated=[Segment(translate(item.text,source_lang),item.page,item.start,item.end) for item in segments]
            write_srt(translation_srt,translated)
        page_seconds={}
        for item in segments: page_seconds[item.page]=page_seconds.get(item.page,0)+(item.end-item.start)/1000
        page_list=work/"paginas.txt";lines=[]
        for page,seconds in page_seconds.items(): lines.extend((f"file '{_concat_escape(images[page])}'",f"duration {max(0.1,seconds):.3f}"))
        lines.append(f"file '{_concat_escape(images[next(iter(page_seconds))])}'");page_list.write_text("\n".join(lines)+"\n",encoding="utf-8")
        original_filter=str(original_srt.resolve()).replace("\\","/").replace(":","\\:").replace("'","\\'")
        vf=f"subtitles=filename='{original_filter}':force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,OutlineColour=&H00000000,Outline=2,Alignment=2,MarginV=26'"
        if translated:
            translate_filter=str(translation_srt.resolve()).replace("\\","/").replace(":","\\:").replace("'","\\'")
            vf+=f",subtitles=filename='{translate_filter}':force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFF00,BackColour=&H80000000,OutlineColour=&H00000000,Outline=2,Alignment=6,MarginV=26'"
        _run([ffmpeg,"-y","-f","concat","-safe","0","-i",str(page_list),"-i",str(audio),"-vf",vf,"-shortest","-r","25","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart",str(video)],"No se pudo crear el MP4 subtitulado")
    return AudiobookResult(audio,video,srt,original_srt,translation_srt)



