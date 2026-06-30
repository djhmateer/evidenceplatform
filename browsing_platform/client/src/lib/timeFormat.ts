// Format a duration in seconds as m:ss (e.g. 75 → "1:15"). Non-finite/undefined → "0:00".
export function formatTime(seconds?: number): string {
    if (seconds === undefined || seconds === null || !isFinite(seconds)) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
}
