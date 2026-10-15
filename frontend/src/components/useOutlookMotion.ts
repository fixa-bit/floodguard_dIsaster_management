import { useEffect, useState } from "react";

export function useOutlookMotion(active: boolean) {
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [visible, setVisible] = useState(() => !document.hidden);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onPreference = () => setReducedMotion(preference.matches);
    const onVisibility = () => setVisible(!document.hidden);
    preference.addEventListener("change", onPreference);
    document.addEventListener("visibilitychange", onVisibility);
    return () => { preference.removeEventListener("change", onPreference); document.removeEventListener("visibilitychange", onVisibility); };
  }, []);

  return { canAnimate: active && visible && enabled && !reducedMotion, reducedMotion, setEnabled, enabled };
}
