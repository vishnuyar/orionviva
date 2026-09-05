import { afterEach, describe, expect, it } from "vitest";
import { createDetectedBridgeClient, createHostBridgeClient, hasHostBridge } from "./client";
import { BridgeRefusal, BridgeUnreadable } from "./contracts";
import type { BridgeRequest, BridgeResponse, BridgeTransport } from "./contracts";

describe("bridge transport framing", () => {
  afterEach(() => { delete window.orionVivaBridge; });

  it("frames vault open and all surface reads", async () => {
    const frames: Array<{ requestId: string; operation: string; payload: Record<string, unknown> }> = [];
    const transport: BridgeTransport = { request: async <T>(frame: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
      frames.push(frame);
      const result = frame.operation === "bridge.open_vault" ? { state: "opened" } : { surface: frame.payload.surface, job_id: "job", data: {} };
      return { protocol: "1.0", request_id: frame.requestId, ok: true, result: result as T };
    } };
    const client = createHostBridgeClient(transport);
    await client.openVault("/vault", "secret", false);
    await client.readOverview({ page: 1 });
    await client.readDocuments();
    await client.readConversation({ limit: 2 });
    await client.readSpending?.({ period: "custom", granularity: "subcategory", account_id: "acct:checking", currency: "USD", start_date: "2026-08-01", end_date: "2026-08-31" });
    await client.readAccountLedger("acct:checking", "opaque-cursor", 25);

    expect(frames.map((frame) => frame.requestId)).toEqual(["desktop-1", "desktop-2", "desktop-3", "desktop-4", "desktop-5", "desktop-6"]);
    expect(frames.map((frame) => frame.operation)).toEqual(["bridge.open_vault", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read"]);
    expect(frames[0].payload).toEqual({ vault_directory: "/vault", passphrase: "secret", create: false });
    expect(frames[1].payload).toEqual({ surface: "overview", parameters: { page: 1 }, job_id: "desktop-overview-2" });
    expect(frames[2].payload).toEqual({ surface: "documents", parameters: {}, job_id: "desktop-documents-3" });
    expect(frames[3].payload).toEqual({ surface: "conversation", parameters: { limit: 2 }, job_id: "desktop-conversation-4" });
    expect(frames[4].payload).toEqual({ surface: "spending", parameters: { period: "custom", granularity: "subcategory", account_id: "acct:checking", currency: "USD", start_date: "2026-08-01", end_date: "2026-08-31" }, job_id: "desktop-spending-5" });
    expect(frames[5].payload).toEqual({ surface: "account_ledger", parameters: { account_id: "acct:checking", cursor: "opaque-cursor", limit: 25 }, job_id: "desktop-account_ledger-6" });
  });

  it("does not erase an explicitly invalid account-ledger limit", async () => {
    const frames: BridgeRequest[] = [];
    const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      return { protocol: "2.0", request_id: frame.requestId, ok: true,
        result: { surface: "account_ledger", job_id: "job", data: {} } as T };
    } });

    await client.readAccountLedger("acct:checking", undefined, 0);
    await client.readAccountLedger("acct:checking", undefined, -1);
    await client.readAccountLedger("acct:checking", undefined, 101);

    expect(frames.map((frame) => frame.payload.parameters)).toEqual([
      { account_id: "acct:checking", limit: 0 },
      { account_id: "acct:checking", limit: -1 },
      { account_id: "acct:checking", limit: 101 },
    ]);
  });

  it("frames a correction reply as part of conversation", async () => {
    const frames: BridgeRequest[] = [];
    const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      return { protocol: "1.0", request_id: frame.requestId, ok: true, result: { kind: "completed", message: "Set aside.", state: null, reason: null } as T };
    } });

    await client.declineQuestion("question-2", "dont_know");

    expect(frames.map((frame) => frame.operation)).toEqual(["viva.conversation.decline"]);
    expect(frames[0].payload).toEqual({ question_id: "question-2", reason: "dont_know" });
  });

  it("sends only the exact Activity movement and desired-value identities", async () => {
    const frames: BridgeRequest[] = [];
    const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      return { protocol: "2.0", request_id: frame.requestId, ok: true, result: { kind: "completed", message: "Recorded.", state: null, reason: null } as T };
    } });

    await client.assignActivityCategory("movement:key", "groceries");
    await client.assignActivityClassification(["movement:one", "movement:two"], "groceries", "supermarket");
    await client.assignActivityMeaning("movement:key", "loan", "Sam");
    await client.replaceActivityTags("movement:key", ["japan", "tax"]);
    await client.replaceActivityTags("movement:key", []);
    await client.addActivityTags(["movement:one", "movement:two"], ["japan", "tax"]);
    await client.removeActivityTags(["movement:one", "movement:two"], ["tax"]);
    await client.confirmActivityTransfer("movement:key", "movement:counterpart");
    await client.rejectActivityTransfer("movement:key");
    await client.unlinkActivityTransfer("movement:key", "movement:counterpart");

    expect(frames.map((frame) => frame.operation)).toEqual(["viva.activity.assign_category", "viva.activity.assign_classification", "viva.activity.assign_meaning", "viva.activity.replace_tags", "viva.activity.replace_tags", "viva.activity.add_tags", "viva.activity.remove_tags", "viva.activity.confirm_transfer", "viva.activity.reject_transfer", "viva.activity.unlink_transfer"]);
    expect(frames.map((frame) => frame.payload)).toEqual([
      { movement_key: "movement:key", category_id: "groceries" },
      { movement_ids: ["movement:one", "movement:two"], category_id: "groceries", subcategory_id: "supermarket" },
      { movement_key: "movement:key", meaning: "loan", counterparty: "Sam" },
      { movement_key: "movement:key", tag_ids: ["japan", "tax"] },
      { movement_key: "movement:key", tag_ids: [] },
      { movement_ids: ["movement:one", "movement:two"], tag_ids: ["japan", "tax"] },
      { movement_ids: ["movement:one", "movement:two"], tag_ids: ["tax"] },
      { movement_key: "movement:key", counterpart_key: "movement:counterpart" },
      { movement_key: "movement:key" },
      { movement_key: "movement:key", counterpart_key: "movement:counterpart" },
    ]);
    expect(frames.map((frame) => Object.keys(frame.payload).sort())).toEqual([
      ["category_id", "movement_key"], ["category_id", "movement_ids", "subcategory_id"], ["counterparty", "meaning", "movement_key"], ["movement_key", "tag_ids"], ["movement_key", "tag_ids"], ["movement_ids", "tag_ids"], ["movement_ids", "tag_ids"],
      ["counterpart_key", "movement_key"], ["movement_key"], ["counterpart_key", "movement_key"],
    ]);
  });

  it("frames proposal confirmation by opaque identity and a yes-or-no sentence", async () => {
    const frames: BridgeRequest[] = [];
    const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      return { protocol: "1.0", request_id: frame.requestId, ok: true,
        result: { kind: "completed", message: "Recorded.", state: null, reason: null } as T };
    } });

    await client.confirmProposal?.("proposal-1", "yes", "Open Sample Loan?");

    expect(frames.map((frame) => frame.operation)).toEqual(["viva.conversation.confirm"]);
    expect(frames[0].payload).toEqual({ proposal_id: "proposal-1", said: "yes", asked: "Open Sample Loan?" });
  });

  it("frames a capture as one path per request and asserts no job identity", async () => {
    const frames: BridgeRequest[] = [];
    const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      return { protocol: "1.0", request_id: frame.requestId, ok: true, result: { kind: "completed", message: "Saved privately.", state: null, reason: null } as T };
    } });

    await client.uploadDocument("/chosen/first.pdf");
    await client.uploadDocument("/chosen/second.pdf");

    expect(frames.map((frame) => frame.operation)).toEqual(["viva.documents.upload", "viva.documents.upload"]);
    expect(frames[0].payload).toEqual({ path: "/chosen/first.pdf" });
    expect(frames[1].payload).toEqual({ path: "/chosen/second.pdf" });
    for (const frame of frames) expect(Object.keys(frame.payload)).toEqual(["path"]);
  });

  it("forwards the native file picker and the dropped-path subscription without a sidecar frame", async () => {
    const frames: unknown[] = [];
    let listener: ((paths: readonly string[]) => void) | null = null;
    const client = createHostBridgeClient({
      request: async <T>(frame: BridgeRequest) => { frames.push(frame); return { protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }; },
      pickDocumentPaths: async () => ["/chosen/first.pdf", "/chosen/second.pdf"],
      subscribeToDroppedPaths: async (listen) => { listener = listen; return () => { listener = null; }; },
    });

    await expect(client.pickDocumentPaths?.()).resolves.toEqual(["/chosen/first.pdf", "/chosen/second.pdf"]);
    const stop = await client.subscribeToDroppedPaths?.(() => {});
    expect(listener).not.toBeNull();
    stop?.();
    expect(listener).toBeNull();
    expect(frames).toEqual([]);
  });

  it("offers no capture verbs when the host transport carries none", async () => {
    const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => ({ protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }) });
    expect(client.pickDocumentPaths).toBeUndefined();
    expect(client.subscribeToDroppedPaths).toBeUndefined();
  });

  it("keeps three unlike failures apart at the transport", async () => {
    const refusing = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => ({ protocol: "1.0", request_id: frame.requestId, ok: false, error: { code: "invalid_request", message: "reason must be one of: dont_know, not_now" } } as BridgeResponse<T>) });
    const empty = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => ({ protocol: "1.0", request_id: frame.requestId, ok: true } as BridgeResponse<T>) });
    const silent = createHostBridgeClient({ request: async () => { throw new Error("the sidecar went away"); } });

    // A sidecar that said no, a sidecar that said yes and sent nothing to read,
    // and a sidecar that was never reached. The second may have written, so it
    // must never arrive looking like the third.
    await expect(refusing.declineQuestion("question-1", "not_now")).rejects.toBeInstanceOf(BridgeRefusal);
    await expect(refusing.declineQuestion("question-1", "not_now")).rejects.toMatchObject({ code: "invalid_request" });
    await expect(empty.declineQuestion("question-1", "not_now")).rejects.toBeInstanceOf(BridgeUnreadable);
    const unreached = await silent.declineQuestion("question-1", "not_now").catch((failure) => failure);
    expect(unreached).not.toBeInstanceOf(BridgeRefusal);
    expect(unreached).not.toBeInstanceOf(BridgeUnreadable);
  });

  it("forwards the native folder picker without a sidecar frame", async () => {
    const frames: unknown[] = [];
    const client = createHostBridgeClient({
      request: async <T>(frame: BridgeRequest) => { frames.push(frame); return { protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }; },
      pickVaultDirectory: async () => "/chosen/local-vault",
    });
    await expect(client.pickVaultDirectory?.()).resolves.toBe("/chosen/local-vault");
    expect(frames).toEqual([]);
  });

  it("bounds missing results and failed bridge envelopes", async () => {
    const missing = createHostBridgeClient({ request: async () => ({ protocol: "1.0", request_id: "req", ok: true }) });
    const failed = createHostBridgeClient({ request: async () => ({ protocol: "1.0", request_id: "req", ok: false, error: { code: "vault_open_failed", message: "bounded failure" } }) });
    await expect(missing.openVault("/vault", "secret", false)).rejects.toBeInstanceOf(BridgeUnreadable);
    await expect(failed.openVault("/vault", "secret", false)).rejects.toThrow("bounded failure");
  });

  it("detects only the installed window transport", () => {
    expect(hasHostBridge()).toBe(false);
    expect(createDetectedBridgeClient()).toBeNull();
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => ({ protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }) };
    expect(hasHostBridge()).toBe(true);
    expect(createDetectedBridgeClient()).not.toBeNull();
  });
});
