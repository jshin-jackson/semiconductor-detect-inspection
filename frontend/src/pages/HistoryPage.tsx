import { useEffect, useState } from "react";
import { fetchHistory, type InspectionRecord } from "../api/client";
import StatusBadge from "../components/StatusBadge";

export default function HistoryPage() {
  const [records, setRecords] = useState<InspectionRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);

  const load = async (n: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchHistory(n);
      setRecords(res.records);
      setTotal(res.total);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(limit);
  }, [limit]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Inspection History</h1>
          {!loading && (
            <p className="text-sm text-gray-500 mt-0.5">{total} records found</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="text-sm border border-gray-300 rounded px-2 py-1.5 text-gray-700"
          >
            {[20, 50, 100, 200].map((n) => (
              <option key={n} value={n}>
                Last {n} records
              </option>
            ))}
          </select>
          <button
            onClick={() => void load(limit)}
            className="text-sm text-blue-600 hover:underline"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">
          Failed to load data: {error}
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {["Filename", "Anomaly Score", "Result", "Inspected At", "Model Version"].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide"
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                [...Array(8)].map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    {[...Array(5)].map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 bg-gray-200 rounded w-24" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : records.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-gray-400">
                    No inspection history. Go to /inspect to run your first inspection.
                  </td>
                </tr>
              ) : (
                records.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-medium text-gray-800 max-w-xs truncate">
                      {r.filename}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`font-mono font-semibold ${
                          r.is_anomaly ? "text-red-600" : "text-blue-600"
                        }`}
                      >
                        {Number(r.anomaly_score).toFixed(4)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        status={r.is_anomaly ? "anomaly" : "normal"}
                        label={r.is_anomaly ? "Defect" : "Normal"}
                      />
                    </td>
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                      {formatTimestamp(r.timestamp)}
                    </td>
                    <td className="px-4 py-3 text-gray-400 font-mono text-xs truncate max-w-xs">
                      {r.model_version ?? "-"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-US", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(ts);
  }
}
