# NexAgent Wiki Knowledge Base Design

## Context

NexAgent already has a lightweight LLM Wiki flow:

- `backend/packages/core/nexagent/services/wiki_service.py` stores generated Markdown pages under `.nexagent/wiki`.
- `backend/app/gateway/routers/wiki.py` exposes global `/api/wiki/*` endpoints.
- `frontend/src/components/chat/WikiModal.tsx` can distill a conversation and optionally push the Markdown into a normal knowledge base.
- `frontend/src/app/knowledge/wiki/page.tsx` browses those global pages.

This is not a real knowledge base. It does not use the normal file lifecycle, does not expose a `wiki` KB type, cannot be selected or searched as a first-class KB in the same way as Milvus/LightRAG, and lacks the page graph, lint, candidates, and manual editing workflows from `/Users/baba/项目/a-yuxi`.

The reference implementation in `a-yuxi` treats Wiki as a dedicated knowledge base backend:

- `backend/package/yuxi/knowledge/implementations/wiki/*` stores Markdown pages with YAML frontmatter.
- Source files are parsed and compiled into source/topic/entity/synthesis/note pages.
- Wiki pages support wikilinks, graph edges, lint checks, repair candidates, and conversation crystallization.
- Frontend `WikiWorkbench.vue` provides source management, pages, graph, lint, and crystallization in one workspace.

## Goals

Implement NexAgent's Wiki as a first-class knowledge base type that users can create, upload sources into, compile, browse, search, and use from Agent runs.

The implementation should:

- Add `wiki` to the local `KnowledgeBase` backend system.
- Keep Wiki content Markdown-first with frontmatter and stable page IDs.
- Reuse NexAgent's upload, parse, task, search, and frontend knowledge hub conventions.
- Preserve current global Wiki endpoints as a compatibility layer where reasonable, but move the primary workflow into per-KB endpoints.
- Improve weak parts of the reference implementation instead of copying them blindly.

## Non-Goals

- Do not make Wiki pages depend on Milvus vectors or Neo4j triples.
- Do not require an embedding model to create a Wiki KB.
- Do not migrate old `.nexagent/wiki/index.json` pages automatically in the first implementation.
- Do not build a separate database schema for Wiki pages in the first implementation; local Markdown files are the source of truth for the local backend.
- Do not attempt full production Postgres/MinIO parity before the local Wiki backend works end-to-end.

## Chosen Approach

Use a dedicated `KBType.WIKI` backend.

This mirrors the useful shape of `a-yuxi` while fitting NexAgent's current abstractions:

- `KnowledgeBase` keeps owning file upload, parsing, metadata, state transitions, and deletion.
- `WikiKB` implements `_do_index`, `_do_search`, `_do_delete_kb`, and `_do_delete_file`.
- Wiki-specific APIs live under `/api/knowledge/{kb_id}/wiki/*`.
- Frontend Wiki UI is integrated into `/knowledge/[id]` when `kb.kb_type === "wiki"`, with a dedicated graph route for larger visualization.

Rejected alternatives:

- Keeping the global Markdown notebook and only improving UI would preserve the current architectural split.
- Storing Wiki pages as Milvus chunks would make search easy but lose Wiki-specific maintenance, links, page types, and review workflows.

## Backend Design

### Data Model

Extend `KBType`:

```python
class KBType(StrEnum):
    MILVUS = "milvus"
    LIGHTRAG = "lightrag"
    WIKI = "wiki"
```

Wiki page types:

- `source`
- `topic`
- `entity`
- `synthesis`
- `comparison`
- `query`
- `note`

Confidence values:

- `EXTRACTED`
- `INFERRED`
- `AMBIGUOUS`
- `UNVERIFIED`

Markdown page frontmatter:

```yaml
id: topic:transformer-architecture
title: Transformer Architecture
type: topic
sources:
  - file-id
confidence: EXTRACTED
updated_at: 2026-06-08T00:00:00+00:00
manual_edited: false
version: 1
```

