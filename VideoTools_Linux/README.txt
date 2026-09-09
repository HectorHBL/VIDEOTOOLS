VideoTools v41 - corrección de traducción SRT y exportación por segmentos

Cambios principales:
- v37 añade perfiles de extracción de audio: MP3, AAC/M4A, WAV/PCM, FLAC y Opus.
  Al elegir uno, el vídeo se convierte a audio y no se divide innecesariamente.
- Los audios cargados se transcriben directamente y producen también un MP4 ligero con
  fondo oscuro y subtítulos sincronizados, útil para revisar el resultado.
- La interfaz se organiza en dos pestañas. “Reproductor y edición” permite cargar un
  vídeo y un SRT, seleccionar varias partidas con Ctrl/Mayús, reproducirlas mediante
  FFplay y exportar la selección, el resto conservado o ambos en el formato elegido.
- Cada salida del editor genera su SRT reajustado al nuevo inicio de los segmentos.
- Un PDF se detecta por su extensión y se traduce sin pasar por FFmpeg.
- La cola puede alternar vídeo, PDF y vídeo. Cada vídeo conserva las opciones
  capturadas al pulsar iniciar.
- El botón “Añadir vídeo / PDF / SRT” acepta un SRT directamente. Selecciona
  ES → EN o EN → ES en el combobox antes de iniciar; esa elección determina
  la dirección de traducción del SRT.
- Los SRT se traducen en bloques consecutivos con contexto y se reconstruye
  exactamente una partida por cada bloque original, con sus mismos tiempos.
- Si un bloque devuelve texto repetitivo o desproporcionado, se vuelve a intentar
  con bloques menores. Una partida que siga fallando se conserva sin traducir,
  se registra como R104 y el SRT completo sí se guarda.
- Automático detecta la dirección del PDF; también puede elegirse ES → EN o
  EN → ES en la interfaz.
- La barra inferior muestra avances aproximados de conversión FFmpeg y de
  transcripción, además de registrar cada 5 %% de avance en el cuadro de texto.
- El checkbox "Convertir vídeo" habilita perfiles FFmpeg compatibles: H.264/AAC,
  H.265/AAC, MPEG-4/AAC, H.264/AAC 3GP, VP9/Opus, AV1/Opus, ProRes/PCM y FFV1/FLAC.
- Después de convertir, las partes automáticas se recalculan con el peso real
  del archivo resultante; una cantidad de partes indicada manualmente se respeta.
- El icono cinematográfico se aplica a la ventana y a los cuadros de diálogo v35.
- La interfaz permite añadir vídeo, PDF o SRT desde un solo botón; el botón de
  inicio se resalta mientras procesa y reproduce avisos sonoros por archivo y al final.
- Las salidas existentes no se sobrescriben; se agrega un número al nombre.

Los PDF escaneados sin texto seleccionable requieren OCR y se reportan como
error R201. Para traducción offline, conserva las carpetas argos_models y
models de la distribución integral.

Compilación completa en otra PC
-------------------------------
Ejecuta PowerShell como usuario normal y usa:

  powershell -ExecutionPolicy Bypass -File .\Instalar_y_compilar_completo.ps1

El script descarga las librerías, FFmpeg, los modelos Argos y Helsinki; también
descarga los modelos Whisper small, medium y large-v3 salvo que se use
`-OmitirModelosWhisper`. Al terminar crea `Distribucion_completa` con el EXE,
modelos y herramientas listas para mover a otra computadora.



- v38 añade la columna DISPOSICIÓN: ELIMINAR, RESUMEN o sin marca. PROCESAR genera en ese orden los vídeos _RESUMEN, _VANAL y _ELIMINAR, con una barra de avance.
- El reproductor permite navegar por los subtítulos, usar doble clic para reproducir desde una partida, mover la barra temporal y ajustar el divisor entre reproductor y lista.


- v41 evita WinError 206 al exportar RESUMEN, VANAL o ELIMINAR: prepara los segmentos por separado y los concatena mediante una lista temporal de FFmpeg, sin comandos gigantes.


Audiolibro PDF v42
-----------------
Selecciona un PDF de la cola y pulsa Generar audiolibro PDF. Piper funciona offline con es_MX-ald y en_US-lessac instaladas. ElevenLabs requiere Internet y una API Key guardada sólo en el almacén seguro del sistema. Se generan audio MP3, video MP4 H.264/AAC, SRT original y SRT de traducción cuando se activa el modo bilingüe.


YouTube y lista interna v43
---------------------------
- Puedes añadir o arrastrar accesos directos .URL de YouTube a la cola. Se requiere Internet.
  VideoTools descarga los subtítulos ES/EN disponibles (manuales o automáticos), detecta
  el idioma y genera/puede traducir el SRT al idioma contrario.
- Un acceso .URL que no sea de YouTube se identifica como PÁGINA y no se procesa, por lo
  que la cola continúa con el siguiente renglón.
- En Reproductor y edición, la lista interna admite varios vídeos/SRT y permite arrastrar
  vídeos. Busca un SRT cuyo nombre coincida o comparta el prefijo; si no existe lo agrega
  como "SRT pendiente" para asignarlo manualmente. PROCESAR atiende todas las partidas.
- Las secuencias contiguas de renglones con la misma disposición se exportan como un solo
  bloque de vídeo; esto evita crear cientos de fragmentos diminutos.
