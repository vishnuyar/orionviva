"""The shared exam question. One template for every candidate (proctor rule).

Version the prompt like everything else on the trust path: results are only
comparable within a prompt version, and the run records carry it.

p2: one page per call. A whole dense document needs ~62k output tokens, which
exceeds the output ceiling of every small candidate (32k for the Qwen class) —
scoring them on a truncated answer would measure the ceiling, not the reading.
Pages are therefore extracted one at a time and merged; the model is told which
page it is looking at so claim page numbers stay absolute.

Input modes: the same question, asked over different inputs, so the benchmark
can measure whether preprocessing helps rather than assume it. Versions are
per-mode so that adding a mode never invalidates results already collected
under another one — "p2" image records stay comparable forever.
"""

import pathlib

from . import promptstore

PROMPT_VERSION = "p2"        # the image-mode prompt; unchanged since p2

INPUT_MODES = ("image", "text", "text+image")

PROMPT_VERSIONS = {
    "image": "p2",
    "text": "t1",
    "text+image": "ti1",
}

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"

# The text lives in `prompts/extract-image-p2.txt`, not here. A literal was
# editable in place while its version constant was bumped independently — the
# exact mechanism that lost merchantcore's earlier enrichment prompts.
EXTRACTION_PROMPT = promptstore.load(PROMPTS, f"extract-image-{PROMPT_VERSION}")



# Each mode owns its opening: what the input IS, and how the page is identified.
# The task itself (everything from "Extract EVERY factual claim") is shared
# verbatim, so a mode comparison measures the input, not a reworded question.
# The image header is byte-identical to p2 — image results stay comparable.
# Each mode owns its opening: what the input IS, and how the page is identified.
# The task itself (everything from "Extract EVERY factual claim") is shared
# verbatim, so a mode comparison measures the input, not a reworded question.
# The image header is byte-identical to p2 — image results stay comparable.
#
# The three headers are FILES (prompts/header-*.txt). A benchmark that reworded
# its own question between runs would measure nothing, so the exam text is
# pinned exactly like every other prompt.
_HEADER_IDS = {"image": "header-image-p2", "text": "header-text-t1",
               "text+image": "header-textimage-ti1"}
_HEADERS = {mode: promptstore.load(PROMPTS, pid)
            for mode, pid in _HEADER_IDS.items()}

_PAGE_TEXT_BLOCK = promptstore.load(PROMPTS, "page-text-block-v1")


def page_prompt(
    page_number: int, page_count: int, mode: str = "image", page_text: str = ""
) -> str:
    """The exam question for one page, in one input mode.

    Identical for every candidate within a mode (the proctor rule): only the
    input changes, never the question. Plain substitution, not str.format: the
    template contains literal JSON braces, and an accidental format-spec error
    in the exam question would be a silent change to what every candidate is
    asked.
    """
    if mode not in INPUT_MODES:
        raise ValueError(f"unknown input mode {mode!r}; expected one of {INPUT_MODES}")

    marker = "Extract EVERY factual claim"
    body = EXTRACTION_PROMPT[EXTRACTION_PROMPT.index(marker):]   # the shared task
    prompt = _HEADERS[mode] + "\n" + body
    if mode in ("text", "text+image"):
        # An empty block is honest: this page carries no embedded text. The
        # caller has already established it is blank rather than a scan.
        body_text = page_text if page_text.strip() else "(this page has no embedded text)"
        prompt += _PAGE_TEXT_BLOCK.replace("{page_text}", body_text)
    return prompt.replace("{page_number}", str(page_number)).replace(
        "{page_count}", str(page_count)
    )
