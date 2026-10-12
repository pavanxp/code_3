"""The run: one video at a time, in every directory under the working
directory. For each video: find its metadata, check the required fields, add
catalogue_path to the metadata at the source, then update the DB."""
import csv
import os
import posixpath
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from catalogue.config import METADATA_FIELDS, REQUIRED_FIELDS
from catalogue.db import save_video
from catalogue.mcapmeta import read_mcap_metadata
from catalogue.versions import version_of
from catalogue.metadata import MetadataError, add_catalogue_path, is_video, lookup, metadata_names, parse


def skipped_file_name(catalogue_dir: str) -> str:
    """One skipped file per working directory set in .env."""
    return "skipped_" + re.sub(r"[^A-Za-z0-9]+", "_", catalogue_dir).strip("_") + ".csv"


def _process(storage, settings, collection, apply, db_lock, folder, names, video):
    """One video, start to finish. Returns (video path, reason skipped or
    None, lines to print)."""
    video_path = storage.full_path(posixpath.join(folder, video))

    meta_keys = [posixpath.join(folder, n) for n in metadata_names(video, names)]

    # an .mcap carries its metadata inside the file; it may have no file beside it
    inside, mcap_problem = {}, None
    if video.lower().endswith(".mcap"):
        try:
            with storage.open(posixpath.join(folder, video)) as stream:
                inside = read_mcap_metadata(stream)
        except Exception as e:
            mcap_problem = f"could not read the .mcap ({type(e).__name__})"

    if not meta_keys and not inside:
        if mcap_problem:
            return video_path, mcap_problem, []
        if video.lower().endswith(".mcap"):
            return video_path, "no metadata inside the .mcap and no metadata file beside it", []
        return video_path, "no metadata file (.json or .txt) with the video's name", []
    try:
        contents = {key: storage.read(key) for key in meta_keys}
        parsed = [parse(key, data) for key, data in contents.items()]
        updated = {key: add_catalogue_path(key, data, video_path) for key, data in contents.items()}
    except MetadataError as e:
        return video_path, str(e), []
    if inside:
        parsed.append(inside)

    # checked before anything is written: a failing video is left untouched
    fields = {"file_name": video, "path": video_path, "contractor_name": settings.contractor_name}
    for db_field in METADATA_FIELDS:
        for doc in parsed:
            value = lookup(doc, settings.field_names[db_field])
            if value is not None:
                fields[db_field] = value
                break
    if video.lower().endswith(".mcap"):
        # an .mcap whose metadata says nothing about the device
        fields.setdefault("device_type", "")
        fields.setdefault("device_model", "")
    missing = [f for f in REQUIRED_FIELDS if f not in fields]
    if missing:
        return video_path, " and ".join(missing) + " not present in the metadata", []

    changed = [key for key in meta_keys if updated[key] is not contents[key]]
    if not apply:
        lines = [video_path]
        for key in meta_keys:
            state = "add catalogue_path" if key in changed else "already has catalogue_path"
            lines.append(f"    metadata {storage.full_path(key)}: {state}")
        if inside:
            lines.append("    metadata read from inside the .mcap (the .mcap itself is not changed)")
        lines.append(f"    DB fields: {fields}")
        return video_path, None, lines
    for key in changed:
        storage.write(key, updated[key])
    # one at a time, so two videos can never be given the same video_id
    with db_lock:
        video_id, action = save_video(collection, fields, settings.video_id_prefix)
    return video_path, None, [f"{video_path}: metadata updated in {len(changed)} file(s), DB {action} as {video_id}"]


def run(storage, settings, *, collection=None, apply: bool = False, out=print, skipped_dir: str = ".",
        workers: int | None = None, limit: int | None = None):
    """Returns (number of videos done, [(video path, reason skipped)]).
    Videos are worked on in parallel, one worker per CPU core by default."""
    by_dir: dict[str, list[str]] = {}
    for key in storage.list_files():
        by_dir.setdefault(posixpath.dirname(key), []).append(posixpath.basename(key))

    done = 0
    skipped: list[tuple[str, str]] = []
    shapes: Counter = Counter()
    jobs = []
    for folder in sorted(by_dir):
        names = sorted(by_dir[folder])
        videos = [n for n in names if is_video(n)]
        if videos:
            shapes[version_of(names)] += 1
        jobs += [(folder, names, video) for video in videos]

    workers = workers or os.cpu_count() or 1
    found = len(jobs)
    if limit is not None:
        jobs = jobs[:limit]
    out(f"{found} video(s) found, working on {len(jobs)} with {workers} worker(s)")
    db_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda job: _process(storage, settings, collection, apply, db_lock, *job), jobs)
        for video_path, reason, lines in results:
            if reason is not None:
                skipped.append((video_path, reason))
                continue
            for line in lines:
                out(line)
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
    out("directory versions found:")
    for shape, count in sorted(shapes.items()):
        out(f"    {shape}: {count} director{'y' if count == 1 else 'ies'}")
    out(f"videos {'done' if apply else 'ready'}: {done}, skipped: {len(skipped)}")
    if skipped:
        out(f"skipped videos are listed in {path}")
    return done, skipped
