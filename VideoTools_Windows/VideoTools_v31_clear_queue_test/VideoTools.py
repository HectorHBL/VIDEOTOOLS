"""VideoTools v36: cola mixta de vídeo, PDF y SRT con recuperación segura."""
from __future__ import annotations
import ctypes, json, math, os, queue, re, shutil, subprocess, sys, threading, time, urllib.request, wave, zipfile
from datetime import datetime
try: import winsound
except ImportError: winsound=None
import argostranslate.package, argostranslate.translate, argostranslate.settings
import pymupdf as fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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
VIDEO_TYPES=[("Vídeos, PDF y SRT","*.mp4 *.mkv *.avi *.mov *.m4v *.webm *.3g2 *.pdf *.srt"),("Todos","*.*")]; SRT_TYPES=[("Subtítulos SRT","*.srt"),("Todos","*.*")]
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
}
ERROR_HELP="E001: vídeo no encontrado.\nE002: SRT español no encontrado.\nE003: SRT inglés no encontrado.\nE004: SRT inválido o no legible.\nE005: FFprobe no pudo leer la duración.\nE006: FFmpeg falló en la etapa indicada.\nE007: no se pudo crear o escribir la carpeta de salida.\nE008: proceso detenido por el usuario.\nT101: no se pudo descargar o cargar el modelo offline.\nT102: no se pudo analizar/abrir el audio del vídeo.\nT103: falló la transcripción del audio.\nT104: no se pudo crear el SRT transcrito.\nT105: no se detectó diálogo en el audio.\nV101: Vosk no está instalado o no pudo cargarse.\nV102: no se pudo descargar/preparar el modelo Vosk.\nV103: no se pudo extraer el audio WAV para Vosk.\nV104: Vosk no pudo transcribir el audio."
ERROR_HELP += "\nE009: faltan subtítulos para quemar.\nR101: no hay SRT válido para traducir.\nR102/R202: falta el modelo Argos requerido.\nR103/R203: falló la traducción.\nR104: salida anómala descartada; el SRT se conserva y continúa.\nR201: PDF inválido, ilegible o sin texto seleccionable."
class StopRequested(Exception): pass
class ProcessError(Exception):
    def __init__(self, code, message): super().__init__(f"{code}: {message}"); self.code=code
