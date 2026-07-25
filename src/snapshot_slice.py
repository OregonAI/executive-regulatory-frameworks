"""snapshot_slice_module (corpus.yml: plugins.snapshot_slice_module) — the
ITCS/ORS-chapter/OAR shared-snapshot slicing rules already live in
repo_lib.snapshot_slice() and already match the toolkit's expected
`(doc_id, snapshot_id, raw_text) -> str` signature exactly; this is just the
adapter so the toolkit doesn't need to know that function's name."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repo_lib import snapshot_slice as slice  # noqa: A002 (module attr name, not a call site)
