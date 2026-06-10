# London Brain Data

This package data directory is reserved for the sanitized public London brain.

Expected bundled artifact:

- `london_brain.sqlite` - normalized SQLite built from vetted extraction JSON.

Raw archive inputs stay outside the package. Do not commit videos, metadata,
raw `data/extractions` JSON, historical Chroma folders, screenshots, generated
media caches, `.env` files, or local tool caches here.

Build or refresh the sanitized database with:

```bash
uv run python scripts/import_brain.py --input data/extractions --output src/london/data/london_brain.sqlite
```

SQLite is the source of truth for public installs. Chroma or any other vector
store should be treated as a derived optional index that can be rebuilt from the
SQLite file, not as a required runtime dependency.
