"""The run: one video at a time, in every directory under the working
directory. For each video: find its metadata, check the required fields, add
catalogue_path to the metadata at the source, then update the DB."""
import csv
import os
import posixpath
import re
from collections import Counter

from catalogue.config import METADATA_FIELDS, REQUIRED_FIELDS
from catalogue.db import save_video
from catalogue.metadata import MetadataError, add_catalogue_path, is_video, lookup, metadata_names, parse


def skipped_file_name(catalogue_dir: str) -> str:
    """One skipped file per working directory set in .env."""
    return "skipped_" + re.sub(r"[^A-Za-z0-9]+", "_", catalogue_dir).strip("_") + ".csv"


def _shape(names: list[str]) -> str:
    """A directory's version: the file formats found together in it."""
    exts = {os.path.splitext(n)[1].lower() or "(none)" for n in names}
    return " + ".join(sorted(exts))


def run(storage, settings, *, collection=None, apply: bool = False, out=print, skipped_dir: str = "."):
    """Returns (number of videos done, [(video path, reason skipped)])."""
    by_dir: dict[str, list[str]] = {}
    for key in storage.list_files():
        by_dir.setdefault(posixpath.dirname(key), []).append(posixpath.basename(key))

    done = 0
    skipped: list[tuple[str, str]] = []
    shapes: Counter = Counter()

    for folder in sorted(by_dir):
        names = sorted(by_dir[folder])
        videos = [n for n in names if is_video(n)]
        if videos:
            shapes[_shape(names)] += 1
        for video in videos:
            video_path = storage.full_path(posixpath.join(folder, video))

            meta_keys = [posixpath.join(folder, n) for n in metadata_names(video, names)]
            if not meta_keys:
                skipped.append((video_path, "no metadata file (.json or .txt) with the video's name"))
                continue
            try:
                contents = {key: storage.read(key) for key in meta_keys}
                parsed = [parse(key, data) for key, data in contents.items()]
                updated = {key: add_catalogue_path(key, data, video_path) for key, data in contents.items()}
            except MetadataError as e:
                skipped.append((video_path, str(e)))
                continue

            # checked before anything is written: a failing video is left untouched
            fields = {"file_name": video, "path": video_path}
            for db_field in METADATA_FIELDS:
                for doc in parsed:
                    value = lookup(doc, settings.field_names[db_field])
                    if value is not None:
                        fields[db_field] = value
                        break
            missing = [f for f in REQUIRED_FIELDS if f not in fields]
            if missing:
                skipped.append((video_path, " and ".join(missing) + " not present in the metadata"))
                continue

            changed = [key for key in meta_keys if updated[key] is not contents[key]]
            if apply:
                for key in changed:
                    storage.write(key, updated[key])
                video_id, action = save_video(collection, fields, settings.video_id_prefix)
                out(f"{video_path}: metadata updated in {len(changed)} file(s), DB {action} as {video_id}")
            else:
                out(f"{video_path}")
                for key in meta_keys:
                    state = "add catalogue_path" if key in changed else "already has catalogue_path"
                    out(f"    metadata {storage.full_path(key)}: {state}")
                out(f"    DB fields: {fields}")
            done += 1

    path = os.path.join(skipped_dir, skipped_file_name(settings.catalogue_dir))
    if skipped:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["path", "reason"])
            writer.writerows(skipped)
    elif os.path.exists(path):
        os.remove(path)

    out("")
    out("directory versions found (file formats together in one directory):")
    for shape, count in sorted(shapes.items()):
        out(f"    {shape}: {count} director{'y' if count == 1 else 'ies'}")
    out(f"videos {'done' if apply else 'ready'}: {done}, skipped: {len(skipped)}")
    if skipped:
        out(f"skipped videos are listed in {path}")
    return done, skipped
