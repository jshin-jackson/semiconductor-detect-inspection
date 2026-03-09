/** 상태 배지 컴포넌트 — ok/degraded/error/normal/anomaly 등 */
interface Props {
  status: "ok" | "degraded" | "error" | "normal" | "anomaly" | "connected" | "disconnected";
  label?: string;
}

const STYLES: Record<Props["status"], string> = {
  ok: "bg-green-100 text-green-800 border-green-200",
  connected: "bg-green-100 text-green-800 border-green-200",
  normal: "bg-blue-100 text-blue-800 border-blue-200",
  degraded: "bg-yellow-100 text-yellow-800 border-yellow-200",
  error: "bg-red-100 text-red-800 border-red-200",
  disconnected: "bg-red-100 text-red-800 border-red-200",
  anomaly: "bg-red-100 text-red-800 border-red-200",
};

const DOTS: Record<Props["status"], string> = {
  ok: "bg-green-500",
  connected: "bg-green-500",
  normal: "bg-blue-500",
  degraded: "bg-yellow-500",
  error: "bg-red-500",
  disconnected: "bg-red-500",
  anomaly: "bg-red-500",
};

export default function StatusBadge({ status, label }: Props) {
  const text = label ?? status.toUpperCase();
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${STYLES[status]}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${DOTS[status]}`} />
      {text}
    </span>
  );
}
