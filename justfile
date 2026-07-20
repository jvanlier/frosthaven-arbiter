# Just use public pypi
export UV_EXTRA_INDEX_URL := ""

lock:
    uv lock

sync:
    uv sync

sync-sources:
    uv run frosthaven-arbiter sync

serve:
    uv run frosthaven-arbiter serve

serve-chat:
    llama-server \
        -hf unsloth/Qwen3.6-27B-MTP-GGUF:Q8_0 \
        --spec-type draft-mtp \
        -ngl 999 \
        -fa on \
        -c 131072 \
        --port 8080 \
        --host 127.0.0.1

serve-embed:
    llama-server \
        -hf gpustack/bge-m3-GGUF:Q8_0 \
        --embeddings \
        --parallel 4 \
        --ubatch-size 1024 \
        -ngl 999 \
        --port 8081 \
        --host 127.0.0.1
