"""Writing one video's document to the DB (MongoDB)."""
import re

VIDEO_ID_LENGTH = 12


def _next_video_id(collection, prefix: str) -> str:
    digits = VIDEO_ID_LENGTH - len(prefix)
    pattern = f"^{re.escape(prefix)}\\d{{{digits}}}$"
    # fixed width, so the highest id is also the last in text order
    last = collection.find_one({"video_id": {"$regex": pattern}}, sort=[("video_id", -1)])
    number = int(last["video_id"][len(prefix):]) + 1 if last else 1
    return f"{prefix}{number:0{digits}d}"


def save_video(collection, fields: dict, prefix: str) -> tuple[str, str]:
    """Add the video's document, or update the one already there for its
    path. Returns (video_id, "added" or "updated")."""
    existing = collection.find_one({"path": fields["path"]})
    if existing is None:
        video_id = _next_video_id(collection, prefix)
        collection.insert_one({"video_id": video_id, **fields})
        return video_id, "added"
    video_id = existing.get("video_id") or _next_video_id(collection, prefix)
    collection.update_one({"_id": existing["_id"]}, {"$set": {**fields, "video_id": video_id}})
    return video_id, "updated"
