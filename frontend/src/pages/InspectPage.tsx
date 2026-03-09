import { useCallback, useState } from "react";
import { postPredict, type PredictResponse } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import ScoreBar from "../components/ScoreBar";

type State = "idle" | "loading" | "done" | "error";

export default function InspectPage() {
  const [state, setState] = useState<State>("idle");
  const [preview, setPreview] = useState<string | null>(null);
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  // 파일 선택 또는 드롭 시 처리
  const handleFile = useCallback(async (file: File) => {
    // 미리보기 URL 생성
    setPreview(URL.createObjectURL(file));
    setResult(null);
    setErrorMsg(null);
    setState("loading");

    try {
      const res = await postPredict(file);
      setResult(res);
      setState("done");
    } catch (e) {
      setErrorMsg(String(e));
      setState("error");
    }
  }, []);

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void handleFile(file);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  };

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };

  const onDragLeave = () => setDragging(false);

  const reset = () => {
    setState("idle");
    setPreview(null);
    setResult(null);
    setErrorMsg(null);
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-800">이미지 검사</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 왼쪽: 업로드 영역 */}
        <div className="space-y-4">
          {/* 드래그&드롭 영역 */}
          <label
            onDrop={onDrop}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            className={`flex flex-col items-center justify-center w-full h-52 border-2 border-dashed rounded-xl cursor-pointer transition-colors ${
              dragging
                ? "border-blue-500 bg-blue-50"
                : "border-gray-300 bg-white hover:border-blue-400 hover:bg-gray-50"
            }`}
          >
            <input
              type="file"
              accept="image/png,image/jpeg,image/bmp"
              className="hidden"
              onChange={onFileInput}
            />
            <svg
              className="w-10 h-10 text-gray-400 mb-2"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M4 16v1a2 2 0 002 2h12a2 2 0 002-2v-1M12 12V4m0 0L8 8m4-4l4 4"
              />
            </svg>
            <p className="text-sm text-gray-600">
              이미지를 드래그하거나 클릭해서 업로드
            </p>
            <p className="text-xs text-gray-400 mt-1">PNG / JPEG / BMP</p>
          </label>

          {/* 미리보기 */}
          {preview && (
            <div className="relative bg-white border border-gray-200 rounded-lg overflow-hidden">
              <img src={preview} alt="미리보기" className="w-full object-contain max-h-64" />
              <button
                onClick={reset}
                className="absolute top-2 right-2 bg-white/80 hover:bg-white rounded-full p-1 shadow text-gray-500 hover:text-gray-700"
                title="초기화"
              >
                <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                  <path
                    fillRule="evenodd"
                    d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                    clipRule="evenodd"
                  />
                </svg>
              </button>
            </div>
          )}

          {/* 추론 중 스피너 */}
          {state === "loading" && (
            <div className="flex items-center gap-2 text-blue-600 text-sm">
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
                <path fill="currentColor" className="opacity-75" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              PaDiM 추론 중...
            </div>
          )}

          {/* 오류 메시지 */}
          {state === "error" && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3">
              추론 실패: {errorMsg}
            </div>
          )}
        </div>

        {/* 오른쪽: 결과 패널 */}
        <div>
          {state === "done" && result ? (
            <ResultPanel result={result} />
          ) : (
            <div className="flex items-center justify-center h-52 bg-white border-2 border-dashed border-gray-200 rounded-xl text-gray-400 text-sm">
              왼쪽에서 이미지를 업로드하면 결과가 표시됩니다
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ResultPanel({ result }: { result: PredictResponse }) {
  const isAnomaly = result.is_anomaly;

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      {/* 판정 결과 헤더 */}
      <div
        className={`px-5 py-4 flex items-center justify-between ${
          isAnomaly ? "bg-red-50" : "bg-green-50"
        }`}
      >
        <div>
          <p className="text-xs text-gray-500 mb-1">파일명</p>
          <p className="font-medium text-gray-800 text-sm truncate max-w-xs">
            {result.filename}
          </p>
        </div>
        <StatusBadge
          status={isAnomaly ? "anomaly" : "normal"}
          label={isAnomaly ? "결함 검출" : "정상"}
        />
      </div>

      <div className="p-5 space-y-5">
        {/* 점수 게이지 */}
        <ScoreBar score={result.anomaly_score} threshold={result.threshold} />

        {/* 수치 정보 */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <InfoRow label="이상 점수" value={result.anomaly_score.toFixed(6)} />
          <InfoRow label="임계값" value={String(result.threshold)} />
          <InfoRow label="추론 ID" value={result.inference_id.slice(0, 8) + "..."} mono />
          <InfoRow
            label="히트맵"
            value={result.heatmap_minio_path ? "저장됨" : "없음"}
          />
        </div>

        {/* 히트맵 이미지 — MinIO에 업로드된 경우 로컬 결과 폴더에서 표시 */}
        {result.result_json_path && (
          <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 font-mono break-all">
            {result.result_json_path}
          </div>
        )}
      </div>
    </div>
  );
}

function InfoRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="bg-gray-50 rounded p-2">
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`text-gray-800 font-medium mt-0.5 ${mono ? "font-mono text-xs" : "text-sm"}`}>
        {value}
      </p>
    </div>
  );
}
