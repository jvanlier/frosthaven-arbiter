# Frosthaven Arbiter

## Problem Statement

Frosthaven rules are spread across a long rulebook and a continuously updated official FAQ. Finding and reconciling the relevant passages during play is slow, the FAQ contains spoilers, and general-purpose language models may invent rules or present community opinions as authoritative.

The user needs a laptop-only web application that can answer rules questions from cited evidence, account for the current campaign and party, protect locked content, and clearly decline to make a ruling when the available authoritative evidence is insufficient. The application must use local llama.cpp models and must not require cloud inference.

## Solution

Build a local web application named Frosthaven Arbiter. It indexes the Frosthaven Rulebook Transcription at <https://pikdonker.github.io/frosthaven-rule-book/> and the official Frosthaven FAQ at <https://cephalofairgames.github.io/frosthaven-faq/>. It retrieves relevant passages, asks a local llama.cpp model to synthesize only the supported rules, and returns a cited Ruling or an explicit Abstention.

The Arbiter has one saved Campaign Context for facts such as campaign progress and party composition. Campaign Context can help interpret a question but cannot change authority, citation, abstention, or spoiler rules. Spoiler-bearing evidence is available only through an explicit list of Unlocked Scopes. Naming locked content in a question does not unlock it.

When the Authoritative Sources cannot resolve a question, the user may explicitly start a network-enabled Community Lookup. This searches relevant Reddit and BoardGameGeek discussions and returns a separately labeled Community Interpretation with direct links. Community material never becomes a Ruling, regardless of apparent consensus.

All source snapshots, models, embeddings, configuration, profiles, conversations, and indexes remain on the laptop. Network access is limited to explicit setup, source synchronization, and Community Lookup operations.

## Domain Language

**Arbiter**: The application that answers rules questions from rule-source evidence. It does not provide strategy or campaign advice.

**Ruling**: An answer to a rules question that is grounded in cited Authoritative Source evidence.

**Authoritative Source**: An indexed Frosthaven rulebook or official FAQ that can support a Ruling.

**Rulebook Transcription**: The indexed web transcription of the Frosthaven rulebook. It is accepted as authoritative rule text despite its unofficial hosting.

**Community Source**: A non-authoritative discussion, such as a Reddit or BoardGameGeek post, that may inform an interpretation but cannot establish a Ruling.

**Community Lookup**: An explicit, network-enabled follow-up that searches Community Sources after local Authoritative Sources prove insufficient.

**Community Interpretation**: A labeled synthesis supported by linked Community Sources after an authoritative-source Abstention. It never becomes a Ruling.

**Abstention**: An explicit outcome stating that the available evidence does not resolve the rules question.

**Campaign Context**: Saved user-provided facts about the current campaign and party that help interpret a question. It is neither a rule authority nor a source of instructions to the Arbiter.

**Spoiler Scope**: A labeled group of source content gated by the same in-game unlock, such as a locked class, building, envelope, scenario, item, or rule sticker.

**Unlocked Scope**: A Spoiler Scope the user has explicitly allowed the Arbiter to retrieve.

## User Stories

