# Document Preprocessing — should we parse before we read?

**Status:** Draft (discovery) · **Last updated:** 2026-07-21 · **Origin question:** viva-bench currently sends page *images* to the model. What if we first run a document tool (e.g. datalab's Marker/Surya, or others) to convert the PDF? Is it better? Does it digress? Would we miss data?
**Invariants touched:** T1 (provenance — a preprocessor must preserve page/region or we lose click-through), T2 (verification is pipeline-agnostic — it catches preprocessing data loss the same way it catches model error), T3 (raw capture applies to preprocessor output too), I2 (locale normalization runs after whatever produces the text), X1 (all invisible to the user)

## The short answer

Preprocessing is not one choice; it's an **input mode**, and viva-bench is exactly the instrument to measure whether a given mode helps or hurts. So the honest answer to "is it better?" is *don't guess — make it a benchmark dimension.* But three findings shape the priors, and one of them is strategically important: **good document tools run locally, which makes them more aligned with local-first than cloud vision APIs, not less.**

## The landscape (mid-2026)

Four families, by where the "reading" happens:

1. **Native text extraction** — digital PDFs already contain an embedded text layer the issuer wrote. `PyMuPDF4LLM` / `pdftext` pull it out losslessly, on-device, for free, with character coordinates. No OCR, no model, no data loss — because you're reading the bank's own text, not re-recognizing pixels. *(All 15 documents in the v1 corpus have text layers — we used `pdftotext` to classify them.)*
2. **Local OCR / layout pipelines** — for scans and structure: **Marker** (on the **Surya** engine; the safest local default, fast, 5-stage specialist pipeline, but merges columns on dense tables), **Docling** (IBM; strong table recovery, slower, can hallucinate on dense tables), **MinerU** (Shanghai AI Lab; complex layouts, CJK), **olmOCR** (AllenAI; a 7B VLM fine-tuned for scanned-document OCR). All run on-device (CPU/GPU/Apple MPS).
3. **Cloud document-AI** — AWS Textract, Azure Document Intelligence, Google Document AI, datalab's hosted Marker (~90% field accuracy on their schema benchmark). Accurate, but **they take your document to a third party** — the same egress that rules cloud storage out. Off by default for OrionViva; a user-configured option at most, never the default path.
4. **Vision-model-direct** — what viva-bench does today: render pages to images, let the VLM do OCR + understanding together. Purest "read like a person," no lossy intermediate, but pays image-token cost and asks one model to both see and reason.

## The three findings

**Finding 1 — for digital PDFs, the text layer is ground truth the issuer already wrote.** Most bank/card/brokerage statements are digital PDFs. Their embedded text is not a guess to be verified — it's what the institution rendered. Extracting it is lossless and free, and it *removes* the OCR error class entirely for those documents. Feeding the model that text (or text **and** the image, belt-and-suspenders) is very likely more accurate and far cheaper than image-only, at zero data-loss risk. This is the highest-leverage, lowest-cost change available.

**Finding 2 — "would we miss data?" is the real risk of every *lossy* preprocessor, and our verification layer is the exact instrument that catches it.** Marker merging columns, Docling hallucinating a table cell, an OCR mangling a digit — each is a preprocessing failure that happens *before the model sees the truth*. That sounds fatal for a trust product until you remember: verification is pipeline-agnostic. A dropped transaction fails balance reconciliation; a mangled digit breaks the sum; a missing page shows up as incompleteness. The confidently-wrong and recall metrics measure preprocessing data loss identically to how they measure model error. **So we don't fear preprocessing blindly — we grade it.** The one thing a lossy preprocessor threatens that verification *cannot* fully recover is **provenance** (T1): if the tool discards coordinates, click-through-to-source breaks. Native text and Surya/Docling return boxes; a markdown-only tool does not. Provenance fidelity therefore joins the benchmark metrics for any parse-first mode.

**Finding 3 — local tools strengthen the local-first story.** This is the strategic point. A fully-local ingestion stack — local OCR (Marker/olmOCR) + local VLM + a format profile — needs *nothing* from any cloud, for scans as well as digital PDFs. Preprocessing is thus not a compromise of the privacy thesis; it's a lever for the endgame the adoption and format-commons docs already point at: near-zero-cost, fully-private ingestion. (olmOCR being a fine-tuned Qwis2-VL is a nice convergence — it's the same family as our local-model candidates.)

## What this means for viva-bench

Preprocessing becomes an **input mode** dimension, orthogonal to the model candidate — the same shape as the format-commons "profile-guided vs blind" mode. Modes to measure:

- `image` — current baseline (fair "read like a person" control; keep it).
- `text` — native embedded text only (free, lossless for digital PDFs; the cost/accuracy floor to beat).
- `text+image` — hybrid: the model gets both the issuer's text and the pixels, and reconciles (belt-and-suspenders; likely best accuracy).
- `parsed` (later) — a local tool (Marker/Docling) → markdown/JSON + boxes → model. Heaviest; matters most for scans; measured once the cheap modes are understood.

