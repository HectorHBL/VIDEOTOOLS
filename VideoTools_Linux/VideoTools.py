"""VideoTools v48: cola mixta de vídeo, PDF y SRT con recuperación segura."""
from __future__ import annotations
import ctypes, json, math, os, queue, re, shutil, subprocess, sys, tempfile, threading, time, urllib.request, wave, zipfile
from urllib.parse import urlparse
from datetime import datetime
try: import winsound
except ImportError: winsound=None
import argostranslate.package, argostranslate.translate, argostranslate.settings
import pymupdf as fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from dataclasses import dataclass
from videotools_services.audiobook import AudiobookError, PIPER_VOICES, build_audiobook, elevenlabs_voices
from videotools_services.credentials import CredentialError, get_elevenlabs_key, set_elevenlabs_key
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
for _stream in (sys.stdout, sys.stderr):
    try: _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    APP_WINDOW=TkinterDnD.Tk
except Exception:
    DND_FILES=None;APP_WINDOW=tk.Tk

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PDF_TYPES=[("PDF con texto seleccionable","*.pdf")]
VIDEO_EXTENSIONS={".mp4",".mkv",".avi",".mov",".m4v",".webm",".3g2",".3gp",".ts",".mts",".m2ts",".wmv",".flv"}
AUDIO_EXTENSIONS={".mp3",".wav",".m4a",".aac",".flac",".ogg",".opus",".wma",".aiff",".alac"}
MEDIA_EXTENSIONS=VIDEO_EXTENSIONS|AUDIO_EXTENSIONS
VIDEO_TYPES=[("Vídeos, audios, PDF y SRT","*.mp4 *.mkv *.avi *.mov *.m4v *.webm *.3g2 *.3gp *.ts *.mts *.m2ts *.wmv *.flv *.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma *.aiff *.alac *.pdf *.srt *.url"),("Todos","*.*")]; SRT_TYPES=[("Subtítulos SRT","*.srt"),("Todos","*.*")]
MAX_PART_BYTES=134*1024*1024
SAFE_PART_BYTES=130*1024*1024
CONVERSION_PROFILES={
    "H.264 / AAC · MP4 (predeterminado)":(".mp4","H264_AAC",["-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart"],True),
    "H.265 / AAC · MP4":(".mp4","H265_AAC",["-c:v","libx265","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart"],True),
    "MPEG-4 / AAC · MP4":(".mp4","MPEG4_AAC",["-c:v","mpeg4","-c:a","aac","-b:a","128k","-movflags","+faststart"],True),
    "H.264 / AAC · 3GP":(".3gp","H264_AAC_3GP",["-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-b:a","96k","-f","3gp"],True),
    "H.264 / AAC · MKV":(".mkv","H264_AAC",["-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k"],True),
    "H.265 / AAC · MKV":(".mkv","H265_AAC",["-c:v","libx265","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k"],True),
    "VP9 / Opus · WebM":(".webm","VP9_OPUS",["-c:v","libvpx-vp9","-crf","32","-c:a","libopus","-b:a","128k"],True),
    "AV1 / Opus · MKV":(".mkv","AV1_OPUS",["-c:v","libaom-av1","-crf","32","-c:a","libopus","-b:a","128k"],True),
    "ProRes 422 / PCM · MOV":(".mov","PRORES_PCM",["-c:v","prores_ks","-profile:v","3","-c:a","pcm_s16le"],False),
    "FFV1 / FLAC · MKV":(".mkv","FFV1_FLAC",["-c:v","ffv1","-c:a","flac"],False),
    "MP3 · Audio":(".mp3","MP3",["-vn","-c:a","libmp3lame","-b:a","192k"],False),
    "AAC · Audio M4A":(".m4a","AAC_M4A",["-vn","-c:a","aac","-b:a","192k"],False),
    "WAV · PCM":(".wav","WAV_PCM",["-vn","-c:a","pcm_s16le"],False),
    "FLAC · Audio":(".flac","FLAC",["-vn","-c:a","flac"],False),
    "Opus · Audio":(".opus","OPUS",["-vn","-c:a","libopus","-b:a","160k"],False),
}
ERROR_HELP="E001: vídeo no encontrado.\nE002: SRT español no encontrado.\nE003: SRT inglés no encontrado.\nE004: SRT inválido o no legible.\nE005: FFprobe no pudo leer la duración.\nE006: FFmpeg falló en la etapa indicada.\nE007: no se pudo crear o escribir la carpeta de salida.\nE008: proceso detenido por el usuario.\nT101: no se pudo descargar o cargar el modelo offline.\nT102: no se pudo analizar/abrir el audio del vídeo.\nT103: falló la transcripción del audio.\nT104: no se pudo crear el SRT transcrito.\nT105: no se detectó diálogo en el audio.\nV101: Vosk no está instalado o no pudo cargarse.\nV102: no se pudo descargar/preparar el modelo Vosk.\nV103: no se pudo extraer el audio WAV para Vosk.\nV104: Vosk no pudo transcribir el audio."
ERROR_HELP += "\nE009: faltan subtítulos para quemar.\nR101: no hay SRT válido para traducir.\nR102/R202: falta el modelo Argos requerido.\nR103/R203: falló la traducción.\nR104: salida anómala; no se guarda un SRT que conserve el idioma original.\nR201: PDF inválido, ilegible o sin texto seleccionable."
class StopRequested(Exception): pass
class ProcessError(Exception):
    def __init__(self, code, message): super().__init__(f"{code}: {message}"); self.code=code
@dataclass(frozen=True)
class Subtitle: start:int; end:int; text:str
@dataclass
class Job: video:Path; spanish:Path|None=None; english:Path|None=None; status:str="ESPERA"; parts:int=1; manual_parts:bool=False; direct_srt:bool=False; youtube_url:str|None=None
def is_audio(path): return path.suffix.casefold() in AUDIO_EXTENSIONS
def is_video(path): return path.suffix.casefold() in VIDEO_EXTENSIONS
def url_from_shortcut(path):
    try:
        match=re.search(r"(?im)^URL=(.+)$",path.read_text(encoding="utf-8-sig",errors="replace"))
        return match.group(1).strip() if match else None
    except OSError:return None
def is_youtube_url(value):
    host=urlparse(value).netloc.casefold().split(":",1)[0]
    return host in {"youtu.be","youtube.com"} or host.endswith(".youtube.com")
def app_dir(): return Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent
def resource_path(name): return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))/name
def binary(name):
    local=app_dir()/(name+(".exe" if os.name=="nt" else "")); found=str(local) if local.is_file() else shutil.which(name)
    if not found: raise ProcessError("E006",f"No se encontró {name}.")
    return found
