# Frosthaven Arbiter

Local Frosthaven rules arbitration backed by authoritative rulebook and FAQ sources.

## Run Locally

The Arbiter requires a chat and an embedding `llama-server` process. Keep each running in its own terminal.

### 1. Start The Chat Model

From the repository root, run:

```bash
just serve-chat
```

### 2. Start The Embedding Model

From the repository root, run:

```bash
just serve-embed
```

The `serve-embed` recipe sets `--ubatch-size 1024`, which is required for the longest indexed source chunks.

### 3. Synchronize Authoritative Sources

From the repository root, run:

```bash
just sync-sources
```

Run synchronization once before first use and again whenever the indexed rulebook or FAQ should be refreshed.

### 4. Start The Web Interface

```bash
just serve
```

Open <http://127.0.0.1:8088>.

## Local Ports

| Service | Address |
| --- | --- |
| Chat model | `http://127.0.0.1:8080` |
| Embedding model | `http://127.0.0.1:8081` |
| Web interface | `http://127.0.0.1:8088` |
