# Demo de punta a punta del TP final de MLOps 2, pensada para grabarla en video.
# Sigue el orden de la materia: capas de acceso (clases 1 a 4), federado (clase 5),
# Data Lake (clase 6) y seguridad (clase 7).
# Cada paso muestra un título, ejecuta los comandos y espera Enter: no hay que tipear nada.
#
#   powershell -ExecutionPolicy Bypass -File .\presentacion\demo\demo_grabacion.ps1
#
# Antes: correr chequeo_previo.ps1 y loguearse en Airflow y en la consola de MinIO.
# -SinPausa corre todo de un tirón y no abre el navegador (sirve para ensayar).

param([switch]$SinPausa)

$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..\..")      # carpeta MLOps2_TP_Final

$AUTO = @{ name = "Maruti Swift Dzire VDI"; year = 2014; km_driven = 145500; fuel = "Diesel"
           seller_type = "Individual"; transmission = "Manual"; owner = "First Owner"
           mileage = "23.4 kmpl"; engine = "1248 CC"; max_power = "74 bhp"
           torque = "190Nm@ 2000rpm"; seats = 5 }
$AUTO_NUEVO = $AUTO.Clone(); $AUTO_NUEVO.year = 2019; $AUTO_NUEVO.km_driven = 30000
$GQL_AUTO = '{name: "Maruti Swift Dzire VDI", year: 2014, kmDriven: 145500, fuel: diesel, sellerType: individual, transmission: manual, owner: first, mileage: "23.4 kmpl", engine: "1248 CC", maxPower: "74 bhp", torque: "190Nm@ 2000rpm", seats: 5}'

# ------------------------------------------------------------------ ayudas
function Paso($n, $bloque, $titulo, $idea) {
    Clear-Host
    Write-Host ""
    Write-Host ("  " + $bloque) -ForegroundColor DarkGray
    Write-Host ("  PASO " + $n) -ForegroundColor DarkYellow
    Write-Host ("  " + $titulo) -ForegroundColor White
    Write-Host ("  " + $idea) -ForegroundColor Gray
    Write-Host ""
}

function Comando($texto) {
    Write-Host ""
    Write-Host ("  > " + $texto) -ForegroundColor Cyan
}

function Seguir {
    if ($SinPausa) { return }
    Write-Host ""
    Read-Host "  [Enter] para seguir" | Out-Null
}

function Abrir($url) {
    if (-not $SinPausa) { Start-Process $url }
}

function Pedido($metodo, $ruta, $token, $cuerpo) {
    $h = @{}
    if ($token) { $h.Authorization = "Bearer $token" }
    $p = @{ UseBasicParsing = $true; Method = $metodo; Uri = "http://localhost:8010$ruta"; Headers = $h }
    if ($cuerpo) { $p.Body = ($cuerpo | ConvertTo-Json); $p.ContentType = "application/json" }
    try {
        $r = Invoke-WebRequest @p
        $texto = $r.Content
        if ($texto.Length -gt 300) { $texto = $texto.Substring(0, 300) + " ..." }
        Write-Host ("    " + $r.StatusCode + "  " + $texto) -ForegroundColor Green
    } catch {
        $resp = $_.Exception.Response
        if ($resp) {
            Write-Host ("    " + [int]$resp.StatusCode + "  " + $_.ErrorDetails.Message) -ForegroundColor Yellow
        } else {
            Write-Host ("    error: " + $_.Exception.Message) -ForegroundColor Red
        }
    }
}

