# Guion de la demo grabada — TP final MLOps 2

Video de punta a punta del TP, para mostrar en la presentación en lugar de una demo en vivo.
Duración objetivo: **5 a 6 minutos** editados. Recorre la materia en orden: capas de acceso,
federado, Data Lake y seguridad.

## Antes de grabar (10 minutos)

1. Levantar todo:
   ```powershell
   cd TP_Final\MLOps1_final ; docker compose up -d
   cd ..\MLOps2_TP_Final   ; docker compose up -d --build
   ```
2. Chequeo previo: tiene que terminar en **"Todo listo para grabar."**
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\presentacion\demo\chequeo_previo.ps1
   ```
3. Ensayo sin pausas, para "calentar" los contenedores (la primera corrida siempre es más lenta):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\presentacion\demo\demo_grabacion.ps1 -SinPausa
   ```
4. Navegador: loguearse **antes** en Airflow (`http://localhost:8080`, admin / admin) y en la
   consola de MinIO (`http://localhost:9001`, minioadmin / minioadmin123), así no aparece el login
   en el video. Cerrar las demás pestañas.
5. Terminal: Windows Terminal o PowerShell a pantalla completa, fuente de 18 a 20 pt, fondo
   oscuro. Silenciar notificaciones (Asistente de concentración de Windows).

## Cómo grabar

- **OBS Studio** (gratis): una escena con "Captura de pantalla" + micrófono. Formato MP4, 1920×1080,
  30 fps. Graba la terminal y el navegador sin cortes.
- Alternativa sin instalar nada: **Xbox Game Bar** (`Win + Alt + R`), pero graba una sola ventana;
  las partes del navegador habría que grabarlas aparte.
- Grabar de un tirón; los errores se cortan después. Al editar, **acelerar las esperas** (la
  publicación de los 2000 eventos, el federado, el ataque al stream y el demo de ataques) a 2× o 4×.
- Para la presentación: tener el MP4 descargado en la computadora (no depender de internet) y
  probar el audio en la sala.

## La demo, paso a paso

Correr `demo_grabacion.ps1` (sin `-SinPausa`). Sigue el **orden de la materia**: primero las capas
de acceso (clases 1 a 4), después el federado (5), el Data Lake (6) y por último la seguridad (7),
que junta todos los controles al final. Cada paso muestra arriba a qué bloque pertenece, ejecuta
solo y con **Enter** se pasa al siguiente. Lo que está en *cursiva* es para decir en voz alta.

