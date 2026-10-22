'use client';

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';

function prefersReducedMotion() {
  return typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Tab state with a cross-fade: `selected` moves at once (for aria-selected and
 * focus), `shown` follows after the panel has faded out.
 */
export function useFadingTabs(count: number, idPrefix: string) {
  const [selected, setSelected] = useState(0);
  const [shown, setShown] = useState(0);
  const [visible, setVisible] = useState(true);
  const timers = useRef<number[]>([]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const select = useCallback(
    (i: number) => {
      setSelected(i);
      timers.current.forEach(clearTimeout);
      timers.current = [];
      if (prefersReducedMotion()) {
        setShown(i);
        setVisible(true);
        return;
      }
      setVisible(false);
      timers.current.push(
        window.setTimeout(() => {
          setShown(i);
          timers.current.push(window.setTimeout(() => setVisible(true), 40));
        }, 200),
      );
    },
    [],
  );

  // WAI-ARIA tabs: arrow keys, Home and End move selection and focus.
  const onKeyDown = (e: KeyboardEvent) => {
    let i = selected;
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') i = (selected + 1) % count;
    else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') i = (selected - 1 + count) % count;
    else if (e.key === 'Home') i = 0;
    else if (e.key === 'End') i = count - 1;
    else return;
    e.preventDefault();
    if (i !== selected) select(i);
    document.getElementById(idPrefix + i)?.focus();
  };

  const tabProps = (i: number) => ({
    role: 'tab' as const,
    id: idPrefix + i,
    'aria-selected': i === selected,
    'aria-controls': idPrefix + 'panel',
    tabIndex: i === selected ? 0 : -1,
    onClick: () => i !== selected && select(i),
  });

  const panelProps = {
    role: 'tabpanel' as const,
    id: idPrefix + 'panel',
    'aria-labelledby': idPrefix + selected,
  };

  return { selected, shown, fadeStyle: { opacity: visible ? 1 : 0, transition: 'opacity .25s ease' }, onKeyDown, tabProps, panelProps };
}