1. As a Frosthaven player, I want to ask a natural-language rules question, so that I can resolve it without manually searching long documents.
2. As a Frosthaven player, I want each Ruling to cite its supporting passages, so that I can verify the answer myself.
3. As a Frosthaven player, I want citations to identify the source and section or page, so that I can understand where the rule came from.
4. As a Frosthaven player, I want to open a citation and read the stored source excerpt, so that verification still works when the laptop is offline.
5. As a Frosthaven player, I want the official FAQ to override conflicting rulebook text, so that errata and later clarifications are applied.
6. As a Frosthaven player, I want conflicting passages to be shown and explained, so that an override is not silently hidden.
7. As a Frosthaven player, I want the Arbiter to abstain when authoritative evidence is insufficient, so that model guesses are not presented as rules.
8. As a Frosthaven player, I want an Abstention to explain what relevant evidence was found, so that I understand why no Ruling was possible.
9. As a Frosthaven player, I want to explicitly request Community Lookup after an Abstention, so that questions are not sent to external sites without my action.
10. As a Frosthaven player, I want Community Interpretations to be visibly different from Rulings, so that I do not mistake community opinion for an official rule.
11. As a Frosthaven player, I want Community Interpretations to link directly to their discussions, so that I can assess the reasoning and context.
12. As a Frosthaven player, I want the original Abstention to remain visible after Community Lookup, so that the lack of authoritative resolution remains clear.
13. As a Frosthaven player, I want to save facts about campaign progress and party composition, so that I do not need to repeat them in every question.
14. As a Frosthaven player, I want to edit Campaign Context in the web interface, so that it stays aligned with the current campaign.
15. As a Frosthaven player, I want Campaign Context to be treated only as factual context, so that accidental instructions cannot weaken evidence or spoiler rules.
16. As a Frosthaven player, I want one Campaign Context to persist across application restarts, so that local state is durable.
17. As a Frosthaven player, I want to see and manage Spoiler Scopes, so that retrieval reflects what the party has unlocked.
18. As a Frosthaven player, I want locked passages excluded before model generation, so that the model cannot accidentally reveal them.
19. As a Frosthaven player, I want naming locked content in a question not to unlock it, so that spoiler permission remains explicit.
20. As a Frosthaven player, I want the application to explain when relevant evidence is locked, so that I can deliberately update the unlock list if appropriate.
21. As a Frosthaven player, I want spoiler-free portions of mixed passages to remain searchable, so that hidden names do not make otherwise public rules unavailable.
22. As a Frosthaven player, I want chat answers to stream into the browser, so that local generation feels responsive.
23. As a Frosthaven player, I want conversation history to persist locally, so that I can revisit earlier Rulings.
24. As a Frosthaven player, I want to clear conversation history without deleting Campaign Context or the source index, so that these lifecycles remain independent.
25. As a Frosthaven player, I want source revision information in the interface, so that I know how current the index is.
26. As a Frosthaven player, I want source updates to require a manual command, so that network access and index changes are deliberate.
27. As a Frosthaven player, I want synchronization to skip unchanged content, so that routine updates avoid unnecessary embedding work.
28. As a Frosthaven player, I want synchronization to replace the index atomically, so that interrupted updates do not corrupt the working corpus.
29. As a laptop owner, I want all inference and embedding generation to use local llama.cpp processes, so that questions and campaign details are not sent to model providers.
30. As a laptop owner, I want all application processes bound to the loopback interface, so that the Arbiter is not exposed to the local network.
31. As a laptop owner, I want a single startup command, so that I do not have to manage multiple inference and web processes manually.
32. As a maintainer, I want model paths and inference settings to be configurable, so that models can be replaced without application changes.
33. As a maintainer, I want the protected system prompt to be configurable in code or configuration, so that arbitration behavior can be refined and versioned.
34. As a maintainer, I want source parsing to retain provenance, revisions, anchors, and content hashes, so that citations and incremental updates are reliable.
35. As a maintainer, I want retrieval quality measured against representative rules questions, so that changes can be evaluated rather than judged anecdotally.
36. As a maintainer, I want generated citation labels validated against supplied evidence, so that fabricated citations cannot reach the interface.
37. As a maintainer, I want external community pages treated as untrusted data, so that embedded instructions cannot alter Arbiter behavior.
38. As a maintainer, I want downloaded copyrighted material and derived indexes excluded from version control, so that the repository does not redistribute them.

## Implementation Decisions

### Product Behavior

- The Arbiter is rules-only. Strategy, party optimization, campaign advice, and unsupported card or scenario guidance are outside its role.
- A response from the authoritative flow has exactly one outcome classification: Ruling or Abstention.
- A Ruling must be supported by retrieved Authoritative Source evidence and must cite that evidence inline.
- An Abstention is preferred over a plausible but unsupported answer.
- The Rulebook Transcription is accepted as authoritative. Official FAQ text has higher precedence and overrides it when they conflict.
- Community Lookup is available only as an explicit action after an Abstention. It is never an automatic retrieval fallback.
- Community Lookup produces a Community Interpretation or reports that no useful Community Sources were found. It cannot convert an Abstention into a Ruling.
- The application does not infer spoiler permission from the question or Campaign Context.
- Version one derives Spoiler Scopes from the source authors' spoiler markup and surrounding labels. This is the default because a separate manual spoiler catalog has not been requested.

### Application Shape