@dataclass(frozen=True)
class Subtitle: start:int; end:int; text:str
@dataclass
class Job: video:Path; spanish:Path|None=None; english:Path|None=None; status:str="ESPERA"; parts:int=1; manual_parts:bool=False; direct_srt:bool=False
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
        super().__init__();self.title("VideoTools v36");self.conversion_profile=tk.StringVar(value=next(iter(CONVERSION_PROFILES)));self.icon_path=resource_path("VideoTools.ico")
        try:self.iconbitmap(default=str(self.icon_path))
        except tk.TclError:pass
        self.geometry("1180x735");self.minsize(780,500);self.parts,self.convert,self.burn=tk.IntVar(value=1),tk.BooleanVar(value=True),tk.BooleanVar(value=False);self.transcribe_only=tk.BooleanVar(value=False);self.translate_only=tk.BooleanVar(value=False);self.translation_choice=tk.StringVar(value="Automático");self.run_translate=False;self.engine_name=tk.StringVar(value="faster-whisper (preciso)");self.model_name=tk.StringVar(value="small");self.audio_language=tk.StringVar(value="Auto");self.run_srt_only=False;self.run_convert=False;self.run_engine="whisper";self.run_model="small";self.run_language=None;self.whisper_models={};self.vosk_models={};self.es_en_hf=None;self.jobs={};self.n=0;self.events=queue.Queue();self.status=tk.StringVar(value="Añade vídeo, PDF o SRT a la cola.");self.current=tk.StringVar(value="Sin proceso activo");self.stage_widgets={};self.stop_event=threading.Event();self.pause_event=threading.Event();self.active_process=None;self.preventing_sleep=False;self.ui();self.protocol("WM_DELETE_WINDOW",self.on_close);self.after(100,self.receive)
        self.run_burn=False;self.run_translation_choice="Automático";self.clearing=False;self.last_progress_marker=None
    def ui(self):
        box=ttk.Frame(self,padding=16);box.pack(fill="both",expand=True);box.columnconfigure(0,weight=1);box.rowconfigure(3,weight=1)
        ttk.Label(box,text="Cola mixta: PDF y SRT se traducen por archivo; los vídeos conservan las opciones seleccionadas.").grid(row=1,sticky="w",pady=(0,5))
        self.stage_frame=ttk.Frame(box);self.stage_frame.grid(row=2,sticky="w",pady=(0,6));self.build_stages()
        cols=("status","video","parts","folder","spanish","english");self.tree=ttk.Treeview(box,columns=cols,show="headings",height=10,selectmode="browse")
        for k,t,w in (("status","Estatus",120),("video","Archivo (vídeo/PDF/SRT)",220),("parts","Partes ≤134 MB",115),("folder","Ruta",330),("spanish","SRT español",180),("english","SRT inglés",180)):self.tree.heading(k,text=t);self.tree.column(k,width=w,minwidth=90,stretch=False)
        self.tree.tag_configure("ok",foreground="#006100",background="#C6EFCE");self.tree.tag_configure("working",foreground="#7F6000",background="#FFEB9C");self.tree.tag_configure("error",foreground="#9C0006",background="#FFC7CE");self.tree.grid(row=3,sticky="nsew")
        if DND_FILES:self.tree.drop_target_register(DND_FILES);self.tree.dnd_bind("<<Drop>>",self.drop_files)
        v=ttk.Scrollbar(box,orient="vertical",command=self.tree.yview);v.grid(row=3,column=1,sticky="ns");self.tree.configure(yscrollcommand=v.set);h=ttk.Scrollbar(box,orient="horizontal",command=self.tree.xview);h.grid(row=4,sticky="ew");self.tree.configure(xscrollcommand=h.set);self.tree.bind("<<TreeviewSelect>>",self.on_select)
        a=ttk.Frame(box);a.grid(row=5,sticky="w",pady=8);self.add=ttk.Button(a,text="Añadir vídeo / PDF / SRT",command=self.add_videos);self.add.pack(side="left");self.es=ttk.Button(a,text="Cargar SRT en español",command=lambda:self.assign("spanish"));self.es.pack(side="left",padx=6);self.en=ttk.Button(a,text="Cargar SRT en inglés",command=lambda:self.assign("english"));self.en.pack(side="left");self.remove=ttk.Button(a,text="Quitar seleccionado",command=self.remove_job);self.remove.pack(side="left",padx=6);self.clear=ttk.Button(a,text="Limpiar cola",command=self.clear_jobs);self.clear.pack(side="left")
        o=ttk.Frame(box);o.grid(row=6,sticky="w");self.parts_label=ttk.Label(o,text="Partes automáticas (máx. 134 MB):");self.parts_label.pack(side="left");self.part_input=ttk.Spinbox(o,from_=1,to=999,textvariable=self.parts,width=8,command=self.set_manual_parts);self.part_input.bind("<FocusOut>",lambda _e:self.set_manual_parts());self.part_input.bind("<Return>",lambda _e:self.set_manual_parts());self.part_input.pack(side="left",padx=8);self.conv=ttk.Checkbutton(o,text="Convertir a H.264 / AAC",variable=self.convert,command=self.build_stages);self.conv.pack(side="left",padx=12);self.burn_box=ttk.Checkbutton(o,text="Quemar subtítulos",variable=self.burn,command=self.build_stages);self.burn_box.pack(side="left",padx=12);self.srt_only_box=ttk.Checkbutton(o,text="Generar SRT offline (único proceso)",variable=self.transcribe_only,command=self.update_srt_mode);self.srt_only_box.pack(side="left",padx=12);self.translate_box=ttk.Checkbutton(o,text="Traducir SRT offline (único proceso)",variable=self.translate_only,command=self.update_translate_mode);self.translate_choice_box=ttk.Combobox(o,textvariable=self.translation_choice,values=("Automático","ES → EN","EN → ES"),state="readonly",width=15);self.engine_box=ttk.Combobox(o,textvariable=self.engine_name,values=("Vosk (rápido)","faster-whisper (preciso)"),state="readonly",width=24);self.engine_box.bind("<<ComboboxSelected>>",lambda _e:self.engine_changed());self.model_box=ttk.Combobox(o,textvariable=self.model_name,values=("small","medium","large-v3"),state="readonly",width=9);self.lang_box=ttk.Combobox(o,textvariable=self.audio_language,values=("Auto","Inglés","Español"),state="readonly",width=10);self.model_box.pack(side="left",padx=(8,2));self.lang_box.pack(side="left",padx=2);self.engine_box.pack_forget();self.model_box.pack_forget();self.lang_box.pack_forget()
        self.translate_choice_box.pack(side="left",padx=8)
        self.profile_box=ttk.Combobox(o,textvariable=self.conversion_profile,values=tuple(CONVERSION_PROFILES),state="readonly",width=31)
        self.parts_label.configure(text="Dividir en:");self.conv.configure(text="Convertir a",command=self.update_conversion_mode);self.srt_only_box.configure(text="Generar SRT")
        self.profile_box.pack(side="left",padx=(2,8),before=self.burn_box)
        run=ttk.Frame(box);run.grid(row=7,sticky="ew",pady=8);run.columnconfigure(0,weight=1);self.start=tk.Button(run,text="INICIAR PROCESOS EN ARCHIVOS",command=self.start_queue,bg="#FFF2CC",activebackground="#FFE699",relief="raised",font=("Segoe UI",10,"bold"));self.start.grid(row=0,column=0,sticky="ew");self.pause_button=ttk.Button(run,text="Pausar",command=self.toggle_pause,state="disabled");self.pause_button.grid(row=0,column=1,padx=6);self.stop_button=ttk.Button(run,text="Detener",command=self.stop_queue,state="disabled");self.stop_button.grid(row=0,column=2);ttk.Label(box,text="Avance general de renglones finalizados:").grid(row=8,sticky="w");self.bar=ttk.Progressbar(box,maximum=100);self.bar.grid(row=9,sticky="ew");ttk.Label(box,textvariable=self.current).grid(row=10,sticky="w");ttk.Label(box,textvariable=self.status).grid(row=11,sticky="w");log_frame=ttk.Frame(box);log_frame.grid(row=12,sticky="nsew");log_frame.columnconfigure(0,weight=1);log_frame.rowconfigure(0,weight=1);self.log=tk.Text(log_frame,height=8,state="disabled",wrap="word");self.log.grid(row=0,column=0,sticky="nsew");log_scroll=ttk.Scrollbar(log_frame,orient="vertical",command=self.log.yview);log_scroll.grid(row=0,column=1,sticky="ns");self.log.configure(yscrollcommand=log_scroll.set);box.rowconfigure(12,weight=1)
        self.tree_tip=Tip(self.tree,"Lista de vídeos. El detalle de códigos aparece aquí solo si existe un ERROR.")
        for w,t in ((self.add,"Añade vídeos a la cola."),(self.es,"Asocia SRT español, incluso de otra carpeta."),(self.en,"Asocia SRT inglés, incluso de otra carpeta."),(self.part_input,"Número de fragmentos por vídeo."),(self.conv,"Activa la conversión del vídeo antes de dividir."),(self.profile_box,"Perfiles compatibles de FFmpeg. H.264/AAC es el predeterminado; los perfiles sin pérdida pueden crear archivos grandes."),(self.burn_box,"Integra ambos subtítulos de manera permanente."),(self.srt_only_box,"Ejecuta solamente la generación de SRT desde el audio para toda la cola."),(self.engine_box,"Vosk es rápido y funciona offline después de descargar su modelo. faster-whisper es más preciso, pero más lento."),(self.model_box,"Modelo faster-whisper: small es más rápido; medium y large-v3 son más precisos."),(self.lang_box,"Auto detecta inglés o español. Puedes forzar un idioma."),(self.start,"Inicia los renglones ESPERA en orden."),(self.pause_button,"Pausa la cola al terminar la etapa de FFmpeg en curso; vuelve a pulsar para reanudar."),(self.stop_button,"Detiene el FFmpeg activo y deja los renglones restantes en ESPERA."),(self.bar,"Porcentaje de renglones finalizados."),(self.log,"Mensajes, etapas y errores.")):Tip(w,t)
    def build_stages(self, has_es=None, has_en=None):
        if self.translate_only.get():
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
            names.append(("video", "DIVIDIR VÍDEO"))
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
        elif mode=="srt":
            names=[]
            if self.run_convert:names.append(("convert",f"CONVERTIR: {self.profile_spec(True)[1]}"))
            if self.run_engine=="vosk":names += [("model","PREPARAR MODELO VOSK"),("audio","EXTRAER AUDIO WAV"),("transcribe","TRANSCRIBIR CON VOSK"),("srt","GENERAR ARCHIVO SRT")]
            else:names += [("model","CARGAR MODELO IA"),("audio","ANALIZAR AUDIO"),("transcribe","TRANSCRIBIR AUDIO"),("srt","GENERAR ARCHIVO SRT")]
        else:
            names=[]
            if self.run_burn:names.append(("burn","QUEMAR SUBTÍTULOS"))
            if self.run_convert:names.append(("convert",f"CONVERTIR: {self.profile_spec(True)[1]}"))
            names.append(("video","DIVIDIR VÍDEO"))
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
            if j.video.suffix.casefold() in {".pdf",".srt"}:
                kind="PDF" if j.video.suffix.casefold()==".pdf" else "SRT"
                self.parts.set(1);self.status.set(f"{j.video.name}: {kind}; se traducirá automáticamente al llegar su turno.");return
            if not j.manual_parts: j.parts=self.estimate_parts(j.video);self.refresh(k)
            self.parts.set(j.parts);mode="manual" if j.manual_parts else "automática"
            self.status.set(f"{j.video.name}: {j.parts} parte(s), configuración {mode}.")
    def set_manual_parts(self):
        k=self.tree.selection()
        if not k:return
        j=self.jobs[k[0]]
        if j.video.suffix.casefold() in {".pdf",".srt"}:messagebox.showinfo("VideoTools v36","Los PDF y SRT no se dividen en partes.",parent=self);return
        try:value=max(1,int(self.parts.get()))
        except (ValueError,tk.TclError):messagebox.showwarning("VideoTools v36","Indica un número válido.",parent=self);return
        j.parts=value;j.manual_parts=True;self.parts.set(value);self.refresh(k[0]);self.status.set(f"{j.video.name}: partes manuales = {value}.")
    def values(self,j):return(j.status,j.video.name,"—" if j.video.suffix.casefold() in {".pdf",".srt"} else j.parts,str(j.video.parent),j.spanish.name if j.spanish else "—",j.english.name if j.english else "—")
    def refresh(self,k):
        j=self.jobs[k];tag={"OK":"ok","PROCESANDO":"working"}.get(j.status,"error" if j.status.startswith("ERROR") else "");self.tree.item(k,values=self.values(j),tags=(tag,) if tag else ())
    def add_paths(self,paths):
        for x in paths:
            v=Path(x);self.n+=1;k=str(self.n)
            if v.suffix.casefold()==".pdf":self.jobs[k]=Job(v,parts=1,manual_parts=True)
            elif v.suffix.casefold()==".srt":self.jobs[k]=Job(v,parts=1,manual_parts=True,direct_srt=True)
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
        active = self.active_process is not None or self.start.cget("state") == "disabled"
        text = "¿Deseas cerrar VideoTools?"
        if active: text += "\n\nHay procesos en ejecución. Se detendrán y los renglones restantes quedarán en ESPERA."
        if not messagebox.askyesno("Cerrar VideoTools v36", text,parent=self): return
        if active:
            self.stop_queue()
            self.after(400, self.finish_close)
        else: self.keep_awake(False);self.destroy()
    def finish_close(self):
        p = self.active_process
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
        if k and self.jobs[k].video.suffix.casefold() in {".pdf",".srt"}:messagebox.showinfo("VideoTools v36","Los SRT solo pueden asociarse a un renglón de vídeo.",parent=self);return
        if k and (x:=filedialog.askopenfilename(title="Selecciona SRT",filetypes=SRT_TYPES)):setattr(self.jobs[k],language,Path(x));self.refresh(k);self.update_burn();self.update_translate_visibility()
    def update_burn(self):
        show=any(j.spanish and j.english for j in self.jobs.values())
        if show and not self.burn_box.winfo_manager():self.burn_box.pack(side="left",padx=12)
        if not show and self.burn_box.winfo_manager():self.burn.set(False);self.burn_box.pack_forget()
    def remove_job(self):
        if(k:=self.selected()):self.tree.delete(k);self.jobs.pop(k,None);self.update_burn();self.update_translate_visibility();self.refresh_error_tip()
    def clear_jobs(self):
        if not self.jobs:return
        if not messagebox.askyesno("VideoTools v36","¿Vaciar cola?",parent=self):return
        self.clearing=True
        try:
            self.tree.selection_remove(self.tree.selection());self.tree.delete(*self.tree.get_children());self.jobs.clear();self.update_burn();self.update_translate_visibility();self.refresh_error_tip();self.status.set("Cola vacía.")
        finally:
            self.clearing=False
        self.focus_set()
    def controls(self, state):
        for x in (self.add,self.es,self.en,self.remove,self.clear,self.start,self.part_input,self.conv,self.burn_box,self.srt_only_box,self.translate_box):x.configure(state=state)
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
# El modo se congela antes de iniciar el hilo; SRT offline nunca ejecuta división.
        self.run_srt_only=self.transcribe_only.get();self.run_translate=self.translate_only.get()
        self.run_convert=self.convert.get();self.run_conversion_profile=self.conversion_profile.get();self.run_burn=self.burn.get();self.run_translation_choice=self.translation_choice.get()
        self.run_engine="vosk" if self.engine_name.get().startswith("Vosk") else "whisper"
        self.run_model=self.model_name.get()
        self.run_language={"Auto":None,"Inglés":"en","Español":"es"}[self.audio_language.get()]
        keys=[k for k in self.tree.get_children() if self.jobs[k].status=="ESPERA"]
        try:
            if not keys:raise ValueError("No hay renglones en ESPERA.")
            video_keys=[k for k in keys if self.jobs[k].video.suffix.casefold() not in {".pdf",".srt"}]
            if not self.run_translate and any(self.jobs[k].parts<1 for k in video_keys):raise ValueError("No se pudo calcular el número de partes.")
            if video_keys and self.run_srt_only and self.run_engine=="vosk" and self.run_language is None:raise ValueError("Vosk requiere elegir Español o Inglés.")
        except Exception as e:messagebox.showerror("VideoTools v36",str(e),parent=self);return
        self.build_stages(any(self.jobs[k].spanish for k in keys),any(self.jobs[k].english for k in keys));self.bar["value"]=0;self.stop_event.clear();self.pause_event.clear();self.start.configure(text="CORRIENDO PROCESOS EN ARCHIVOS",bg="#B7C98A",activebackground="#A6B879");self.pause_button.configure(state="normal",text="Pausar");self.stop_button.configure(state="normal");self.controls("disabled");self.keep_awake(True);self.addlog("Protección contra suspensión automática activada mientras la cola está en ejecución.\n");threading.Thread(target=self.queue_run,args=(keys,),daemon=True).start()
    def validate(self,j):
        if j.video.suffix.casefold()==".pdf":
            if not j.video.is_file():raise ProcessError("R201",f"No existe el PDF: {j.video}")
            return
        if j.direct_srt or j.video.suffix.casefold()==".srt":
            if not j.video.is_file():raise ProcessError("R101",f"No existe el SRT: {j.video}")
            return
        if not self.run_translate and not j.video.is_file():raise ProcessError("E001",f"No existe el vídeo: {j.video}")
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
        self.events.put(("stage_start","srt")); suffix=self.run_language
        try: write_srt(job.video.with_name(f"{job.video.stem}_{suffix}.srt"),items)
        except Exception as e: raise ProcessError("T104",str(e))
        self.events.put(("log",f"SRT Vosk generado ({suffix}): {len(items)} subtítulos.\n"));self.events.put(("stage","srt"))
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
            try: write_srt(job.video.with_name(f"{job.video.stem}_{suffix}.srt"), items)
            except Exception as e: raise ProcessError("T104", str(e))
            self.events.put(("log", f"SRT generado con idioma {suffix}: {len(items)} subtítulos.\n")); self.events.put(("stage", "srt"))
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
        """Traduce bloques con contexto; si un bloque falla se reduce sin perder el SRT."""
        # El modelo neuronal ES → EN ya conserva mejor el sentido por partida.
        # No se reparte texto de un bloque entre subtítulos, pues eso podía activar
        # el respaldo y dejar el español original aunque el PDF sí se tradujera.
        if type(translator).__name__=="HelsinkiSpanishEnglish":
            result=[];fallbacks=0
            for index,item in enumerate(items,1):
                self.checkpoint()
                try:text=translator.translate(item.text)
                except Exception:text=""
                if self.translation_issue(item.text,text):
                    text=item.text;fallbacks+=1;self.events.put(("log",f"R104: subtítulo {index} se conservó sin traducir para evitar texto dañado.\n"))
                result.append(Subtitle(item.start,item.end,text.strip()))
            if fallbacks:self.events.put(("log",f"SRT terminado con {fallbacks} partida(s) sin traducir; el resto se tradujo.\n"))
            return result
        result=[None]*len(items);batch=[];batch_size=0;fallbacks=0
        def flush():
            nonlocal batch,batch_size,fallbacks
            if not batch:return
            def translate_block(block):
                nonlocal fallbacks
                self.checkpoint();source=" ".join(re.sub(r"\s+"," ",item.text).strip() for _,item in block)
                try:combined=translator.translate(source)
                except Exception:combined=""
                issue=self.translation_issue(source,combined)
                if not issue:
                    for (index,item),text in zip(block,self.distribute_srt_translation(combined,block)):
                        result[index]=Subtitle(item.start,item.end,text)
                    return
                if len(block)>1:
                    middle=len(block)//2
                    self.events.put(("log",f"R104: bloque anómalo; se reintenta en bloques más pequeños ({len(block)} partidas).\n"))
                    translate_block(block[:middle]);translate_block(block[middle:]);return
                index,item=block[0];fallbacks+=1;result[index]=Subtitle(item.start,item.end,item.text)
                self.events.put(("log",f"R104: subtítulo {index+1} se conservó sin traducir para evitar texto dañado.\n"))
            translate_block(batch)
            batch=[];batch_size=0
        for index,item in enumerate(items):
            self.checkpoint();size=len(item.text)
            if batch and (len(batch)>=16 or batch_size+size>1600):flush()
            batch.append((index,item));batch_size+=size
        flush()
        if fallbacks:self.events.put(("log",f"SRT terminado con {fallbacks} partida(s) conservada(s) sin traducir; el resto se tradujo.\n"))
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
            self.events.put(("log",f"SRT {from_code.upper()} a {to_code.upper()}: {len(items)} partidas.\n"));self.events.put(("stage_start","translate"));translated=[Subtitle(item.start,item.end,self.translate_es_en(item.text).strip()) for item in items] if (from_code,to_code)==("es","en") else self.translate_srt_items(items,translator)
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
    def job_run(self,j):
        self.validate(j)
        if j.video.suffix.casefold()==".pdf":
            self.translate_pdf(j);return
        if j.direct_srt or j.video.suffix.casefold()==".srt":
            self.events.put(("log","SRT detectado: se conservarán sus tiempos y se usará la dirección del combobox.\n"));self.translate_srt(j);return
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
            mode="pdf" if j.video.suffix.casefold()==".pdf" else "translate" if j.direct_srt or j.video.suffix.casefold()==".srt" or self.run_translate else "srt" if self.run_srt_only else "video"
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
                elif kind=="done":self.addlog(e[1]+"\n");self.controls("normal");self.update_burn();self.update_translate_visibility();self.status.set("Proceso terminado.");self.notification(True);messagebox.showinfo("VideoTools v36",e[1],parent=self)
        except queue.Empty:pass
        self.after(100,self.receive)
    def addlog(self,text):self.log.configure(state="normal");self.log.insert("end",text);self.log.see("end");self.log.configure(state="disabled")
if __name__=="__main__":App().mainloop()




