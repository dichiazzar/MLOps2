import os
import time

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

MINIO_ENDPOINT = os.environ["MINIO_ENDPOINT"]
MINIO_ACCESS_KEY = os.environ["MINIO_ROOT_USER"]
MINIO_SECRET_KEY = os.environ["MINIO_ROOT_PASSWORD"]

RAW_BUCKET = "raw-data"
ARTIFACTS_BUCKET = "mlflow-artifacts"
DATASET_PATH = "/dataset/Car details v3.csv"
OBJECT_KEY = "car_details_v3.csv"


def get_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def ensure_bucket(client, bucket_name: str):
    try:
        client.head_bucket(Bucket=bucket_name)
        print(f"Bucket '{bucket_name}' already exists.")
    except ClientError:
        client.create_bucket(Bucket=bucket_name)
        print(f"Bucket '{bucket_name}' created.")


def wait_for_minio(client, retries: int = 20, delay: int = 3):
    for attempt in range(retries):
        try:
            client.list_buckets()
            return
        except Exception as exc:
            print(f"Waiting for MinIO ({attempt + 1}/{retries})... {exc}")
            time.sleep(delay)
    raise RuntimeError("MinIO did not become available in time")


def main():
    client = get_client()
    wait_for_minio(client)

    ensure_bucket(client, RAW_BUCKET)
    ensure_bucket(client, ARTIFACTS_BUCKET)

    client.upload_file(DATASET_PATH, RAW_BUCKET, OBJECT_KEY)
    print(f"Uploaded {DATASET_PATH} -> s3://{RAW_BUCKET}/{OBJECT_KEY}")


if __name__ == "__main__":
    main()
