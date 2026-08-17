import { demoState, type DemoState } from "./model";

export type SurfaceDataSource = {
  id: "synthetic-demo" | "local-vault";
  label: string;
  snapshot: () => DemoState;
};

// The shell consumes this boundary so a sidecar-backed source can replace the
// fixture without changing navigation or feature components.
export const syntheticSurfaceData: SurfaceDataSource = {
  id: "synthetic-demo",
  label: "Synthetic local corpus",
  snapshot: () => demoState,
};

export function readSurface(source: SurfaceDataSource): DemoState {
  return source.snapshot();
}
