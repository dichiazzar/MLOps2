# Chequeo previo a grabar la demo del TP final de MLOps 2.
# Revisa que todo esté levantado y sano, y dice qué arreglar si algo falla.
#
#   powershell -ExecutionPolicy Bypass -File .\presentacion\demo\chequeo_previo.ps1
#
# No cambia nada: solo mira.

$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..\..")      # carpeta MLOps2_TP_Final
$fallas = 0

function Resultado($ok, $que, $arreglo) {
    if ($ok) {
        Write-Host ("  OK     " + $que) -ForegroundColor Green
    } else {
        Write-Host ("  FALLA  " + $que) -ForegroundColor Red
        Write-Host ("         -> " + $arreglo) -ForegroundColor Yellow
        $script:fallas++
    }
}

function Responde($url) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
        return $r.StatusCode -lt 500
    } catch {
        return $false
    }
}

Write-Host ""
Write-Host "  Chequeo previo a la grabación" -ForegroundColor White
Write-Host ""

# 1. Docker
docker info *> $null
Resultado ($LASTEXITCODE -eq 0) "Docker está corriendo" "Abrir Docker Desktop y esperar a que arranque"

# 2. Stack base de MLOps 1
$corriendo = docker ps --format "{{.Names}}"
foreach ($c in "mlops-postgres", "mlops-minio", "mlops-mlflow", "mlops-airflow-webserver", "mlops-airflow-scheduler") {
    Resultado ($corriendo -contains $c) "MLOps 1: $c" "cd ..\MLOps1_final ; docker compose up -d"
}

# 3. Las capas de este TP
foreach ($c in "capas-rest", "capas-graphql", "capas-grpc", "capas-redpanda", "capas-streaming-consumer") {
    Resultado ($corriendo -contains $c) "MLOps 2: $c" "docker compose up -d --build"
}

# 4. Archivos y recursos de la seguridad
Resultado (Test-Path ".env") "Archivo .env del TP" "Copy-Item .env.example .env  (y cambiar los secretos)"
docker volume inspect mlops2-tp-final_certs *> $null
Resultado ($LASTEXITCODE -eq 0) "Volumen certs (certificado TLS de gRPC)" "docker compose --profile seguridad run --rm seguridad-certs"
docker image inspect capas-seguridad *> $null
Resultado ($LASTEXITCODE -eq 0) "Imagen de herramientas (capas-seguridad)" "docker compose --profile manual build seguridad-tests"

# 5. Consolas web que se muestran en el video
Resultado (Responde "http://localhost:8080/health") "Airflow en http://localhost:8080" "Levantar el stack de MLOps 1"
Resultado (Responde "http://localhost:5000/health") "MLflow en http://localhost:5000" "Levantar el stack de MLOps 1"
Resultado (Responde "http://localhost:9001") "Consola de MinIO en http://localhost:9001" "Levantar el stack de MLOps 1"

# 6. El modelo en Production y cargado en las capas
try {
    $mv = Invoke-RestMethod -Uri "http://localhost:5000/api/2.0/mlflow/registered-models/get-latest-versions?name=xgb_best&stages=Production" -TimeoutSec 5
    $prod = ($mv.model_versions | Measure-Object).Count -gt 0
} catch { $prod = $false }
Resultado $prod "xgb_best en Production en MLflow" "Correr el DAG de Airflow (README de MLOps1_final)"

foreach ($p in @(@{n = "REST"; u = "http://localhost:8010/health"}, @{n = "GraphQL"; u = "http://localhost:8001/health"})) {
    try { $h = Invoke-RestMethod -Uri $p.u -TimeoutSec 5; $ok = $h.model_loaded -eq $true } catch { $ok = $false }
    Resultado $ok ("Modelo cargado en " + $p.n) "docker compose restart  (y revisar los logs)"
}

$logs = docker compose logs grpc streaming-consumer 2>$null | Out-String
Resultado ($logs -match "integridad verificada") "gRPC y streaming verificaron la integridad del modelo" "docker compose --profile lake run --rm lake-preparar ; docker compose restart"

Write-Host ""
if ($fallas -eq 0) {
    Write-Host "  Todo listo para grabar." -ForegroundColor Green
} else {
    Write-Host "  Hay $fallas cosas para arreglar antes de grabar." -ForegroundColor Red
}
Write-Host ""