- The application uses Python 3.12 managed with `uv`.
- The browser interface is server-rendered with FastAPI, Jinja templates, and locally vendored HTMX. No JavaScript package build or content delivery network is required.
- The application stores structured state in SQLite and uses SQLite FTS5 for lexical retrieval.
- Dense embeddings are stored with chunk metadata in SQLite and loaded into a normalized NumPy matrix for exact similarity search. The expected corpus is small enough that an approximate-nearest-neighbor database is unnecessary.
- The application uses direct SQL rather than an ORM so that source, retrieval, and persistence behavior remain inspectable.
- The application communicates directly with llama.cpp's local HTTP interface rather than using a broad agent or RAG framework.
- One supervised runtime starts the chat model server, embedding model server, and web application, handles readiness, and stops child processes cleanly.
- All servers bind to `127.0.0.1` by default.

### Models

- The initial chat model is `unsloth/Qwen3.6-27B-MTP-GGUF` in GGUF `Q8_0` quantization.
- The initial embedding model is `gpustack/bge-m3-GGUF` in GGUF `Q8_0` quantization.
- Model paths, context size, GPU offload, ports, generation parameters, and executable path are local configuration rather than constants.
- The target laptop is an Apple M5 Max with 64 GB of unified memory and an existing Homebrew llama.cpp installation.
- A neural reranker is not included initially. It will be considered only if evaluation shows a material improvement over hybrid retrieval.

### Configuration And Prompts

- Version-controlled defaults define model settings, retrieval limits, source locations, generation behavior, and local server ports.
- Machine-specific values and model locations may be overridden without editing version-controlled defaults.
- The protected system prompt is version-controlled and configurable outside application code.
- Campaign Context is entered in the web interface and stored separately from the system prompt.
- Campaign Context is placed in a clearly delimited factual section of the model input and is explicitly lower priority than system behavior and Authoritative Sources.
- Source excerpts and Community Sources are treated as quoted data, not model instructions.

### Source Synchronization

- Source synchronization is an explicit command and is not triggered by asking a question or opening the web interface.
- Synchronization checks the latest Git revision affecting each upstream `index.md`, downloads a revision-pinned artifact, and records the commit SHA, declared update date, retrieval time, canonical URL, and content hash.
- Source snapshots are retained locally to make ingestion reproducible and citations inspectable offline.
- Unchanged chunks retain their embeddings. Added or changed chunks are embedded locally, and removed chunks are deleted in the replacement index.
- Index replacement is transactional. A failed download, parse, or embedding operation leaves the previous usable index intact.
- Source text, source snapshots, embeddings, model files, and the application database are local runtime data and are excluded from version control.

### Parsing And Chunking

- The Rulebook Transcription is parsed from its Markdown source while retaining heading hierarchy, physical page anchors, lists, tables, block quotes, image alt text, and links.
- The rulebook table of contents and duplicate new-to-Frosthaven subset are excluded from retrieval.
- Rulebook chunks follow leaf sections and target approximately 350 to 600 tokens. Long sections split at paragraph or list boundaries with limited overlap, while short procedures and tables remain atomic.
- The FAQ is parsed as one question-and-answer entry per chunk where possible. Long answers may split while repeating enough question and heading context to remain understandable.
- FAQ errata is split by individual correction or closely related correction group.
- Decorative images and dividers are removed. Meaningful image alt text and image references are retained.
- Source text is normalized without silently correcting it. FAQ errata remains the mechanism for correcting rulebook text.

### Spoiler Handling

- Spoiler markup is interpreted before chunking so that public and protected text are never merged solely to reach a target size.
- Mixed passages produce a spoiler-safe representation and one or more protected representations as needed.
- Every protected chunk has at least one Spoiler Scope.
- Retrieval receives the current set of Unlocked Scopes and filters ineligible chunks before lexical ranking, vector ranking, adjacency expansion, and prompt construction.
- The model is never expected to hide evidence it has already received. Prevention occurs before model input.
- The interface provides searchable controls for Spoiler Scopes discovered during synchronization.
- When a likely relevant scope is locked, the application may report the scope label but must not expose protected excerpts or answers.

### Retrieval

- The authoritative retrieval module presents one deep interface: accept a question and Unlocked Scopes, then return ranked, prompt-ready evidence with provenance.
- Query embeddings are generated locally through the embedding llama.cpp server.
- Lexical and semantic searches each produce a larger candidate set than the final evidence set.
- Candidate ranks are combined using reciprocal-rank fusion rather than scores that are difficult to calibrate across retrieval methods.
- Official FAQ evidence receives precedence during final evidence ordering and conflict handling, but rulebook evidence remains independently capable of supporting a Ruling.
- Immediately adjacent chunks may be added when they contain a continuation, exception, or necessary procedural context.
- Final evidence is bounded by a configurable token budget and receives stable citation identifiers.

