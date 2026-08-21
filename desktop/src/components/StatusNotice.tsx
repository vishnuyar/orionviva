import type { ReactNode } from "react";
import type { Notice, NoticeKind } from "../surface/types";

// How a notice is dressed follows the kind it declares. Nothing here reads the
// sentence: a notice saying something did not happen must not be able to
// arrive wearing the mark that has only ever meant it did.
export function StatusNotice({ notice, onDismiss, icons, dismissIcon }: { notice: Notice | null; onDismiss: () => void; icons: Record<NoticeKind, ReactNode>; dismissIcon: ReactNode }) {
  if (!notice) return null;
  return <div className={notice.kind === "refused" ? "notice notice-refused" : "notice"} role="status" data-kind={notice.kind}>{icons[notice.kind]}<span>{notice.text}</span><button className="notice-close" onClick={onDismiss} aria-label="Dismiss notice">{dismissIcon}</button></div>;
}
