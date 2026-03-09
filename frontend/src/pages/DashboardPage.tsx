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
      // 오늘 날짜 통계 (첫 번째 row = 최신)
      setTodayStat(s.rows[0] ?? null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // 30초마다 자동 갱신
    const id = setInterval(() => void load(), 30_000);
    return () => clearInterval(id);
  }, []);

  if (loading) return <Skeleton />;
  if (error)
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-red-700">
        서버 연결 실패: {error}
      </div>
    );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">대시보드</h1>
        <button
          onClick={() => void load()}
          className="text-sm text-blue-600 hover:underline"
        >
          새로고침
        </button>
      </div>

      {/* 서버 상태 카드 */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          서버 상태
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatusCard
            title="API 서버"
            value={
              <StatusBadge
                status={health?.status === "ok" ? "ok" : "degraded"}
                label={health?.status ?? "-"}
              />
            }
          />
          <StatusCard
            title="모델"
            value={
              <StatusBadge
                status={health?.model_loaded ? "ok" : "error"}
                label={health?.model_loaded ? "로드됨" : "미로드"}
              />
            }
          />
          <StatusCard
            title="MinIO"
            value={
              <StatusBadge
                status={health?.minio_connected ? "connected" : "disconnected"}
                label={health?.minio_connected ? "연결됨" : "오류"}
              />
            }
          />
          <StatusCard
            title="StarRocks"
            value={
              <StatusBadge
                status={health?.starrocks_connected ? "connected" : "disconnected"}
                label={health?.starrocks_connected ? "연결됨" : "오류"}
              />
            }
          />
        </div>
      </section>

      {/* 모델 정보 카드 */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          모델 정보
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatusCard
            title="버전"
            value={
              <span className="text-sm font-mono text-gray-700 truncate" title={model?.model_version ?? "-"}>
                {model?.model_version ?? "-"}
              </span>
            }
          />
          <StatusCard
            title="백본"
            value={<span className="font-medium text-gray-800">{model?.backbone ?? "-"}</span>}
          />
          <StatusCard
            title="n_features"
            value={<span className="font-medium text-gray-800">{model?.n_features ?? "-"}</span>}
          />
          <StatusCard
            title="임계값"
            value={
              <span className="font-bold text-blue-600 text-lg">
                {model?.threshold ?? "-"}
              </span>
            }
          />
        </div>
      </section>

      {/* 오늘 통계 */}
      {todayStat && (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            오늘 검사 통계 ({todayStat.inspection_date})
          </h2>
          <div className="grid grid-cols-3 gap-4">
            <BigStatCard
              label="총 검사 건수"
              value={todayStat.total_count}
              color="text-gray-800"
            />
            <BigStatCard
              label="결함 건수"
              value={todayStat.anomaly_count}
              color="text-red-600"
            />
            <BigStatCard
              label="평균 이상 점수"
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
