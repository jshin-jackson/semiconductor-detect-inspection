/** 이상 점수 게이지 바 — 0~1 범위 */
interface Props {
  score: number;       // 0~1
  threshold: number;   // 임계값 (예: 0.5)
  showLabel?: boolean;
}

export default function ScoreBar({ score, threshold, showLabel = true }: Props) {
  const pct = Math.round(score * 100);
  const isAnomaly = score >= threshold;
  const barColor = isAnomaly ? "bg-red-500" : "bg-blue-500";
  const thresholdPct = Math.round(threshold * 100);

  return (
    <div className="w-full">
      {showLabel && (
        <div className="flex justify-between text-sm mb-1">
          <span className="font-medium text-gray-700">이상 점수</span>
          <span className={`font-bold ${isAnomaly ? "text-red-600" : "text-blue-600"}`}>
            {score.toFixed(4)}
          </span>
        </div>
      )}
      <div className="relative h-4 bg-gray-200 rounded-full overflow-visible">
        {/* 점수 바 */}
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
        {/* 임계값 마커 */}
        <div
          className="absolute top-0 h-full w-0.5 bg-gray-700"
          style={{ left: `${thresholdPct}%` }}
          title={`임계값: ${threshold}`}
        />
      </div>
      <div className="flex justify-between text-xs text-gray-400 mt-0.5">
        <span>0</span>
        <span style={{ marginLeft: `${thresholdPct - 10}%` }}>임계값({threshold})</span>
        <span>1</span>
      </div>
    </div>
  );
}
