VideoTools v36 - cola mixta de vídeos, PDF y traducción SRT con recuperación segura

Cambios principales:
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
