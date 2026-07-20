# Agent & Model Landscape (mid-2026)

**Status:** Draft · **Last updated:** 2026-07-19 · **Refresh trigger:** new frontier model generation, major SDK release

## Why this doc exists

OrionViva's stances ("read documents like a person would," "memory is the moat, not the model") assume models are commodities and improving. This doc tracks what's actually available so we build on the current floor, not a 2024 mental model.

## Agent frameworks

The landscape has split into provider-native SDKs (Anthropic, OpenAI, Google) and cross-provider frameworks (LangGraph, CrewAI, Pydantic AI). Key observations:

- **Claude Agent SDK** (Python/TS) exposes the Claude Code harness — file access, command execution, tool use — as a programmable framework. Safety-first architecture, auditable extended thinking. Now has its own subscription credit line (June 2026).
- **OpenAI Agents SDK** added sandboxed execution (April 2026), closing much of the OS-access gap with Anthropic.
- **LangGraph** (1.0+) is the production-proven cross-provider option: durable execution, checkpointing, human-in-the-loop interrupts, long-term memory primitives. Most operational mileage (Klarna, Uber, LinkedIn scale).
- Consensus guidance: prototype with the framework closest to your model provider; heavy frameworks earn their weight only with complex multi-agent graphs.

**Implication for OrionViva.** Viva is a *single* agent with tools (read document, query ledger, compute) — not a multi-agent graph. That argues for the thinnest viable harness: either a provider SDK or a hand-rolled tool loop over the raw API. A hand-rolled loop maximizes provider independence (fits "models are commodities") and keeps the trust-critical path — what gets sent where — fully inspectable, which matters when the payload is someone's bank statement. Framework lock-in is a real cost here because the moat is our data model and memory, not orchestration. **Leaning:** direct API tool loop with a thin provider-abstraction layer; adopt an SDK only if we hit real orchestration pain. (Open: Q4.)

## MCP

MCP won. Linux Foundation governance, 10k+ public servers, support across Claude, ChatGPT, Gemini, Copilot, Cursor; financial institutions (Bloomberg, PayPal, banks) shipping servers.

**Implication.** Two-way relevance: (a) OrionViva could *consume* MCP servers (aggregators, brokerages as they ship them); (b) more strategically, OrionViva could *expose* a local MCP server — letting any agent the user already trusts query their verified financial picture, with OrionViva enforcing provenance and permissioning. That's a concrete, near-term step toward the Phase 4 "your agent answers other agents" arc, without building counterparty infrastructure. Worth a design sketch during architecture phase.

## Model capabilities for document understanding

- **Cloud frontier models** (Claude, GPT, Gemini current generations) read statements, tables, and scanned documents natively at high quality. The "no per-institution parsers" stance is fully vindicated — this is now the ordinary way to do it.
- **Local/open VLMs** have improved fast: Qwen3-VL (7B/32B/72B) and peers (GLM-4.5V, DeepSeek-VL2, MiniCPM-V) are credible at OCR, table parsing, and structured JSON extraction. A 7–8B model at 4-bit runs on a 12 GB GPU / recent Apple Silicon.
- The honest gap: local models are credible, not yet *trustworthy for finance without verification*. Their error modes on dense tables and multi-page statements are exactly the ones that matter to us.

**Implication.** Supports ADR-001 (hybrid): cloud default for quality, local path kept open. The extraction benchmark (discovery plan, experiment 1) should include Qwen3-VL alongside cloud models so we have our own numbers, not blog claims. Because verification architecture (the extraction doc) is model-agnostic, a strong verification layer *lowers* the quality floor a local model must clear — the better our checking, the sooner local-only becomes honest to offer. That's a nice structural property: our hardest problem also buys us the purist privacy story over time.

## Open questions

- Q4: harness choice — validate the "thin loop" leaning with a prototype during experiments.
- Q8: re-benchmark local VLMs each generation; define the accuracy/calibration bar that would flip the default to local.
- New: does exposing a local MCP server belong in Phase 0/1 scope, or is it a distraction? (Gut: design for it, don't build it yet — matches "design toward the arc, don't build it.")

## Sources

- [Morph: AI Agent Frameworks 2026 + Claude Agent SDK reference](https://www.morphllm.com/ai-agent-framework)
- [QubitTool: 2026 framework showdown](https://qubittool.com/blog/ai-agent-framework-comparison-2026)
- [Turion: LangGraph vs OpenAI/Claude SDKs 2026](https://turion.ai/blog/langgraph-vs-openai-claude-agent-sdk-2026/)
- [Digital Applied: MCP adoption statistics 2026](https://www.digitalapplied.com/blog/mcp-adoption-statistics-2026-model-context-protocol)
- [Stacklok: State of MCP in Financial Services 2026](https://stacklok.com/wp-content/uploads/2026/01/State-of-MCP-in-Financial-Services-2026_FINAL.pdf)
- [Local AI Master: Qwen3-VL local setup](https://localaimaster.com/blog/qwen-3-vl-local-setup)
- [MyLocalAI: Best local vision models for private OCR/doc Q&A 2026](https://mylocalai.org/blog/best-local-vision-model-ocr)
- [BentoML: Open-source VLM guide 2026](https://www.bentoml.com/blog/multimodal-ai-a-guide-to-open-source-vision-language-models)
