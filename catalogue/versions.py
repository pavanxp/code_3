"""The known directory structures ("versions"): the file formats found
together in one directory. A new structure is added here with the next name."""

VERSIONS = {
    # e.g. xphirobotics-000002-027.aac / .json / .mp4 / .txt in one folder
    "v1": (".aac", ".json", ".mp4", ".txt"),
}


def formats_of(names: list[str]) -> tuple[str, ...]:
    exts = set()
    for name in names:
        dot = name.rfind(".")
        exts.add(name[dot:].lower() if dot > 0 else "(none)")
    return tuple(sorted(exts))


def version_of(names: list[str]) -> str:
    """The version label for a directory holding these files."""
    formats = formats_of(names)
    shape = " + ".join(formats)
    for label, wanted in VERSIONS.items():
        if formats == tuple(sorted(wanted)):
            return f"{label} ({shape})"
    return f"not a known version ({shape})"
