# Frosthaven Arbiter

Local Frosthaven rules arbitration backed by authoritative rulebook and FAQ sources.

## Run Locally

The Arbiter requires two `llama-server` processes. Keep each process running in its own terminal.

### 1. Start The Chat Model

```bash
llama-server \
  -hf unsloth/Qwen3.6-27B-MTP-GGUF:Q8_0 \
  --spec-type draft-mtp \
  -ngl 999 \
  -fa on \
  -c 131072 \
  --port 8080 \
  --host 127.0.0.1
```

### 2. Start The Embedding Model

```bash
llama-server \
  -hf gpustack/bge-m3-GGUF:Q8_0 \
  --embeddings \
  --parallel 4 \
  --ubatch-size 1024 \
  -ngl 999 \
  --port 8081 \
  --host 127.0.0.1
```

The `--ubatch-size 1024` setting is required for the longest indexed source chunks.

### 3. Synchronize Authoritative Sources

From the repository root, run:

```bash
uv run frosthaven-arbiter sync
```

Run synchronization once before first use and again whenever the indexed rulebook or FAQ should be refreshed.

### 4. Start The Web Interface

```bash
uv run frosthaven-arbiter serve
```

Open <http://127.0.0.1:8088>.

## Local Ports

| Service | Address |
| --- | --- |
| Chat model | `http://127.0.0.1:8080` |
| Embedding model | `http://127.0.0.1:8081` |
| Web interface | `http://127.0.0.1:8088` |
