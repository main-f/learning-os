export function formatDuration(milliseconds: number): string {
  const safe = Math.max(0, Math.round(milliseconds));
  const minutes = Math.floor(safe / 60_000);
  const seconds = Math.floor((safe % 60_000) / 1_000);
  const millis = safe % 1_000;
  return `${minutes.toString().padStart(2, '0')}:${seconds
    .toString()
    .padStart(2, '0')}.${millis.toString().padStart(3, '0')}`;
}

export function elapsedFromMonotonic(
  baseRawMs: number,
  baselinePerformanceNow: number,
  currentPerformanceNow: number,
): number {
  return Math.max(0, Math.round(baseRawMs + currentPerformanceNow - baselinePerformanceNow));
}

export function rankedElapsed(rawElapsedMs: number, multiplier: number): number {
  return Math.max(0, Math.round(rawElapsedMs * multiplier));
}
