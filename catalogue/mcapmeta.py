"""Reading the metadata records stored inside an .mcap file. Only the
file's index and its metadata records are read, never the whole file."""
import io
import json


class RangeStream(io.RawIOBase):
    """A seekable read-only view of a remote file, fetched a range at a time."""

    def __init__(self, size: int, fetch):
        self._size = size
        self._fetch = fetch          # fetch(offset, length) -> bytes
        self._pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._size}[whence]
        self._pos = max(0, base + offset)
        return self._pos

    def readinto(self, buffer):
        length = min(len(buffer), self._size - self._pos)
        if length <= 0:
            return 0
        data = self._fetch(self._pos, length)
        buffer[:len(data)] = data
        self._pos += len(data)
        return len(data)


def remote_stream(size: int, fetch):
    return io.BufferedReader(RangeStream(size, fetch), buffer_size=1024 * 1024)


def _value(text):
    # "unknown" is what the MCAP writer puts for a value it did not have
    if isinstance(text, str):
        stripped = text.strip()
        if stripped.lower() == "unknown":
            return None
        if stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except ValueError:
                pass
    return text


def read_mcap_metadata(stream) -> dict:
    """{record name: {field: value}} for every metadata record in the file;
    empty when the file has no index or no metadata records."""
    from mcap.reader import make_reader
    reader = make_reader(stream)
    if reader.get_summary() is None:
        return {}
    records = {}
    for record in reader.iter_metadata():
        records.setdefault(record.name, {}).update({k: _value(v) for k, v in record.metadata.items()})
    return records
