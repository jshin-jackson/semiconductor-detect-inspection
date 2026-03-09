/**
 * FastAPI 백엔드 API 클라이언트
 *
 * Vite dev server proxy를 통해 /api/* → http://localhost:8000/* 로 포워딩됩니다.
 * 프로덕션 빌드 시에는 VITE_API_BASE 환경변수로 URL을 변경할 수 있습니다.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

// ─────────────────────────────────────────────
// TypeScript 타입 정의
// ─────────────────────────────────────────────

export interface HealthResponse {
  status: "ok" | "degraded";
  model_loaded: boolean;
  minio_connected: boolean;
  starrocks_connected: boolean;
  version: string;
}

export interface ModelInfo {
  model_loaded: boolean;
  model_version: string | null;
  backbone: string;
  n_features: number;
  threshold: number;
}

export interface TrainRequest {
  data_root?: string | null;
  no_upload?: boolean;
}

export interface TrainResponse {
  status: "success" | "error";
  checkpoint_path: string | null;
  minio_uri: string | null;
  duration_seconds: number;
  message: string;
}

export interface PredictResponse {
  filename: string;
  anomaly_score: number;
  is_anomaly: boolean;
  threshold: number;
  heatmap_minio_path: string | null;
  result_json_path: string | null;
  inference_id: string;
  message: string;
}

export interface InspectionRecord {
  id: string;
  filename: string;
  timestamp: string;
  anomaly_score: number;
  is_anomaly: boolean;
  heatmap_minio_path: string | null;
  model_version: string | null;
}

export interface HistoryResponse {
  total: number;
  records: InspectionRecord[];
}

export interface StatRow {
  inspection_date: string;
  total_count: number;
  anomaly_count: number;
  avg_score: number;
}

export interface StatsResponse {
  rows: StatRow[];
}

// ─────────────────────────────────────────────
// 공통 fetch 헬퍼
// ─────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} 실패: ${res.status}`);
  return res.json() as Promise<T>;
}

// ─────────────────────────────────────────────
// API 함수
// ─────────────────────────────────────────────

/** GET /health — 서버·모델·MinIO·StarRocks 상태 확인 */
export const fetchHealth = () => get<HealthResponse>("/health");

/** GET /model — 로드된 모델 메타정보 */
export const fetchModel = () => get<ModelInfo>("/model");

/** POST /train — PaDiM 모델 학습 트리거 */
export async function postTrain(req: TrainRequest = {}): Promise<TrainResponse> {
  const res = await fetch(`${BASE}/train`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`POST /train 실패: ${res.status}`);
  return res.json() as Promise<TrainResponse>;
}

/**
 * POST /predict — 이미지 파일 업로드 후 이상 탐지 추론
 * @param file 검사할 이미지 파일 (PNG/JPEG)
 */
export async function postPredict(file: File): Promise<PredictResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/predict`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`POST /predict 실패: ${res.status}`);
  return res.json() as Promise<PredictResponse>;
}

/** GET /history?n=N — 최근 검사 이력 조회 */
export const fetchHistory = (n = 50) =>
  get<HistoryResponse>(`/history?n=${n}`);

/** GET /stats — 일별 이상 탐지 통계 */
export const fetchStats = () => get<StatsResponse>("/stats");
