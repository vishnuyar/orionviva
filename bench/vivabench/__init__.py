"""viva-bench — the exam a model sits before it reads financial documents.

Part of OrionViva (https://orionviva.com).

The verification and model-access layers this package exercises live in
``vivacore``: ``vivacore.verify`` (normalization, arithmetic identities, claim
matching) and ``vivacore.models`` (provider-agnostic, version-pinned model
access). This package holds the harness around them — config, corpus, runner,
key building, scoring, reporting.
"""

__version__ = "0.1.0"
