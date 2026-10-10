#!/bin/sh
# Acceso mínimo en el MinIO de MLOps1_final (clase 7): un usuario por servicio de MLOps2,
# cada uno con una política que solo permite lo que ese servicio necesita.
# Nadie tiene s3:DeleteObject. Se puede correr de nuevo: actualiza políticas y claves.
# Airflow y MLflow (MLOps1) siguen con minioadmin: fuera del alcance (ver Diseño de arquitectura).
set -eu

mc alias set local "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

# Bucket del lake (antes lo creaban lake-preparar y el consumidor; ahora solo acá) + versionado:
# si alguien sobrescribe un objeto, la versión anterior queda.
mc mb --ignore-existing local/datalake >/dev/null
mc version enable local/datalake >/dev/null
echo "bucket datalake listo y versionado"

LEER_MODELO='{"Effect":"Allow","Action":["s3:GetObject"],"Resource":["arn:aws:s3:::mlflow-artifacts/*","arn:aws:s3:::raw-data/car_details_v3.csv"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::mlflow-artifacts"]}'

escribir() {  # escribir <prefijo dentro de datalake> ...
  recursos=""
  for p in "$@"; do recursos="$recursos\"arn:aws:s3:::datalake/$p*\","; done
  echo "{\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\"],\"Resource\":[${recursos%,}]}"
}

crear() {  # crear <usuario> <clave> <statements JSON separados por coma>
  echo "{\"Version\":\"2012-10-17\",\"Statement\":[$3]}" > "/tmp/tp-$1.json"
  mc admin policy create local "tp-$1" "/tmp/tp-$1.json" >/dev/null
  mc admin user add local "$1" "$2" >/dev/null
  mc admin policy attach local "tp-$1" --user "$1" >/dev/null 2>&1 || true   # ya estaba asociada
  rm -f "/tmp/tp-$1.json"
  echo "usuario $1 -> política tp-$1"
}

crear "$MINIO_CAPA_REST_USER" "$MINIO_CAPA_REST_PASSWORD" \
  "$LEER_MODELO,$(escribir raw/auditoria/capa=rest/)"

crear "$MINIO_CAPA_GRPC_USER" "$MINIO_CAPA_GRPC_PASSWORD" \
  "$LEER_MODELO,$(escribir raw/auditoria/capa=grpc/)"

crear "$MINIO_CAPA_GRAPHQL_USER" "$MINIO_CAPA_GRAPHQL_PASSWORD" \
  "$LEER_MODELO,$(escribir raw/auditoria/capa=graphql/),{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\"],\"Resource\":[\"arn:aws:s3:::datalake/raw/streaming/*\",\"arn:aws:s3:::datalake/raw/auditoria/*\"]},{\"Effect\":\"Allow\",\"Action\":[\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::datalake\"]}"

crear "$MINIO_CAPA_STREAMING_USER" "$MINIO_CAPA_STREAMING_PASSWORD" \
  "$LEER_MODELO,$(escribir raw/streaming/ raw/dlq/ raw/auditoria/capa=streaming/)"

crear "$MINIO_LAKE_PREPARAR_USER" "$MINIO_LAKE_PREPARAR_PASSWORD" \
  "{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\"],\"Resource\":[\"arn:aws:s3:::raw-data/*\",\"arn:aws:s3:::mlflow-artifacts/*\"]},{\"Effect\":\"Allow\",\"Action\":[\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::mlflow-artifacts\",\"arn:aws:s3:::raw-data\"]},{\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\"],\"Resource\":[\"arn:aws:s3:::datalake/raw/car_dekho/*\",\"arn:aws:s3:::datalake/curated/*\",\"arn:aws:s3:::mlflow-artifacts/*\"]}"

echo "Listo."
