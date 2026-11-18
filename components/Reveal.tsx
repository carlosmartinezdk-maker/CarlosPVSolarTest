'use client';

import { usePathname } from 'next/navigation';
import { useEffect } from 'react';

/** Fades and raises `[data-reveal]` elements as they scroll into view. */
export default function Reveal() {
  const pathname = usePathname();

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) return;
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          const el = e.target as HTMLElement;
          el.style.opacity = '1';
          el.style.transform = 'none';
          io.unobserve(el);
        }),
      { threshold: 0.12 },
    );
    // Only hide what is below the fold, so nothing already on screen flickers.
    document.querySelectorAll<HTMLElement>('[data-reveal]').forEach((el) => {
      if (el.getBoundingClientRect().top <= window.innerHeight) return;
      el.style.opacity = '0';
      el.style.transform = 'translateY(12px)';
      el.style.transition = 'opacity .6s ease, transform .6s ease';
      io.observe(el);
    });
    return () => io.disconnect();
  }, [pathname]);

  return null;
}
