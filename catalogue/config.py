"""Settings, all from the .env file in the project folder."""
import re
from dataclasses import dataclass, field
from typing import Mapping

# DB fields filled from the metadata, and the two that must be present
METADATA_FIELDS = ("task_name", "task_difficulty", "l1", "device_model", "task_category", "device_type")
REQUIRED_FIELDS = ("task_category", "device_type")


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    catalogue_dir: str
    source_type: str = "local"
    disk_name: str = ""
    azure_storage_account: str = ""
    azure_storage_account_key: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = ""
    db_connection_string: str = ""
    db_name: str = ""
    db_collection: str = ""
    video_id_prefix: str = "VID"
    field_names: dict = field(default_factory=dict)


def read_env_file(path: str) -> dict:
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            env[key.strip()] = value
    return env


def load_settings(env: Mapping[str, str]) -> Settings:
    def get(name: str, default: str = "") -> str:
        return (env.get(name) or "").strip() or default

    catalogue_dir = get("CATALOGUE_DIR")
    if not catalogue_dir:
        raise ConfigError("CATALOGUE_DIR is not set in .env")
    source_type = get("SOURCE_TYPE", "local").lower()
    if source_type not in ("local", "azure", "aws"):
        raise ConfigError("SOURCE_TYPE must be local, azure or aws")
    disk_name = get("DISK_NAME")
    if source_type == "local" and not disk_name:
        raise ConfigError("DISK_NAME is not set in .env (the hard disk's name, e.g. volume 1)")
    prefix = get("VIDEO_ID_PREFIX", "VID")
    if not re.fullmatch(r"[A-Za-z0-9]{0,11}", prefix):
        raise ConfigError("VIDEO_ID_PREFIX must be letters and digits only, 11 characters at most")
    names = {}
    for db_field in METADATA_FIELDS:
        listed = [n.strip() for n in get(f"META_{db_field.upper()}_FIELDS").split(",") if n.strip()]
        names[db_field] = listed or [db_field]
    return Settings(
        catalogue_dir=catalogue_dir,
        source_type=source_type,
        disk_name=disk_name if source_type == "local" else "",
        azure_storage_account=get("AZURE_STORAGE_ACCOUNT"),
        azure_storage_account_key=get("AZURE_STORAGE_ACCOUNT_KEY"),
        aws_access_key_id=get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=get("AWS_SECRET_ACCESS_KEY"),
        aws_region=get("AWS_REGION"),
        db_connection_string=get("DB_CONNECTION_STRING"),
        db_name=get("DB_NAME"),
        db_collection=get("DB_COLLECTION"),
        video_id_prefix=prefix,
        field_names=names,
    )
