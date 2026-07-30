"""The shared exam question: one template for every candidate (the proctor rule).

The prompt is versioned like everything else on the trust path; results are only
comparable within a prompt version, and run records carry it.

One page per call. A dense document needs more output tokens than the smaller
candidates can emit, so pages are extracted one at a time and merged, and the
model is told which page it is looking at so claim page numbers stay absolute.
docs/document-preprocessing.md

Input modes ask the same question over different inputs (image, embedded text,
or both). Versions are per-mode, so adding a mode leaves results already
collected under another mode comparable.
"""

import pathlib

from . import promptstore

PROMPT_VERSION = "p2"        # the image-mode prompt

INPUT_MODES = ("image", "text", "text+image")

PROMPT_VERSIONS = {
    "image": "p2",
    "text": "t1",
    "text+image": "ti1",
}

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"

# The text lives in `prompts/extract-image-<version>.txt`, not here.
EXTRACTION_PROMPT = promptstore.load(PROMPTS, f"extract-image-{PROMPT_VERSION}")



# Each mode owns its opening: what the input is, and how the page is identified.
# The task itself — everything from "Extract EVERY factual claim" onwards — is
# shared verbatim across modes, so a mode comparison varies the input and not
# the question. The image header is byte-identical to the image-mode prompt, so
# image results stay comparable.
#
# The three headers are files (prompts/header-*.txt), pinned and versioned like
# every other prompt.
_HEADER_IDS = {"image": "header-image-p2", "text": "header-text-t1",
               "text+image": "header-textimage-ti1"}
_HEADERS = {mode: promptstore.load(PROMPTS, pid)
            for mode, pid in _HEADER_IDS.items()}

_PAGE_TEXT_BLOCK = promptstore.load(PROMPTS, "page-text-block-v1")


def page_prompt(
    page_number: int, page_count: int, mode: str = "image", page_text: str = ""
) -> str:
    """The exam question for one page, in one input mode.

    Identical for every candidate within a mode: only the input changes, never
    the question. `page_text` is the page's embedded text, used by the "text"
    and "text+image" modes and ignored otherwise. Substitution is plain
    `str.replace`, not `str.format`, because the template contains literal JSON
    braces. Raises ValueError for a mode outside INPUT_MODES.
    """
    if mode not in INPUT_MODES:
        raise ValueError(f"unknown input mode {mode!r}; expected one of {INPUT_MODES}")

    marker = "Extract EVERY factual claim"
    body = EXTRACTION_PROMPT[EXTRACTION_PROMPT.index(marker):]   # the shared task
    prompt = _HEADERS[mode] + "\n" + body
    if mode in ("text", "text+image"):
        # A page with no embedded text says so in the block rather than
        # omitting it; the caller has already established it is blank rather
        # than a scan.
        body_text = page_text if page_text.strip() else "(this page has no embedded text)"
        prompt += _PAGE_TEXT_BLOCK.replace("{page_text}", body_text)
    return prompt.replace("{page_number}", str(page_number)).replace(
        "{page_count}", str(page_count)
    )
