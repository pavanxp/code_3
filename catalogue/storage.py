"""The three kinds of source: a local directory, an Azure Blob container and
an AWS S3 bucket. Each lists every file under the working directory (all
subdirectories included), reads a file, and writes a file back in place.
File keys are relative to the working directory and use "/"."""
import os
import tempfile

from catalogue.mcapmeta import remote_stream


def _mount_point(path: str) -> str:
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path


class LocalStorage:
    """A directory on a hard disk. The path recorded for a file starts with
    the hard disk's name (e.g. "volume 1") followed by the file's path inside
    that disk, so it does not depend on where the disk is mounted."""

    def __init__(self, root: str, disk_name: str = "", mount_point: str | None = None):
        self.root = os.path.abspath(root)
        self.disk_name = disk_name
        self.mount_point = mount_point

    def list_files(self) -> list[str]:
        if not os.path.isdir(self.root):
            raise FileNotFoundError(f"directory not found: {self.root}")
        keys = []
        for folder, _dirs, files in os.walk(self.root):
            rel = os.path.relpath(folder, self.root)
            for name in files:
                keys.append(name if rel == "." else "/".join(rel.split(os.sep) + [name]))
        return sorted(keys)

    def _real(self, key: str) -> str:
        return os.path.join(self.root, *key.split("/"))

    def full_path(self, key: str) -> str:
        real = self._real(key)
        if not self.disk_name:
            return real
        mount = self.mount_point or _mount_point(self.root)
        inside = os.path.relpath(real, mount).replace(os.sep, "/")
        return f"{self.disk_name}/{inside}"

    def read(self, key: str) -> bytes:
        with open(self._real(key), "rb") as f:
            return f.read()

    def open(self, key: str):
        return open(self._real(key), "rb")

    def write(self, key: str, data: bytes) -> None:
        # written beside the file and swapped in, so a crash never leaves half a file
        path = self._real(key)
        mode = os.stat(path).st_mode & 0o777
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".catalogue-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def _as_prefix(prefix: str) -> str:
    prefix = prefix.strip("/")
    return prefix + "/" if prefix else ""


class AzureStorage:
    def __init__(self, container_client, prefix: str = ""):
        self.client = container_client
        self.prefix = _as_prefix(prefix)

    def list_files(self) -> list[str]:
        blobs = self.client.list_blobs(name_starts_with=self.prefix or None)
        return sorted(b.name[len(self.prefix):] for b in blobs)

    def full_path(self, key: str) -> str:
        return f"{self.client.url.rstrip('/')}/{self.prefix}{key}"

    def read(self, key: str) -> bytes:
        return self.client.download_blob(self.prefix + key).readall()

    def open(self, key: str):
        name = self.prefix + key
        size = self.client.get_blob_client(name).get_blob_properties().size
        return remote_stream(size, lambda offset, length: self.client.download_blob(
            name, offset=offset, length=length).readall())

    def write(self, key: str, data: bytes) -> None:
        self.client.upload_blob(self.prefix + key, data, overwrite=True)


class S3Storage:
    def __init__(self, client, bucket: str, prefix: str = ""):
        self.client = client
        self.bucket = bucket
        self.prefix = _as_prefix(prefix)

    def list_files(self) -> list[str]:
        keys = []
        pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix)
        for page in pages:
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith("/"):
                    keys.append(obj["Key"][len(self.prefix):])
        return sorted(keys)

    def full_path(self, key: str) -> str:
        return f"s3://{self.bucket}/{self.prefix}{key}"

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self.prefix + key)["Body"].read()

    def open(self, key: str):
        name = self.prefix + key
        size = self.client.head_object(Bucket=self.bucket, Key=name)["ContentLength"]
        return remote_stream(size, lambda offset, length: self.client.get_object(
            Bucket=self.bucket, Key=name, Range=f"bytes={offset}-{offset + length - 1}")["Body"].read())

    def write(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data)


def make_storage(settings):
    """The storage for SOURCE_TYPE. For azure and aws, CATALOGUE_DIR is
    <container or bucket>/<directory inside it>."""
    kind = settings.source_type
    if kind == "local":
        return LocalStorage(settings.catalogue_dir, settings.disk_name)
    if kind not in ("azure", "aws"):
        raise ValueError("SOURCE_TYPE must be local, azure or aws")
    top, _, prefix = settings.catalogue_dir.strip("/").partition("/")
    if kind == "azure":
        for name, value in (("AZURE_STORAGE_ACCOUNT", settings.azure_storage_account),
                            ("AZURE_STORAGE_ACCOUNT_KEY", settings.azure_storage_account_key)):
            if not value:
                raise ValueError(f"{name} is not set in .env")
        from azure.storage.blob import BlobServiceClient
        service = BlobServiceClient(
            account_url=f"https://{settings.azure_storage_account}.blob.core.windows.net",
            credential=settings.azure_storage_account_key,
        )
        return AzureStorage(service.get_container_client(top), prefix)
    import boto3
    client = boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
        region_name=settings.aws_region or None,
    )
    return S3Storage(client, top, prefix)