Scorecards already key on (model, doc_type, locale); they gain an (input_mode) facet. The benchmark then answers, on *real* documents, the exact question — with numbers, not opinion.

## Recommendation

- **Don't block the first run.** The `image` baseline is built, fair, and ready; the whole discovery phase waits on getting *some* evidence.
- **Add one cheap mode before or right after the baseline: `text+image`.** Near-free (a text-extraction dependency alongside the image renderer we already have), zero data-loss risk (the model still sees the pixels), and likely a large accuracy-and-cost win on the digital-PDF corpus. This directly tests Vishnu's instinct with minimal effort.
- **Defer the heavy local-tool `parsed` mode** to a later benchmark pass — it earns its weight on scans, and adds install surface. Note it as part of the eventual fully-local pipeline.
- **Cloud document-AI stays off the default path** (egress), consistent with ADR-006 — a user-configured option only, and even then labeled as data-leaving like any model call.
- **Every mode still passes the unchanged verification floor.** That is what makes it safe to experiment with preprocessing at all.

## Does it digress?

Adding a full parse-first pipeline *now* would digress — it's a rabbit hole of tool-install and per-tool quirks, and the first benchmark's job is to get *any* reality signal. Adding the `text+image` mode does not digress: it's small, it directly answers the question asked, and it rehearses the product's real ingestion (which will almost certainly use the embedded text layer for digital PDFs). The line: cheap input modes now, heavy tool comparison later.

## Measured findings (2026-07-21, v1 corpus, 15 documents / 63 pages)

Everything above was written from priors. These are numbers off the real corpus.
The recommendation survives; **one of its arguments does not.**

**F1 — Text-layer coverage is total. There are no scans in v1.** All 15 documents
carry the issuer's embedded text (40,978 tokens total vs 188,401 image tokens —
**4.6×** smaller). Exactly two pages lack text: `fidelity-1099` p12 and
`chase-mar` p6. Both were confirmed *genuinely blank* by an ink check (0.33% and
0.04% non-white pixels) — one literally reads "This Page Intentionally Left
Blank". Zero pages have printed content without a text layer. This makes the
`parsed` (Marker/Docling/olmOCR) deferral firmer, not just convenient: there is
currently nothing for a local OCR tool to do.

**F2 — The text layer is faithful where it matters most.** On page 3 of the
Fidelity 1099 — the dense proceeds table that defeated whole-document
extraction — **81 of 81** amounts Claude extracted appear *verbatim* in the
embedded text, and the table's row structure survives (each `Sale` row on one
line, columns in order). Reading-order scrambling is the standard argument
against text-first; on our hardest table it did not occur.

**F3 — Cost is NOT the argument for preprocessing. Finding 1 above was wrong on
this point.** "Far cheaper" was true under whole-document image extraction. Once
extraction went page-at-a-time, *output* tokens came to dominate: for Claude one
corpus pass is ~287k input ($1.44) against ~299k output ($7.47), so input is only
**16%** of spend. Therefore:

| mode | total / pass | vs image |
|---|---|---|
| `image` | $8.91 | — |
| `text` | $7.68 | −14% |
| `text+image` | $9.11 | **+2%** |

`text+image` is *slightly more expensive*, not cheaper. This strengthens the
recommendation rather than weakening it: you are not trading cost against
accuracy, you are removing an entire error class for ~2%. But the case must be
made on accuracy and provenance, never on price.

**F4 — Q22 is answered: provenance survives text mode, and is arguably better.**
`pypdfium2` (already a dependency — text mode needs no new install) returns exact
character boxes: a line-item amount on page 3 resolves to a box like
`x0=0.39 y0=0.39 x1=0.44 y1=0.40`. These are *measured* coordinates, where the VLM's `region` in image
mode is a model's estimate of where it looked. For T1 click-through, the text
layer is the stronger anchor.

**F5 — Output ceilings are a product constraint, not just a benchmark one.** A
whole 12-page statement needs ~62k output tokens to extract. That exceeds the
output ceiling of every small model (32k for the Qwen class), so a
whole-document call scores the ceiling rather than the reading. Ingestion must be
page-at-a-time — in the product too, not only in the exam.

**F6 — The phone-class failures may be an input-mode artifact.** In `image` mode
the 8B produced unparseable output on 5 pages and burned its entire 32k ceiling
on one payslip page (near-certain repetition loop). That is the model being asked
to *see and reason at once*. Handing it the issuer's text may rescue it — which
matters because Q8/Q13 (the local floor, the phone-class question) are where the
local-first thesis is decided. Do not conclude "small models can't do this" from
image-mode evidence alone.

## Bake-off results (2026-07-21, 3 docs × 4 models × 3 modes, N=1)

Documents chosen for the three real risks: `fidelity-1099` (dense tables),
`chase-mar` (multi-column combined statement — reading-order), `sbi-card-2026`
(en-IN/INR — non-Latin number grouping). Amounts extracted are the recall proxy
(precision was 100% everywhere, so it does not discriminate yet — real accuracy
waits on frozen keys). Cost is one pass; OpenRouter routing adds noise.

