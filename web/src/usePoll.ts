import { useEffect, useRef, useState } from "react";

/** Calls `fetcher` every `ms` milliseconds; keeps the last value and error. */
export function usePoll<T>(fetcher: () => Promise<T>, ms: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;

  useEffect(() => {
    let alive = true;
    const run = async () => {
      try {
        const value = await fetchRef.current();
        if (alive) {
          setData(value);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    };
    run();
    const id = setInterval(run, ms);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [ms]);

  return { data, error };
}
