-- Initial schema for the Frosthaven Arbiter authoritative vertical slice.

CREATE TABLE sources (
    source_key          TEXT PRIMARY KEY,
    display_name        TEXT NOT NULL,
    authority_label     TEXT NOT NULL,
    precedence          INTEGER NOT NULL,
    canonical_url       TEXT NOT NULL,
    repository_url      TEXT NOT NULL,
    current_revision_id INTEGER NULL
);

CREATE TABLE source_revisions (
    id                  INTEGER PRIMARY KEY,
    source_key          TEXT NOT NULL REFERENCES sources(source_key),
    commit_sha          TEXT NOT NULL,
    declared_updated_at TEXT NULL,
    retrieved_at        TEXT NOT NULL,
    artifact_url        TEXT NOT NULL,
    content_sha256      TEXT NOT NULL,
    snapshot_path       TEXT NOT NULL,
    UNIQUE(source_key, commit_sha),
    UNIQUE(source_key, content_sha256)
);

CREATE TABLE chunks (
    id                 INTEGER PRIMARY KEY,
    source_revision_id INTEGER NOT NULL REFERENCES source_revisions(id),
    position           INTEGER NOT NULL,
    section_key        TEXT NOT NULL,
    anchor             TEXT NULL,
    heading_path_json  TEXT NOT NULL,
    page_or_section    TEXT NULL,
    body               TEXT NOT NULL,
    search_text        TEXT NOT NULL,
    token_count        INTEGER NOT NULL,
    content_sha256     TEXT NOT NULL,
    visibility         TEXT NOT NULL CHECK (visibility IN ('public', 'protected')),
    UNIQUE(source_revision_id, position)
);

CREATE TABLE spoiler_scopes (
    scope_key              TEXT PRIMARY KEY,
    label                  TEXT NOT NULL,
    source_key             TEXT NOT NULL REFERENCES sources(source_key),
    first_seen_revision_id INTEGER NOT NULL REFERENCES source_revisions(id)
);

CREATE TABLE chunk_spoiler_scopes (
    chunk_id  INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    scope_key TEXT NOT NULL REFERENCES spoiler_scopes(scope_key),
    PRIMARY KEY(chunk_id, scope_key)
);

CREATE TABLE embeddings (
    id                INTEGER PRIMARY KEY,
    model_fingerprint TEXT NOT NULL,
    input_sha256      TEXT NOT NULL,
    dimensions        INTEGER NOT NULL,
    vector_f32        BLOB NOT NULL,
    norm              REAL NOT NULL,
    UNIQUE(model_fingerprint, input_sha256)
);

CREATE TABLE chunk_embeddings (
    chunk_id     INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    embedding_id INTEGER NOT NULL REFERENCES embeddings(id)
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    search_text,
    heading_path,
    content='chunks',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, search_text, heading_path)
    VALUES (new.id, new.search_text, new.heading_path_json);
END;

CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, search_text, heading_path)
    VALUES ('delete', old.id, old.search_text, old.heading_path_json);
END;

CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, search_text, heading_path)
    VALUES ('delete', old.id, old.search_text, old.heading_path_json);
    INSERT INTO chunks_fts(rowid, search_text, heading_path)
    VALUES (new.id, new.search_text, new.heading_path_json);
END;

CREATE TABLE campaign_profile (
    singleton_id    INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    context_text    TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL
);

INSERT INTO campaign_profile (singleton_id, context_text, updated_at)
VALUES (1, '', datetime('now'));

CREATE TABLE unlocked_scopes (
    scope_key    TEXT PRIMARY KEY REFERENCES spoiler_scopes(scope_key),
    unlocked_at  TEXT NOT NULL
);

CREATE TABLE conversations (
    id          INTEGER PRIMARY KEY,
    title       TEXT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE messages (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sequence_no     INTEGER NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'arbiter')),
    status          TEXT NOT NULL CHECK (status IN ('pending', 'complete', 'failed')),
    outcome_kind    TEXT NULL CHECK (outcome_kind IN ('ruling', 'abstention')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    completed_at    TEXT NULL,
    UNIQUE(conversation_id, sequence_no)
);

CREATE TABLE message_citations (
    message_id          INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    citation_id         TEXT NOT NULL,
    display_order       INTEGER NOT NULL,
    chunk_id            INTEGER NOT NULL REFERENCES chunks(id),
    source_key          TEXT NOT NULL,
    source_title        TEXT NOT NULL,
    authority_label     TEXT NOT NULL,
    heading_path_json   TEXT NOT NULL,
    page_or_section     TEXT NULL,
    anchor              TEXT NULL,
    excerpt             TEXT NOT NULL,
    revision            TEXT NOT NULL,
    canonical_url       TEXT NOT NULL,
    PRIMARY KEY(message_id, citation_id)
);

INSERT INTO sources (source_key, display_name, authority_label, precedence, canonical_url, repository_url, current_revision_id)
VALUES
    ('rulebook', 'Frosthaven Rulebook Transcription', 'Rulebook', 0, 'https://pikdonker.github.io/frosthaven-rule-book/', 'https://github.com/pikdonker/frosthaven-rule-book', NULL),
    ('faq', 'Official Frosthaven FAQ', 'Official FAQ', 1, 'https://cephalofairgames.github.io/frosthaven-faq/', 'https://github.com/CephalofairGames/frosthaven-faq', NULL);
