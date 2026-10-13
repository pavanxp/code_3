"""Finding a video's metadata file, reading fields from it, and adding
catalogue_path to it. Metadata is a .json or .txt file with the video's name."""
import json
import re

VIDEO_EXTS = (".mp4", ".mcap", ".mov")
METADATA_EXTS = (".json", ".txt")
PATH_FIELD = "catalogue_path"

# "key: value" or "key = value"; the separator is kept as the file wrote it
_LINE = re.compile(r"^(?P<key>[^:=#\s][^:=]*?)(?P<sep>\s*[:=]\s*)(?P<value>.*)$")


class MetadataError(Exception):
    """This metadata file cannot be used; the message is the reason."""


def is_video(name: str) -> bool:
    return name.lower().endswith(VIDEO_EXTS)


def metadata_names(video_name: str, names_in_dir: list[str]) -> list[str]:
    """The files in the video's directory that are its metadata: the video's
    name with a .json or .txt extension (also <name>.metadata.<ext>)."""
    stem = video_name.rsplit(".", 1)[0].lower()
    # where <name>.metadata.json exists, it alone is the metadata; the other
    # files beside it (e.g. a .txt) are left untouched
    dedicated = {stem + ".metadata.json", video_name.lower() + ".metadata.json"}
    found = sorted(n for n in names_in_dir if n.lower() in dedicated)
    if found:
        return found
    wanted = set()
    for ext in METADATA_EXTS:
        wanted |= {stem + ext, stem + ".metadata" + ext, video_name.lower() + ".metadata" + ext}
    return sorted(n for n in names_in_dir if n.lower() in wanted)


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise MetadataError("metadata is not UTF-8 text") from None


def _is_json(name: str, text: str) -> bool:
    return name.lower().endswith(".json") or text.lstrip().startswith("{")


def _json_object(text: str) -> dict:
    try:
        doc = json.loads(text)
    except ValueError:
        raise MetadataError("metadata is not valid JSON") from None
    if not isinstance(doc, dict):
        raise MetadataError("metadata is not a JSON object")
    return doc


def parse(name: str, data: bytes) -> dict:
    text = _text(data)
    if _is_json(name, text):
        return _json_object(text)
    fields = {}
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if m:
            fields[m["key"].strip()] = m["value"].strip()
    return fields


def _find(data: dict, name: str):
    """The value under `name`: the top level first, then nested objects."""
    value = data.get(name)
    if value not in (None, "") and not isinstance(value, (dict, list)):
        return value
    for child in data.values():
        if isinstance(child, dict):
            found = _find(child, name)
            if found is not None:
                return found
    return None


def lookup(data: dict, names: list[str]):
    """The first value present under any of `names`, or None."""
    for name in names:
        found = _find(data, name)
        if found is not None:
            return found
    return None


def add_catalogue_path(name: str, data: bytes, video_path: str) -> bytes:
    """The metadata with catalogue_path set to the video's path and nothing
    else changed. Returns `data` itself when it already says so."""
    text = _text(data)
    if _is_json(name, text):
        doc = _json_object(text)
        if doc.get(PATH_FIELD) == video_path:
            return data
        doc[PATH_FIELD] = video_path
        return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    lines = text.splitlines(keepends=True)
    sep = ": "
    first_sep = None
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        m = _LINE.match(body.strip())
        if not m:
            continue
        first_sep = first_sep or m["sep"]
        if m["key"].strip() == PATH_FIELD:
            if m["value"].strip() == video_path:
                return data
            lines[i] = f"{PATH_FIELD}{m['sep']}{video_path}" + line[len(body):]
            return "".join(lines).encode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    lines.append(f"{PATH_FIELD}{first_sep or sep}{video_path}{newline}")
    return "".join(lines).encode("utf-8")