def duration(path):
    try:
        p=subprocess.run([binary("ffprobe"),"-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],check=True,capture_output=True,text=True,creationflags=NO_WINDOW); return float(p.stdout.strip())
    except Exception as e: raise ProcessError("E005",f"No se pudo obtener duración de {path.name}: {e}")
def parse_time(value):
    m=re.fullmatch(r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3,})",value.strip())
    if not m: raise ValueError(value)
    h,mn,s,ms=m.groups(); return (int(h)*3600+int(mn)*60+int(s))*1000+int(ms[:3])
def fmt(ms):
    h,ms=divmod(max(0,ms),3600000); mn,ms=divmod(ms,60000); s,ms=divmod(ms,1000); return f"{h:02d}:{mn:02d}:{s:02d},{ms:03d}"
def read_srt(path):
    try:
        result=[]
        for block in re.split(r"\r?\n\s*\r?\n",path.read_text(encoding="utf-8-sig").strip()):
            lines=block.splitlines(); i=1 if lines and lines[0].strip().isdigit() else 0
            if len(lines)<=i or "-->" not in lines[i]: continue
            a,b=(x.strip() for x in lines[i].split("-->",1)); text="\n".join(lines[i+1:]).strip()
            if text: result.append(Subtitle(parse_time(a),parse_time(b),text))
        return result
    except Exception as e: raise ProcessError("E004",f"No se pudo leer {path.name}: {e}")
def write_srt(path,items):
    try:
        out=[]
        for n,x in enumerate(items,1): out += [str(n),f"{fmt(x.start)} --> {fmt(x.end)}",x.text,""]
        path.write_text("\n".join(out),encoding="utf-8")
    except Exception as e: raise ProcessError("E007",f"No se pudo escribir {path.name}: {e}")
def part_srt(items,a,b): return [Subtitle(max(x.start,a)-a,min(x.end,b)-a,x.text) for x in items if x.end>a and x.start<b]
def filter_path(path): return str(path.resolve()).replace("\\","/").replace(":","\\:").replace("'","\\'")
class Tip:
    def __init__(self,w,text): self.w,self.text,self.top=w,text,None; w.bind("<Enter>",self.show,add="+"); w.bind("<Leave>",self.hide,add="+")
    def show(self,_=None):
        if self.top:return
        self.top=tk.Toplevel(self.w)
        try:self.top.iconbitmap(default=str(self.w.winfo_toplevel().icon_path))
        except Exception:pass
        self.top.wm_overrideredirect(True);self.top.wm_geometry(f"+{self.w.winfo_rootx()+12}+{self.w.winfo_rooty()+self.w.winfo_height()+5}");ttk.Label(self.top,text=self.text,justify="left",padding=7,relief="solid",borderwidth=1,wraplength=440).pack()
    def hide(self,_=None):
        if self.top:self.top.destroy();self.top=None
class App(APP_WINDOW):
    def __init__(self):
        super().__init__();self.title("VideoTools v48");self.conversion_profile=tk.StringVar(value=next(iter(CONVERSION_PROFILES)));self.icon_path=resource_path("VideoTools.ico")
        try:self.iconbitmap(default=str(self.icon_path))
        except tk.TclError:pass
        self.geometry("1180x735");self.minsize(780,500);self.parts,self.convert,self.burn=tk.IntVar(value=1),tk.BooleanVar(value=True),tk.BooleanVar(value=False);self.transcribe_only=tk.BooleanVar(value=False);self.translate_only=tk.BooleanVar(value=False);self.translation_choice=tk.StringVar(value="Automático");self.run_translate=False;self.engine_name=tk.StringVar(value="faster-whisper (preciso)");self.model_name=tk.StringVar(value="small");self.audio_language=tk.StringVar(value="Auto");self.run_srt_only=False;self.run_convert=False;self.run_engine="whisper";self.run_model="small";self.run_language=None;self.whisper_models={};self.vosk_models={};self.es_en_hf=None;self.jobs={};self.n=0;self.events=queue.Queue();self.status=tk.StringVar(value="Añade vídeo, audio, PDF o SRT a la cola.");self.current=tk.StringVar(value="Sin proceso activo");self.stage_widgets={};self.stop_event=threading.Event();self.pause_event=threading.Event();self.active_process=None;self.preventing_sleep=False;self.editor_media=None;self.editor_srt=None;self.editor_items=[];self.editor_dispositions={};self.editor_jobs=[];self.editor_active_job=None;self.editor_player=None;self.editor_process=None;self.editor_busy=False;self.editor_position=0.0;self.editor_duration=0.0;self.editor_playing=False;self.editor_paused=True;self.editor_profile=tk.StringVar(value=next(iter(CONVERSION_PROFILES)));self.editor_status=tk.StringVar(value="Carga un vídeo o audio y su SRT para editar por subtítulos.");self.audiobook_mode=tk.BooleanVar(value=False);self.audiobook_settings=None;self.ui();self.protocol("WM_DELETE_WINDOW",self.on_close);self.after(100,self.receive)
        self.run_burn=False;self.run_translation_choice="Automático";self.run_has_direct_srt=False;self.audiobook_busy=False;self.audiobook_cancel=threading.Event();self.clearing=False;self.last_progress_marker=None
    def ui(self):
        self.notebook=ttk.Notebook(self);self.notebook.pack(fill="both",expand=True)
        self.queue_tab=ttk.Frame(self.notebook);self.editor_tab=ttk.Frame(self.notebook)
        self.notebook.add(self.queue_tab,text="Procesos y conversión")
        self.notebook.add(self.editor_tab,text="Reproductor y edición")
        box=ttk.Frame(self.queue_tab,padding=16);box.pack(fill="both",expand=True);box.columnconfigure(0,weight=1);box.rowconfigure(3,weight=1)
        ttk.Label(box,text="Cola mixta: PDF y SRT se traducen por archivo; los vídeos conservan las opciones seleccionadas.").grid(row=1,sticky="w",pady=(0,5))
        self.stage_frame=ttk.Frame(box);self.stage_frame.grid(row=2,sticky="w",pady=(0,6));self.build_stages()
        cols=("status","video","parts","folder","spanish","english");self.tree=ttk.Treeview(box,columns=cols,show="headings",height=10,selectmode="browse")
        for k,t,w in (("status","Estatus",120),("video","Archivo (vídeo/PDF/SRT)",220),("parts","Partes ≤134 MB",115),("folder","Ruta",330),("spanish","SRT español",180),("english","SRT inglés",180)):self.tree.heading(k,text=t);self.tree.column(k,width=w,minwidth=90,stretch=False)
        self.tree.tag_configure("ok",foreground="#006100",background="#C6EFCE");self.tree.tag_configure("working",foreground="#7F6000",background="#FFEB9C");self.tree.tag_configure("error",foreground="#9C0006",background="#FFC7CE");self.tree.grid(row=3,sticky="nsew")
        if DND_FILES:self.tree.drop_target_register(DND_FILES);self.tree.dnd_bind("<<Drop>>",self.drop_files)
        v=ttk.Scrollbar(box,orient="vertical",command=self.tree.yview);v.grid(row=3,column=1,sticky="ns");self.tree.configure(yscrollcommand=v.set);h=ttk.Scrollbar(box,orient="horizontal",command=self.tree.xview);h.grid(row=4,sticky="ew");self.tree.configure(xscrollcommand=h.set);self.tree.bind("<<TreeviewSelect>>",self.on_select)
        a=ttk.Frame(box);a.grid(row=5,sticky="w",pady=8);self.add=ttk.Button(a,text="Añadir vídeo / PDF / SRT",command=self.add_videos);self.add.pack(side="left");self.es=ttk.Button(a,text="Cargar SRT en español",command=lambda:self.assign("spanish"));self.es.pack(side="left",padx=6);self.en=ttk.Button(a,text="Cargar SRT en inglés",command=lambda:self.assign("english"));self.en.pack(side="left");self.remove=ttk.Button(a,text="Quitar seleccionado",command=self.remove_job);self.remove.pack(side="left",padx=6);self.clear=ttk.Button(a,text="Limpiar cola",command=self.clear_jobs);self.clear.pack(side="left");self.audiobook_button=ttk.Button(a,text="Configurar audiolibro PDF",command=self.open_audiobook_dialog);self.audiobook_button.pack_forget()
        o=ttk.Frame(box);o.grid(row=6,sticky="w");self.parts_label=ttk.Label(o,text="Partes automáticas (máx. 134 MB):");self.parts_label.pack(side="left");self.part_input=ttk.Spinbox(o,from_=1,to=999,textvariable=self.parts,width=8,command=self.set_manual_parts);self.part_input.bind("<FocusOut>",lambda _e:self.set_manual_parts());self.part_input.bind("<Return>",lambda _e:self.set_manual_parts());self.part_input.pack(side="left",padx=8);self.conv=ttk.Checkbutton(o,text="Convertir a H.264 / AAC",variable=self.convert,command=self.build_stages);self.conv.pack(side="left",padx=12);self.burn_box=ttk.Checkbutton(o,text="Quemar subtítulos",variable=self.burn,command=self.build_stages);self.burn_box.pack(side="left",padx=12);self.srt_only_box=ttk.Checkbutton(o,text="Generar SRT offline (único proceso)",variable=self.transcribe_only,command=self.update_srt_mode);self.srt_only_box.pack(side="left",padx=12);self.translate_box=ttk.Checkbutton(o,text="Traducir SRT offline (único proceso)",variable=self.translate_only,command=self.update_translate_mode);self.audiobook_mode_box=ttk.Checkbutton(o,text="Generar audiolibro del PDF seleccionado",variable=self.audiobook_mode,command=self.update_audiobook_mode);self.audiobook_mode_box.pack(side="left",padx=12);self.translate_choice_box=ttk.Combobox(o,textvariable=self.translation_choice,values=("Automático","ES → EN","EN → ES"),state="readonly",width=15);self.engine_box=ttk.Combobox(o,textvariable=self.engine_name,values=("Vosk (rápido)","faster-whisper (preciso)"),state="readonly",width=24);self.engine_box.bind("<<ComboboxSelected>>",lambda _e:self.engine_changed());self.model_box=ttk.Combobox(o,textvariable=self.model_name,values=("small","medium","large-v3"),state="readonly",width=9);self.lang_box=ttk.Combobox(o,textvariable=self.audio_language,values=("Auto","Inglés","Español"),state="readonly",width=10);self.model_box.pack(side="left",padx=(8,2));self.lang_box.pack(side="left",padx=2);self.engine_box.pack_forget();self.model_box.pack_forget();self.lang_box.pack_forget()
        self.translate_choice_box.pack(side="left",padx=8)
        self.profile_box=ttk.Combobox(o,textvariable=self.conversion_profile,values=tuple(CONVERSION_PROFILES),state="readonly",width=31)
        self.parts_label.configure(text="Dividir en:");self.conv.configure(text="Convertir a",command=self.update_conversion_mode);self.srt_only_box.configure(text="Generar SRT")
        self.profile_box.pack(side="left",padx=(2,8),before=self.burn_box)
        run=ttk.Frame(box);run.grid(row=7,sticky="ew",pady=8);run.columnconfigure(0,weight=1);self.start=tk.Button(run,text="INICIAR PROCESOS EN ARCHIVOS",command=self.start_queue,bg="#FFF2CC",activebackground="#FFE699",relief="raised",font=("Segoe UI",10,"bold"));self.start.grid(row=0,column=0,sticky="ew");self.pause_button=ttk.Button(run,text="Pausar",command=self.toggle_pause,state="disabled");self.pause_button.grid(row=0,column=1,padx=6);self.stop_button=ttk.Button(run,text="Detener",command=self.stop_queue,state="disabled");self.stop_button.grid(row=0,column=2);ttk.Label(box,text="Avance general de renglones finalizados:").grid(row=8,sticky="w");self.bar=ttk.Progressbar(box,maximum=100);self.bar.grid(row=9,sticky="ew");ttk.Label(box,textvariable=self.current).grid(row=10,sticky="w");ttk.Label(box,textvariable=self.status).grid(row=11,sticky="w");log_frame=ttk.Frame(box);log_frame.grid(row=12,sticky="nsew");log_frame.columnconfigure(0,weight=1);log_frame.rowconfigure(0,weight=1);self.log=tk.Text(log_frame,height=8,state="disabled",wrap="word");self.log.grid(row=0,column=0,sticky="nsew");log_scroll=ttk.Scrollbar(log_frame,orient="vertical",command=self.log.yview);log_scroll.grid(row=0,column=1,sticky="ns");self.log.configure(yscrollcommand=log_scroll.set);box.rowconfigure(12,weight=1)
        self.tree_tip=Tip(self.tree,"Lista de vídeos y audios. El detalle de códigos aparece aquí solo si existe un ERROR.")
        self.build_editor_tab()
        for w,t in ((self.add,"Añade vídeos a la cola."),(self.es,"Asocia SRT español, incluso de otra carpeta."),(self.en,"Asocia SRT inglés, incluso de otra carpeta."),(self.part_input,"Número de fragmentos por vídeo."),(self.conv,"Activa la conversión del vídeo antes de dividir."),(self.profile_box,"Perfiles compatibles de FFmpeg. H.264/AAC es el predeterminado; los perfiles sin pérdida pueden crear archivos grandes."),(self.burn_box,"Integra ambos subtítulos de manera permanente."),(self.srt_only_box,"Ejecuta solamente la generación de SRT desde el audio para toda la cola."),(self.engine_box,"Vosk es rápido y funciona offline después de descargar su modelo. faster-whisper es más preciso, pero más lento."),(self.model_box,"Modelo faster-whisper: small es más rápido; medium y large-v3 son más precisos."),(self.lang_box,"Auto detecta inglés o español. Puedes forzar un idioma."),(self.start,"Inicia los renglones ESPERA en orden."),(self.pause_button,"Pausa la cola al terminar la etapa de FFmpeg en curso; vuelve a pulsar para reanudar."),(self.stop_button,"Detiene el FFmpeg activo y deja los renglones restantes en ESPERA."),(self.bar,"Porcentaje de renglones finalizados."),(self.log,"Mensajes, etapas y errores.")):Tip(w,t)
    def open_audiobook_dialog(self):
        if self.audiobook_busy:
            messagebox.showinfo("VideoTools v48","Ya hay audiolibros en generación.",parent=self);return
        pdfs=[j.video for j in self.jobs.values() if j.video.suffix.casefold()==".pdf" and j.status=="ESPERA"]
        if not pdfs:
            messagebox.showwarning("VideoTools v48","Añade al menos un PDF en ESPERA antes de configurar el audiolibro.",parent=self);return
        saved=self.audiobook_settings or {}
        dialog=tk.Toplevel(self);dialog.title("Generar audiolibro y video subtitulado");dialog.transient(self);dialog.grab_set();dialog.columnconfigure(1,weight=1);dialog.minsize(640,520)
        def center_dialog():
            dialog.update_idletasks();width=max(680,dialog.winfo_reqwidth());height=max(560,dialog.winfo_reqheight());x=self.winfo_rootx()+max(0,(self.winfo_width()-width)//2);y=self.winfo_rooty()+max(0,(self.winfo_height()-height)//2);dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.after_idle(center_dialog)
        provider=tk.StringVar(value=saved.get("provider","Piper (offline)"));voice=tk.StringVar(value=saved.get("voice",next(iter(PIPER_VOICES))));speed=tk.DoubleVar(value=saved.get("speed",1.0));language=tk.StringVar(value=saved.get("language","Automático"));folder=tk.StringVar(value=str(saved.get("folder",pdfs[0].parent)));pauses=tk.BooleanVar(value=saved.get("pauses",True));bilingual=tk.BooleanVar(value=saved.get("bilingual",True));status=tk.StringVar(value=f"La configuración se aplicará a {len(pdfs)} PDF(s) en la lista.")
        def row(number,label,widget):ttk.Label(dialog,text=label).grid(row=number,column=0,sticky="w",padx=10,pady=5);widget.grid(row=number,column=1,sticky="ew",padx=10,pady=5)
        provider_box=ttk.Combobox(dialog,textvariable=provider,values=("Piper (offline)","ElevenLabs (online)"),state="readonly",width=28);row(0,"Proveedor de voz:",provider_box)
        voice_box=ttk.Combobox(dialog,textvariable=voice,values=tuple(PIPER_VOICES),state="readonly",width=34);row(1,"Voz:",voice_box)
        row(2,"Velocidad:",ttk.Spinbox(dialog,from_=0.5,to=2.0,increment=0.1,textvariable=speed,width=8));row(3,"Idioma de los PDF:",ttk.Combobox(dialog,textvariable=language,values=("Automático","es","en"),state="readonly",width=16))
        folder_frame=ttk.Frame(dialog);ttk.Entry(folder_frame,textvariable=folder).pack(side="left",fill="x",expand=True);ttk.Button(folder_frame,text="Carpeta…",command=lambda: folder.set(filedialog.askdirectory(parent=dialog,initialdir=folder.get()) or folder.get())).pack(side="left",padx=(5,0));row(4,"Carpeta destino:",folder_frame)
        ttk.Checkbutton(dialog,text="Conservar pausas entre párrafos",variable=pauses).grid(row=5,column=0,columnspan=2,sticky="w",padx=10,pady=(5,1));ttk.Checkbutton(dialog,text="Subtítulos bilingües (traducción arriba, original abajo)",variable=bilingual).grid(row=6,column=0,columnspan=2,sticky="w",padx=10,pady=1)
        ttk.Label(dialog,text="Los parámetros guardados se usarán para todos los PDF cargados. ElevenLabs envía el texto al proveedor.",wraplength=510).grid(row=7,column=0,columnspan=2,sticky="w",padx=10,pady=(6,2));ttk.Label(dialog,textvariable=status,wraplength=510).grid(row=8,column=0,columnspan=2,sticky="w",padx=10,pady=(3,7))
        def refresh_voices(_event=None):
            if provider.get()=="Piper (offline)":voice_box.configure(values=tuple(PIPER_VOICES));voice.set(next(iter(PIPER_VOICES)));status.set("Piper usa voz local y no envía los PDF a Internet.");return
            secret=get_elevenlabs_key()
            if not secret:status.set("Configura primero la API Key de ElevenLabs o cambia a Piper.");return
            try:
                voices=elevenlabs_voices(secret);voice_box.configure(values=tuple(name for name,_ in voices));dialog.eleven_voice_ids=dict(voices);voice.set(voices[0][0] if voices else "");status.set("Voces de ElevenLabs cargadas.")
            except AudiobookError as error:status.set(str(error))
        provider_box.bind("<<ComboboxSelected>>",refresh_voices)
        def configure_key():
            value=simpledialog.askstring("ElevenLabs","API Key (se guarda sólo en el almacén seguro del sistema):",show="*",parent=dialog)
            if value:
                try:set_elevenlabs_key(value);status.set("API Key guardada en el almacén seguro.")
                except CredentialError as error:messagebox.showerror("VideoTools v48",str(error),parent=dialog)
        def save():
            target=Path(folder.get())
            if not target.is_dir():messagebox.showerror("VideoTools v48","Elige una carpeta destino válida.",parent=dialog);return
            selected_voice=voice.get()
            if provider.get().startswith("ElevenLabs"):
                selected_voice=getattr(dialog,"eleven_voice_ids",{}).get(selected_voice,selected_voice)
                if not selected_voice:messagebox.showerror("VideoTools v48","Elige una voz ElevenLabs o actualiza la lista.",parent=dialog);return
            self.audiobook_settings={"provider":provider.get(),"voice":selected_voice,"speed":float(speed.get()),"language":language.get(),"folder":target,"bilingual":bool(bilingual.get()),"pauses":bool(pauses.get())};self.status.set(f"Configuración de audiolibro guardada para {len(pdfs)} PDF(s). Pulsa INICIAR PROCESOS EN ARCHIVOS.");dialog.destroy()
        buttons=ttk.Frame(dialog);buttons.grid(row=9,column=0,columnspan=2,sticky="e",padx=10,pady=10);ttk.Button(buttons,text="Configurar API Key",command=configure_key).pack(side="left",padx=4);ttk.Button(buttons,text="Guardar",command=save).pack(side="left",padx=4);ttk.Button(buttons,text="Cerrar",command=dialog.destroy).pack(side="left",padx=4)

    def start_audiobook_batch(self):
        settings=self.audiobook_settings
        pdfs=[(key,j) for key,j in self.jobs.items() if j.video.suffix.casefold()==".pdf" and j.status=="ESPERA"]
        if not settings:
            messagebox.showwarning("VideoTools v48","Configura y guarda primero los parámetros del audiolibro.",parent=self);return
        if not pdfs:
            messagebox.showwarning("VideoTools v48","No hay PDFs en ESPERA para procesar.",parent=self);return
        self.audiobook_busy=True;self.audiobook_cancel.clear();self.bar["value"]=0;self.stop_event.clear();self.pause_event.clear();self.start.configure(text="CORRIENDO AUDIOLIBROS",bg="#B7C98A",activebackground="#A6B879");self.controls("disabled");self.keep_awake(True);self.status.set(f"Preparando {len(pdfs)} audiolibro(s)...");threading.Thread(target=self.audiobook_batch_worker,args=(pdfs,settings),daemon=True).start()
    def audiobook_batch_worker(self,pdfs,settings):
        try:
            results=[];total=len(pdfs)
            for number,(key,job) in enumerate(pdfs,1):
                pdf=job.video;self.events.put(("audiobook_working",key,number,total,pdf.name))
                def translate(text,detected):return self.translate_es_en(text) if detected=="es" else self.argos_translator("en","es","R202").translate(text)
                result=build_audiobook(pdf,settings["folder"],settings["provider"],settings["voice"],settings["speed"],settings["language"],settings["bilingual"],settings["pauses"],binary("ffmpeg"),binary("ffprobe"),app_dir(),translate,get_elevenlabs_key,self.audiobook_cancel.is_set,lambda label,done,parts,n=number,name=pdf.name:self.events.put(("audiobook_progress",n,total,name,label,done,parts)))
                results.append(result);self.events.put(("audiobook_finished",key));self.events.put(("audiobook_batch_progress",number,total))
            self.events.put(("audiobook_batch_done",tuple(results)))
        except Exception as error:self.events.put(("audiobook_failed",str(error)))
    def build_editor_tab(self):
        box=ttk.Frame(self.editor_tab,padding=14);box.pack(fill="both",expand=True);box.columnconfigure(0,weight=1);box.rowconfigure(3,weight=1)
        ttk.Label(box,text="Edición guiada por subtítulos",font=("Segoe UI",11,"bold")).grid(row=0,column=0,sticky="w")
        ttk.Label(box,text="Carga un vídeo o audio y su SRT. Selecciona varias partidas para extraerlas o eliminarlas del resultado conservado.",wraplength=900).grid(row=1,column=0,sticky="w",pady=(2,8))
        actions=ttk.Frame(box);actions.grid(row=2,column=0,sticky="ew",pady=(0,8))
        self.editor_media_button=ttk.Button(actions,text="Cargar vídeo / audio",command=self.editor_choose_media);self.editor_media_button.pack(side="left");self.editor_add_job_button=ttk.Button(actions,text="Añadir vídeo + SRT",command=self.editor_add_job);self.editor_add_job_button.pack(side="left",padx=6)
        self.editor_srt_button=ttk.Button(actions,text="Cargar SRT",command=self.editor_choose_srt);self.editor_srt_button.pack(side="left",padx=6)
        self.editor_play_button=ttk.Button(actions,text="Reproducir RESUMEN",command=lambda:self.editor_play_disposition("RESUMEN"));self.editor_play_button.pack(side="left",padx=(18,0))
        self.editor_play_selection_button=ttk.Button(actions,text="REPRODUCIR SIN MARCA",command=lambda:self.editor_play_disposition(""));self.editor_play_selection_button.pack(side="left",padx=6);self.editor_play_delete_button=ttk.Button(actions,text="REPRODUCIR ELIMINAR",command=lambda:self.editor_play_disposition("ELIMINAR"));self.editor_play_delete_button.pack(side="left",padx=6)
        self.editor_stop_button=ttk.Button(actions,text="Detener reproductor",command=self.editor_stop_player);self.editor_stop_button.pack(side="left")
        queue_box=ttk.LabelFrame(box,text="Lista de vídeos/SRT",padding=4);queue_box.grid(row=3,column=0,sticky="ew",pady=(0,8));queue_box.columnconfigure(0,weight=1)
        self.editor_jobs_list=tk.Listbox(queue_box,height=6,exportselection=False);self.editor_jobs_list.grid(row=0,column=0,sticky="ew");self.editor_jobs_list.bind("<<ListboxSelect>>",self.editor_select_job)
        jobs_scrollbar=ttk.Scrollbar(queue_box,orient="vertical",command=self.editor_jobs_list.yview);jobs_scrollbar.grid(row=0,column=1,sticky="ns");self.editor_jobs_list.configure(yscrollcommand=jobs_scrollbar.set)
        if DND_FILES:self.editor_jobs_list.drop_target_register(DND_FILES);self.editor_jobs_list.dnd_bind("<<Drop>>",self.editor_drop_jobs)
        self.editor_jobs_progress=ttk.Progressbar(queue_box,maximum=100);self.editor_jobs_progress.grid(row=1,column=0,columnspan=2,sticky="ew",pady=(5,0))
        box.rowconfigure(4,weight=1,minsize=360);self.editor_pane=tk.PanedWindow(box,orient=tk.VERTICAL,sashrelief=tk.RAISED,opaqueresize=True,showhandle=True);self.editor_pane.grid(row=4,column=0,sticky="nsew",pady=(0,5));player_box=ttk.LabelFrame(self.editor_pane,text="Reproductor de vídeo y audio",padding=3);player_box.configure(height=230)
        self.editor_time=tk.DoubleVar(value=0.0);self.editor_player_host=tk.Frame(player_box,bg="#101820",height=220);self.editor_player_host.pack(fill="both",expand=True);self.editor_player_host.bind("<Configure>",self.editor_resize_player);self.editor_time_scale=ttk.Scale(player_box,from_=0,to=1,variable=self.editor_time,command=self.editor_slider_changed);self.editor_time_scale.pack(fill="x",padx=5,pady=(2,3));self.editor_time_scale.bind("<ButtonRelease-1>",self.editor_slider_released);Tip(self.editor_time_scale,"Arrastra para adelantar o retroceder. Al soltar, el reproductor continúa desde esa posición.")
        self.editor_media_label=ttk.Label(box,text="Medio: —");self.editor_media_label.grid(row=5,column=0,sticky="nw",pady=(0,3))
        tree_frame=ttk.Frame(self.editor_pane);tree_frame.columnconfigure(0,weight=1);tree_frame.rowconfigure(0,weight=1)
        columns=("number","start","end","disposition","text")
        self.editor_tree=ttk.Treeview(tree_frame,columns=columns,show="headings",selectmode="extended",height=13)
        for key,title,width in (("number","#",55),("start","Inicio",105),("end","Fin",105),("disposition","DISPOSICIÓN",120),("text","Texto del subtítulo",640)):
            self.editor_tree.heading(key,text=title);self.editor_tree.column(key,width=width,minwidth=55,stretch=key=="text")
        self.editor_tree.grid(row=0,column=0,sticky="nsew");self.editor_tree.bind("<<TreeviewSelect>>",self.editor_select_subtitle);self.editor_tree.bind("<Double-1>",self.editor_doubleclick_subtitle)
        scrollbar=ttk.Scrollbar(tree_frame,orient="vertical",command=self.editor_tree.yview);scrollbar.grid(row=0,column=1,sticky="ns");self.editor_tree.configure(yscrollcommand=scrollbar.set)
        self.editor_pane.add(player_box,minsize=190,stretch="always")
        self.editor_pane.add(tree_frame,minsize=150,stretch="always")
        Tip(self.editor_pane,"Arrastra esta división para dar más espacio al reproductor o al listado de subtítulos.")
        output=ttk.LabelFrame(box,text="Exportar segmentos",padding=8);output.grid(row=7,column=0,sticky="ew",pady=(9,0))
        ttk.Label(output,text="Formato de salida:").pack(side="left")
        video_profiles=tuple(name for name in CONVERSION_PROFILES if not self.profile_is_audio(name))
        self.editor_profile_box=ttk.Combobox(output,textvariable=self.editor_profile,values=video_profiles,state="readonly",width=31);self.editor_profile_box.pack(side="left",padx=6)
        self.editor_extract_button=ttk.Button(output,text="ELIMINAR",command=lambda:self.editor_mark("ELIMINAR"));self.editor_extract_button.pack(side="left",padx=(14,4))
        self.editor_keep_button=ttk.Button(output,text="RESUMEN",command=lambda:self.editor_mark("RESUMEN"));self.editor_keep_button.pack(side="left",padx=4)
        self.editor_both_button=ttk.Button(output,text="PROCESAR",command=self.editor_process_all);self.editor_both_button.pack(side="left",padx=4)
        self.editor_progress=ttk.Progressbar(output,maximum=100,length=180);self.editor_progress.pack(side="left",padx=(16,4),fill="x",expand=True)
        self.editor_progress_text=ttk.Label(output,text="Sin proceso");self.editor_progress_text.pack(side="left")
        status_frame=ttk.Frame(box);status_frame.grid(row=8,column=0,sticky="ew",pady=(8,0));status_frame.columnconfigure(0,weight=1);ttk.Label(status_frame,textvariable=self.editor_status,wraplength=700).grid(row=0,column=0,sticky="w");self.editor_file_progress=ttk.Progressbar(status_frame,maximum=100,length=210);self.editor_file_progress.grid(row=0,column=1,sticky="e",padx=(10,0))
        Tip(self.editor_tree,"Usa Ctrl o Mayús para seleccionar varias partidas. ELIMINAR y RESUMEN definen qué salida recibirá cada renglón.")
        for widget,text in ((self.editor_media_button,"Carga el vídeo o audio que se editará."),(self.editor_srt_button,"Carga el SRT que delimita las escenas."),(self.editor_play_button,"Reproduce el primer segmento marcado RESUMEN."),(self.editor_play_selection_button,"Reproduce el primer segmento sin disposición."),(self.editor_play_delete_button,"Reproduce el primer segmento marcado ELIMINAR."),(self.editor_stop_button,"Detiene la reproducción actual."),(self.editor_profile_box,"Elige el formato de salida de los vídeos generados."),(self.editor_extract_button,"Marca como ELIMINAR todos los renglones seleccionados."),(self.editor_keep_button,"Marca como RESUMEN todos los renglones seleccionados."),(self.editor_both_button,"Genera primero RESUMEN, después VANAL y por último ELIMINAR."),(self.editor_progress,"Muestra el avance de la salida que FFmpeg está creando.")):Tip(widget,text)

    def profile_is_audio(self, name):
        return "-vn" in CONVERSION_PROFILES.get(name, (None,None,[],None))[2]

    def editor_save_active_job(self):
        if self.editor_active_job is not None:
            job=self.editor_jobs[self.editor_active_job];job["dispositions"]=dict(self.editor_dispositions)
    def editor_add_job(self):
        media=filedialog.askopenfilename(title="Selecciona vídeo",filetypes=[("Vídeo","*.mp4 *.mkv *.avi *.mov *.webm *.3gp"),("Todos","*.*")])
        if not media:return
        srt=filedialog.askopenfilename(title="Selecciona SRT de este vídeo",filetypes=SRT_TYPES)
        if not srt:return
        try:items=read_srt(Path(srt));duration(Path(media))
        except ProcessError as error:messagebox.showerror("VideoTools v48",str(error),parent=self);return
        self.editor_save_active_job();self.editor_jobs.append({"media":Path(media),"srt":Path(srt),"items":items,"dispositions":{}});self.editor_jobs_list.insert("end",Path(media).name);self.editor_jobs_list.selection_clear(0,"end");self.editor_jobs_list.selection_set("end");self.editor_select_job()
    def editor_select_job(self,_event=None):
        picked=self.editor_jobs_list.curselection()
        if not picked:return
        self.editor_save_active_job();self.editor_active_job=picked[0];job=self.editor_jobs[self.editor_active_job];self.editor_stop_player();self.editor_media=job["media"];self.editor_srt=job["srt"];self.editor_items=job["items"];self.editor_dispositions=dict(job["dispositions"]);self.editor_duration=duration(self.editor_media);self.editor_time_scale.configure(to=max(1,self.editor_duration));self.editor_time.set(0);self.editor_media_label.configure(text=f"Medio: {self.editor_media}");self.editor_refresh_subtitles();self.editor_status.set(f"Partida {self.editor_active_job+1}/{len(self.editor_jobs)} cargada: {len(self.editor_items)} subtítulos." if self.editor_items else "SRT pendiente: pulsa Cargar SRT para esta partida.")
    def editor_drop_jobs(self,event):
        self.editor_add_paths(self.tk.splitlist(event.data));return "break"
    def editor_add_paths(self,paths):
        added=0;missing=[]
        for value in paths:
            media=Path(value)
            if not is_video(media):continue
            candidates=[item for item in media.parent.glob("*.srt") if item.stem.casefold().startswith(media.stem.casefold()) or media.stem.casefold().startswith(item.stem.casefold())]
            srt=next((item for item in candidates if item.is_file()),None)
            try:items=read_srt(srt) if srt else [];duration(media)
            except ProcessError:continue
            self.editor_jobs.append({"media":media,"srt":srt,"items":items,"dispositions":{}});self.editor_jobs_list.insert("end",media.name+("  [SRT pendiente]" if not srt else ""));added+=1
            if not srt:missing.append(media.name)
        if added:
            self.editor_jobs_list.selection_clear(0,"end");self.editor_jobs_list.selection_set("end");self.editor_select_job()
        if missing:self.editor_status.set(f"Añadidos: {added}. SRT pendiente para: {', '.join(missing[:3])}. Selecciona el vídeo y pulsa Cargar SRT.")
    def editor_choose_media(self):
        path=filedialog.askopenfilename(title="Selecciona vídeo o audio",filetypes=[("Vídeo o audio","*.mp4 *.mkv *.avi *.mov *.m4v *.webm *.3g2 *.3gp *.ts *.mts *.m2ts *.wmv *.flv *.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma *.aiff *.alac"),("Todos","*.*")])
        if not path:return
        self.editor_media=Path(path);self.editor_media_label.configure(text=f"Medio: {self.editor_media}");self.editor_duration=duration(self.editor_media);self.editor_time_scale.configure(to=max(1,self.editor_duration));self.editor_time.set(0)
        possible=[item for item in self.editor_media.parent.glob("*.srt") if item.stem.casefold().startswith(self.editor_media.stem.casefold()) or self.editor_media.stem.casefold().startswith(item.stem.casefold())]
        found=next((item for item in possible if item.is_file()),None)
        if found:self.editor_load_srt(found)
        else:self.editor_srt=None;self.editor_items=[];self.editor_refresh_subtitles();self.editor_status.set("Medio cargado. Carga o genera el SRT antes de seleccionar segmentos.")

    def editor_choose_srt(self):
        path=filedialog.askopenfilename(title="Selecciona SRT",filetypes=SRT_TYPES)
        if path:self.editor_load_srt(Path(path))

    def editor_load_srt(self, path):
        try:items=read_srt(path)
        except ProcessError as error:messagebox.showerror("VideoTools v48",str(error),parent=self);return
        if not items:messagebox.showwarning("VideoTools v48","El SRT no contiene partidas válidas.",parent=self);return
        self.editor_srt=Path(path);self.editor_items=items;self.editor_dispositions={};
        if self.editor_active_job is not None:
            job=self.editor_jobs[self.editor_active_job];job["srt"]=self.editor_srt;job["items"]=items;job["dispositions"]={};self.editor_jobs_list.delete(self.editor_active_job);self.editor_jobs_list.insert(self.editor_active_job,job["media"].name);self.editor_jobs_list.selection_set(self.editor_active_job)
        self.editor_refresh_subtitles();self.editor_status.set(f"SRT cargado: {len(items)} partidas. Selecciona las que deseas eliminar o extraer.")

    def editor_refresh_subtitles(self):
        self.editor_tree.delete(*self.editor_tree.get_children())
        for number,item in enumerate(self.editor_items,1):
            text=re.sub(r"\s+"," ",item.text).strip()
            self.editor_tree.insert("","end",iid=str(number-1),values=(number,fmt(item.start),fmt(item.end),self.editor_dispositions.get(number-1,""),text))

    def editor_mark(self, disposition):
        selected=self.editor_tree.selection()
        if not selected:messagebox.showwarning("VideoTools v48","Selecciona uno o más subtítulos.",parent=self);return
        for value in selected:self.editor_dispositions[int(value)]=disposition
        self.editor_save_active_job();self.editor_refresh_subtitles();self.editor_tree.selection_set(selected);self.editor_status.set(f"{len(selected)} renglón(es) marcado(s) como {disposition}.")

    def editor_select_subtitle(self, _event=None):
        selected=self.editor_tree.selection()
        if selected:self.editor_position=self.editor_items[int(selected[0])].start/1000;self.editor_seek_current(False)

    def editor_doubleclick_subtitle(self, _event=None):
        selected=self.editor_tree.selection()
        if selected:self.editor_position=self.editor_items[int(selected[0])].start/1000;self.editor_seek_current(True)

    def editor_ranges_for(self, disposition):
        indexes=[index for index,value in self.editor_dispositions.items() if value==disposition]
        return self.editor_ranges_from_indexes(indexes)

    def editor_ranges_from_indexes(self, indexes):
        """Agrupa renglones consecutivos de la lista, aunque exista silencio entre ellos."""
        chosen=sorted(set(indexes))
        if not chosen:return []
        result=[];first=previous=chosen[0]
        for index in chosen[1:]:
            if index==previous+1:previous=index;continue
            result.append((self.editor_items[first].start/1000,self.editor_items[previous].end/1000));first=previous=index
        result.append((self.editor_items[first].start/1000,self.editor_items[previous].end/1000))
        return result
    def editor_selected_ranges(self):
        return self.editor_ranges_from_indexes(int(value) for value in self.editor_tree.selection())
    def editor_complement_ranges(self, removed, total):
        result=[];cursor=0.0
        for start,end in removed:
            if start>cursor+0.015:result.append((cursor,min(start,total)))
            cursor=max(cursor,end)
        if cursor<total-0.015:result.append((cursor,total))
        return [(start,end) for start,end in result if end-start>=0.04]

    def editor_slider_changed(self, value):
        if not getattr(self,"editor_updating_time",False):self.editor_position=float(value)

    def editor_slider_released(self, _event=None):
        self.editor_position=float(self.editor_time.get())
        self.editor_seek_current(self.editor_playing)

    def editor_tick_time(self):
        if self.editor_playing and self.editor_player and self.editor_player.poll() is None:
            self.editor_position=min(self.editor_duration,self.editor_play_origin+time.monotonic()-self.editor_play_started)
            self.editor_updating_time=True;self.editor_time.set(self.editor_position);self.editor_updating_time=False
        self.after(250,self.editor_tick_time)
    def editor_resize_player(self, event=None):
        if os.name!="nt" or not getattr(self,"editor_player_hwnd",None):return
        try:
            width=max(1,self.editor_player_host.winfo_width());height=max(1,self.editor_player_host.winfo_height())
            ctypes.windll.user32.MoveWindow(self.editor_player_hwnd,0,0,width,height,True)
        except Exception:pass

    def editor_embed_player(self, tries=0):
        if os.name!="nt" or not self.editor_player or self.editor_player.poll() is not None:return
        try:
            hwnd=ctypes.windll.user32.FindWindowW(None,getattr(self,"editor_player_title","") )
            if hwnd:
                host=self.editor_player_host.winfo_id();user32=ctypes.windll.user32
                user32.SetParent(hwnd,host);style=user32.GetWindowLongW(hwnd,-16)
                user32.SetWindowLongW(hwnd,-16,(style & ~0x00C00000) | 0x40000000 | 0x10000000)
                self.editor_player_hwnd=hwnd;self.editor_resize_player();user32.ShowWindow(hwnd,5)
                self.editor_status.set("Reproductor integrado en esta pestaña.");return
        except Exception:pass
        if tries<25:self.after(120,lambda:self.editor_embed_player(tries+1))
        elif self.editor_player and self.editor_player.poll() is None:self.editor_status.set("Reproductor FFplay abierto en una ventana independiente.")
    def editor_stop_player(self):
        if self.editor_player and self.editor_player.poll() is None:
            try:self.editor_player.terminate()
            except OSError:pass
        self.editor_player=None;self.editor_player_hwnd=None;self.editor_playing=False;self.editor_paused=True;self.editor_status.set("Reproductor detenido.")

    def editor_seek_current(self, play):
        if not self.editor_media:return
        was_playing=self.editor_player is not None and self.editor_player.poll() is None
        if was_playing:self.editor_stop_player()
        if play or was_playing:self.editor_play_at(self.editor_position)
        else:self.editor_status.set(f"Posición preparada: {self.editor_position:.1f} s.")

    def editor_play_disposition(self, disposition):
        if not self.editor_media:return
        if disposition=="":indexes=[i for i in range(len(self.editor_items)) if not self.editor_dispositions.get(i)]
        else:indexes=[i for i,v in self.editor_dispositions.items() if v==disposition]
        ranges=self.editor_ranges_from_indexes(indexes)
        if not ranges:messagebox.showwarning("VideoTools v48",f"No hay renglones con disposición {disposition or 'SIN MARCA'}.",parent=self);return
        self.editor_play_at(ranges[0][0],ranges[0][1]-ranges[0][0])

    def editor_play_at(self, start, length=None):
        self.editor_position=start
        self.editor_play(False,start,length)
    def editor_play(self, selection=False, start=None, length=None):
        if not self.editor_media or not self.editor_media.is_file():messagebox.showwarning("VideoTools v48","Primero carga un vídeo o audio.",parent=self);return
        try:player=binary("ffplay")
        except ProcessError:
            messagebox.showerror("VideoTools v48","No se encontró ffplay.exe. Colócalo junto a ffmpeg.exe para usar el reproductor.",parent=self);return
        self.editor_stop_player();self.editor_player_title=f"VideoTools Player {id(self)}";args=[player,"-hide_banner","-loglevel","error","-autoexit","-window_title",self.editor_player_title]
        if selection:
            ranges=self.editor_selected_ranges()
            if not ranges:messagebox.showwarning("VideoTools v48","Selecciona al menos una partida de subtítulo.",parent=self);return
            start,end=ranges[0];length=end-start
        if start is not None:args += ["-ss",f"{start:.3f}"]
        if length is not None:args += ["-t",f"{length:.3f}"]
        args.append(str(self.editor_media))
        try:self.editor_player=subprocess.Popen(args,creationflags=NO_WINDOW);self.editor_play_origin=start or 0.0;self.editor_play_started=time.monotonic();self.editor_playing=True;self.editor_paused=False;self.after(120,self.editor_embed_player);self.after(250,self.editor_tick_time);self.editor_status.set("Abriendo reproductor...")
        except OSError as error:messagebox.showerror("VideoTools v48",f"No se pudo abrir el reproductor: {error}",parent=self)
    def editor_probe_streams(self, source):
        try:
            probe=subprocess.run([binary("ffprobe"),"-v","error","-show_entries","stream=codec_type","-of","json",str(source)],capture_output=True,text=True,encoding="utf-8",errors="replace",check=True,creationflags=NO_WINDOW)
            kinds={item.get("codec_type") for item in json.loads(probe.stdout).get("streams",[])}
            return "video" in kinds,"audio" in kinds
        except Exception as error:raise ProcessError("E005",f"No se pudieron leer los streams de {source.name}: {error}")

    def editor_unique_output(self, suffix, extension):
        base=self.editor_media.with_name(f"{self.editor_media.stem}_{suffix}{extension}");number=2;result=base
        while result.exists():result=self.editor_media.with_name(f"{self.editor_media.stem}_{suffix}_{number}{extension}");number+=1
        return result

    def editor_srt_for_ranges(self, ranges):
        result=[];offset=0
        for start,end in ranges:
            for item in part_srt(self.editor_items,round(start*1000),round(end*1000)):
                result.append(Subtitle(item.start+round(offset*1000),item.end+round(offset*1000),item.text))
            offset += end-start
        return result

    def editor_ff(self, cmd, label, expected_seconds):
        self.events.put(("editor_status",label+"..."));cmd=cmd[:-1]+["-progress","pipe:1","-nostats","-loglevel","error",cmd[-1]]
        process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",bufsize=1,creationflags=NO_WINDOW);self.editor_process=process;last=-1
        while process.poll() is None:
            line=process.stdout.readline() if process.stdout else ""
            if line.startswith("out_time_ms=") and expected_seconds:
                try:percent=min(99,int(line.split("=",1)[1].strip())/(expected_seconds*1000000)*100)
                except ValueError:percent=0
                if int(percent)>last:last=int(percent);self.events.put(("editor_progress",label,percent))
            elif not line:time.sleep(0.15)
        _,errors=process.communicate();self.editor_process=None
        if process.returncode:raise ProcessError("E006",f"{label}: {errors[-1400:]}")
        self.events.put(("editor_progress",label,100));self.events.put(("editor_step",))

    def editor_render_ranges(self, ranges, suffix):
        """Exporta sin rebasar el límite de longitud de comandos de Windows.

        FFmpeg recibe un segmento por proceso y los une desde un archivo temporal de
        concat. Esto evita WinError 206 incluso con cientos de subtítulos marcados.
        """
        if not ranges:raise ProcessError("E010",f"No hay segmentos para exportar como {suffix}.")
        source=self.editor_media;has_video,has_audio=self.editor_probe_streams(source)
        if not has_video:raise ProcessError("E011","El editor por segmentos requiere un vídeo. Para un audio, primero genera su vídeo ligero con subtítulos desde la primera pestaña.")
        if not has_audio:raise ProcessError("E012","El vídeo no tiene pista de audio; aún no se puede unir desde este editor.")
        extension,_,tag,args,_=self.profile_spec_for_editor()
        output_suffix=suffix if suffix in {"RESUMEN","VANAL","ELIMINAR"} else suffix+"_"+tag
        out=self.editor_unique_output(output_suffix,extension)
        temp_dir=Path(tempfile.mkdtemp(prefix="videotools_editor_"))
        try:
            entries=[];total_seconds=sum(end-start for start,end in ranges)
            for number,(start,end) in enumerate(ranges,1):
                self.checkpoint()
                segment=temp_dir/f"segmento_{number:05d}.mkv"
                command=[binary("ffmpeg"),"-y","-ss",f"{start:.3f}","-t",f"{end-start:.3f}","-i",str(source),"-map","0:v:0","-map","0:a:0","-c:v","libx264","-pix_fmt","yuv420p","-preset","veryfast","-c:a","aac","-ar","48000","-ac","2",str(segment)]
                self.editor_ff(command,f"Preparando {suffix} {number}/{len(ranges)}",end-start)
                entries.append(segment)
            concat_file=temp_dir/"segmentos.txt"
            def concat_name(path):return path.resolve().as_posix().replace("'","'\\''")
            concat_file.write_text("".join(f"file '{concat_name(path)}'\n" for path in entries),encoding="utf-8")
            command=[binary("ffmpeg"),"-y","-f","concat","-safe","0","-i",str(concat_file),"-map","0:v:0","-map","0:a:0",*args,str(out)]
            self.editor_ff(command,f"Uniendo {suffix}",total_seconds)
        finally:
            shutil.rmtree(temp_dir,ignore_errors=True)
        srt_items=self.editor_srt_for_ranges(ranges)
        if srt_items:write_srt(out.with_suffix(".srt"),srt_items)
        return out

    def profile_spec_for_editor(self):
        name=self.editor_profile.get();extension,tag,args,limit=CONVERSION_PROFILES.get(name,next(iter(CONVERSION_PROFILES.values())))
        if "-vn" in args:raise ProcessError("E013","Elige un formato de vídeo para editar segmentos.")
        return extension,name.split(" · ",1)[0],tag,args,limit

    def editor_export(self, mode):
        if self.editor_busy:messagebox.showinfo("VideoTools v48","Ya hay una exportación en curso.",parent=self);return
        if self.active_process is not None or self.start.cget("state")=="disabled":messagebox.showwarning("VideoTools v48","Espera a que termine la cola principal antes de editar segmentos.",parent=self);return
        if not self.editor_media or not self.editor_media.is_file():messagebox.showwarning("VideoTools v48","Carga primero un vídeo.",parent=self);return
        selected=self.editor_selected_ranges()
        if not selected:messagebox.showwarning("VideoTools v48","Selecciona una o más partidas del SRT.",parent=self);return
        try:total=duration(self.editor_media)
        except ProcessError as error:messagebox.showerror("VideoTools v48",str(error),parent=self);return
        selected=[(max(0,start),min(total,end)) for start,end in selected if end>0 and start<total]
        if not selected:messagebox.showwarning("VideoTools v48","La selección está fuera de la duración del vídeo.",parent=self);return
        self.editor_busy=True
        for widget in (self.editor_extract_button,self.editor_keep_button,self.editor_both_button):widget.configure(state="disabled")
        self.editor_status.set("Preparando exportación por segmentos...")
        threading.Thread(target=self.editor_export_worker,args=(mode,selected,total),daemon=True).start()

    def editor_export_worker(self, mode, selected, total):
        try:
            outputs=[]
            if mode in {"selected","both"}:outputs.append(self.editor_render_ranges(selected,"eliminar"))
            if mode in {"keep","both"}:outputs.append(self.editor_render_ranges(self.editor_complement_ranges(selected,total),"conservar"))
            self.events.put(("editor_done",tuple(outputs)))
        except Exception as error:self.events.put(("editor_failed",str(error)))
    def editor_process_all(self):
        if self.editor_busy:messagebox.showinfo("VideoTools v48","Ya hay un proceso en curso.",parent=self);return
        if self.editor_jobs:
            self.editor_save_active_job();self.editor_batch=[{"media":j["media"],"items":j["items"],"dispositions":dict(j["dispositions"])} for j in self.editor_jobs]
        elif self.editor_media and self.editor_items:self.editor_batch=[{"media":self.editor_media,"items":self.editor_items,"dispositions":dict(self.editor_dispositions)}]
        else:messagebox.showwarning("VideoTools v48","Añade al menos un vídeo y su SRT válido.",parent=self);return
        self.editor_busy=True;self.editor_jobs_progress["value"]=0
        for widget in (self.editor_extract_button,self.editor_keep_button,self.editor_both_button,self.editor_add_job_button):widget.configure(state="disabled")
        threading.Thread(target=self.editor_process_worker,daemon=True).start()

    def editor_process_worker(self):
        try:
            outputs=[];total=len(self.editor_batch)
            for position,job in enumerate(self.editor_batch,1):
                self.editor_media=job["media"];self.editor_items=job["items"];self.editor_dispositions=job["dispositions"]
                groups=(("RESUMEN",self.editor_ranges_for("RESUMEN")),("VANAL",self.editor_ranges_from_indexes([i for i in range(len(self.editor_items)) if not self.editor_dispositions.get(i)])),("ELIMINAR",self.editor_ranges_for("ELIMINAR")))
                self.events.put(("editor_plan",sum(len(ranges)+1 for _,ranges in groups if ranges)))
                for number,(name,ranges) in enumerate(groups,1):
                    self.events.put(("editor_status",f"Vídeo {position}/{total}: {name}, etapa {number}/3."))
                    if ranges:outputs.append(self.editor_render_ranges(ranges,name))
                self.events.put(("editor_batch_progress",position,total))
            self.events.put(("editor_done",tuple(outputs)))
        except Exception as error:self.events.put(("editor_failed",str(error)))
    def build_stages(self, has_es=None, has_en=None):
        if self.translate_only.get() or getattr(self,"run_has_direct_srt",False):
            names=(("translate_model","CARGAR ARGOS TRANSLATE"),("translate","TRADUCIR ARCHIVO"))
        elif self.transcribe_only.get():
            names=[]
            if self.convert.get(): names.append(("convert", f"CONVERTIR: {self.profile_spec()[1]}"))
            if self.engine_name.get().startswith("Vosk"):
                names += (("model", "PREPARAR MODELO VOSK"), ("audio", "EXTRAER AUDIO WAV"), ("transcribe", "TRANSCRIBIR CON VOSK"), ("srt", "GENERAR ARCHIVO SRT"))
            else:
                names += (("model", "CARGAR MODELO IA"), ("audio", "ANALIZAR AUDIO"), ("transcribe", "TRANSCRIBIR AUDIO"), ("srt", "GENERAR ARCHIVO SRT"))
        else:
            if has_es is None: has_es=any(j.spanish for j in self.jobs.values())
            if has_en is None: has_en=any(j.english for j in self.jobs.values())
            names=[]
            if self.burn.get(): names.append(("burn", "QUEMAR SUBTÍTULOS"))
            if self.convert.get(): names.append(("convert", f"CONVERTIR: {self.profile_spec()[1]}"))
            if not (self.convert.get() and self.profile_is_audio(self.conversion_profile.get())):names.append(("video", "DIVIDIR VÍDEO"))
            if has_es: names.append(("es", "DIVIDIR SRT ES"))
            if has_en: names.append(("en", "DIVIDIR SRT EN"))
        for w in self.stage_frame.winfo_children(): w.destroy()
        self.stage_widgets={}
        for key,text in names:
            w=tk.Label(self.stage_frame,text=text,bg="#E7E6E6",fg="#333333",padx=8,pady=4,relief="groove");w.pack(side="left",padx=(0,5));self.stage_widgets[key]=w
    def build_run_stages(self, mode, has_es=False, has_en=False):
        """Muestra las etapas del renglón actual sin alterar las opciones congeladas de la cola."""
        if mode=="pdf":
            names=[("translate_model","CARGAR ARGOS TRANSLATE"),("translate","TRADUCIR PDF")]
        elif mode=="translate":
            names=[("translate_model","CARGAR ARGOS TRANSLATE"),("translate","TRADUCIR SRT")]
        elif mode in {"srt","audio"}:
            names=[]
            if self.run_convert:names.append(("convert",f"CONVERTIR: {self.profile_spec(True)[1]}"))
            if self.run_engine=="vosk":names += [("model","PREPARAR MODELO VOSK"),("audio","EXTRAER AUDIO WAV"),("transcribe","TRANSCRIBIR CON VOSK"),("srt","GENERAR ARCHIVO SRT")]
            else:names += [("model","CARGAR MODELO IA"),("audio","ANALIZAR AUDIO"),("transcribe","TRANSCRIBIR AUDIO"),("srt","GENERAR ARCHIVO SRT")]
            if mode=="audio":names.append(("preview","CREAR VÍDEO LIGERO CON SUBTÍTULOS"))
        else:
            names=[]
            if self.run_burn:names.append(("burn","QUEMAR SUBTÍTULOS"))
            if self.run_convert:names.append(("convert",f"CONVERTIR: {self.profile_spec(True)[1]}"))
            if not (self.run_convert and self.profile_is_audio(self.run_conversion_profile)):names.append(("video","DIVIDIR VÍDEO"))
            if has_es:names.append(("es","DIVIDIR SRT ES"))
            if has_en:names.append(("en","DIVIDIR SRT EN"))
        for w in self.stage_frame.winfo_children():w.destroy()
        self.stage_widgets={}
        for key,text in names:
            w=tk.Label(self.stage_frame,text=text,bg="#E7E6E6",fg="#333333",padx=8,pady=4,relief="groove");w.pack(side="left",padx=(0,5));self.stage_widgets[key]=w
    def refresh_error_tip(self):
        if any(j.status.startswith("ERROR") for j in self.jobs.values()):
            self.tree_tip.text="Errores presentes en la lista.\n\n"+ERROR_HELP
        else:
            self.tree_tip.text="Lista de vídeos. El detalle de códigos aparece aquí solo si existe un ERROR."
    def reset_stages(self):
        for w in self.stage_widgets.values():w.configure(bg="#E7E6E6",fg="#333333")
    def stage_work(self,key):
        if key in self.stage_widgets:self.stage_widgets[key].configure(bg="#FFEB9C",fg="#7F6000")
    def stage_ok(self,key):
        if key in self.stage_widgets:self.stage_widgets[key].configure(bg="#C6EFCE",fg="#006100")
    def engine_changed(self):
        vosk=self.engine_name.get().startswith("Vosk")
        if vosk and self.audio_language.get()=="Auto": self.audio_language.set("Español")
        self.model_box.pack_forget() if vosk else self.model_box.pack(side="left",padx=(8,2))
        self.build_stages()
    def update_conversion_mode(self):
        self.profile_box.configure(state="readonly" if self.convert.get() else "disabled")
        self.build_stages()
    def profile_spec(self,running=False):
        name=getattr(self,"run_conversion_profile",None) if running else self.conversion_profile.get()
        name=name or next(iter(CONVERSION_PROFILES))
        extension,tag,args,limit=CONVERSION_PROFILES.get(name,next(iter(CONVERSION_PROFILES.values())))
        return extension,name.split(" · ",1)[0],tag,args,limit
    def conversion_args(self,source,parts,running=False):
        _,_,_,args,limit=self.profile_spec(running)
        return [*args,*(self.encode_options(source,parts) if limit else [])]
    def update_translate_visibility(self):
        show=any(j.spanish or j.english for j in self.jobs.values())
        if show and not self.translate_box.winfo_manager(): self.translate_box.pack(side="left",padx=12)
        if not show and self.translate_box.winfo_manager(): self.translate_only.set(False);self.translate_box.pack_forget()
    def update_translate_mode(self):
        only=self.translate_only.get()
        if only:
            self.transcribe_only.set(False);self.convert.set(False);self.burn.set(False)
            for w in (self.parts_label,self.part_input,self.conv,self.profile_box,self.burn_box,self.srt_only_box,self.engine_box,self.model_box,self.lang_box,self.es,self.en,self.add): w.pack_forget()
            self.start.configure(text="Traducir SRT y PDF de renglones en espera")
        else:
            self.add.pack(side="left");self.profile_box.pack(side="left",padx=(2,8),before=self.burn_box);self.update_srt_mode();self.update_conversion_mode()
        self.build_stages()
    def update_srt_mode(self):
        only=self.transcribe_only.get()
        if only:
            self.convert.set(False)
            for w in (self.parts_label,self.part_input,self.burn_box,self.es,self.en):w.pack_forget()
            self.conv.pack(side="left",padx=12);self.engine_box.pack(side="left",padx=(8,2));self.model_box.pack(side="left",padx=(2,2));self.lang_box.pack(side="left",padx=2);self.engine_changed();self.start.configure(text="Generar SRT de renglones en espera")
        else:
            self.parts_label.pack(side="left");self.part_input.pack(side="left",padx=8);self.conv.pack(side="left",padx=12)
            self.burn_box.pack(side="left",padx=12)
            self.es.pack(side="left",padx=6);self.en.pack(side="left");self.engine_box.pack_forget();self.model_box.pack_forget();self.lang_box.pack_forget();self.start.configure(text="Procesar renglones en espera")
        self.build_stages()
    def update_audiobook_mode(self):
        if self.audiobook_mode.get():
            self.audiobook_button.pack(side="left",padx=(14,0));self.start.configure(text="INICIAR AUDIOLIBROS DE PDFs")
        else:
            self.audiobook_button.pack_forget();self.start.configure(text="Procesar renglones en espera")
    def auto(self,v):
        f,s=v.parent,v.stem;es=next((x for x in (f/f"{s}.srt",f/f"{s}_es.srt",f/f"{s}_spanish.srt") if x.is_file()),None);en=next((x for x in (f/f"{s}_en.srt",f/f"{s}_english.srt") if x.is_file()),None);return es,en
    def estimate_parts(self, video):
        """Calcula antes de convertir usando el tamaño del archivo y margen de seguridad."""
        try: return max(1, math.ceil(video.stat().st_size / SAFE_PART_BYTES))
        except OSError: return 1
    def on_select(self, _event=None):
        if self.clearing:return
        k=self.selected()
        if k:
            j=self.jobs[k]
            if j.video.suffix.casefold() in {".pdf",".srt"} or is_audio(j.video):
                kind="PDF" if j.video.suffix.casefold()==".pdf" else "SRT" if j.video.suffix.casefold()==".srt" else "AUDIO"
                self.parts.set(1);self.status.set(f"{j.video.name}: {kind}; se traducirá automáticamente al llegar su turno.");return
            if not j.manual_parts: j.parts=self.estimate_parts(j.video);self.refresh(k)
            self.parts.set(j.parts);mode="manual" if j.manual_parts else "automática"
            self.status.set(f"{j.video.name}: {j.parts} parte(s), configuración {mode}.")
    def set_manual_parts(self):
        k=self.tree.selection()
        if not k:return
        j=self.jobs[k[0]]
        if j.video.suffix.casefold() in {".pdf",".srt"}:messagebox.showinfo("VideoTools v48","Los PDF y SRT no se dividen en partes.",parent=self);return
        try:value=max(1,int(self.parts.get()))
        except (ValueError,tk.TclError):messagebox.showwarning("VideoTools v48","Indica un número válido.",parent=self);return
        j.parts=value;j.manual_parts=True;self.parts.set(value);self.refresh(k[0]);self.status.set(f"{j.video.name}: partes manuales = {value}.")
    def values(self,j):return(j.status,j.video.name,"—" if j.video.suffix.casefold() in {".pdf",".srt"} or is_audio(j.video) else j.parts,str(j.video.parent),j.spanish.name if j.spanish else "—",j.english.name if j.english else "—")
    def refresh(self,k):
        j=self.jobs[k];tag={"OK":"ok","PROCESANDO":"working"}.get(j.status,"error" if j.status.startswith("ERROR") else "");self.tree.item(k,values=self.values(j),tags=(tag,) if tag else ())
    def add_paths(self,paths):
        for x in paths:
            v=Path(x);self.n+=1;k=str(self.n)
            if v.suffix.casefold()==".pdf":self.jobs[k]=Job(v,parts=1,manual_parts=True)
            elif v.suffix.casefold()==".srt":self.jobs[k]=Job(v,parts=1,manual_parts=True,direct_srt=True)
            elif v.suffix.casefold()==".url":
                link=url_from_shortcut(v);self.jobs[k]=Job(v,status="ESPERA" if link and is_youtube_url(link) else "PÁGINA",parts=1,manual_parts=True,youtube_url=link if link and is_youtube_url(link) else None)
            elif is_audio(v):self.jobs[k]=Job(v,parts=1,manual_parts=True)
            else:
                es,en=self.auto(v);self.jobs[k]=Job(v,es,en,parts=self.estimate_parts(v))
            self.tree.insert("","end",iid=k,values=self.values(self.jobs[k]))
        self.update_burn();self.update_translate_visibility()
    def add_videos(self):self.add_paths(filedialog.askopenfilenames(title="Añade vídeo, PDF o SRT",filetypes=VIDEO_TYPES))
    def drop_files(self,event):self.add_paths(self.tk.splitlist(event.data));self.status.set("Archivo(s) añadido(s) al arrastrar a la lista.");return "break"
    def add_pdfs(self):
        for x in filedialog.askopenfilenames(title="Añade PDF(s) con texto seleccionable",filetypes=PDF_TYPES):
            v=Path(x);self.n+=1;k=str(self.n);self.jobs[k]=Job(v,parts=1,manual_parts=True);self.tree.insert("","end",iid=k,values=self.values(self.jobs[k]))
    def keep_awake(self, enabled):
        """Evita la suspensión automática de Windows mientras hay una cola activa."""
        if os.name != "nt": return
        try:
            flags = 0x80000000 | (0x00000001 if enabled else 0)
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
            self.preventing_sleep = enabled
        except Exception: pass
    def on_close(self):
        active = self.active_process is not None or self.editor_process is not None or self.editor_busy or self.start.cget("state") == "disabled"
        text = "¿Deseas cerrar VideoTools?"
        if active: text += "\n\nHay procesos en ejecución. Se detendrán y los renglones restantes quedarán en ESPERA."
        if not messagebox.askyesno("Cerrar VideoTools v48", text,parent=self): return
        if active:
            self.stop_queue();self.editor_stop_player()
            if self.editor_process and self.editor_process.poll() is None:
                try:self.editor_process.terminate()
                except OSError:pass
            self.after(400, self.finish_close)
        else: self.keep_awake(False);self.destroy()
    def finish_close(self):
        p = self.active_process or self.editor_process
        if p and p.poll() is None:
            try: p.terminate()
            except OSError: pass
            self.after(300, self.finish_close); return
        self.keep_awake(False)
        self.destroy()
    def selected(self):
        x=self.tree.selection()
        if not x:return None
        return x[0]
    def assign(self,language):
        k=self.selected()
        if k and self.jobs[k].video.suffix.casefold() in {".pdf",".srt"}:messagebox.showinfo("VideoTools v48","Los SRT solo pueden asociarse a un renglón de vídeo.",parent=self);return
        if k and (x:=filedialog.askopenfilename(title="Selecciona SRT",filetypes=SRT_TYPES)):setattr(self.jobs[k],language,Path(x));self.refresh(k);self.update_burn();self.update_translate_visibility()
    def update_burn(self):
        show=any(j.spanish and j.english for j in self.jobs.values())
        if show and not self.burn_box.winfo_manager():self.burn_box.pack(side="left",padx=12)
        if not show and self.burn_box.winfo_manager():self.burn.set(False);self.burn_box.pack_forget()
    def remove_job(self):
        if(k:=self.selected()):self.tree.delete(k);self.jobs.pop(k,None);self.update_burn();self.update_translate_visibility();self.refresh_error_tip()
    def clear_jobs(self):
        if not self.jobs:return
        if not messagebox.askyesno("VideoTools v48","¿Vaciar cola?",parent=self):return
        self.clearing=True
        try:
            self.tree.selection_remove(self.tree.selection());self.tree.delete(*self.tree.get_children());self.jobs.clear();self.update_burn();self.update_translate_visibility();self.refresh_error_tip();self.status.set("Cola vacía.")
        finally:
            self.clearing=False
        self.focus_set()
    def controls(self, state):
        for x in (self.add,self.es,self.en,self.remove,self.clear,self.start,self.part_input,self.conv,self.burn_box,self.srt_only_box,self.translate_box,self.audiobook_mode_box,self.audiobook_button):x.configure(state=state)
        combo_state="readonly" if state=="normal" else "disabled"
        for x in (self.translate_choice_box,self.engine_box,self.model_box,self.lang_box):x.configure(state=combo_state)
        self.profile_box.configure(state=combo_state if self.convert.get() else "disabled")
        if state == "normal":
            self.keep_awake(False)
            self.start.configure(text="INICIAR PROCESOS EN ARCHIVOS",bg="#FFF2CC",activebackground="#FFE699")
            self.pause_button.configure(state="disabled", text="Pausar")
            self.stop_button.configure(state="disabled")
    def toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear(); self.pause_button.configure(text="Pausar"); self.status.set("Cola reanudada.")
        else:
            self.pause_event.set(); self.pause_button.configure(text="Reanudar"); self.status.set("Pausa solicitada: se aplicará al terminar la etapa actual.")
    def stop_queue(self):
        self.stop_event.set(); self.pause_event.clear(); self.pause_button.configure(state="disabled")
        if self.active_process and self.active_process.poll() is None:
            try: self.active_process.terminate()
            except OSError: pass
        self.status.set("Detención solicitada...")
    def checkpoint(self):
        while self.pause_event.is_set():
            if self.stop_event.is_set(): raise StopRequested()
            time.sleep(0.2)
        if self.stop_event.is_set(): raise StopRequested()
    def start_queue(self):
        if self.audiobook_mode.get():
            self.start_audiobook_batch();return
# El modo se congela antes de iniciar el hilo; SRT offline nunca ejecuta división.
        self.run_srt_only=self.transcribe_only.get();self.run_translate=self.translate_only.get()
        self.run_convert=self.convert.get();self.run_conversion_profile=self.conversion_profile.get();self.run_burn=self.burn.get();self.run_translation_choice=self.translation_choice.get()
        self.run_engine="vosk" if self.engine_name.get().startswith("Vosk") else "whisper"
        self.run_model=self.model_name.get()
        self.run_language={"Auto":None,"Inglés":"en","Español":"es"}[self.audio_language.get()]
        keys=[k for k in self.tree.get_children() if self.jobs[k].status=="ESPERA"]
        self.run_has_direct_srt=any(self.jobs[k].direct_srt or self.jobs[k].video.suffix.casefold()==".srt" for k in keys)
        try:
            if not keys:raise ValueError("No hay renglones en ESPERA.")
            video_keys=[k for k in keys if is_video(self.jobs[k].video)]
            srt_keys=[k for k in keys if is_audio(self.jobs[k].video) or (is_video(self.jobs[k].video) and self.run_srt_only)]
            if not self.run_translate and any(self.jobs[k].parts<1 for k in video_keys):raise ValueError("No se pudo calcular el número de partes.")
            if srt_keys and self.run_engine=="vosk" and self.run_language is None:raise ValueError("Vosk requiere elegir Español o Inglés.")
        except Exception as e:messagebox.showerror("VideoTools v48",str(e),parent=self);return
        self.build_stages(any(self.jobs[k].spanish for k in keys),any(self.jobs[k].english for k in keys));self.bar["value"]=0;self.stop_event.clear();self.pause_event.clear();self.start.configure(text="CORRIENDO PROCESOS EN ARCHIVOS",bg="#B7C98A",activebackground="#A6B879");self.pause_button.configure(state="normal",text="Pausar");self.stop_button.configure(state="normal");self.controls("disabled");self.keep_awake(True);self.addlog("Protección contra suspensión automática activada mientras la cola está en ejecución.\n");threading.Thread(target=self.queue_run,args=(keys,),daemon=True).start()
    def validate(self,j):
        if j.youtube_url:self.download_youtube_subtitles(j);return
        if j.video.suffix.casefold()==".pdf":
            if not j.video.is_file():raise ProcessError("R201",f"No existe el PDF: {j.video}")
            return
        if j.direct_srt or j.video.suffix.casefold()==".srt":
            if not j.video.is_file():raise ProcessError("R101",f"No existe el SRT: {j.video}")
            return
        if not self.run_translate and not j.video.is_file():raise ProcessError("E001",f"No existe el medio: {j.video}")
        if j.spanish and not j.spanish.is_file():raise ProcessError("E002",f"No existe el SRT español: {j.spanish}")
        if j.english and not j.english.is_file():raise ProcessError("E003",f"No existe el SRT inglés: {j.english}")
    def ff(self, cmd, label):
        self.checkpoint(); self.events.put(("log", label + "...\n"))
        source=next((Path(cmd[index+1]) for index,value in enumerate(cmd[:-1]) if value=="-i"),None)
        try: total_ms=max(1,int(duration(source)*1000)) if source else None
        except Exception: total_ms=None
        cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats", "-loglevel", "error", cmd[-1]]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW)
        self.active_process = p
        last_percent=-1
        while p.poll() is None:
            if self.stop_event.is_set():
                try: p.terminate()
                except OSError: pass
                p.communicate(); self.active_process = None; raise StopRequested()
            line=p.stdout.readline() if p.stdout else ""
            if line.startswith("out_time_ms=") and total_ms:
                try: percent=min(99,int(line.split("=",1)[1].strip())/(total_ms*1000)*100)
                except ValueError: percent=0
                if int(percent)>last_percent:
                    last_percent=int(percent);self.events.put(("progress",label,percent))
            elif not line:time.sleep(0.15)
        _, errors = p.communicate(); self.active_process = None
        if p.returncode: raise ProcessError("E006", f"{label}: {errors[-1400:]}")
        if total_ms:self.events.put(("progress",label,100))
        self.checkpoint()
    def configure_argos(self):
        bundled=app_dir() / "argos_models"
        if bundled.is_dir(): argostranslate.settings.package_data_dir=bundled
    def model_directory(self):
        # Prioriza modelos distribuidos junto al EXE; si no existen usa el caché local.
        bundled=app_dir() / "models"
        if bundled.is_dir(): return bundled
        root = Path(os.environ.get("LOCALAPPDATA", str(app_dir()))) / "VideoTools" / "models"
        root.mkdir(parents=True, exist_ok=True); return root
    def vosk_directory(self, language):
        name = "vosk-model-small-es-0.42" if language=="es" else "vosk-model-small-en-us-0.15"
        root=self.model_directory() / "vosk"; target=root/name
        if target.is_dir(): return target
        root.mkdir(parents=True,exist_ok=True); archive=root/(name+".zip")
        try:
            self.events.put(("log",f"Descargando modelo Vosk {language}; se conservará para uso offline...\n"))
            urllib.request.urlretrieve(f"https://alphacephei.com/vosk/models/{name}.zip", archive)
            with zipfile.ZipFile(archive) as z: z.extractall(root)
            archive.unlink(missing_ok=True)
        except Exception as e:
            raise ProcessError("V102",str(e))
        if not target.is_dir(): raise ProcessError("V102",f"No se encontró la carpeta {name} después de descargarla.")
        return target
    def generate_vosk_srt(self, job):
        self.events.put(("stage_start","model"))
        try:
            from vosk import KaldiRecognizer, Model
            if self.run_language not in self.vosk_models: self.vosk_models[self.run_language]=Model(str(self.vosk_directory(self.run_language)))
        except ProcessError: raise
        except Exception as e: raise ProcessError("V101",str(e))
        self.events.put(("stage","model")); temp=job.video.with_name(job.video.stem+"_videotools_vosk.wav")
        try:
            self.events.put(("stage_start","audio"));self.ff([binary("ffmpeg"),"-y","-i",str(job.video),"-vn","-ac", "1","-ar","16000","-f","wav",str(temp)],"Extrayendo audio para Vosk");self.events.put(("stage","audio"))
        except ProcessError as e: raise ProcessError("V103",str(e))
        try:
            self.events.put(("stage_start","transcribe"));rec=KaldiRecognizer(self.vosk_models[self.run_language],16000);rec.SetWords(True); words=[]
            with wave.open(str(temp),"rb") as wav:
                total_frames=max(1,wav.getnframes());last_percent=-1
                while True:
                    self.checkpoint(); data=wav.readframes(4000)
                    if not data: break
                    if rec.AcceptWaveform(data): words += json.loads(rec.Result()).get("result",[])
                    percent=int(wav.tell()/total_frames*100)
                    if percent>=last_percent+5:last_percent=percent;self.events.put(("progress","Transcribiendo audio (Vosk)",percent))
                words += json.loads(rec.FinalResult()).get("result",[])
            self.events.put(("progress","Transcribiendo audio (Vosk)",100))
            self.events.put(("stage","transcribe"))
        except Exception as e: raise ProcessError("V104",str(e))
        finally:
            try: temp.unlink(missing_ok=True)
            except OSError: pass
        items=[]; group=[]
        for word in words:
            if group and (len(group)>=10 or word["start"]-group[-1]["end"]>1.25):
                items.append(Subtitle(round(group[0]["start"]*1000),round(group[-1]["end"]*1000)," ".join(x["word"] for x in group)));group=[]
            group.append(word)
        if group: items.append(Subtitle(round(group[0]["start"]*1000),round(group[-1]["end"]*1000)," ".join(x["word"] for x in group)))
        if not items: raise ProcessError("T105","Vosk no detectó diálogo transcribible.")
        self.events.put(("stage_start","srt")); suffix=self.run_language;out=job.video.with_name(f"{job.video.stem}_{suffix}.srt")
        try: write_srt(out,items)
        except Exception as e: raise ProcessError("T104",str(e))
        self.events.put(("log",f"SRT Vosk generado ({suffix}): {len(items)} subtítulos.\n"));self.events.put(("stage","srt"));return out
    def create_audio_subtitle_video(self, audio, srt):
        out=self.unique_output(audio,"subtitulos",".mp4")
        style="FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H000000&,Outline=2,Alignment=2,MarginV=26"
        vf=f"[1:v]subtitles=filename='{filter_path(srt)}':force_style='{style}'[video]"
        self.events.put(("stage_start","preview"))
        self.ff([binary("ffmpeg"),"-y","-i",str(audio),"-f","lavfi","-i","color=c=#101820:s=640x360:r=25","-filter_complex",vf,"-map","[video]","-map","0:a:0","-shortest","-c:v","libx264","-preset","veryfast","-crf","28","-pix_fmt","yuv420p","-c:a","aac","-b:a","96k","-movflags","+faststart",str(out)],"Creando vídeo ligero con subtítulos")
        self.events.put(("stage","preview"));self.events.put(("log",f"Vídeo ligero creado para revisar subtítulos: {out.name}\n"));return out
    def generate_srt(self, job):
        if self.run_engine=="vosk": return self.generate_vosk_srt(job)
        try:
            self.events.put(("stage_start", "model"))
            if self.run_model not in self.whisper_models:
                from faster_whisper import WhisperModel
                self.events.put(("log", f"Cargando modelo offline {self.run_model}. Si es la primera vez se descargará una sola vez...\n"))
                try: self.whisper_models[self.run_model] = WhisperModel(self.run_model, device="cpu", compute_type="int8", download_root=str(self.model_directory()))
                except Exception as e: raise ProcessError("T101", str(e))
            self.events.put(("stage", "model"));self.events.put(("stage_start", "audio"))
            try: segments, info = self.whisper_models[self.run_model].transcribe(str(job.video), language=self.run_language, vad_filter=True, beam_size=5)
            except Exception as e: raise ProcessError("T102", str(e))
            self.events.put(("stage", "audio"));self.events.put(("stage_start", "transcribe"))
            try:
                items=[];total_duration=max(0.0,float(getattr(info,"duration",0) or 0));last_percent=-1
                for x in segments:
                    if x.text.strip():items.append(Subtitle(round(x.start*1000),round(x.end*1000),x.text.strip()))
                    if total_duration:
                        percent=min(99,int(x.end/total_duration*100))
                        if percent>=last_percent+5:last_percent=percent;self.events.put(("progress","Transcribiendo audio",percent))
                if total_duration:self.events.put(("progress","Transcribiendo audio",100))
            except Exception as e: raise ProcessError("T103", str(e))
            self.events.put(("stage", "transcribe"))
            if not items: raise ProcessError("T105", "No se detectó diálogo transcribible.")
            self.events.put(("stage_start", "srt"));suffix = self.run_language or getattr(info, "language", "auto") or "auto"
            out=job.video.with_name(f"{job.video.stem}_{suffix}.srt")
            try: write_srt(out, items)
            except Exception as e: raise ProcessError("T104", str(e))
            self.events.put(("log", f"SRT generado con idioma {suffix}: {len(items)} subtítulos.\n")); self.events.put(("stage", "srt")); return out
        except ProcessError: raise
        except Exception as e: raise ProcessError("T103", str(e))
    def encode_options(self, source, parts):
        """Bitrate conservador para que un fragmento convertido permanezca bajo 134 MB."""
        try: seconds=max(1.0,duration(source)/max(1,parts))
        except ProcessError: return []
        video_bps=max(250000,int(((MAX_PART_BYTES*8/seconds)-128000)*0.90))
        kbps=max(250,video_bps//1000)
        return ["-b:v",f"{kbps}k","-maxrate",f"{kbps}k","-bufsize",f"{kbps*2}k"]
    def unique_output(self,source,language,extension):
        out=source.with_name(f"{source.stem}_{language}{extension}")
        number=2
        while out.exists():out=source.with_name(f"{source.stem}_{language}_{number}{extension}");number+=1
        return out
    def argos_translator(self,from_code,to_code,error_code):
        if (from_code,to_code)==("es","en"):return type("HelsinkiSpanishEnglish",(),{"translate":lambda _self,text:self.translate_es_en(text)})()
        self.configure_argos()
        try:
            languages={x.code:x for x in argostranslate.translate.get_installed_languages()}
            src=languages[from_code];dst=languages[to_code];translator=src.get_translation(dst)
            if translator is None:raise LookupError("traducción no instalada")
            return translator
        except Exception as e:raise ProcessError(error_code,f"Falta el modelo Argos {from_code}->{to_code}: {e}")
    def translate_es_en(self,text):
        folder=app_dir()/"models"/"es_en_hf"
        try:
            if self.es_en_hf is None:
                from transformers import AutoModelForSeq2SeqLM,AutoTokenizer
                if not folder.is_dir():raise FileNotFoundError(folder)
                self.events.put(("log","Cargando modelo neuronal ES-EN offline...\n"));self.es_en_hf=(AutoTokenizer.from_pretrained(folder,local_files_only=True),AutoModelForSeq2SeqLM.from_pretrained(folder,local_files_only=True))
            tokenizer,model=self.es_en_hf;chunks=[];current=""
            for part in re.split(r"(?<=[.!?])\s+",text):
                if current and len(current)+len(part)>850:chunks.append(current);current=""
                current=(current+" "+part).strip()
            if current:chunks.append(current)
            result=[]
            for chunk in chunks or [text]:
                self.checkpoint();encoded=tokenizer(chunk,return_tensors="pt",truncation=True,max_length=512);output=model.generate(**encoded,max_new_tokens=512);result.append(tokenizer.decode(output[0],skip_special_tokens=True))
            return "\n".join(result)
        except Exception as e:raise ProcessError("R202",f"Modelo ES-EN: {e}")
    def pdf_direction(self,text):
        if self.run_translation_choice=="ES → EN":return "es","en"
        if self.run_translation_choice=="EN → ES":return "en","es"
        tokens=re.findall(r"[a-záéíóúüñ]+",text.casefold())
        spanish={"el","la","los","las","de","del","que","y","en","para","por","con","una","un","es","como","su","se","al","más"}
        english={"the","of","and","to","in","for","is","with","that","this","from","as","by","an","are","on","it","or","be"}
        es_score=sum(word in spanish for word in tokens)+3*len(re.findall(r"[áéíóúüñ¿¡]",text.casefold()))
        en_score=sum(word in english for word in tokens)
        return ("es","en") if es_score>en_score else ("en","es")
    def translation_issue(self,source,translated):
        source_clean=re.sub(r"\s+"," ",source).strip();target_clean=re.sub(r"\s+"," ",translated).strip()
        if not target_clean:return "el traductor devolvió texto vacío"
        if len(target_clean)>max(280,len(source_clean)*7+80):return "la salida es desproporcionadamente larga"
        words=re.findall(r"[\wáéíóúüñ]+",target_clean.casefold())
        if len(words)>=20 and max(words.count(word) for word in set(words))/len(words)>0.55:
            return "se detectó repetición anómala"
        return None
    def ensure_reasonable_translation(self,source,translated,label):
        if issue:=self.translation_issue(source,translated):raise ProcessError("R104",f"{label}: {issue}.")
        return translated.strip()
    def distribute_srt_translation(self,translated,batch):
        """Reparte una traducción contextual entre las partidas, sin alterar sus tiempos."""
        words=re.findall(r"\S+",translated.strip())
        if not words:return [item.text for _,item in batch]
        weights=[max(1,len(re.findall(r"\S+",item.text))) for _,item in batch]
        total=sum(weights);result=[];start=0;accumulated=0
        for position,(_,item) in enumerate(batch):
            accumulated+=weights[position]
            end=len(words) if position==len(batch)-1 else round(len(words)*accumulated/total)
            remaining_items=len(batch)-position-1
            end=max(start,min(end,len(words)-remaining_items))
            chunk=" ".join(words[start:end]).strip()
            result.append(chunk or item.text)
            start=end
        return result
    def translate_srt_items(self,items,translator):
        """Traduce cada partida manteniendo sus tiempos; nunca guarda el original como si fuera traducción."""
        result=[]
        for index,item in enumerate(items,1):
            self.checkpoint()
            try:text=translator.translate(item.text).strip()
            except ProcessError:raise
            except Exception as error:raise ProcessError("R103",f"Subtítulo {index}: {error}")
            if issue:=self.translation_issue(item.text,text):
                raise ProcessError("R104",f"Subtítulo {index}: {issue}. No se guardó un SRT sin traducir.")
            result.append(Subtitle(item.start,item.end,text))
            if index==1 or index%25==0 or index==len(items):
                self.events.put(("log",f"SRT: traducidas {index}/{len(items)} partidas.\\n"))
        return result

    def translate_srt(self,job):
        targets=[]
        if job.direct_srt:
            direct_items=read_srt(job.video)
            if not direct_items:raise ProcessError("R101",f"{job.video.name} no contiene subtítulos válidos.")
            from_code,to_code=self.pdf_direction("\n".join(item.text for item in direct_items[:120]))
            targets.append((job.video,from_code,to_code,direct_items))
        else:
            if job.spanish:targets.append((job.spanish,"es","en",None))
            if job.english:targets.append((job.english,"en","es",None))
        if not targets:raise ProcessError("R101","No hay un SRT en la columna español ni en la columna inglés.")
        if len(targets)>1 and self.run_translation_choice=="ES → EN":targets=targets[:1]
        elif len(targets)>1 and self.run_translation_choice=="EN → ES":targets=targets[1:]
        created=[]
        for source,from_code,to_code,known_items in targets:
            self.checkpoint();self.events.put(("stage_start","translate_model"));translator=self.argos_translator(from_code,to_code,"R102");self.events.put(("stage","translate_model"))
            items=known_items if known_items is not None else read_srt(source)
            if not items:raise ProcessError("R101",f"{source.name} no contiene subtítulos válidos.")
            self.events.put(("log",f"SRT {from_code.upper()} a {to_code.upper()}: {len(items)} partidas.\n"));self.events.put(("stage_start","translate"));translated=self.translate_srt_items(items,translator)
            out=self.unique_output(source,to_code,".srt");write_srt(out,translated);created.append(out)
            if to_code=="en":job.english=out
            else:job.spanish=out
            self.events.put(("log",f"SRT {from_code.upper()} a {to_code.upper()}: {out.name}\n"))
        self.events.put(("stage","translate"));return created
    def translate_pdf(self,job):
        source=job.video;doc=None;temp=None
        try:
            try:doc=fitz.open(source)
            except Exception as e:raise ProcessError("R201",f"No se pudo abrir {source.name}: {e}")
            page_texts=[page.get_text("text").strip() for page in doc]
            full_text="\n".join(page_texts).strip()
            if not full_text:raise ProcessError("R201","El PDF no contiene texto seleccionable; requiere OCR.")
            from_code,to_code=self.pdf_direction(full_text);self.events.put(("log",f"PDF detectado: traducción {from_code.upper()} a {to_code.upper()} sin FFmpeg.\n"))
            self.events.put(("stage_start","translate_model"));translator=self.argos_translator(from_code,to_code,"R202");self.events.put(("stage","translate_model"))
            out=self.unique_output(source,to_code,".pdf");temp=out.with_name(f".{out.stem}_videotools_temporal.pdf");c=canvas.Canvas(str(temp),pagesize=A4);width,height=A4
            self.events.put(("stage_start","translate"))
            total_pages=len(page_texts)
            for number,text in enumerate(page_texts,1):
                self.checkpoint();self.events.put(("log",f"PDF: traduciendo página {number}/{total_pages}.\n"))
                try:translated=translator.translate(text) if text else ""
                except Exception as e:raise ProcessError("R203",f"Página {number}: {e}")
                y=height-48;c.setFont("Helvetica",9);c.drawString(42,y,f"Página fuente {number}");y-=20;c.setFont("Helvetica",10)
                for paragraph in translated.splitlines() or [""]:
                    words=paragraph.split();line=""
                    for word in words:
                        candidate=(line+" "+word).strip()
                        if stringWidth(candidate,"Helvetica",10)>width-84:
                            if line:c.drawString(42,y,line);y-=14
                            line=word
                            if y<45:c.showPage();y=height-48;c.setFont("Helvetica",10)
                        else:line=candidate
                    if line:c.drawString(42,y,line);y-=14
                    if y<45:c.showPage();y=height-48;c.setFont("Helvetica",10)
                c.showPage()
            c.save();temp.replace(out);temp=None;self.events.put(("log",f"PDF traducido: {out.name}\n"));self.events.put(("stage","translate"));return out
        finally:
            if doc is not None:doc.close()
            if temp is not None:
                try:temp.unlink(missing_ok=True)
                except OSError:pass
    def download_youtube_subtitles(self,j):
        try:urllib.request.urlopen("https://www.youtube.com/generate_204",timeout=8).close()
        except Exception:raise ProcessError("Y101","YouTube requiere conexión a Internet.")
        try:from yt_dlp import YoutubeDL
        except Exception as error:raise ProcessError("Y102",f"yt-dlp no está disponible: {error}")
        options={"skip_download":True,"writesubtitles":True,"writeautomaticsub":True,"subtitleslangs":["es","es-419","en","en-US"],"subtitlesformat":"srt/best","outtmpl":str(j.video.parent/f"{j.video.stem}_youtube_%(id)s.%(ext)s"),"quiet":True,"no_warnings":True}
        try:
            with YoutubeDL(options) as dl:dl.extract_info(j.youtube_url,download=True)
        except Exception as error:raise ProcessError("Y103",f"No se pudieron obtener subtítulos: {error}")
        files=list(j.video.parent.glob(f"{j.video.stem}_youtube_*.srt"));j.spanish=next((x for x in files if re.search(r"\.es\.srt$",x.name,re.I)),None);j.english=next((x for x in files if re.search(r"\.en\.srt$",x.name,re.I)),None)
        if not(j.spanish or j.english):raise ProcessError("Y104","El video no ofrece subtítulos ES/EN disponibles.")
        self.translate_srt(j)
    def job_run(self,j):
        self.validate(j)
        if j.youtube_url:self.download_youtube_subtitles(j);return
        if j.video.suffix.casefold()==".pdf":
            self.translate_pdf(j);return
        if j.direct_srt or j.video.suffix.casefold()==".srt":
            self.events.put(("log","SRT detectado: se conservarán sus tiempos y se usará la dirección del combobox.\n"));self.translate_srt(j);return
        if is_audio(j.video):
            self.events.put(("log","Audio detectado: se generará SRT y un vídeo ligero para revisar los subtítulos.\n"))
            srt=self.generate_srt(j);self.create_audio_subtitle_video(j.video,srt);return
        if self.run_translate:
            self.events.put(("log","Traducción SRT por columna; no se enviará el vídeo a FFmpeg.\n"));self.translate_srt(j);return
        if self.run_srt_only:
            source=j.video
            if self.run_convert:
                try:
                    folder=j.video.parent/f"{j.video.stem}_partes";folder.mkdir(exist_ok=True)
                except Exception as e:raise ProcessError("E007",str(e))
                extension,label,tag,_,_=self.profile_spec(True);source=folder/f"{j.video.stem}_{tag}{extension}"
                self.events.put(("stage_start","convert"));self.ff([binary("ffmpeg"),"-y","-i",str(j.video),*self.conversion_args(j.video,j.parts,True),str(source)],f"Convirtiendo a {label}")
                self.events.put(("stage","convert"))
            self.events.put(("log","Modo SRT offline: no se dividirá el vídeo.\n"));self.generate_srt(Job(source));return
        try:folder=j.video.parent/f"{j.video.stem}_partes";folder.mkdir(exist_ok=True)
        except Exception as e:raise ProcessError("E007",str(e))
        video=j.video
        if self.run_burn:
            if not(j.spanish and j.english):raise ProcessError("E009",f"{j.video.name} necesita SRT español e inglés para quemar subtítulos.")
            out=folder/f"{j.video.stem}_bilingue.mp4";es,en=filter_path(j.spanish),filter_path(j.english);vf=f"subtitles=filename='{es}':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00008B&,OutlineColour=&H000000&,Outline=2,Alignment=6,MarginV=15',subtitles=filename='{en}':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H008000&,OutlineColour=&H000000&,Outline=2,MarginV=15,Alignment=2'";self.events.put(("stage_start","burn"));self.ff([binary("ffmpeg"),"-y","-i",str(video),"-vf",vf,"-c:v","libx264","-pix_fmt","yuv420p",*self.encode_options(video,j.parts),"-c:a","copy",str(out)],"Quemando subtítulos");video=out;self.events.put(("stage","burn"))
        if self.run_convert:
            extension,label,tag,_,_=self.profile_spec(True);out=folder/f"{video.stem}_{tag}{extension}";self.events.put(("stage_start","convert"));self.ff([binary("ffmpeg"),"-y","-i",str(video),*self.conversion_args(video,j.parts,True),str(out)],f"Convirtiendo a {label}");video=out;self.events.put(("stage","convert"))
            if self.profile_is_audio(self.run_conversion_profile):
                self.events.put(("log",f"Conversión de vídeo a audio terminada: {video.name}. No se dividirá una pista de audio.\n"));return
            if not j.manual_parts:
                before=j.parts;j.parts=self.estimate_parts(video);self.events.put(("log",f"Conversión terminada: tamaño real {video.stat().st_size/1024/1024:.1f} MB; partes recalculadas: {before} a {j.parts}.\n"))
        total=duration(video);es=read_srt(j.spanish) if j.spanish else [];en=read_srt(j.english) if j.english else [];ranges=[]
        self.events.put(("stage_start","video"));
        for n in range(j.parts):
            a=n*total/j.parts;b=total if n==j.parts-1 else(n+1)*total/j.parts;base=folder/f"{video.stem}_{n+1:02d}";self.ff([binary("ffmpeg"),"-y","-ss",f"{a:.3f}","-i",str(video),"-t",f"{b-a:.3f}","-c","copy",str(base.with_suffix(video.suffix or ".mp4"))],f"Dividiendo vídeo {n+1}/{j.parts}");ranges.append((base,a,b))
        self.events.put(("stage","video"))
        if j.spanish:
            for base,a,b in ranges:write_srt(Path(str(base)+"_es.srt"),part_srt(es,round(a*1000),round(b*1000)))
            self.events.put(("stage","es"))
        if j.english:
            for base,a,b in ranges:write_srt(Path(str(base)+"_en.srt"),part_srt(en,round(a*1000),round(b*1000)))
            self.events.put(("stage","en"))
    def queue_run(self, keys):
        fails = 0; total = len(keys)
        for i, k in enumerate(keys):
            j=self.jobs[k]
            mode="youtube" if j.youtube_url else "pdf" if j.video.suffix.casefold()==".pdf" else "translate" if j.direct_srt or j.video.suffix.casefold()==".srt" else "audio" if is_audio(j.video) else "translate" if self.run_translate else "srt" if self.run_srt_only else "video"
            self.events.put(("working",k,i,total,j.video.name,mode,bool(j.spanish),bool(j.english)))
            try: self.job_run(j)
            except StopRequested:
                self.events.put(("stopped", k, i, total)); break
            except Exception as e:
                fails += 1; self.events.put(("failed", k, i+1, total, str(e)))
            else: self.events.put(("ok", k, i+1, total, j.video.name))
        else:
            self.events.put(("done", f"Cola terminada. Correctos: {total-fails}; con error: {fails}.")); return
        self.events.put(("done", "Proceso detenido por el usuario."))
    def notification(self,final=False):
        if winsound is None:return
        tones=((740,110),(880,150)) if not final else ((523,140),(659,140),(784,170),(1047,350))
        def play():
            try:
                for frequency,duration in tones:winsound.Beep(frequency,duration)
            except RuntimeError:pass
        threading.Thread(target=play,daemon=True).start()
    def receive(self):
        try:
            while True:
                e=self.events.get_nowait();kind=e[0]
                if kind=="log":self.addlog(e[1]);self.status.set(e[1].strip())
                elif kind=="audiobook_working":
                    _,key,number,total,name=e;self.jobs[key].status="PROCESANDO";self.refresh(key);self.tree.selection_set(key);self.tree.focus(key);self.tree.see(key);self.current.set(f"Audiolibro {number}/{total}: {name}")
                elif kind=="audiobook_progress":
                    _,number,total,name,label,done,parts=e;self.current.set(f"Audiolibro {number}/{total}: {name}");self.status.set(f"{label}: {done}/{parts}.")
                elif kind=="audiobook_finished":
                    _,key=e;self.jobs[key].status="OK";self.refresh(key)
                elif kind=="audiobook_batch_progress":
                    _,done,total=e;self.bar["value"]=done/total*100
                elif kind=="audiobook_batch_done":
                    self.audiobook_busy=False;self.controls("normal");self.update_audiobook_mode();self.status.set("Audiolibros terminados.");messagebox.showinfo("VideoTools v48",f"Audiolibros creados: {len(e[1])}",parent=self)
                elif kind=="audiobook_failed":
                    self.audiobook_busy=False;self.controls("normal");self.update_audiobook_mode();self.status.set("El audiolibro no terminó.");messagebox.showerror("VideoTools v48",f"Error de audiolibro:\n{e[1]}",parent=self)
                elif kind=="editor_status":
                    self.editor_status.set(e[1])
                elif kind=="editor_batch_progress":
                    _,done,total=e;self.editor_jobs_progress["value"]=done/total*100
                elif kind=="editor_plan":
                    self.editor_progress_total=max(1,e[1]);self.editor_progress_done=0;self.editor_file_progress["value"]=0
                elif kind=="editor_step":
                    self.editor_progress_done=min(getattr(self,"editor_progress_total",1),getattr(self,"editor_progress_done",0)+1);self.editor_file_progress["value"]=self.editor_progress_done/getattr(self,"editor_progress_total",1)*100
                elif kind=="editor_progress":
                    _,label,percent=e;self.editor_status.set(f"{label}: {percent:.0f}% a las {datetime.now().strftime('%I:%M %p').lstrip('0').lower()}")
                    self.editor_progress["value"]=percent;self.editor_progress_text.configure(text=f"{label}: {percent:.0f}%")
                elif kind=="editor_done":
                    self.editor_busy=False
                    for widget in (self.editor_extract_button,self.editor_keep_button,self.editor_both_button,self.editor_add_job_button):widget.configure(state="normal")
                    names="\n".join(str(path) for path in e[1]);self.editor_status.set("Exportación terminada.");self.notification(True);messagebox.showinfo("VideoTools v48",f"Archivos creados:\n{names}",parent=self)
                elif kind=="editor_failed":
                    self.editor_busy=False
                    for widget in (self.editor_extract_button,self.editor_keep_button,self.editor_both_button,self.editor_add_job_button):widget.configure(state="normal")
                    self.editor_status.set("La exportación no terminó.");messagebox.showerror("VideoTools v48",f"Error al exportar segmentos:\n{e[1]}",parent=self)
                elif kind=="working":
                    _,k,i,total,name,mode,has_es,has_en=e;self.jobs[k].status="PROCESANDO";self.refresh(k);self.tree.selection_set(k);self.tree.focus(k);self.tree.see(k);self.build_run_stages(mode,has_es,has_en);self.reset_stages();self.current.set(f"Archivo {i+1}/{total}: {name}");self.status.set("Procesando...")
                elif kind=="stage_start":self.stage_work(e[1]);self.last_progress_marker=None
                elif kind=="stage":self.stage_ok(e[1])
                elif kind=="progress":
                    _,label,percent=e;percent=max(0,min(100,percent));self.status.set(f"{label}: {percent:.0f}%")
                    marker=(label,int(percent)//5)
                    if marker!=self.last_progress_marker:self.last_progress_marker=marker;self.addlog(f"{label}: {percent:.0f}% a las {datetime.now().strftime('%I:%M %p').lstrip('0').lower()}.\n")
                elif kind=="stopped":
                    _,k,i,total=e;self.jobs[k].status="DETENIDO";self.refresh(k);self.status.set("Proceso detenido; los renglones restantes permanecen en ESPERA.")
                elif kind=="ok":
                    _,k,n,total,name=e;self.jobs[k].status="OK";self.refresh(k);self.bar["value"]=n/total*100;self.addlog(f"OK: {name}\n");self.status.set(f"Finalizados: {n}/{total}");self.notification()
                elif kind=="failed":
                    _,k,n,total,error=e;code=error.split(":",1)[0] if re.match(r"[ERTV]\d{3}",error) else "E006";self.jobs[k].status=f"ERROR {code}";self.refresh(k);self.refresh_error_tip();self.bar["value"]=n/total*100;self.addlog("ERROR "+error+"\n");self.status.set(f"Error {code}; continúa con el siguiente.")
                elif kind=="done":self.addlog(e[1]+"\n");self.controls("normal");self.update_burn();self.update_translate_visibility();self.status.set("Proceso terminado.");self.notification(True);messagebox.showinfo("VideoTools v48",e[1],parent=self)
        except queue.Empty:pass
        self.after(100,self.receive)
    def addlog(self,text):self.log.configure(state="normal");self.log.insert("end",text);self.log.see("end");self.log.configure(state="disabled")
if __name__=="__main__":App().mainloop()





























































