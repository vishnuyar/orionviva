import { demoState, type DemoState } from "./model";

export type SurfaceName = "overview" | "documents" | "review";
export type SurfaceParameters = Record<string, string | number>;

export type BridgeResponse<T> = {
  protocol: string;
  request_id: string;
  ok: boolean;
  result?: T;
  error?: { code: string; message: string };
};

export type SurfaceReadResult = {
  surface: SurfaceName;
  job_id: string;
  data: Record<string, unknown>;
};

export type BridgeRequest = {
  requestId: string;
  operation: string;
  payload: Record<string, unknown>;
};

export type BridgeTransport = {
  request: <T>(frame: BridgeRequest) => Promise<BridgeResponse<T>>;
};

declare global {
  interface Window {
    orionVivaBridge?: BridgeTransport;
  }
}

export type BridgeClient = {
  openVault: (vaultDirectory: string, passphrase: string) => Promise<void>;
  readOverview: (parameters?: SurfaceParameters) => Promise<SurfaceReadResult>;
  readDocuments: () => Promise<SurfaceReadResult>;
  readReview: (parameters?: SurfaceParameters) => Promise<SurfaceReadResult>;
  snapshot: () => Promise<DemoState>;
};

function fixtureRead(surface: SurfaceName, data: Record<string, unknown>): SurfaceReadResult {
  return { surface, job_id: `fixture-${surface}`, data };
}

export function createFixtureBridgeClient(snapshot: DemoState = demoState): BridgeClient {
  return {
    openVault: async () => undefined,
    readOverview: async () => fixtureRead("overview", { state: "ready", snapshot }),
    readDocuments: async () => fixtureRead("documents", { state: "ready", snapshot }),
    readReview: async () => fixtureRead("review", { state: "ready", snapshot }),
    snapshot: async () => snapshot,
  };
}

export function createHostBridgeClient(transport: BridgeTransport): BridgeClient {
  let requestNumber = 0;
  async function request<T>(operation: string, payload: Record<string, unknown>): Promise<T> {
    const requestId = `desktop-${++requestNumber}`;
    const response = await transport.request<T>({ requestId, operation, payload });
    if (!response.ok || response.result === undefined) {
      throw new Error(response.error?.message ?? "desktop bridge request failed");
    }
    return response.result;
  }

  async function read(surface: SurfaceName, parameters: SurfaceParameters = {}): Promise<SurfaceReadResult> {
    return request<SurfaceReadResult>("viva.surface.read", {
      surface,
      parameters,
      job_id: `desktop-${surface}-${requestNumber + 1}`,
    });
  }

  return {
    openVault: async (vaultDirectory, passphrase) => {
      await request("bridge.open_vault", { vault_directory: vaultDirectory, passphrase });
    },
    readOverview: (parameters) => read("overview", parameters),
    readDocuments: () => read("documents"),
    readReview: (parameters) => read("review", parameters),
    snapshot: async () => {
      const [overview, documents, review] = await Promise.all([
        read("overview"),
        read("documents"),
        read("review"),
      ]);
      return snapshotFromBridge(overview.data, documents.data, review.data);
    },
  };
}

export function createDetectedBridgeClient(): BridgeClient {
  if (typeof window !== "undefined" && window.orionVivaBridge) {
    return createHostBridgeClient(window.orionVivaBridge);
  }
  return createFixtureBridgeClient();
}

export function hasHostBridge(): boolean {
  return typeof window !== "undefined" && Boolean(window.orionVivaBridge);
}

function snapshotFromBridge(
  overview: Record<string, unknown>,
  documents: Record<string, unknown>,
  review: Record<string, unknown>,
): DemoState {
  // The bridge returns product read models. Keep the UI fallback for fields
  // not yet represented by the reviewed surface contract.
  return {
    ...demoState,
    currentThrough: String(overview.as_of ?? demoState.currentThrough),
    corpusSource: "Opened local vault",
    corpusCoverage: "Live vault surface",
    accounts: Array.isArray(overview.accounts) ? overview.accounts.map((item, index) => {
      const account = item as Record<string, unknown>;
      const balance = (account.balance ?? {}) as Record<string, unknown>;
      const amount = String(balance.amount ?? "0");
      const currency = String(balance.currency ?? account.currency ?? "");
      return {
        ...demoState.accounts[index % demoState.accounts.length],
        id: String(account.account ?? `account-${index + 1}`),
        name: String(account.name ?? account.account ?? `Account ${index + 1}`),
        kind: String(account.kind ?? "Account"),
        currency,
        exactValue: amount,
        display: currency ? `${currency} ${amount}` : amount,
        grade: String(balance.grade ?? "unverified") as typeof demoState.accounts[number]["grade"],
        gradeLabel: String(balance.grade ?? "Unverified"),
        asOf: String(balance.dated ?? balance.as_of ?? ""),
        coverage: "Opened vault projection",
        note: String(balance.explanation ?? "Read from opened vault"),
        state: "ready" as const,
      };
    }) : demoState.accounts,
    documents: Array.isArray(documents.documents) ? documents.documents.map((item, index) => ({
      ...demoState.documents[index % demoState.documents.length],
      name: String((item as Record<string, unknown>).id ?? `document-${index + 1}`),
      state: (item as Record<string, unknown>).resolved ? "Verified" : "Pending",
    })) : demoState.documents,
    reviewCount: Array.isArray(review.questions) ? review.questions.length : demoState.reviewCount,
  };
}
