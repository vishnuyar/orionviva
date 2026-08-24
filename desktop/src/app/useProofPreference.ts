import { useCallback, useState } from "react";
import { readShowVerificationDetails, writeShowVerificationDetails } from "../bridge/device-preferences";

export { SHOW_VERIFICATION_DETAILS_KEY, readShowVerificationDetails, writeShowVerificationDetails } from "../bridge/device-preferences";

export function useProofPreference() {
  const [showVerificationDetails, setStoredValue] = useState(() => readShowVerificationDetails());
  const setShowVerificationDetails = useCallback((value: boolean) => {
    // A storage failure takes the safe session fallback too: routine proof is
    // never made visible under a preference the installed copy cannot retain.
    setStoredValue(writeShowVerificationDetails(value) ? value : false);
  }, []);
  return { showVerificationDetails, setShowVerificationDetails };
}
