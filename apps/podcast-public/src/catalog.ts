export type PublicEpisode = {
  id: string;
  title: string;
  description: string;
  audio: string;
  sha256: string;
  duration_seconds: number;
  published_at: string;
};
export type PublicCatalog = {
  schema_version: 1;
  generated_at: string;
  episodes: PublicEpisode[];
};
export type LocalProgress = {
  position_seconds: number;
  playback_rate: number;
  version: number;
  updated_at: string | null;
};
export interface ProgressStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const catalogKeys = ['schema_version', 'generated_at', 'episodes'];
const episodeKeys = ['id', 'title', 'description', 'audio', 'sha256', 'duration_seconds', 'published_at'];
const validDate = (value: unknown): value is string =>
  typeof value === 'string' && /^\d{4}-\d\d-\d\dT/.test(value) && Number.isFinite(Date.parse(value));
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export function parseCatalog(value: unknown): PublicCatalog {
  if (!isRecord(value) || value.schema_version !== 1 || !validDate(value.generated_at) ||
    Object.keys(value).some((key) => !catalogKeys.includes(key)) ||
    !Array.isArray(value.episodes) || value.episodes.length > 14) throw new Error('节目单格式无效');
  const ids = new Set<string>();
  const episodes = value.episodes.map((entry): PublicEpisode => {
    if (!isRecord(entry) || Object.keys(entry).some((key) => !episodeKeys.includes(key)) ||
      typeof entry.id !== 'string' || !/^[a-z0-9][a-z0-9-]{0,79}$/.test(entry.id) ||
      ids.has(entry.id) || typeof entry.title !== 'string' || !entry.title.trim() ||
      entry.title.length > 200 || typeof entry.description !== 'string' || entry.description.length > 1000 ||
      typeof entry.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(entry.sha256) ||
      typeof entry.audio !== 'string' || !/^media\/[a-f0-9]{64}\.(m4a|mp3|wav)$/.test(entry.audio) ||
      !entry.audio.includes(entry.sha256) || typeof entry.duration_seconds !== 'number' ||
      !Number.isFinite(entry.duration_seconds) || entry.duration_seconds <= 0 ||
      entry.duration_seconds > 14_400 || !validDate(entry.published_at)) throw new Error('节目单包含无效单集');
    ids.add(entry.id);
    return {
      id: entry.id, title: entry.title, description: entry.description, audio: entry.audio,
      sha256: entry.sha256, duration_seconds: entry.duration_seconds, published_at: entry.published_at,
    };
  });
  return { schema_version: 1, generated_at: value.generated_at, episodes };
}

const EMPTY: LocalProgress = { position_seconds: 0, playback_rate: 1, version: 0, updated_at: null };

export class LocalPodcastProgress {
  private memory = new Map<string, string>();
  private storage: ProgressStorage | null;
  persistent: boolean;
  constructor(storage: ProgressStorage | null) {
    this.storage = storage;
    this.persistent = storage !== null;
  }
  private key(episode: PublicEpisode) { return 'rae.podcasts.v1.' + episode.id + '.' + episode.sha256; }
  private get(key: string): string | null {
    try { return this.storage ? this.storage.getItem(key) : this.memory.get(key) || null; }
    catch { this.persistent = false; this.storage = null; return this.memory.get(key) || null; }
  }
  private set(key: string, value: string) {
    this.memory.set(key, value);
    try { this.storage?.setItem(key, value); }
    catch { this.persistent = false; this.storage = null; }
  }
  read(episode: PublicEpisode): LocalProgress {
    try {
      const value: unknown = JSON.parse(this.get(this.key(episode)) || 'null');
      if (!isRecord(value) || typeof value.position_seconds !== 'number' ||
        !Number.isFinite(value.position_seconds) || value.position_seconds < 0 ||
        typeof value.playback_rate !== 'number' || ![0.75, 1, 1.25, 1.5, 1.75, 2].includes(value.playback_rate) ||
        typeof value.version !== 'number' || !Number.isInteger(value.version) || value.version < 0 ||
        !validDate(value.updated_at)) return { ...EMPTY };
      return {
        position_seconds: Math.min(value.position_seconds, episode.duration_seconds),
        playback_rate: value.playback_rate, version: value.version, updated_at: value.updated_at,
      };
    } catch { return { ...EMPTY }; }
  }
  save(episode: PublicEpisode, position: number, rate: number, expectedVersion: number): LocalProgress {
    const previous = this.read(episode);
    if (previous.version !== expectedVersion) throw new Error('progress_conflict');
    if (!Number.isFinite(position) || position < 0 || ![0.75, 1, 1.25, 1.5, 1.75, 2].includes(rate)) {
      throw new Error('invalid_position');
    }
    const next: LocalProgress = {
      position_seconds: Math.min(position, episode.duration_seconds),
      playback_rate: rate, version: previous.version + 1, updated_at: new Date().toISOString(),
    };
    this.set(this.key(episode), JSON.stringify(next));
    this.set('rae.podcasts.last-episode.v1', episode.id);
    return next;
  }
  lastEpisode(): string | null { return this.get('rae.podcasts.last-episode.v1'); }
}

export function browserProgress(): LocalPodcastProgress {
  try { return new LocalPodcastProgress(window.localStorage); }
  catch { return new LocalPodcastProgress(null); }
}

export function helsinkiDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Europe/Helsinki', month: 'long', day: 'numeric',
  }).format(new Date(value));
}
