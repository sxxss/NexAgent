from __future__ import annotations

import re

WIKI_PAGE_TYPES = {"source", "entity", "topic", "synthesis", "comparison", "query", "note"}
CONFIDENCE_VALUES = {"EXTRACTED", "INFERRED", "AMBIGUOUS", "UNVERIFIED"}
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:[|#][^\]]*)?\]\]")
WIKI_PROMPT_VERSION = "2026-06-08-v1"
NOISE_WIKILINKS = {"content", "contents", "目录", "tableofcontents"}
