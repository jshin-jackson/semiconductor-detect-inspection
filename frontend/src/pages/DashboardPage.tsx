import { useEffect, useState } from "react";
import {
  fetchHealth,
  fetchModel,
  fetchStats,
  type HealthResponse,
  type ModelInfo,
  type StatRow,
} from "../api/client";
import StatusBadge from "../components/StatusBadge";

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [todayStat, setTodayStat] = useState<StatRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [h, m, s] = await Promise.all([fetchHealth(), fetchModel(), fetchStats()]);
      setHealth(h);
      setModel(m);
      setTodayStat(s.rows[0] ?? null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 30_000);
    return () => clearInterval(id);
  }, []);

  if (loading) return <Skeleton />;
  if (error)
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-red-700">
        Server connection failed: {error}
      </div>
    );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">Dashboard</h1>
        <button
          onClick={() => void load()}
          className="text-sm text-blue-600 hover:underline"
        >
          Refresh
        </button>
      </div>

      {/* Server Status */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Server Status
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatusCard
            title="API Server"
            value={
              <StatusBadge
                status={health?.status === "ok" ? "ok" : "degraded"}
                label={health?.status ?? "-"}
              />
            }
          />
          <StatusCard
            title="Model"
            value={
              <StatusBadge
                status={health?.model_loaded ? "ok" : "error"}
                label={health?.model_loaded ? "Loaded" : "Not loaded"}
              />
            }
          />
          <StatusCard
            title="MinIO"
            value={
              <StatusBadge
                status={health?.minio_connected ? "connected" : "disconnected"}
                label={health?.minio_connected ? "Connected" : "Error"}
              />
            }
          />
          <StatusCard
            title="StarRocks"
            value={
              <StatusBadge
                status={health?.starrocks_connected ? "connected" : "disconnected"}
                label={health?.starrocks_connected ? "Connected" : "Error"}
              />
            }
          />
        </div>
      </section>

      {/* Model Info */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Model Info
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatusCard
            title="Version"
            value={
              <span className="text-sm font-mono text-gray-700 truncate" title={model?.model_version ?? "-"}>
                {model?.model_version ?? "-"}
              </span>
            }
          />
          <StatusCard
            title="Backbone"
            value={<span className="font-medium text-gray-800">{model?.backbone ?? "-"}</span>}
          />
          <StatusCard
            title="n_features"
            value={<span className="font-medium text-gray-800">{model?.n_features ?? "-"}</span>}
          />
          <StatusCard
            title="Threshold"
            value={
              <span className="font-bold text-blue-600 text-lg">
                {model?.threshold ?? "-"}
              </span>
            }
          />
        </div>
      </section>

      {/* Today's Stats */}
      {todayStat && (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Today's Inspection Stats ({todayStat.inspection_date})
          </h2>
          <div className="grid grid-cols-3 gap-4">
            <BigStatCard
              label="Total Inspections"
              value={todayStat.total_count}
              color="text-gray-800"
            />
            <BigStatCard
              label="Defects Detected"
              value={todayStat.anomaly_count}
              color="text-red-600"
            />
            <BigStatCard
              label="Avg Anomaly Score"
              value={Number(todayStat.avg_score).toFixed(4)}
              color="text-blue-600"
            />
          </div>
        </section>
      )}
    </div>
  );
}

function StatusCard({ title, value }: { title: string; value: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
      <p className="text-xs text-gray-500 mb-2">{title}</p>
      <div>{value}</div>
    </div>
  );
}

function BigStatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-5 text-center">
      <p className="text-sm text-gray-500 mb-1">{label}</p>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-40" />
      <div className="grid grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-20 bg-gray-200 rounded-lg" />
        ))}
      </div>
    </div>
  );
}
