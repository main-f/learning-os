export type PlaybackState = {
  episode_id: string;
  position_seconds: number;
  playback_rate: number;
  version: number;
  updated_at: string | null;
};

export type PlaybackPosition = Pick<PlaybackState, 'position_seconds' | 'playback_rate'>;

export function audioTime(seconds: number): string {
  const value = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  return Math.floor(value / 60) + ':' + String(value % 60).padStart(2, '0');
}

export function resumePosition(position: number, duration: number): number {
  return Math.min(Math.max(0, position), Math.max(0, duration));
}

// One request at a time; coalesce timeupdate/pause/seek bursts, with a CAS version.
// A conflict/offline error pauses writes until the user chooses how to resolve it.
export class PlaybackWriter {
  version: number;
  halted = false;
  private pending: PlaybackPosition | null = null;
  private running: Promise<void> | null = null;
  constructor(
    version: number,
    private save: (value: PlaybackPosition & { version: number }) => Promise<PlaybackState>,
    private saved: (state: PlaybackState) => void,
    private failed: () => void,
  ) { this.version = version; }

  write(value: PlaybackPosition): Promise<void> {
    this.pending = value;
    return this.flush();
  }

  flush(): Promise<void> {
    if (this.running) return this.running;
    if (this.halted || !this.pending) return Promise.resolve();
    this.running = this.drain().finally(() => {
      this.running = null;
      if (this.pending && !this.halted) void this.flush();
    });
    return this.running;
  }

  adopt(version: number, discardPending = false): void {
    this.version = version;
    this.halted = false;
    if (discardPending) this.pending = null;
  }

  private async drain(): Promise<void> {
    while (this.pending && !this.halted) {
      const value = this.pending;
      this.pending = null;
      try {
        const state = await this.save({ ...value, version: this.version });
        this.version = state.version;
        this.saved(state);
      } catch {
        this.pending = this.pending || value;
        this.halted = true;
        this.failed();
      }
    }
  }
}