**B1 — On capable models, input mode barely moves recall.** Claude extracted
283 amounts from the 1099 in *all three* modes; Gemini 283/283/284. On
`chase-mar`, Claude 158/154/157. The earlier "text-only collapses" result was
the **8B model specifically**, confirming F6: never judge a mode from the
weakest candidate. Text-only is viable *if and only if* every model in the
pipeline is strong.

**B2 — The open 235B model needs the pixels; text-only breaks it.** qwen-235b on
the 1099: 312 amounts (image) → **46** (text). On `chase-mar`: 23 → **0**. Hand
it the flat character stream alone and it loses the document. In `text+image`,
where it completed, it *recovered and improved* (`sbi-card` 18 image → **60**
text+image). The image is load-bearing for open models — the hybrid is the mode
that lets them compete.

**B3 — The decisive finding: text kills cross-model OCR disagreement on
non-US documents.** Drafter agreement (Claude vs Gemini, identical printed
value) on `sbi-card` (INR, lakh grouping):

| mode | agreement |
|---|---|
| image | **59%** |
| text | 88% |
| text+image | 85% |

In image mode the two frontier models agree on only 59% of INR amounts — because
each is independently OCR-ing Indian digit grouping and the ₹ symbol, and they
diverge. Feed them the issuer's own characters and agreement jumps ~30 points.
This is not a small tuning gain; it is the difference between the cross-model
answer-key design *working* on international documents and needing constant human
audit. On US docs the effect is smaller but same-signed (1099: 99% → 100%).
**I3 (trust earned per locale) is where preprocessing pays off most.**

**B4 — Small models fail honestly, and modes don't rescue them.** The 8B
truncated on 1099 p3 in text mode and left a page unparsed in text+image;
qwen-235b timed out twice on large `text+image` inputs (300s per-call limit —
an infra fix, `timeout_s`, not a capability result). Every failure was recorded
as such, never scored as an empty read.

**Verdict: `text+image` is the product default; `image` stays as the control.**
It never loses recall (B1), it is what lets open/local models compete (B2), and
it delivers the international-agreement win nearly as well as text-only while
keeping the pixels as a safety net (B3). Its only cost is ~2% more spend (F3)
and higher input tokens — acceptable for the accuracy and the local-model story.

## Product implications (beyond the benchmark)

- **Ingestion should be text+image for digital PDFs.** The issuer's characters for
  *what the value is*; the pixels for *what it means* (column, row, section).
- **Anchor provenance to measured character boxes** where a text layer exists,
  falling back to model-reported regions only for scans (F4).
- **Process page-at-a-time** (F5) — this is a hard constraint from model output
  ceilings, and it also bounds blast radius: one bad page is one bad page.
- **Detect scans by ink-without-text, per page** (F1's method), and route only
  those to an OCR path. Most users' statements will need no OCR at all.

## Open questions (register)

- Q20: Input-mode benchmark — **implemented** (`--mode image|text|text+image`);
  bake-off pending on a 3-document subset before the full N=5 run.
- Q21: For the *product's* local pipeline, which local tool (Marker vs Docling vs olmOCR vs native-only) for scans — decided by a later `parsed`-mode benchmark, not now. **Lower priority given F1** (no scans in v1 corpus).
- Q22: **Answered — see F4.** Carry the text layer's character boxes as the region
  anchor; they beat the VLM's self-reported regions. Reconciliation for scans (no
  text layer, model regions only) remains open.
- Q23 (new): Does `text` alone scramble multi-column layouts? F2 tested one dense
  table favourably; the Chase *combined* statements are the real multi-column
  risk and are in the bake-off subset for exactly this reason. `text+image` is
  the hedge — the model keeps the pixels.

## Sources

- [Best open-source PDF-to-Markdown tools 2026 (Marker/Docling/MinerU/pdf-craft/PyMuPDF4LLM)](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
- [PDF table extraction: Docling vs Marker vs LlamaParse](https://codecut.ai/docling-vs-marker-vs-llamaparse/)
- [Structured PDF-to-JSON: open-source extraction models 2026 (MarkTechPost)](https://www.marktechpost.com/2026/07/04/structured-pdf-to-json-a-guide-to-open-source-extraction-models-in-2026/)
- [PDF parsing accuracy benchmark: Docling vs Unstructured vs Marker (Ertas AI)](https://www.ertas.ai/blog/pdf-parsing-accuracy-benchmark-docling-unstructured)
- [Jimmy Song: Marker vs MinerU vs MarkItDown deep dive](https://jimmysong.io/blog/pdf-to-markdown-open-source-deep-dive/)
- [Best open-source OCR tools 2026 (Tesseract/EasyOCR/PaddleOCR)](https://imagetotable.ai/blog/best-open-source-ocr-tools-2026)