Local layout under `NEXAGENT_DATA_DIR/knowledge/wiki/<kb_id>/`:

```text
files/
parsed/
wiki/
  sources/
  topics/
  entities/
  synthesis/
  comparisons/
  queries/
  notes/
.wiki-cache.json
.wiki-state.json
index.md
log.md
purpose.md
```

### WikiKB Modules

Add a package:

```text
backend/packages/core/nexagent/knowledge/implementations/wiki/
  __init__.py
  constants.py
  storage.py
  links.py
  compile.py
  graph.py
  lint.py
  repair.py
  kb.py
```

`kb.py` exposes `WikiKB`.

The mixins keep responsibilities small:

- `WikiStorageMixin`: layout, frontmatter read/write, atomic writes, state/cache.
- `WikiLinksMixin`: wikilink extraction, normalization, title resolution, snippets.
- `WikiCompileMixin`: LLM JSON compile, validation, repair prompt, source/topic/entity/synthesis generation.
- `WikiGraphMixin`: page graph with wikilink, source-overlap, common-neighbor, and type-affinity signals.
- `WikiLintMixin`: broken links, duplicate titles, missing sources, orphan pages, stale compile cache.
- `WikiRepairMixin`: optional LLM repair candidate generation.

### Backend Registration

Update `KnowledgeBaseManager._create_backend`:

- `milvus` -> `MilvusKB`
- `lightrag` -> `LightRagKB`
- `wiki` -> `WikiKB`

Update manager helpers:

- default query config for `wiki`: `mode="wiki"`, `final_top_k=10`
- available modes for `wiki`: `["wiki"]`
- query options for `wiki`: top-k only
- diagnostics to include Wiki page counts, compile status, and lint issues

### Create KB Behavior

`KBCreateRequest.kb_type` accepts `wiki`.

Wiki creation:

- Requires `name`.
- Does not require `embed_model`.
- Uses `llm_info` from the selected chat model if supplied, otherwise falls back to normal NexAgent model loading during compile.
- Saves purpose text from description in `purpose.md`.

For local storage, `WikiKB.create_kb` can override base creation enough to ensure the Wiki layout. It should still use `KBMeta` and the normal metadata file.

### Index/Compile Behavior

For a parsed file:

1. Read `file_meta.parsed_path`.
2. Build an LLM compile prompt with:
   - Wiki purpose
   - filename
   - headings
   - entity candidates
   - parsed markdown up to a conservative limit
3. Ask the model for JSON:
   - `source`
   - `topics`
   - `entities`
   - optional `synthesis`
4. Validate and sanitize JSON.
5. Write source/topic/entity pages with frontmatter.
6. Refresh `Wiki Synthesis`.
7. Refresh `index.md`.
8. Save compile cache with source content hash, model spec, and prompt version.
9. Return page count as `chunk_count`.

Improvement from `a-yuxi`: topics/entities are capped, but not forced. The prompt may request useful pages, and validation accepts zero generated topics/entities when source material is too small.

Manual pages are protected:

- If a generated page would overwrite a manually edited page, store it as a candidate in `.wiki-state.json`.
- Users can accept or discard the candidate.

### Search Behavior

`WikiKB._do_search` returns `SearchResult` objects.

Scoring:

- title hit: high weight
- body hit: count-based weight
- wikilink hit: medium weight
- source filename hit: medium weight
- confidence and type may be included in metadata, not as primary ranking.

Each result includes:

- content snippet
- page title as source
- source file IDs
- page ID
- page type
- confidence
- match reasons

This allows `knowledge_search` to cite Wiki pages using the same evidence formatting as other KBs.

### Wiki API

Add endpoints under `backend/app/gateway/routers/knowledge.py`:

