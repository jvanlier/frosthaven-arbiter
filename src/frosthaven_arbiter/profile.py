"""Campaign Context and Unlocked Scopes persistence.

`ProfileManager` is the single seam for reading and replacing the saved
Campaign Context and Unlocked Scopes. It rejects unknown scope keys so
that unlocking always refers to scopes discovered during synchronization.
"""

from __future__ import annotations

from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import Profile


class UnknownScopeError(ValueError):
    def __init__(self, unknown_keys: frozenset[str]) -> None:
        super().__init__(f"unknown spoiler scope keys: {sorted(unknown_keys)}")
        self.unknown_keys = unknown_keys


class ProfileManager:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self) -> Profile:
        with self._database.connect() as conn:
            context_row = conn.execute("SELECT context_text FROM campaign_profile WHERE singleton_id = 1").fetchone()
            scope_rows = conn.execute("SELECT scope_key FROM unlocked_scopes").fetchall()
        context_text = context_row["context_text"] if context_row else ""
        return Profile(
            campaign_context=context_text,
            unlocked_scope_keys=frozenset(row["scope_key"] for row in scope_rows),
        )

    def replace(self, campaign_context: str, unlocked_scope_keys: set[str]) -> Profile:
        with self._database.transaction() as conn:
            known = {row["scope_key"] for row in conn.execute("SELECT scope_key FROM spoiler_scopes").fetchall()}
            unknown = frozenset(unlocked_scope_keys) - known
            if unknown:
                raise UnknownScopeError(unknown)

            conn.execute(
                "UPDATE campaign_profile SET context_text = ?, updated_at = datetime('now') WHERE singleton_id = 1",
                (campaign_context,),
            )
            conn.execute("DELETE FROM unlocked_scopes")
            conn.executemany(
                "INSERT INTO unlocked_scopes (scope_key, unlocked_at) VALUES (?, datetime('now'))",
                [(key,) for key in unlocked_scope_keys],
            )
        return self.get()

    def known_scopes(self) -> tuple[tuple[str, str], ...]:
        """Return (scope_key, label) pairs for every discovered spoiler scope."""
        with self._database.connect() as conn:
            rows = conn.execute("SELECT scope_key, label FROM spoiler_scopes ORDER BY label").fetchall()
        return tuple((row["scope_key"], row["label"]) for row in rows)
