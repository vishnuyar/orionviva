# A Trained Domain Model vs. Orchestration Rules

**Status:** Draft · **Last updated:** 2026-07-19 · **Prompted by:** Vishnu's challenge to ADR-001 — "instead of writing orchestration rules (find balances, tally numbers, notice the missing Feb bill), why not train a model that already *knows* what an insurance or broker statement is? Look at River AI."

## Untangling the question

The challenge bundles three distinct ideas that have different answers. Separating them is most of the analysis.

**Idea A — a model that knows what financial documents *are*.** Domain knowledge: recognizing a broker statement, knowing insurance policies carry premiums and riders, understanding that statements have opening/closing balances.

**Idea B — moving the checking into the model.** Letting a trained model tally numbers, notice missing months, and reconcile — so we write fewer explicit rules.

**Idea C — a model that continually learns *this user*** (the River AI thesis: LoRA + RL for continual personal specialization, eventually on local hardware).

## What the evidence says

**On Idea A: frontier models already have the domain knowledge; fine-tuning buys consistency and cost, not understanding.** 2026 head-to-heads are unusually clear. On merchant-info extraction from financial transactions, LoRA-tuned LLaMA-8B hit 96.75% F1 vs. 96.60% for a well-prompted small frontier model — a 0.15-point gap. Fine-tuned Qwen2.5-VL-3B reaches ~98% on invoice extraction. What fine-tuning reliably delivers is *schema discipline* (consistent JSON, no prompt fragility) and much cheaper/faster inference — a tuned 3B model costs ~$1 to train on 200 documents and runs on a laptop. What it does not deliver is broader understanding: tuned small models excel on *narrow, repeating formats* and degrade on the long tail. OrionViva's core promise — "no 'we don't support that institution,'" read *anything* like a person would — lives precisely in the long tail where frontier breadth wins. A model trained on statements stumbles on the handwritten note, the foreign-format pension letter, the property tax bill.

**On Idea B: the "rules" aren't overhead — they're the product.** This is the crux. Tallying balances, checking that line items sum, noticing the missing February statement: these look like tedious orchestration, but they are the *verification layer*, and verification is what converts model output into something the user can trust (the extraction doc). Moving them into model weights would mean arithmetic "in the model's head" — explicitly an anti-goal, because a model that internally tallied can't show its work, and a check you can't audit isn't a check. Two of the examples aren't even model territory: "tally the numbers" is deterministic arithmetic, and "Feb bill is missing" is a completeness query over the ledger — if the data model is right, that's one SQL query, infinitely more reliable than any model noticing it. The rules we'd write are few, boring, and load-bearing. That's the good kind of code.

There's also a calibration point: a fine-tuned model is *still* uncalibrated about its own errors — 98% accurate means 1-in-50 figures wrong with full confidence. The verification layer is what catches the 2%. So training doesn't remove the need for the rules; it just changes which model the rules are checking.

**On Idea C: River's bet is real but currently unauditable — and the evidence still favors explicit memory for trust-critical use.** River AI (Babuschkin, June 2026) is betting on continual parametric personalization: LoRA/RL loops so the model itself becomes yours. It's the most credible version of that bet, and it rhymes with our "memory is the moat" stance. But 2026 research still shows continual fine-tuning risks catastrophic forgetting and drift (repeated learning cycles can *collapse* rather than compound), and the field's practical consensus keeps retrieval/explicit-memory approaches ahead for interpretability. For OrionViva the disqualifier is sharper than performance: parametric memory can't carry provenance. If Viva believes your rent is $2,400, we must be able to show *which document* taught her that. Weights can't cite. Explicit memory can. Our memory moat should stay inspectable, correctable, and exportable — properties a LoRA can't offer today.

## Where the idea genuinely wins: the specialization flywheel

Here's the strongest version of Vishnu's thought, and it's worth adopting: **OrionViva's verification layer will manufacture exactly the training data a specialized model needs.** Every extraction that passes deterministic verification is a *labeled, ground-truth example* — document in, verified JSON out — accumulated as a side effect of normal use, at zero extra cost, entirely on the user's machine.

That creates a flywheel unavailable to anyone without a verification layer:

1. v0: frontier cloud model extracts; deterministic layer verifies; verified pairs accumulate locally.
2. When the corpus is large enough: LoRA-tune a local VLM (Qwen3-VL-class) on the user's own verified documents — cheaply, locally, on *their* statement formats specifically.
3. The tuned local model becomes the extraction default; the frontier model becomes the fallback for novel document types; the verification layer (unchanged) still grades everything.
4. Result: the ADR-001 "flip to local" happens *sooner and personally* — the user's own model, trained on their own verified data, never leaving their machine. Privacy story gets stronger with use.

This reframes ADR-001's hybrid not as a static compromise but as a *trajectory*: cloud → verified corpus → personally-specialized local model. It's also, notably, our version of River's thesis — but specialized on documents (auditable via verification) rather than on the user's persona (unauditable). If River ships infrastructure that makes local LoRA loops trivial, we're a natural consumer of it at step 2.

## Recommendation

Keep ADR-001's decision, amend its framing: the local path isn't just "kept open," it has a mechanism — the specialization flywheel. Concretely: (a) design the ledger so verified extractions are trivially exportable as training pairs from day one (near-zero cost now, enables everything later); (b) do **not** move verification into any model, ever — that stance graduates from leaning to principle; (c) add Idea C to the watchlist: revisit parametric personalization if/when adapters can carry provenance or River-class tooling changes the economics. New register items: Q9 (flywheel corpus threshold — how many verified pairs before a personal LoRA beats frontier on the user's own formats? The extraction benchmark gives the baseline), Q10 (River AI trajectory).

## Sources

- [River AI](https://river.ai/) · [Bloomberg: Babuschkin launches River AI (June 2026)](https://www.bloomberg.com/news/articles/2026-06-10/xai-co-founder-babuschkin-unveils-new-startup-for-personalized-ai) · [Yahoo Finance: xAI alumni launch River AI](https://finance.yahoo.com/sectors/technology/articles/xai-alumni-launch-river-ai-170322683.html)
- [LoRA fine-tuning 270M–8B for merchant extraction in financial transactions (arXiv 2606.08051)](https://arxiv.org/html/2606.08051v1)
- [Fine-tuning Qwen2.5-VL-7B for invoice extraction (CORD)](https://medium.com/@shrinath.suresh/finetuning-qwen-2-5-vl-7b-invoice-extraction-part-7-e8997d3f667a)
- [AWS: fine-tune VLMs for multipage document-to-JSON](https://aws.amazon.com/blogs/machine-learning/fine-tune-vlms-for-multipage-document-to-json-with-sagemaker-ai-and-swift/)
- [Empirical study of catastrophic forgetting in continual fine-tuning (arXiv 2308.08747)](https://arxiv.org/abs/2308.08747)
- [Continual learning for sequential personalization of small LMs (arXiv 2606.27634)](https://arxiv.org/pdf/2606.27634)
- [SPRInG: continual LLM personalization via selective parametric adaptation + retrieval (arXiv 2601.09974)](https://arxiv.org/pdf/2601.09974)
- [Turing Post: continual learning in LLMs](https://www.turingpost.com/p/continual-learning-llms-ai-models-sleep)