- `POST /api/knowledge/{kb_id}/wiki/compile`
- `GET /api/knowledge/{kb_id}/wiki/pages`
- `GET /api/knowledge/{kb_id}/wiki/pages/{page_id}`
- `PUT /api/knowledge/{kb_id}/wiki/pages/{page_id}`
- `DELETE /api/knowledge/{kb_id}/wiki/pages/{page_id}`
- `POST /api/knowledge/{kb_id}/wiki/pages/{page_id}/accept-generated`
- `POST /api/knowledge/{kb_id}/wiki/pages/{page_id}/discard-generated`
- `GET /api/knowledge/{kb_id}/wiki/graph`
- `GET /api/knowledge/{kb_id}/wiki/lint`
- `POST /api/knowledge/{kb_id}/wiki/repair`
- `POST /api/knowledge/{kb_id}/wiki/crystallize`

These endpoints validate that the target KB is `wiki`.

Compile and repair use NexAgent's existing task registry:

- kind `wiki_compile`
- kind `wiki_repair`
- progress is updated per processed file or repaired page
- cancellation checks use `is_cancel_requested`

### Conversation Crystallization

Replace the primary behavior of `crystallize_thread`:

- Require a target Wiki KB for first-class crystallization.
- Load conversation messages.
- Ask an LLM to produce a concise Markdown page.
- Register the Markdown as a source file in the target Wiki KB.
- Create a `note` or `query` page with `manual_edited=True`, `confidence=UNVERIFIED`.
- Best-effort parse/index the source file through the Wiki backend.

Compatibility:

- Keep global `/api/wiki/crystallize` for existing UI calls during transition.
- When `kb_id` is a Wiki KB, route to the new per-KB service.
- When `kb_id` is omitted, allow the old local notebook path for now.
- When `kb_id` is Milvus/LightRAG, return a clear warning or reject depending on route; the main UI should only offer Wiki KBs for Wiki crystallization.

### Production Storage

NexAgent defaults to `knowledge.storage_backend: postgres`, but the current production service only branches Milvus vs LightRAG. Wiki still needs to work in that default app mode.

Phase 1 uses a hybrid storage strategy:

- Milvus and LightRAG continue to use `ProductionKnowledgeService` when production mode is enabled.
- Wiki KBs always use the local `KnowledgeBaseManager` backend under `NEXAGENT_DATA_DIR/knowledge/wiki`.
- `GET /api/knowledge/` merges production KBs with local Wiki KBs and marks Wiki items with `extra.storage = "local_wiki"`.
- `POST /api/knowledge/` routes `kb_type="wiki"` to the local manager even when production mode is enabled.
- Per-file and per-wiki endpoints route Wiki KB IDs to the local manager and non-Wiki production KB IDs to production service.
- Wiki diagnostics includes `storage: "local_wiki"` so users can see the storage difference.

This is not full Postgres/MinIO parity, but it makes Wiki usable in the default NexAgent configuration without forcing a second schema migration. A later phase can add object-store page persistence and page metadata records if deployment needs require fully centralized Wiki storage.

## Frontend Design

### Knowledge List

Update `KBMeta.kb_type` to include `wiki`.

Create dialog behavior:

- Type selector has three options: Vector RAG, LightRAG Graph, Wiki.
- Embedding section is hidden or disabled for Wiki.
- LLM section is shown for Wiki compile model selection when model providers are available.
- Submit validation:
  - Milvus/LightRAG require embedding.
  - Wiki requires name and can use default chat model.

Stats:

- Count Wiki KBs from `fetchKBs`, not global wiki pages.
- The old `LLM Wiki` built-in card can be removed or replaced by a compatibility link only if old pages exist.

### Knowledge Detail

When `kb.kb_type === "wiki"`, render a Wiki-specific workbench instead of the Milvus/LightRAG model/retrieval panel.

Workbench sections:

- Sources: upload files, process pending files, show compile status and failed source results.
- Pages: filter by type/status/source/search, read Markdown, edit, save, delete, accept/discard candidates.
- Graph: show page graph with React Flow, filters for type and weak edges.
- Health: lint issue list, issue severity, actions to recompile or open page.
- Crystallize: manual note/query page form with title, type, confidence, sources, and Markdown body.

