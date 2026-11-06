import type { CSSProperties, ReactNode } from 'react';

/** Label → 40px rule → serif headline → optional supporting line. */
export default function SectionHead({
  label,
  title,
  sub,
  titleStyle,
  subStyle,
  as: H = 'h2',
}: {
  label: string;
  title: ReactNode;
  sub?: ReactNode;
  titleStyle?: CSSProperties;
  subStyle?: CSSProperties;
  as?: 'h1' | 'h2';
}) {
  return (
    <>
      <div className="label">{label}</div>
      <div className="rule" />
      <H className={H === 'h1' ? 'h1' : 'h2'} style={titleStyle}>
        {title}
      </H>
      {sub && (
        <p className="sub" style={subStyle}>
          {sub}
        </p>
      )}
    </>
  );
}