### Arbitration

- The primary application seam accepts a question and the saved profile state and returns a streamed Ruling or Abstention plus structured citations.
- The system prompt requires the model to use only supplied Authoritative Source evidence for a Ruling, distinguish Campaign Context from rules, apply FAQ precedence, avoid strategy advice, and abstain when evidence is insufficient.
- The generated response is parsed into a structured outcome rather than inferred from presentation text.
- Every referenced citation identifier is checked against the supplied evidence before rendering.
- Unknown citation identifiers, malformed outcomes, and model-server failures produce a safe error or Abstention rather than an uncited answer.
- Recent conversation may resolve pronouns and follow-up questions, but earlier model answers are not treated as Authoritative Sources.

### Community Research

- Community research is a separate application seam that accepts the original question and Abstention context only after explicit user authorization.
- Search is restricted to relevant Reddit and BoardGameGeek domains.
- Search and page-fetch behavior sits behind a replaceable adapter because public search endpoints and site markup may change.
- Retrieved pages are reduced to relevant text, title, URL, publication metadata when available, and short excerpts. Scripts, navigation, and hidden instructions are discarded.
- Fetched content is size-limited, sanitized, and delimited as untrusted quoted material before local model synthesis.
- A Community Interpretation identifies disagreements and uncertainty instead of claiming consensus from a small result set.
- Community results are linked directly and are never inserted into the authoritative index.
- Network failures or blocked pages do not affect the local authoritative workflow.

### Persistence

- SQLite stores source revisions, chunks, embeddings, Spoiler Scopes, one Campaign Context, Unlocked Scopes, conversations, messages, and outcome citations.
- Campaign Context and Unlocked Scopes persist independently from conversation history.
- Clearing a conversation does not delete profile state, sources, or embeddings.
- Deleting local application data is documented and does not require network access.

### Web Interface

- The main view contains conversation history, a question composer, streamed responses, outcome labels, and citation controls.
- Rulings, Abstentions, and Community Interpretations have visually distinct labels and presentation.
- Citation controls show the stored excerpt, source authority, heading path, page or section, revision, and canonical external link.
- An Abstention exposes a separate action for Community Lookup. No community request begins until that action is selected.
- A profile panel edits Campaign Context and Unlocked Scopes and shows when changes have been persisted.
- A source-status panel shows indexed revisions, synchronization dates, chunk counts, and model readiness.
- The interface works on desktop and mobile-sized browser windows, although the application itself runs only on the laptop.
- All scripts, styles, and fonts required for operation are served locally.

### Operational Commands

- A setup workflow downloads or registers the configured GGUF models explicitly.
- A synchronization command downloads and indexes Authoritative Sources.
- A serve command supervises inference and starts the web interface.
- A diagnostic command reports configuration, model availability, database state, source revisions, and llama.cpp health without exposing private Campaign Context.

### Copyright And Distribution

- The application is intended for personal local use.
- The FAQ states that Cephalofair denies permission for its use in training an AI model or LLM. This application performs retrieval and local inference rather than model training, but source copies and derived embeddings still remain private local artifacts.
- The repository contains ingestion code and source URLs, not redistributed rule text, source assets, model files, embeddings, or generated indexes.
- Citations preserve source attribution and canonical links.

## Testing Decisions