Use existing UI style: compact workbench panels, no marketing page, no nested decorative cards.

### Dedicated Graph Page

Add `/knowledge/[id]/wiki/graph` or reuse a tab-level full view. The graph uses `reactflow`, already installed.

Nodes:

- source: blue
- topic: green
- entity: violet
- synthesis: amber
- note/query: slate

Edges:

- explicit wikilink edges are stronger and visually darker.
- inferred edges are lighter.

### Chat Wiki Modal

Update `WikiModal`:

- Only list `kbs.filter(kb => kb.kb_type === "wiki")`.
- Require selecting a Wiki KB before starting first-class crystallization.
- Allow page type `note` or `query`.
- Show warnings from the backend.
- Link to the generated page in the target Wiki KB.

## Error Handling

- Missing KB: `404`.
- Non-Wiki KB passed to Wiki route: `400`.
- Compile without usable LLM: structured `400` with a message telling the user to configure a chat model.
- Invalid page type/confidence: `400`.
- Broken LLM JSON: retry once with repair prompt, then mark file `index_error`.
- Parse/index errors retain normal `FileStatus` transitions.
- Deleting a source file marks the Wiki stale and removes source pages that depend only on that file.

## Testing

Follow TDD during implementation.

Backend unit tests:

- `KBType.WIKI` registration and manager discovery.
- Wiki KB create creates layout and metadata.
- Indexing parsed Markdown writes source/topic/entity/synthesis pages.
- Reindex skips unchanged files unless forced.
- Manual page protection creates candidates.
- Search returns Wiki `SearchResult` with page metadata.
- Graph uses wikilink and source-overlap signals.
- Lint reports broken links, missing sources, stale compile cache.
- Crystallization rejects non-Wiki KBs and writes source + note for Wiki KBs.
- Routes delegate to WikiKB and validate KB type.

Frontend tests or lint/build checks:

- Type unions include `wiki`.
- Create form does not require embedding for Wiki.
- Chat Wiki modal filters to Wiki KBs.
- Wiki API client encodes page IDs.

Verification commands:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py tests/unit/test_wiki_routes.py tests/unit/test_wiki_service.py
cd backend && uv run pytest tests/unit/test_knowledge_agent_tool.py
cd frontend && npm run lint
```

Run broader tests if shared manager/search behavior changes:

```bash
cd backend && uv run pytest tests/unit/test_knowledge_upload_lifecycle.py tests/unit/test_knowledge_search_modes.py
```

## Migration Strategy

The existing global Wiki notebook remains available during the transition:

- `/knowledge/wiki` continues to browse old global pages.
- New Wiki KBs appear in the normal knowledge list.
- Chat crystallization defaults to Wiki KBs.

Later, a migration utility can copy `.nexagent/wiki/*.md` into a selected Wiki KB as `note` pages.

## Decisions

- Wiki uses local Markdown storage in both legacy and production app modes for the first implementation.
- The current global Wiki feature remains as compatibility and is not removed.
- Full Postgres/MinIO-backed Wiki page storage is intentionally deferred.

## Acceptance Criteria

- Users can create a Wiki KB from the knowledge hub.
- Users can upload Markdown/text/documents to the Wiki KB and process them.
- Processing a source compiles Markdown Wiki pages with frontmatter.
- Users can browse, filter, edit, delete, and review generated candidates.
- Users can see a Wiki page relationship graph.
- Users can run health checks and see actionable issues.
- Agent `knowledge_search` can search Wiki KBs and cite Wiki pages.
- Chat crystallization can create a Wiki page inside a selected Wiki KB.
- Default NexAgent production mode can create, list, open, process, and search Wiki KBs via the local Wiki backend.
- Existing global Wiki pages are not deleted or broken.
- Backend unit tests and frontend lint pass for the touched surface.
