import type { Destination } from "../surface/types";

export const destinations: Array<{ id: Destination; label: string; eyebrow: string }> = [
  { id: "overview", label: "Overview", eyebrow: "Your picture" },
  { id: "accounts", label: "Accounts", eyebrow: "Where money sits" },
  { id: "activity", label: "Activity", eyebrow: "What moved" },
  { id: "documents", label: "Documents", eyebrow: "What supports it" },
  { id: "review", label: "Review", eyebrow: "What needs you" },
  { id: "trust", label: "Trust", eyebrow: "How it works" },
];
