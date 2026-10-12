"""python -m catalogue           show what would be changed, write nothing
python -m catalogue --apply   update the metadata at the source and the DB
python -m catalogue --limit N   work on only the first N videos found"""
import argparse
import sys

from catalogue.config import ConfigError, load_settings, read_env_file
from catalogue.runner import run
from catalogue.storage import make_storage


def _collection(settings):
    for name, value in (("DB_CONNECTION_STRING", settings.db_connection_string), ("DB_NAME", settings.db_name),
                        ("DB_COLLECTION", settings.db_collection)):
        if not value:
            raise ConfigError(f"{name} is not set in .env")
    from pymongo import MongoClient
    client = MongoClient(settings.db_connection_string, serverSelectionTimeoutMS=10000)
    try:
        client.admin.command("ping")
    except Exception as e:
        # the message never includes the connection string
        raise ConfigError(f"could not connect to the DB ({type(e).__name__})") from None
    return client[settings.db_name][settings.db_collection]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m catalogue", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the changes (without it nothing is written)")
    parser.add_argument("--limit", type=int, metavar="N", help="work on only the first N videos found")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be 1 or more")
    try:
        settings = load_settings(read_env_file(".env"))
        storage = make_storage(settings)
        collection = _collection(settings) if args.apply else None
    except (ConfigError, ValueError, FileNotFoundError) as e:
        print(f"cannot start: {e}")
        return 2
    if not args.apply:
        print("DRY RUN: nothing is written. Run again with --apply to write.\n")
    try:
        run(storage, settings, collection=collection, apply=args.apply, limit=args.limit)
    except FileNotFoundError as e:
        print(f"cannot start: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
