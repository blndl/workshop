/** Small line chart of recent values; fixed vertical range so changes are comparable. */
export function Sparkline({ values, min, max, width = 180, height = 40 }: {
  values: number[];
  min: number;
  max: number;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return <svg width={width} height={height} className="spark" />;
  const step = width / (values.length - 1);
  const y = (v: number) => height - ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * (height - 4) - 2;
  const points = values.map((v, i) => `${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} className="spark" role="img" aria-label="signal history">
      <polyline points={points} fill="none" strokeWidth="2" />
    </svg>
  );
}
