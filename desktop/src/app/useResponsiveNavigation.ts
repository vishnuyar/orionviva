import { useEffect, useState } from "react";

export const narrowNavigationQuery = "(max-width: 760px)";

function readNarrowNavigation() {
  return typeof globalThis.matchMedia === "function" && globalThis.matchMedia(narrowNavigationQuery).matches;
}

export function useResponsiveNavigation() {
  const [isNarrow, setIsNarrow] = useState(readNarrowNavigation);

  useEffect(() => {
    if (typeof globalThis.matchMedia !== "function") {
      setIsNarrow(false);
      return undefined;
    }
    const media = globalThis.matchMedia(narrowNavigationQuery);
    const update = (event: MediaQueryListEvent | MediaQueryList) => setIsNarrow(event.matches);
    update(media);
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", update);
      return () => media.removeEventListener("change", update);
    }
    media.addListener(update);
    return () => media.removeListener(update);
  }, []);

  return isNarrow;
}
