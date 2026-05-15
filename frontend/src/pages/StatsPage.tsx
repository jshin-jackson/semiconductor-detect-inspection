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

  const totalCount = rows.reduce((s, r) => s + Number(r.total_count), 0);
  const totalAnomaly = rows.reduce((s, r) => s + Number(r.anomaly_count), 0);
  const anomalyRate = totalCount > 0 ? ((totalAnomaly / totalCount) * 100).toFixed(1) : "0.0";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">Daily Statistics</h1>
        <button onClick={() => void load()} className="text-sm text-blue-600 hover:underline">
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">
          Failed to load data: {error}
        </div>
      )}

      {/* Summary cards */}
      {!loading && rows.length > 0 && (
        <div className="grid grid-cols-3 gap-4">
          <SummaryCard label="Total Inspections" value={totalCount} color="text-gray-800" />
          <SummaryCard label="Defects Detected" value={totalAnomaly} color="text-red-600" />
          <SummaryCard label="Defect Rate" value={`${anomalyRate}%`} color="text-orange-600" />
        </div>
      )}

      {loading ? (
        <ChartSkeleton />
      ) : rows.length === 0 ? (
        <div className="bg-white border-2 border-dashed border-gray-200 rounded-xl py-16 text-center text-gray-400">
          No statistics available. Run some inspections first.
        </div>
      ) : (
        <>
          {/* Bar chart */}
          <ChartCard title="Daily Inspections (Total vs Defects)">
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
                    name === "total_count" ? "Total" : "Defects",
                  ]}
                  labelFormatter={(label) => `Date: ${label}`}
                />
                <Legend
                  formatter={(value) =>
                    value === "total_count" ? "Total Inspections" : "Defects"
                  }
                />
                <Bar dataKey="total_count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                <Bar dataKey="anomaly_count" fill="#ef4444" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* Line chart */}
          <ChartCard title="Daily Average Anomaly Score">
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
                  formatter={(value: number) => [value.toFixed(4), "Avg Anomaly Score"]}
                  labelFormatter={(label) => `Date: ${label}`}
                />
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
              * Score ≥ 0.5 is flagged as a potential defect
            </p>
          </ChartCard>

          {/* Data table */}
          <ChartCard title="Per-Day Details">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    {["Date", "Total", "Defects", "Defect Rate", "Avg Score"].map((h) => (
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

function shortDate(dateStr: string): string {
  const parts = dateStr.split("-");
  if (parts.length === 3) return `${parseInt(parts[1])}/${parseInt(parts[2])}`;
  return dateStr;
}
