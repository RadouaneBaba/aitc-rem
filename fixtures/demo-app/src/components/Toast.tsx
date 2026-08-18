import { useEffect } from 'react';

/**
 * Auto-dismisses after 2.5s. This is the case SS6.5 exists for: a recorder that
 * snapshots on the next tick misses the toast entirely, and an assertion about
 * it is then ungroundable.
 */
export function Toast({ message, onDone }: { message: string; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 2500);
    return () => clearTimeout(t);
  }, [message, onDone]);

  return (
    <div className="toast" role="status" aria-live="polite">
      {message}
    </div>
  );
}
