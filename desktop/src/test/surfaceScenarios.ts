import type {
  AccountView,
  FeatureResult,
  FigureView,
  OverviewData,
  PictureView,
  SurfaceMode,
  SurfaceSnapshot,
} from "../surface/types";

export const LONG_TRUTH = "A deliberately long supplied truth value stays visible and wraps without truncation across supported narrow viewport boundaries.";

export function absent<T>(): FeatureResult<T> {
  return { state: "absent", reason: "not_read" };
}

export function ready<T>(data: T): FeatureResult<T> {
  return { state: "ready", data };
}

export function partial<T>(data: T): FeatureResult<T> {
  return { state: "partial", data, issues: [{ code: "partial", message: "Some supplied fields were unavailable." }] };
}

export function needsInput<T>(data: T): FeatureResult<T> {
  return { state: "needs_input", data, issues: [{ code: "needs_input", message: "Some supplied fields need input." }] };
}

export function unavailable<T>(): FeatureResult<T> {
  return { state: "unavailable", reason: "not_connected" };
}

export function failed<T>(): FeatureResult<T> {
  return { state: "failed", reason: "read_failed" };
}

export function makeAccount(overrides: Partial<AccountView> = {}): AccountView {
  return {
    id: "scenario-account",
    name: "Scenario account",
    kind: "Depository",
    measure: "balance",
    exactValue: "",
    currency: "USD",
    display: "$10.00",
    grade: "unavailable",
    gradeLabel: "Evidence status unavailable",
    gradeDescription: "The read did not supply a recognized evidence status.",
    note: null,
    asOf: "",
    coverage: null,
    provenance: null,
    evidenceLinks: [],
    state: "ready",
    ...overrides,
  };
}

export function makeFigure(overrides: Partial<FigureView> = {}): FigureView {
  return {
    id: "scenario-currency",
    display: "$10.00",
    exactValue: "",
    currency: "USD",
    measure: "net_worth",
    grade: "unavailable",
    gradeLabel: "Evidence status unavailable",
    gradeDescription: "The read did not supply a recognized evidence status.",
    asOf: "",
    coverage: [],
    caveats: [],
    evidenceLinks: [],
    ...overrides,
  };
}

export function makePicture(overrides: Partial<PictureView> = {}): PictureView {
  return {
    coverage: "",
    readOn: "",
    figures: [],
    withheld: [],
    unplaced: [],
    ...overrides,
  };
}

export function makeOverview(overrides: Partial<OverviewData> = {}): OverviewData {
  return {
    picture: makePicture(),
    corpusCoverage: "",
    accounts: [],
    recent: [],
    ...overrides,
  };
}

const disclosure = (mode: SurfaceMode): SurfaceSnapshot["disclosure"] => mode === "demo" ? {
  title: "Sample vault",
  subtitle: "Fictional sample data",
  detail: "Every name, document, and figure in this vault is fictional and stored with the app.",
} : {
  title: "Private vault",
  subtitle: "Opened on this device",
  detail: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so.",
};

export function makeSurfaceScenario(mode: SurfaceMode, overrides: Partial<Omit<SurfaceSnapshot, "mode" | "disclosure">> = {}): SurfaceSnapshot {
  return {
    mode,
    disclosure: disclosure(mode),
    overview: absent(),
    documents: absent(),
    review: absent(),
    activity: absent(),
    conversation: absent(),
    trust: absent(),
    ...overrides,
  };
}