- Tests exercise the highest stable seams: authoritative arbitration and explicit community research. Internal parser, retrieval, and persistence behavior receives focused tests only where failures would be difficult to diagnose through those seams.
- Good tests assert externally meaningful behavior: outcome classification, evidence eligibility, source precedence, citations, persistence, network consent, and spoiler non-disclosure. They do not assert incidental SQL statements, template structure, prompt whitespace, or private helper calls.
- Parser tests use small, representative source fixtures containing headings, page anchors, FAQ questions, errata, tables, icons, nested lists, details elements, hidden spans, and mixed spoiler content.
- Synchronization tests verify revision pinning, idempotency, incremental embedding, transactional replacement, and preservation of the previous index after failure.
- Retrieval tests use deterministic synthetic embeddings and fixed FTS content to verify semantic ranking, lexical ranking, reciprocal-rank fusion, source precedence, adjacency expansion, token limits, and Spoiler Scope filtering.
- Spoiler regression tests prove that locked text cannot appear in candidates, prompts, generated output, citation excerpts, or conversation history.
- Arbitration tests use a fake local-model adapter to verify Rulings, Abstentions, FAQ overrides, unsupported questions, malformed model responses, unavailable models, and rejection of fabricated citation identifiers.
- Prompt-injection tests place hostile instructions in Campaign Context, Authoritative Source fixtures, and Community Sources and verify that they cannot alter authority or disclosure behavior.
- Community research tests verify that no network adapter is called before explicit authorization, results remain non-authoritative, direct links are retained, disagreements are represented, and network failure leaves the Abstention intact.
- Persistence tests verify independent lifecycles for Campaign Context, Unlocked Scopes, conversations, source data, and indexes.
- Web tests verify profile editing, question submission, streaming, citation expansion, clear-chat behavior, locked-scope messaging, Community Lookup authorization, and restart persistence.
- A small browser-level test runs against fake inference and search adapters to cover the complete user journey without external network access.
- Local model evaluation uses a curated set of representative Frosthaven questions with expected source sections and answer points. It includes direct rules, exceptions, multi-section questions, FAQ corrections, ambiguous cases, locked content, follow-up questions, and questions that must produce Abstention.
- Evaluation reports retrieval recall at the final evidence limit, reciprocal rank, outcome correctness, answer correctness, citation precision, citation completeness, spoiler leakage, and abstention accuracy.
- Model, quantization, prompt revision, source revisions, retrieval settings, temperature, and seed are recorded with evaluation results so quality changes are reproducible.
- Ruff formatting and linting, static type checking, unit tests, integration tests, and the narrow browser suite run before a change is considered complete.
- There is no prior test structure because the repository begins empty; these decisions establish the initial conventions.

## Acceptance Criteria

- A user can configure local GGUF model paths, synchronize both Authoritative Sources, start the application, and open the interface without a cloud account.
- A supported question produces a streamed Ruling with valid citations to stored excerpts.
- A documented FAQ correction overrides conflicting rulebook text and cites both sources.
- An unsupported question produces an Abstention rather than an unsupported answer.
- Community network access occurs only after the user explicitly starts Community Lookup from an Abstention.
- Community Lookup produces a clearly labeled Community Interpretation with direct links and leaves the Abstention visible.
- Locked source text is absent from retrieval and model input unless all required Spoiler Scopes are unlocked.
- Mentioning locked content in a question does not change Unlocked Scopes.
- Campaign Context persists across restarts but cannot alter protected Arbiter behavior.
- Asking ordinary questions performs no external network request.
- The application binds only to the loopback interface by default.
- Source synchronization is idempotent, revision-aware, and leaves the previous index usable after failure.
- Source snapshots, embeddings, databases, model files, and copyrighted source content are not tracked by Git.
- The documented verification suite passes on the target laptop.

## Out of Scope

- Strategy recommendations, character builds, party optimization, or scenario walkthroughs
- Indexing ability cards, item cards, scenario books, section books, event decks, or campaign narrative beyond content already present in the two Authoritative Sources
- Cloud-hosted inference, embedding, storage, analytics, or authentication
- Multi-user accounts, access control, remote hosting, or local-network exposure
- Multiple campaign profiles in version one
- Automatic inference of campaign progress or spoiler permission
- Automatic Community Lookup or promotion of community consensus into a Ruling
- Training or fine-tuning a language model on Frosthaven material
- Redistributing downloaded source text, source assets, embeddings, indexes, or GGUF models
- A neural reranker before baseline hybrid retrieval has been evaluated
- OCR or interpretation of image-only rules content in version one
- Native desktop or mobile applications

## Further Notes

- The rulebook source intentionally omits some unrevealed rule stickers, while the FAQ is continuously updated. Source status and revision visibility are therefore part of correctness, not merely operational metadata.
- Version one trusts upstream spoiler markup. If evaluation finds missing or unsafe markup, a reviewed spoiler catalog or conservative classifier can be introduced later without changing the explicit-unlock rule.
- The exact community search provider remains replaceable and may depend on which unauthenticated endpoints remain reliable. Provider choice must not weaken the explicit-consent requirement.
- Exact retrieval limits, fusion constants, generation parameters, and context budgets should be selected through the local evaluation set rather than fixed by this specification.
- Image references are preserved in citations, but image-only meaning is not indexed initially. Any rule question that depends on such an image should produce an Abstention unless textual evidence resolves it.
