import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  LineChart,
  Line,
  ResponsiveContainer,
} from "recharts";
import { fetchStats, type StatRow } from "../api/client";

export default function StatsPage() {
  const [rows, setRows] = useState<StatRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchStats();
      // 날짜 오름차순으로 정렬 (차트는 왼쪽→오른쪽이 시간 순서)
      const sorted = [...res.rows].sort((a, b) =>
        a.inspection_date.localeCompare(b.inspection_date)
      );
      setRows(sorted);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  // 전체 집계 계산
  const totalCount = rows.reduce((s, r) => s + Number(r.total_count), 0);
  const totalAnomaly = rows.reduce((s, r) => s + Number(r.anomaly_count), 0);
  const anomalyRate = totalCount > 0 ? ((totalAnomaly / totalCount) * 100).toFixed(1) : "0.0";

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">일별 통계</h1>
        <button onClick={() => void load()} className="text-sm text-blue-600 hover:underline">
          새로고침
        </button>
      </div>

      {/* 오류 */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">
          데이터 로드 실패: {error}
        </div>
      )}

      {/* 요약 카드 */}
      {!loading && rows.length > 0 && (
        <div className="grid grid-cols-3 gap-4">
          <SummaryCard label="총 검사 건수" value={totalCount} color="text-gray-800" />
          <SummaryCard label="결함 건수" value={totalAnomaly} color="text-red-600" />
          <SummaryCard label="결함률" value={`${anomalyRate}%`} color="text-orange-600" />
        </div>
      )}

      {loading ? (
        <ChartSkeleton />
      ) : rows.length === 0 ? (
        <div className="bg-white border-2 border-dashed border-gray-200 rounded-xl py-16 text-center text-gray-400">
          통계 데이터가 없습니다. 먼저 이미지를 검사해보세요.
        </div>
      ) : (
        <>
          {/* 검사 건수 막대 차트 */}
          <ChartCard title="일별 검사 건수 (총 검사 vs 결함)">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={rows} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="inspection_date"
                  tick={{ fontSize: 12 }}
                  tickFormatter={shortDate}
                />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip
                  formatter={(value: number, name: string) => [
                    value,
                    name === "total_count" ? "총 건수" : "결함 건수",
                  ]}
                  labelFormatter={(label) => `날짜: ${label}`}
                />
                <Legend
                  formatter={(value) =>
                    value === "total_count" ? "총 검사 건수" : "결함 건수"
                  }
                />
                <Bar dataKey="total_count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                <Bar dataKey="anomaly_count" fill="#ef4444" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* 평균 이상 점수 꺾은선 차트 */}
          <ChartCard title="일별 평균 이상 점수">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={rows} margin={{ top: 10, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="inspection_date"
                  tick={{ fontSize: 12 }}
                  tickFormatter={shortDate}
                />
                <YAxis domain={[0, 1]} tick={{ fontSize: 12 }} />
                <Tooltip
                  formatter={(value: number) => [value.toFixed(4), "평균 이상 점수"]}
                  labelFormatter={(label) => `날짜: ${label}`}
                />
                {/* 임계값 기준선 (0.5) */}
                <Line
                  type="monotone"
                  dataKey="avg_score"
                  stroke="#f97316"
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
                />
              </LineChart>
            </ResponsiveContainer>
            <p className="text-xs text-gray-400 text-right mt-1">
              * 점수 0.5 이상 = 결함 의심 구간
            </p>
          </ChartCard>

          {/* 원시 데이터 테이블 */}
          <ChartCard title="날짜별 상세 수치">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    {["날짜", "총 검사", "결함 수", "결함률", "평균 점수"].map((h) => (
                      <th
                        key={h}
                        className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {[...rows].reverse().map((r) => {
                    const rate =
                      r.total_count > 0
                        ? ((r.anomaly_count / r.total_count) * 100).toFixed(1)
                        : "0.0";
                    return (
                      <tr key={r.inspection_date} className="hover:bg-gray-50">
                        <td className="px-4 py-2 font-medium">{r.inspection_date}</td>
                        <td className="px-4 py-2">{r.total_count}</td>
                        <td className="px-4 py-2 text-red-600 font-medium">
                          {r.anomaly_count}
                        </td>
                        <td className="px-4 py-2 text-orange-600">{rate}%</td>
                        <td className="px-4 py-2 font-mono">
                          {Number(r.avg_score).toFixed(4)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </ChartCard>
        </>
      )}
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-4">{title}</h2>
      {children}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-4 text-center">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="h-72 bg-gray-200 rounded-xl" />
      <div className="h-52 bg-gray-200 rounded-xl" />
    </div>
  );
}

/** "2025-03-09" → "3/9" 짧은 날짜 표시 */
function shortDate(dateStr: string): string {
  const parts = dateStr.split("-");
  if (parts.length === 3) return `${parseInt(parts[1])}/${parseInt(parts[2])}`;
  return dateStr;
}