| Paso | Qué se ve | Qué decir | Tiempo |
|---|---|---|---|
| **Introducción** | | | |
| 1 | `docker ps`: el stack de MLOps 1 y las capas de MLOps 2 | *Este es el sistema completo: el stack de MLOps 1 (Airflow, MLflow, MinIO, Postgres) y lo que sumé en esta materia, en un compose propio que se une a esa red.* | 15 s |
| 2 | Se abren Airflow y MLflow | **En Airflow:** el DAG `train_xgb_pipeline` con sus corridas. **En MLflow:** `xgb_best` versión 1 en Production. *El núcleo: Airflow entrena, MLflow registra. No cambió en todo el TP; todo lo que sigue se construye alrededor.* | 25 s |
| 3 | Se emite un token | *Hoy todas las capas piden un token con rol. Es de la clase 7, lo explico al final; por ahora emito uno para poder usarlas.* | 10 s |
| **Clases 1 a 4 · capas de acceso** | | | |
| 4 | REST: health, info del modelo, dos predicciones | *Clase 1, REST: es la API de MLOps 1, sin reescribirla. Pregunto qué modelo está sirviendo y pido dos precios: el mismo auto, 2014 con 145.000 km y 2019 con 30.000. El modelo responde distinto según los datos.* | 30 s |
| 5 | GraphQL: dos consultas con distintos campos y una predicción | *Clase 2, GraphQL: el cliente elige qué campos quiere. Primero solo la versión; después nombre, versión, features y marcas, en una sola consulta. Y la misma predicción, por GraphQL.* | 25 s |
| 6 | gRPC: una predicción y un lote de cinco | *Clase 3, gRPC: pensado para que otro servicio llame al modelo. Contrato tipado en un .proto, binario, y además del pedido unitario, un lote con respuesta por streaming.* | 20 s |
| 7 | Streaming con drift | *Clase 4, streaming: el productor (concesionaria) publica 2000 autos y a mitad de camino suben los kilómetros. El consumidor (modelo) puntúa cada uno a medida que llega y detecta el cambio: alerta de drift.* (acelerar la espera) | 30 s |
| **Clase 5 · aprendizaje federado** | | | |
| 8 | Federado en vivo y MLflow | *Clase 5: otra forma de entrenar. Tres concesionarias entrenan con sus propios autos sin compartirlos; el servidor solo recibe pesos y los promedia. En 20 rondas llega al mismo error que el entrenamiento centralizado, y se registra aparte: no reemplaza a xgb_best.* **En MLflow:** `linreg_federado`. (acelerar) | 30 s |
| **Clase 6 · Data Lake** | | | |
| 9 | `lake-preparar` | *Clase 6: el Data Lake en MinIO, con zonas raw y curated. La metadata del modelo queda en su run de MLflow, que sigue siendo el registro de modelos.* | 20 s |
| 10 | GraphQL sobre el lake + consola de MinIO | *Las predicciones del streaming no se pierden: quedaron en el lake, por fecha, y GraphQL las consulta desde ahí.* **En MinIO:** mostrar `datalake` con `raw/streaming` por fecha y `curated`. | 25 s |
| **Clase 7 · seguridad con SAIF** | | | |
| 11 | Certificados, usuarios de MinIO | *Clase 7: la seguridad, con los mismos controles en todas las capas. Se prepara una vez: certificado TLS para gRPC, un usuario de MinIO por servicio con permiso solo para lo suyo, y el hash del modelo, que las capas verifican antes de cargarlo.* | 20 s |
| 12 | Puertas cerradas: 401, 422, 403, introspección, costo | *Sin token, 401. Un año 3000 no llega al modelo: 422. Un analista no ve el historial de otros. En GraphQL, la introspección está apagada y 25 predicciones en una consulta superan el costo máximo.* | 30 s |
| 13 | Ataque al stream | *Ahora un productor (concesionaria) malicioso: eventos sin firma, alterados, repetidos, viejos y absurdos. Ninguno se puntúa/predice: van a cuarentena, y el consumidor avisa que hay un ataque en curso.* | 25 s |
| 14 | Auditoría | *Todo queda auditado en el lake: quién hizo qué y con qué resultado. El analista no la puede ver; el admin sí.* **En MinIO** (opcional): `raw/auditoria` y `raw/dlq`. | 20 s |
| 15 | Demo de ataques | *Y para cerrar, 28 ataques contra todas las capas y el lake. Todos frenados.* (acelerar hasta el "TODO OK") | 30 s |
| **Cierre** | | | |
| 16 | Fin | *Un modelo, cuatro puertas de entrada, entrenamiento federado, Data Lake y seguridad en todas las capas: lo que fuimos construyendo clase a clase.* | 5 s |

## Si algo sale mal mientras grabás

- **Un paso falla:** cortar la grabación, correr `chequeo_previo.ps1`, arreglar lo que indique y
  volver a grabar desde ese paso (se edita después).
- **El streaming no muestra la alerta:** el script espera hasta 90 s (drift) y 120 s (DLQ) y sigue
  igual; normalmente es porque el consumidor todavía procesa eventos anteriores. Volver a correr
  el paso.
- **Se puede repetir todo:** los pasos no rompen nada si se corren varias veces. Cada corrida del
  federado registra una versión nueva de `linreg_federado` en MLflow (no toca `xgb_best`).
