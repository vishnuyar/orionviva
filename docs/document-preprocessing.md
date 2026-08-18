# Document Preprocessing — should we parse before we read?

**State:** partial
**Rules:** ING-10, ING-11, ING-12, ING-13, ING-14, ING-15, ING-16
**Invariants touched:** T1 (a preprocessor must preserve page/region or click-through is lost), T2 (verification is pipeline-agnostic — it catches preprocessing data loss the same way it catches model error), T3 (raw capture applies to preprocessor output too), I2 (locale normalization runs after whatever produces the text), X1 (all of it is invisible to the user)

## Rules

### ING-10 — text+image is the product's input mode, and every read records it
**State:** by-review-with-exception
**Code:** product/viva/ingest/reader.py:35 (`_render_and_read_text`), :57 (`_with_embedded`), :81, :222
**Test:** none

1. A document is read by sending the rendered page images together with the issuer's own embedded text, extracted on-device.
2. Every recorded model phase carries the `input_mode` it was read under, and that mode is persisted with the claim.

**Exception:** the field is written as the string literal `"text+image"` at product/viva/ingest/reader.py:81 (classify) and :222 (extract). No code path can stamp another value, so assertion 2 holds because the product has exactly one mode, not because the mode is observed. A second mode would not be recorded automatically.

