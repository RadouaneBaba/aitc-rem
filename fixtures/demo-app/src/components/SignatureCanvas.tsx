import { useRef } from 'react';

/**
 * A canvas the tester draws on. Nothing semantic is knowable here -- only
 * coordinates -- so it must produce `canvas_interaction` and a visible warning
 * rather than an invented description (SS6.8).
 */
export function SignatureCanvas() {
  const ref = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);

  const pos = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = ref.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  return (
    <canvas
      ref={ref}
      className="signature"
      width={420}
      height={120}
      onPointerDown={(e) => {
        drawing.current = true;
        const ctx = ref.current!.getContext('2d')!;
        const { x, y } = pos(e);
        ctx.beginPath();
        ctx.moveTo(x, y);
      }}
      onPointerMove={(e) => {
        if (!drawing.current) return;
        const ctx = ref.current!.getContext('2d')!;
        const { x, y } = pos(e);
        ctx.lineTo(x, y);
        ctx.stroke();
      }}
      onPointerUp={() => (drawing.current = false)}
      onPointerLeave={() => (drawing.current = false)}
    />
  );
}