function Gql($consulta, $token) {
    $h = @{}
    if ($token) { $h.Authorization = "Bearer $token" }
    try {
        $r = Invoke-RestMethod -Method Post -Uri "http://localhost:8001/graphql" -Headers $h `
             -ContentType "application/json" -Body (@{ query = $consulta } | ConvertTo-Json)
        $color = if ($r.errors) { "Yellow" } else { "Green" }
        $texto = $r | ConvertTo-Json -Depth 8 -Compress
        if ($texto.Length -gt 300) { $texto = $texto.Substring(0, 300) + " ..." }
        Write-Host ("    " + $texto) -ForegroundColor $color
    } catch {
        Write-Host ("    " + $_.Exception.Message) -ForegroundColor Yellow
    }
}

function Ahora { (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }

function EsperarLog($patron, $desde, $segundos) {
    # Revisa los logs del consumidor (desde el inicio del paso) cada 2 s hasta ver el patrón.
    Write-Host "    esperando al consumidor..." -ForegroundColor DarkGray
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        $vistas = docker compose logs --since $desde streaming-consumer 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match $patron }
        if ($vistas) { return }
        Start-Sleep -Seconds 2
    }
    Write-Host "    (no apareció en $segundos s: seguir igual)" -ForegroundColor DarkGray
}

function Filtrar($patron) {
    process { if ("$_" -match $patron) { Write-Host ("    " + $_) } }
}

$B0 = "INTRODUCCIÓN"
$B1 = "CLASES 1 A 4 · CAPAS DE ACCESO"
$B5 = "CLASE 5 · APRENDIZAJE FEDERADO"
$B6 = "CLASE 6 · DATA LAKE"
$B7 = "CLASE 7 · SEGURIDAD CON SAIF"

# ================================================================== introducción
Paso 1 $B0 "El sistema levantado" "El stack de MLOps 1 (Airflow, MLflow, MinIO, Postgres) y lo que sumé en MLOps 2."
Comando "docker ps"
docker ps --format "    {{.Names}}  ->  {{.Status}}" | Where-Object { $_ -match "mlops-|capas-" } | Sort-Object
Seguir

Paso 2 $B0 "El núcleo de MLOps 1" "Airflow entrena xgb_best y MLflow lo registra en Production. No cambia en todo el TP."
Comando "abrir Airflow (DAG train_xgb_pipeline) y MLflow (modelo xgb_best)"
Abrir "http://localhost:8080/dags/train_xgb_pipeline/grid"
Abrir "http://localhost:5000/#/models/xgb_best"
Seguir

Paso 3 $B0 "Credencial de acceso" "Hoy todas las capas piden un token con rol (es de la clase 7, se ve al final). Emito uno."
Comando "docker compose --profile manual run --rm emitir-token jaime analista"
$TOKEN = docker compose --profile manual run --rm emitir-token jaime analista 2>$null | Select-Object -Last 1
Write-Host ("    " + $TOKEN.Substring(0, 40) + "...")
$ADMIN = docker compose --profile manual run --rm emitir-token ana admin 2>$null | Select-Object -Last 1
Seguir

# ================================================================== clases 1 a 4
Paso 4 $B1 "REST (clase 1) · puerto 8010" "La API de MLOps 1, sin reescribirla: petición y respuesta JSON de forma fija."
Comando "GET /health";                                    Pedido "GET" "/health" $null $null
Comando "GET /model/info";                                Pedido "GET" "/model/info" $TOKEN $null
Comando "POST /predict   (Swift Dzire 2014, 145.500 km)"; Pedido "POST" "/predict" $TOKEN $AUTO
Comando "POST /predict   (el mismo, 2019, 30.000 km)";    Pedido "POST" "/predict" $TOKEN $AUTO_NUEVO
Seguir

Paso 5 $B1 "GraphQL (clase 2) · puerto 8001" "El cliente pide exactamente los campos que necesita, en una sola consulta."
Comando "{ modelInfo { modelVersion } }";                                 Gql "{ modelInfo { modelVersion } }" $TOKEN
Comando "{ modelInfo { modelName modelVersion nFeatures topBrands } }";    Gql "{ modelInfo { modelName modelVersion nFeatures topBrands } }" $TOKEN
Comando "mutation { predict(car: ...) { predictedPrice modelVersion } }"; Gql ("mutation { predict(car: " + $GQL_AUTO + ") { predictedPrice modelVersion } }") $TOKEN
Seguir

Paso 6 $B1 "gRPC (clase 3) · puerto 50051" "Servicio a servicio: contrato .proto, binario, una predicción y un lote por streaming."
Comando "docker compose exec grpc python -m app.client_example"
docker compose exec -e TOKEN=$TOKEN grpc python -m app.client_example
Seguir

Paso 7 $B1 "Streaming (clase 4) · Redpanda" "La concesionaria publica 2000 autos; a mitad de camino suben los km. El consumidor puntúa cada uno."
$desde = Ahora
Comando "docker compose run --rm streaming-producer   (unos 30 segundos)"
docker compose run --rm streaming-producer 2>&1 | Filtrar "Publicando|Listo"
EsperarLog "ALERTA DE DRIFT" $desde 90
Comando "docker compose logs streaming-consumer  (filtrado)"
docker compose logs --since $desde streaming-consumer 2>&1 | Filtrar "evento (500|1000) \||ALERTA DE DRIFT" | Select-Object -First 3
Seguir

# ================================================================== clase 5
Paso 8 $B5 "Entrenamiento federado" "Tres concesionarias entrenan sin compartir datos; el servidor promedia los pesos (FedAvg, 20 rondas)."
Comando "docker compose --profile federado up fl-servidor fl-cliente-0 fl-cliente-1 fl-cliente-2   (unos 30 segundos)"
docker compose --profile federado up fl-servidor fl-cliente-0 fl-cliente-1 fl-cliente-2 2>&1 | Filtrar "Ronda (1|5|10|20) \||RMSE centralizado|registrado"
Comando "abrir MLflow (modelo linreg_federado, aparte de xgb_best)"
Abrir "http://localhost:5000/#/models/linreg_federado"
Seguir

# ================================================================== clase 6
Paso 9 $B6 "Preparar el Data Lake" "Zonas raw y curated en MinIO, y la metadata del modelo guardada en su run de MLflow."
Comando "docker compose --profile lake run --rm lake-preparar"
docker compose --profile lake run --rm lake-preparar 2>&1 | Filtrar "(raw|curated) +->|lake_metadata|Listo"
Seguir

Paso 10 $B6 "El lake como memoria" "Las predicciones del streaming quedaron en el lake, por fecha; GraphQL las consulta desde ahí."
Comando "{ prediccionesStreaming(limite: 3) }"
Gql "{ prediccionesStreaming(limite: 3) { fecha archivos total items { name kmDriven predictedPrice } } }" $TOKEN
Comando "abrir la consola de MinIO en el bucket datalake"
Abrir "http://localhost:9001/browser/datalake"
Seguir

# ================================================================== clase 7
Paso 11 $B7 "Preparar la seguridad" "Certificado TLS de gRPC, un usuario de MinIO por servicio y el hash del modelo en MLflow."
Comando "docker compose --profile seguridad run --rm seguridad-certs"
docker compose --profile seguridad run --rm seguridad-certs 2>&1 | Filtrar "certificados\]"
Comando "docker compose --profile seguridad run --rm seguridad-minio"
docker compose --profile seguridad run --rm seguridad-minio 2>&1 | Filtrar "usuario|bucket"
Seguir

Paso 12 $B7 "Puertas cerradas" "Token y rol en todas las capas, validación de la entrada y límites contra el abuso."
Comando "REST · POST /predict sin token";               Pedido "POST" "/predict" $null $AUTO
$absurdo = $AUTO.Clone(); $absurdo.year = 3000
Comando "REST · POST /predict con año 3000";            Pedido "POST" "/predict" $TOKEN $absurdo
Comando "REST · historial de otros, como analista";     Pedido "GET" "/predictions/recent?limit=1" $TOKEN $null
Comando "GraphQL · introspección";                      Gql "{ __schema { types { name } } }" $ADMIN
$alias = (0..24 | ForEach-Object { "p$($_): predict(car: $GQL_AUTO) { predictedPrice }" }) -join " "
Comando "GraphQL · 25 predicciones en una consulta";    Gql ("mutation { " + $alias + " }") $TOKEN
Seguir

Paso 13 $B7 "Streaming bajo ataque" "Una concesionaria maliciosa: eventos sin firma, alterados, repetidos, viejos y absurdos."
$desde = Ahora
Comando "docker compose run --rm streaming-producer python -m app.producer --modo ataque"
docker compose run --rm streaming-producer python -m app.producer --modo ataque 2>&1 | Filtrar "Modo ataque|Listo"
EsperarLog "ALERTA DLQ" $desde 120
Comando "docker compose logs streaming-consumer  (filtrado)"
docker compose logs --since $desde streaming-consumer 2>&1 | Filtrar "ALERTA DLQ" | Select-Object -Last 1
Seguir

Paso 14 $B7 "Auditoría" "Quién hizo qué y con qué resultado, guardado en el lake. Solo un admin la puede consultar."
Comando "{ auditoria(capa: rest) } como analista";  Gql '{ auditoria(capa: "rest", limite: 3) { total } }' $TOKEN
Comando "{ auditoria(capa: rest) } como admin";     Gql '{ auditoria(capa: "rest", limite: 4) { total items { usuario rol accion resultado } } }' $ADMIN
Seguir

Paso 15 $B7 "Seguridad de punta a punta" "El demo ataca todas las capas y el lake. Cada línea, un ataque frenado."
Comando "docker compose --profile manual run --rm demo-ataques --integridad   (alrededor de un minuto)"
docker compose --profile manual run --rm demo-ataques --integridad 2>&1 | Filtrar "^(REST|GraphQL|gRPC|Streaming|Lake|Integridad)|  OK|FALLA|TODO OK"
Seguir

Paso 16 "CIERRE" "Fin" "Un modelo, cuatro puertas de entrada, entrenamiento federado, Data Lake y seguridad en todas las capas."
Write-Host "    Repositorio: github.com/dichiazzar/MLOps2" -ForegroundColor Gray
Write-Host ""
