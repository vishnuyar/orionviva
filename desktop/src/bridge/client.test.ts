import { afterEach, describe, expect, it } from "vitest";
import { createDetectedBridgeClient, createHostBridgeClient, hasHostBridge } from "./client";
import { BridgeRefusal, BridgeUnreadable } from "./contracts";
import type { BridgeRequest, BridgeResponse, BridgeTransport } from "./contracts";

describe("bridge transport framing", () => {
  afterEach(() => { delete window.orionVivaBridge; });

  it("uses the atomic priority read advertised by the opened vault", async () => {
    const frames: BridgeRequest[] = [];
    const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      const result = frame.operation === "bridge.open_vault"
        ? { state: "opened", priority_reads: ["overview_accounts"] }
        : { surface: frame.payload.surface, job_id: "job", data: {} };
      return { protocol: "2.0", request_id: frame.requestId, ok: true, result: result as T };
    } });
    await client.openVault("/vault", "secret", false);
    await client.readOverviewAccounts(true);
    expect(frames[1].payload).toEqual({ surface: "overview_accounts", parameters: { refresh: 1 }, job_id: "desktop-overview_accounts-2" });
  });

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
    expect(frames[2].payload).toEqual({ surface: "documents", parameters: { contract_version: "documents-page-v1" }, job_id: "desktop-documents-3" });
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
      pickBackupSavePath: async () => "/chosen/backup.orionvault",
      pickDocumentPaths: async () => ["/chosen/first.pdf", "/chosen/second.pdf"],
      subscribeToDroppedPaths: async (listen) => { listener = listen; return () => { listener = null; }; },
    });

    await expect(client.pickBackupSavePath?.()).resolves.toBe("/chosen/backup.orionvault");
    await expect(client.pickDocumentPaths?.()).resolves.toEqual(["/chosen/first.pdf", "/chosen/second.pdf"]);
    const stop = await client.subscribeToDroppedPaths?.(() => {});
    expect(listener).not.toBeNull();
    stop?.();
    expect(listener).toBeNull();
    expect(frames).toEqual([]);
  });

  it("offers no capture verbs when the host transport carries none", async () => {
    const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => ({ protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }) });
    expect(client.pickBackupSavePath).toBeUndefined();
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

it("frames selected accounting correction, undo and period reads without widening context", async () => {
  const frames: BridgeRequest[] = [];
  const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => {
    frames.push(frame);
    return { protocol: "2.0", request_id: frame.requestId, ok: true, result: { surface: frame.payload.surface, data: {}, kind: "completed", message: "Updated" } as T };
  } });
  await client.askViva("This was a refundable deposit", true, false, "new_question", ["movement-1"]);
  await client.undoAccountingCorrection?.("correction-1");
  await client.readAccounting?.("2026-09-01", "2026-09-30");
  expect(frames[0].operation).toBe("viva.conversation.ask");
  expect(frames[0].payload).toEqual({ question: "This was a refundable deposit", mirrored: true, plan_request: false, context_mode: "new_question", movement_ids: ["movement-1"] });
  expect(frames[1].payload).toEqual({ question: "Undo accounting correction", mirrored: true, undo_correction_id: "correction-1" });
  expect(frames[2].payload).toMatchObject({ surface: "accounting", parameters: { start: "2026-09-01", end: "2026-09-30" } });
});

describe("saved original framing", () => {
  it("sends only document identity and requested page without replaying an older-host refusal", async () => {
    const frames: BridgeRequest[] = [];
    const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      return { protocol: "2.1", request_id: frame.requestId, ok: false, error: { code: "unknown_operation", message: "not supported" } } as BridgeResponse<T>;
    } });
    await expect(client.readDocumentPreview!("a".repeat(64), 2)).rejects.toBeInstanceOf(BridgeRefusal);
    expect(frames).toHaveLength(1);
    expect(frames[0]).toMatchObject({ operation: "viva.documents.preview.read", payload: { document_id: "a".repeat(64), page: 2 } });
  });
});

it("sends only the explicitly supplied opaque saved-answer recovery anchor", async () => {
  const frames: BridgeRequest[] = [];
  const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => {
    frames.push(frame); return { protocol: "2.1", request_id: frame.requestId, ok: true, result: {} as T };
  } });
  await client.askViva("What about a different target?", true, false, "follow_up");
  expect(frames[0].payload).not.toHaveProperty("continuation_recovery");
  const anchor = { version: "allocation-continuation-v1" as const, turn_id: "turn-opaque", answer_id: "answer-opaque" };
  await client.askViva("What about a different target?", true, false, "follow_up", undefined, anchor);
  expect(frames[1].payload).toEqual({ question: "What about a different target?", mirrored: true, plan_request: false, context_mode: "follow_up", continuation_recovery: anchor });
});

describe("five-year sample preparation protocol",()=>{
 const ready = { state:"ready",sample_version:"five-year-life-v1",completed_documents:794,total_documents:794,posted_documents:793,held_documents:1,phase:"ready",message:"Synthetic sample ready" };
 it("prepares and reads progress without directory, passphrase or financial parameters",async()=>{
  const requests:BridgeRequest[]=[];
  const client=createHostBridgeClient({request:async<T>(frame:BridgeRequest)=>{requests.push(frame);return {protocol:"2.0",request_id:frame.requestId,ok:true,result:ready as T};}});
  expect(await client.prepareSampleVault!()).toEqual(ready);expect(await client.readSamplePreparation!()).toEqual(ready);
  expect(requests.map(({operation,payload})=>({operation,payload}))).toEqual([{operation:"bridge.sample.prepare",payload:{}},{operation:"bridge.sample.status",payload:{}}]);
 });
 it.each(["version","total","fraction","negative","oversized","unknown field","ready count","phase mismatch","state","missing field"])("refuses unreadable preparation %s",async(bad)=>{
  const value:Record<string,unknown>={...ready};
  if(bad==="version")value.sample_version="old-sample";if(bad==="total")value.total_documents=793;if(bad==="fraction")value.completed_documents=1.5;if(bad==="negative")value.held_documents=-1;if(bad==="oversized")value.posted_documents=795;if(bad==="unknown field")value.directory="unused";if(bad==="ready count")value.completed_documents=793;if(bad==="phase mismatch")value.phase="capturing";if(bad==="state")value.state="opened";if(bad==="missing field")delete value.message;
  const client=createHostBridgeClient({request:async<T>(frame:BridgeRequest)=>({protocol:"2.0",request_id:frame.requestId,ok:true,result:value as T})});
  await expect(client.prepareSampleVault!()).rejects.toBeInstanceOf(BridgeUnreadable);
 });
});

it("sends explicit new-reading consent and opaque selected confirmations without paths", async () => {
 const frames: BridgeRequest[] = [];
 const client = createHostBridgeClient({ request: async <T>(frame: BridgeRequest) => { frames.push(frame); return { protocol: "2.0", request_id: frame.requestId, ok: true, result: {} as T }; } });
 await client.readRetainedDocuments!([{ documentId: "a".repeat(64), confirmationToken: "opaque.token" }]);
 expect(frames[0].operation).toBe("viva.documents.upload_many");
 expect(frames[0].payload).toEqual({ retained_documents: [{ document_id: "a".repeat(64), confirmation_token: "opaque.token" }], confirm_reading: true });
 await client.uploadDocuments!(["/ordinary.pdf"]); expect(frames[1].payload).toEqual({ paths: ["/ordinary.pdf"] });
});
