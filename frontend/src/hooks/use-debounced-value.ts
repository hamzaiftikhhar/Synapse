"use client";

import { useEffect, useState } from "react";

/**
 * Debounces a fast-changing value (e.g. a search input) so dependent
 * queries don't fire on every keystroke. 300ms is a standard, widely-used
 * interval for search-as-you-type — responsive enough not to feel
 * laggy, long enough to collapse a burst of keystrokes into one request.
 */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