### ING-11 — Input mode is a benchmark dimension, and the modes are image, text, and text+image
**State:** by-review
**Code:** bench/vivabench/cli.py:264, bench/vivabench/capture.py:44 (input mode is part of a cell's identity)
**Test:** none

1. A bench run selects one of exactly `image`, `text`, `text+image`.
2. The same document read by the same model in another mode is a separate cell, never a re-run of the first.
3. A `parsed` mode — a local document tool run over the PDF before the model sees it — is not implemented.

### ING-12 — Provenance anchors to measured character boxes where a text layer exists
**State:** unmet
**Code:** none found
**Test:** none

1. Where a page has an embedded text layer, a figure's source anchor is the character box the text layer reports for it.
2. A model-reported region is the fallback, used only where no text layer exists.

### ING-13 — Ingestion processes a page at a time
**State:** contradicted-by-code
**Code:** product/viva/ingest/reader.py:118
**Test:** none

1. A document is extracted page by page, so one bad page is one bad page and no read is capped by a whole-document output ceiling.

**Contradiction:** this doc concludes that page-at-a-time is a hard product constraint, not just a benchmark one, because a whole twelve-page statement needs roughly 62k output tokens and that exceeds every small model's ceiling. The product does the opposite: `product/viva/ingest/reader.py:118` passes the full `pages` list to one `adapter.extract` call, and the ceiling is handled by continuation instead — `core/vivacore/models/anthropic_adapter.py:42` re-sends the prompt and hands the partial reply back as an assistant prefill. Only the *classify* pass is bounded to one page (`product/viva/ingest/reader.py:70`). The bench does read page-at-a-time (`bench/vivabench/runner.py:118`, `extract_by_page`), so the exam and the product differ on the thing this rule is about.

### ING-14 — A scan is detected per page by ink without text, and only a scan routes to OCR
**State:** unmet
**Code:** none found
**Test:** none

1. A page carrying printed ink but no embedded text is classified as a scan.
2. Only such a page is routed to an OCR path; every other page reads from the text layer.

### ING-15 — Text extraction is on-device, and cloud document-AI is never on the default path
**State:** by-review
**Code:** product/viva/ingest/reader.py:52-53 (`pypdfium2` text extraction, in-process)
**Test:** none

1. The embedded text a read stands on is extracted locally, with no network call.
2. No third-party document-AI service is called on the default ingest path.

### ING-16 — Cloud document-AI, if a user configures it, is labelled data-leaving like any model call
**State:** unmet
**Code:** none found
**Test:** none

1. Cloud document-AI is a user-configured option only, never a default, because it takes the document to a third party (ADR-006).
2. Configured, it is labelled as data-leaving on the same footing as any other model call.

_No cloud document-AI path exists to label, and nothing labels one. The capability registry has a `may_egress` trust effect (product/viva/surface/capabilities.py:37), but only merchant enrichment and ruling export declare it; no ingest capability carries an egress label, and no setting turns a document-AI service on. Assertion 1 holds vacuously today (ING-15); assertion 2 has nothing standing behind it._

## Why

Preprocessing is not one choice; it is an **input mode**, and the honest answer
to "is parsing first better?" is to make it a benchmark dimension rather than an
opinion. Four families of approach exist, distinguished by where the reading
happens: native text extraction from a digital PDF's embedded layer, local
OCR/layout pipelines for scans, cloud document-AI, and vision-model-direct.

Three arguments settle the priors. First, for a digital PDF the embedded text is
not a guess to be verified — it is what the institution itself rendered.
Extracting it is lossless, free and on-device, and it removes the OCR error
class entirely for that document. Second, "would we miss data?" is the real risk
of every lossy preprocessor, and verification is exactly the instrument that
catches it: a dropped transaction fails balance reconciliation, a mangled digit
breaks the sum, a missing page shows up as incompleteness. We do not fear
preprocessing blindly; we grade it. The one thing verification cannot recover is
provenance — a tool that discards coordinates breaks click-through-to-source,
which is why provenance fidelity is a metric for any parse-first mode and not an
afterthought. Third, good document tools run *locally*, which makes them more
aligned with local-first than cloud vision APIs, not less; a fully-local stack
of local OCR plus local model plus a format profile needs nothing from any
cloud.

Measured against a real fifteen-document corpus, several of those priors held
and one broke.

Text-layer coverage was total: every document carried the issuer's embedded
text, 4.6× smaller in tokens than the rendered images, and the only two pages
without text were confirmed genuinely blank by an ink check. Zero pages had
printed content with no text layer. That makes deferring the heavy parse-first
mode firm rather than merely convenient — there is currently nothing for a local
OCR tool to do.

The text layer is faithful where it matters most. On the densest table in the
corpus — the one that defeated whole-document extraction — all 81 amounts a
frontier model extracted appear verbatim in the embedded text, and the row
structure survives. Reading-order scrambling is the standard argument against
text-first, and on the hardest table available it did not occur.

Cost is **not** the argument, and the earlier claim that text-first is "far
cheaper" was wrong. That was true under whole-document image extraction; once
extraction went page-at-a-time, output tokens came to dominate and input fell to
about 16% of spend. Measured per corpus pass: `image` $8.91, `text` $7.68 (−14%),
`text+image` $9.11 (**+2%**). The hybrid is slightly *more* expensive. That
strengthens the recommendation rather than weakening it — you are not trading
cost against accuracy, you are removing an entire error class for two percent —
but the case must be made on accuracy and provenance, never on price.

Provenance survives text mode and is arguably better: `pypdfium2`, already a
dependency, returns exact character boxes, and those are *measured* coordinates
where a vision model's reported region is an estimate of where it looked. For
click-through, the text layer is the stronger anchor.

Output ceilings are a product constraint, not only a benchmark one. A whole
twelve-page statement needs roughly 62k output tokens, which exceeds the ceiling
of every small model, so a whole-document call scores the ceiling rather than
the reading.

On capable models, input mode barely moves recall — one frontier model extracted
the same 283 amounts in all three modes. The earlier "text-only collapses"
result was one 8B model specifically: never judge a mode from the weakest
candidate. But an open 235B model *needs* the pixels; handed the flat character
stream alone it lost the document entirely (312 amounts in image mode down to
46 in text), and recovered and improved in the hybrid. The image is load-bearing
for open models, which makes the hybrid the mode that lets them compete — and
the local-model floor is where the local-first thesis is actually decided.

The decisive finding is international. Cross-model agreement on an INR document
with lakh grouping ran 59% in image mode, 88% in text, 85% in text+image. In
image mode two frontier models agree on barely half the amounts because each is
independently OCR-ing Indian digit grouping and a currency symbol, and they
diverge. Feed them the issuer's own characters and agreement jumps about thirty
points. That is the difference between the cross-model answer-key design working
on international documents and needing constant human audit. On US documents the
effect is smaller but the same sign. Trust earned per locale (I3) is where
preprocessing pays off most.

Hence: `text+image` is the product default and `image` stays as the control. It
never loses recall, it is what lets open and local models compete, it delivers
nearly all of the international-agreement win while keeping the pixels as a
safety net, and its only cost is about two percent more spend.

A full parse-first pipeline would be a digression — a rabbit hole of tool
installs and per-tool quirks — and it earns its weight on scans, which the
corpus does not yet contain. Cheap input modes now, heavy tool comparison later.
Every mode passes the unchanged verification floor, which is what makes it safe
to experiment with preprocessing at all.

## Open

- Which local tool (Marker, Docling, olmOCR, or native-only) the product's scan path should use, decided by a `parsed`-mode benchmark rather than by argument. Low priority while no corpus document is a scan.
- Reconciliation of provenance anchors for scans, where there is no text layer and only model-reported regions exist.
- Whether `text` alone scrambles multi-column layouts. One dense table tested favourably; combined multi-column statements are the real risk, and `text+image` is the hedge because the model keeps the pixels.
- The full N=5 benchmark run: every mode result so far is N=1 and directional, not conclusive.
- The product reads whole documents while the bench reads page-at-a-time (ING-13). One of the two has to move.

## Sources

- [Best open-source PDF-to-Markdown tools (Marker/Docling/MinerU/pdf-craft/PyMuPDF4LLM)](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
- [PDF table extraction: Docling vs Marker vs LlamaParse](https://codecut.ai/docling-vs-marker-vs-llamaparse/)
- [Structured PDF-to-JSON: open-source extraction models (MarkTechPost)](https://www.marktechpost.com/2026/07/04/structured-pdf-to-json-a-guide-to-open-source-extraction-models-in-2026/)
- [PDF parsing accuracy benchmark: Docling vs Unstructured vs Marker (Ertas AI)](https://www.ertas.ai/blog/pdf-parsing-accuracy-benchmark-docling-unstructured)
- [Jimmy Song: Marker vs MinerU vs MarkItDown deep dive](https://jimmysong.io/blog/pdf-to-markdown-open-source-deep-dive/)
- [Best open-source OCR tools (Tesseract/EasyOCR/PaddleOCR)](https://imagetotable.ai/blog/best-open-source-ocr-tools-2026)
