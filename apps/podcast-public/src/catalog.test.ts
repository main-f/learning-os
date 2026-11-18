import { describe, expect, it } from 'vitest';
import { LocalPodcastProgress, parseCatalog, type PublicCatalog, type PublicEpisode } from './catalog';

const episode: PublicEpisode = {
  id: 'synthetic-episode-1', title: 'Synthetic public episode', description: 'Synthetic audio',
  audio: 'media/' + 'a'.repeat(64) + '.m4a', sha256: 'a'.repeat(64), duration_seconds: 120,
  published_at: '2026-11-18T00:00:00Z',
};
const catalog: PublicCatalog = { schema_version: 1, generated_at: '2026-11-18T00:00:00Z', episodes: [episode] };
class Memory {
  values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) || null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

describe('public catalog boundary', () => {
  it('accepts a public content-addressed catalog without private fields', () => {
    expect(parseCatalog(catalog)).toEqual(catalog);
  });
  it.each(['../private.sqlite', 'https://example.com/token', 'media/not-a-hash.m4a', '/api/v1/podcasts/secret'])(
    'rejects unsafe media location %s', (audio) => {
      expect(() => parseCatalog({ ...catalog, episodes: [{ ...episode, audio }] })).toThrow();
    },
  );
  it('rejects duplicate IDs, private extras and corrupted metadata', () => {
    expect(() => parseCatalog({ ...catalog, episodes: [episode, episode] })).toThrow();
    expect(() => parseCatalog({ ...catalog, questions: ['private'] })).toThrow();
    expect(() => parseCatalog({ ...catalog, episodes: [{ ...episode, source_path: '/private/local' }] })).toThrow();
    expect(() => parseCatalog({ ...catalog, episodes: [{ ...episode, duration_seconds: Infinity }] })).toThrow();
    expect(() => parseCatalog({ ...catalog, episodes: [{ ...episode, published_at: 'invalid' }] })).toThrow();
  });
});

describe('browser-only playback progress', () => {
  it('persists speed and intentional rewinds across a new player instance', () => {
    const memory = new Memory();
    const first = new LocalPodcastProgress(memory);
    first.save(episode, 90, 1.5, 0);
    first.save(episode, 20, 1.25, 1);
    const restored = new LocalPodcastProgress(memory);
    expect(restored.read(episode)).toMatchObject({ position_seconds: 20, playback_rate: 1.25, version: 2 });
    expect(restored.lastEpisode()).toBe(episode.id);
  });
  it('detects a stale tab update without overwriting the saved position', () => {
    const memory = new Memory();
    const first = new LocalPodcastProgress(memory);
    const second = new LocalPodcastProgress(memory);
    first.save(episode, 70, 1, 0);
    expect(() => second.save(episode, 2, 1, 0)).toThrow('progress_conflict');
    expect(first.read(episode).position_seconds).toBe(70);
  });
  it('isolates changed audio and recovers from malformed saved data', () => {
    const memory = new Memory();
    const progress = new LocalPodcastProgress(memory);
    progress.save(episode, 200, 1, 0);
    expect(progress.read(episode).position_seconds).toBe(120);
    expect(progress.read({ ...episode, sha256: 'b'.repeat(64) }).position_seconds).toBe(0);
    for (const key of memory.values.keys()) memory.setItem(key, 'broken json');
    expect(progress.read(episode).position_seconds).toBe(0);
  });
  it('continues playback using memory when storage is unavailable', () => {
    const progress = new LocalPodcastProgress({
      getItem: () => { throw new Error('disabled'); },
      setItem: () => { throw new Error('disabled'); },
    });
    progress.save(episode, 20, 1, 0);
    expect(progress.persistent).toBe(false);
    expect(progress.read(episode).position_seconds).toBe(20);
  });
});
