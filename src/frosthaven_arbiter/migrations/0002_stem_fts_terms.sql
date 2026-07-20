-- Match common inflections such as monster/monsters and move/movement.

DROP TRIGGER chunks_ai;
DROP TRIGGER chunks_ad;
DROP TRIGGER chunks_au;
DROP TABLE chunks_fts;

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    search_text,
    heading_path,
    content='chunks',
    content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
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

INSERT INTO chunks_fts(rowid, search_text, heading_path)
SELECT id, search_text, heading_path_json FROM chunks;
