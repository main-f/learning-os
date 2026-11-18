import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { audioTime, resumePosition } from '../../../packages/podcast-playback';
import {
  browserProgress, helsinkiDate, parseCatalog,
  type LocalProgress, type PublicCatalog, type PublicEpisode,
} from './catalog';
import './style.css';

const base = new URL(import.meta.env.BASE_URL, window.location.origin);
const assetUrl = (path: string) => new URL(path, base).href;

function App() {
  const [catalog, setCatalog] = useState<PublicCatalog | null>(null);
  const [selected, setSelected] = useState<PublicEpisode | null>(null);
  const [position, setPosition] = useState(0);
  const [rate, setRate] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saveMessage, setSaveMessage] = useState('进度保存在此浏览器');
  const [conflict, setConflict] = useState(false);
  const [savedPositions, setSavedPositions] = useState<Record<string, LocalProgress>>({});
  const audio = useRef<HTMLAudioElement>(null);
  const current = useRef<PublicEpisode | null>(null);
  const catalogRef = useRef<PublicCatalog | null>(null);
  const loadingMedia = useRef(false);
  const store = useRef(browserProgress());
  const version = useRef(0);
  const pendingRestore = useRef<number | null>(null);
  const restore = useRef<LocalProgress | null>(null);
  const writesPaused = useRef(false);
  const lastSave = useRef(0);
  const initialized = useRef(false);

  function savePosition() {
    const player = audio.current;
    const episode = current.current;
    if (!player || !episode || player.readyState < 1 || writesPaused.current || loadingMedia.current) return;
    try {
      const next = store.current.save(episode, player.currentTime, player.playbackRate, version.current);
      version.current = next.version;
      setSavedPositions((old) => ({ ...old, [episode.id]: next }));
      lastSave.current = Date.now();
      setSaveMessage(store.current.persistent ? '进度已保存到此浏览器' : '浏览器限制了保存；本次播放可继续');
    } catch {
      writesPaused.current = true;
      setConflict(true);
      setSaveMessage('另一个标签页已更新进度，请选择要保留的位置');
    }
  }

  function choose(episode: PublicEpisode, play = true) {
    const player = audio.current;
    if (!player) return;
    if (current.current?.id === episode.id) {
      if (play) void player.play().catch(() => setError('请点击播放器里的播放按钮开始收听'));
      return;
    }
    savePosition();
    player.pause();
    loadingMedia.current = true;
    const previous = store.current.read(episode);
    current.current = episode;
    restore.current = previous;
    version.current = previous.version;
    writesPaused.current = false;
    pendingRestore.current = previous.position_seconds;
    setSelected(episode); setPosition(previous.position_seconds); setRate(previous.playback_rate);
    setConflict(false); setError('');
    setSaveMessage(store.current.persistent ? '进度保存在此浏览器' : '浏览器限制了保存；本次播放可继续');
    if (window.location.hash !== '#/podcasts/' + episode.id) window.location.hash = '#/podcasts/' + episode.id;
    player.src = assetUrl(episode.audio);
    player.load();
    if (play) void player.play().catch(() => setError('请点击播放器里的播放按钮开始收听'));
  }

  async function refresh() {
    setLoading(true);
    try {
      const response = await fetch(assetUrl('episodes.json') + '?refresh=' + Date.now(), { cache: 'no-store' });
      if (!response.ok) throw new Error('暂时无法更新节目单，请稍后刷新');
      const next = parseCatalog(await response.json());
      catalogRef.current = next;
      setCatalog(next);
      const positions: Record<string, LocalProgress> = {};
      next.episodes.forEach((episode) => { positions[episode.id] = store.current.read(episode); });
      setSavedPositions(positions);
      setError('');
      if (!initialized.current) {
        initialized.current = true;
        const requested = window.location.hash.split('/')[2];
        const remembered = store.current.lastEpisode();
        const episode = next.episodes.find((item) => item.id === (requested || remembered));
        if (episode) choose(episode, false);
        else if (requested) setError('这集暂不在当前节目单中，请选择下方单集');
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : '节目单载入失败'); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    void refresh();
    const onHash = () => {
      const id = window.location.hash.split('/')[2];
      const target = catalogRef.current?.episodes.find((item) => item.id === id);
      if (target && target.id !== current.current?.id) choose(target, false);
    };
    const persist = () => savePosition();
    const visible = () => { if (document.visibilityState === 'hidden') persist(); };
    const interval = setInterval(() => { if (document.visibilityState === 'visible') void refresh(); }, 120_000);
    window.addEventListener('hashchange', onHash);
    window.addEventListener('pagehide', persist);
    document.addEventListener('visibilitychange', visible);
    return () => {
      clearInterval(interval);
      window.removeEventListener('hashchange', onHash);
      window.removeEventListener('pagehide', persist);
      document.removeEventListener('visibilitychange', visible);
    };
  }, []);

  function seek(delta: number) {
    const player = audio.current;
    if (player && Number.isFinite(player.duration)) {
      player.currentTime = resumePosition(player.currentTime + delta, player.duration);
    }
  }
  function applyRate(value: number) {
    if (audio.current) {
      audio.current.defaultPlaybackRate = value;
      audio.current.playbackRate = value;
      setRate(value);
    }
  }
  function resolveConflict(keepCurrent: boolean) {
    const episode = current.current;
    const player = audio.current;
    if (!episode || !player) return;
    const previous = store.current.read(episode);
    version.current = previous.version;
    writesPaused.current = false;
    setConflict(false);
    if (!keepCurrent) {
      pendingRestore.current = previous.position_seconds;
      player.currentTime = previous.position_seconds;
      applyRate(previous.playback_rate);
      setPosition(previous.position_seconds);
    }
    savePosition();
  }

  useEffect(() => {
    if (!selected || !('mediaSession' in navigator) || typeof MediaMetadata === 'undefined') return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: selected.title, artist: 'Learning OS', album: 'Cyber Security 课程播客',
      artwork: [{ src: assetUrl('icon.svg'), sizes: '96x96', type: 'image/svg+xml' }],
    });
    const handlers: Array<[MediaSessionAction, MediaSessionActionHandler]> = [
      ['play', () => { void audio.current?.play().catch(() => setError('请点击播放继续收听')); }],
      ['pause', () => audio.current?.pause()],
      ['seekbackward', (event) => seek(-(event.seekOffset || 15))],
      ['seekforward', (event) => seek(event.seekOffset || 15)],
      ['seekto', (event) => { if (audio.current && event.seekTime !== undefined) audio.current.currentTime = event.seekTime; }],
    ];
    for (const [action, handler] of handlers) {
      try { navigator.mediaSession.setActionHandler(action, handler); } catch { /* Device capability. */ }
    }
    return () => {
      for (const [action] of handlers) {
        try { navigator.mediaSession.setActionHandler(action, null); } catch { /* Optional. */ }
      }
    };
  }, [selected?.id]);

  return <>
    <header className="site-header">
      <a className="brand" href="#/podcasts"><span aria-hidden="true">◈</span> RAE LEARNING OS</a>
      <span className="edition">课程播客</span>
    </header>
    <main className={selected ? 'has-player' : ''}>
      <section className="hero">
        <div><p className="eyebrow">CYBER SECURITY · LEARNING RADIO</p>
          <h1>把知识带在路上</h1>
          <p className="intro">中文讲清逻辑，保留 English terms。<br />走路、通勤、做家务时，接着上次的位置听。</p></div>
        <div className="radio-mark" aria-hidden="true"><span>♫</span><small>LISTEN & RECALL</small></div>
      </section>
      <div className="library-heading">
        <div><h2>课程单集 <span>{catalog?.episodes.length || 0}</span></h2>
          {catalog && <p>{Math.round(catalog.episodes.reduce((total, item) => total + item.duration_seconds, 0) / 60)} 分钟内容 · 节目单更新于 {helsinkiDate(catalog.generated_at)}</p>}</div>
        <button className="quiet" onClick={() => void refresh()} disabled={loading}>{loading ? '正在更新…' : '刷新节目单'}</button>
      </div>
      {error && <p className="notice" role="alert">{error}</p>}
      {!catalog && loading && <p role="status">正在载入节目单…</p>}
      {catalog && !catalog.episodes.length && <p className="notice">新单集正在准备中，稍后刷新即可查看。</p>}
      <section className="episodes" aria-label="课程播客单集">
        {catalog?.episodes.map((episode, index) => {
          const progress = savedPositions[episode.id];
          const resume = progress?.position_seconds || 0;
          const currentEpisode = episode.id === selected?.id;
          return <article className={'episode ' + (currentEpisode ? 'selected' : '')} key={episode.id}>
            <div className={'cover cover-' + (index % 3)} aria-hidden="true">
              <span>♫</span><small>PACK {String(index + 1).padStart(2, '0')}</small>
            </div>
            <div className="episode-copy">
              <div className="episode-meta"><span>{audioTime(episode.duration_seconds)}</span><span>中文 · English terms</span></div>
              <h3>{episode.title}</h3><p>{episode.description}</p>
              <div className="episode-actions">
                <button className="primary" onClick={() => choose(episode)}>
                  {currentEpisode && playing ? '正在播放' : resume > 0 ? '从 ' + audioTime(resume) + ' 续播' : '开始收听'}
                  <span aria-hidden="true">↗</span>
                </button>
                <a href={'#/podcasts/' + episode.id}>单集链接</a>
              </div>
              <progress max={episode.duration_seconds} value={resume} aria-label={episode.title + ' 收听进度'} />
            </div>
          </article>;
        })}
      </section>
      <div className="listening-note"><span aria-hidden="true">◌</span>
        <p>点一次播放，再把屏幕收起来。<br /><small>进度只保存在当前浏览器。收听不计入测验成绩。</small></p></div>
    </main>
    <footer><span>RAE LEARNING OS</span><span>Learn at your own pace.</span></footer>
    <section className="player" aria-label="播客播放器" hidden={!selected}>
      <div className="now-playing"><div className="mini-cover" aria-hidden="true">♫</div>
        <div><small>{playing ? '正在收听' : '随时接着听'}</small><strong>{selected?.title}</strong>
          <span>{audioTime(position)} / {audioTime(selected?.duration_seconds || 0)} · {saveMessage}</span></div>
      </div>
      <audio ref={audio} controls preload="metadata"
        onLoadedMetadata={() => {
          const player = audio.current;
          if (!player || !restore.current) return;
          const point = resumePosition(restore.current.position_seconds, player.duration);
          pendingRestore.current = point > 0 ? point : null;
          player.currentTime = point;
          applyRate(restore.current.playback_rate); setPosition(point);
          loadingMedia.current = false;
        }}
        onPlay={() => {
          setPlaying(true);
          if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'playing';
        }}
        onPause={() => {
          setPlaying(false); savePosition();
          if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'paused';
        }}
        onTimeUpdate={() => {
          const player = audio.current;
          if (!player || !current.current) return;
          setPosition(player.currentTime);
          if (!player.paused && Date.now() - lastSave.current >= 5000) savePosition();
          if ('mediaSession' in navigator && Number.isFinite(player.duration)) {
            try { navigator.mediaSession.setPositionState({
              duration: player.duration, playbackRate: player.playbackRate,
              position: Math.min(player.currentTime, player.duration),
            }); } catch { /* Optional. */ }
          }
        }}
        onSeeked={() => {
          if (pendingRestore.current !== null && audio.current &&
            Math.abs(audio.current.currentTime - pendingRestore.current) < 1) pendingRestore.current = null;
          else { pendingRestore.current = null; savePosition(); }
        }}
        onRateChange={() => { setRate(audio.current?.playbackRate || 1); savePosition(); }}
        onEnded={() => { setPlaying(false); savePosition(); }}
        onError={() => setError('音频暂时无法载入。可以刷新节目单后重试，已保存的进度会保留。')} />
      <div className="player-actions">
        <button className="quiet" onClick={() => seek(-15)} aria-label="后退 15 秒">↶ 15 秒</button>
        <button className="quiet" onClick={() => seek(15)} aria-label="前进 15 秒">15 秒 ↷</button>
        <label>倍速<select aria-label="播放倍速" value={rate} onChange={(event) => applyRate(Number(event.target.value))}>
          {[0.75, 1, 1.25, 1.5, 1.75, 2].map((value) => <option key={value} value={value}>{value}×</option>)}
        </select></label>
      </div>
      {conflict && <div className="progress-conflict" role="alert"><p>另一个标签页更新了进度。</p>
        <button className="quiet" onClick={() => resolveConflict(false)}>使用已保存位置</button>
        <button className="quiet" onClick={() => resolveConflict(true)}>保留当前位置</button></div>}
    </section>
  </>;
}

createRoot(document.getElementById('root')!).render(<App />);
