# Just use public pypi
export UV_EXTRA_INDEX_URL := ""

lock:
    uv lock

sync:
    uv sync
