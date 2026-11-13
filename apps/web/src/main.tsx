import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { optionFeedbackClass } from './gameFeel';
import { elapsedFromMonotonic, formatDuration, rankedElapsed } from './timing';
import './style.css';

type AssistanceMode = 'none' | 'zh_translation';

type GameOption = {
  option_token: string;
  text: string;
  text_zh?: string;
};

type GameQuestion = {
  question_id: string;
  question_type: 'single_choice' | 'multiple_choice';
  prompt: string;
  prompt_zh?: string;
  translation_version?: string;
  options: GameOption[];
};

type StartedGame = {
  session_id: string;
  question_set_id: string;
  question_set_version: string;
  ruleset_version: string;
  started_at: string;
  assistance_mode: AssistanceMode;
  time_multiplier: number;
  question_count: number;
  question_order: string[];
  questions: GameQuestion[];
};

type AttemptResult = {
  attempt_id: string;
  event_id: string;
  question_id: string;
  correct: boolean;
  correct_option_tokens: string[];
  source_ref: string;
  explanation: string;
  explanation_status: 'pending_human_review' | 'verified';
  assistance_mode: AssistanceMode;
  evidence_mode: 'unassisted' | 'assisted';
  streak: number;
  xp_earned: number;
  total_xp: number;
  correct_count: number;
  attempted_count: number;
  remaining_count: number;
  saved: boolean;
};

type CompletedGame = {
  session_id: string;
  question_set_id: string;
  question_set_version: string;
  ruleset_version: string;
  completed_at: string;
  duration_ms: number;
  raw_duration_ms: number;
  assistance_mode: AssistanceMode;
  time_multiplier: number;
  ranked_duration_ms: number;
  question_count: number;
  correct_count: number;
  max_streak: number;
  xp_earned: number;
  is_personal_best: boolean;
  saved: boolean;
};

type RestoredGame = StartedGame & {
  status: 'active' | 'completed';
  raw_duration_ms: number;
  ranked_duration_ms: number;
  correct_count: number;
  max_streak: number;
  xp_earned: number;
  attempts: AttemptResult[];
  completed_at?: string;
  duration_ms?: number;
  is_personal_best?: boolean;
  saved?: boolean;
};

type GameConfig = {
  question_set_id: string;
  question_set_version: string;
  ruleset_version: string;
  question_count: number;
  assistance: {
    zh_translation_available: boolean;
    zh_translation_status: 'human_verified' | 'pending_review';
    time_multiplier: number;
  };
};

type DashboardRecord = Omit<CompletedGame, 'is_personal_best' | 'saved' | 'duration_ms'> & {
  duration_ms: number | null;
};

type DashboardData = {
  timezone: 'Europe/Helsinki';
  import_stats: {
    topic_count: number;
    candidate_question_count: number;
    source_verified_count: number;
  };
  recent_game: DashboardRecord | null;
  personal_best: DashboardRecord | null;
  last_imported_at: string | null;
  last_updated_at: string | null;
  official_grade: null;
  official_grade_status: 'pending_confirmation';
  mastery: 'unknown';
  mastery_label: string;
  xp_is_official_grade: false;
};

type PendingAttempt = {
  eventId: string;
  questionId: string;
  chosenOptionTokens: string[];
  responseMs: number;
};

const ACTIVE_SESSION_KEY = 'rae-learning-os.active-game-session';
const configuredApi = (import.meta.env.VITE_PRIVATE_API_URL as string | undefined)?.replace(/\/$/, '');

function endpoint(path: string): string | null {
  if (import.meta.env.DEV) return path;
  return configuredApi ? `${configuredApi}${path}` : null;
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const url = endpoint(path);
  if (!url) throw new Error('此构建未配置私有 Study Core API');
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const body = await response.json() as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // Keep the status-code fallback when an upstream response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

function postJson<T>(path: string, body: object): Promise<T> {
  return apiRequest<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function formatHelsinki(value: string | null | undefined): string {
  if (!value) return '尚无记录';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Europe/Helsinki',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function assistanceLabel(mode: AssistanceMode): string {
  return mode === 'zh_translation' ? '中文辅助 ×1.3' : '无辅助 ×1.0';
}

function useHash(): string {
  const [hash, setHash] = useState(window.location.hash || '#/dashboard');
  useEffect(() => {
    const update = () => setHash(window.location.hash || '#/dashboard');
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  return hash;
}

function useGameClock(
  active: boolean,
  baseRawMs: number,
  multiplier: number,
  sessionId: string | null,
) {
  const [rawMs, setRawMs] = useState(baseRawMs);
  useEffect(() => {
    setRawMs(baseRawMs);
    if (!active || !sessionId) return undefined;
    const baseline = performance.now();
    let frame = 0;
    const tick = () => {
      setRawMs(elapsedFromMonotonic(baseRawMs, baseline, performance.now()));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active, baseRawMs, sessionId]);
  return { rawMs, rankedMs: rankedElapsed(rawMs, multiplier) };
}

function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  function loadDashboard() {
    setLoading(true);
    setError('');
    apiRequest<DashboardData>('/api/v1/dashboard')
      .then(setData)
      .catch((reason: unknown) => setError(
        reason instanceof Error ? reason.message : '无法读取 Dashboard',
      ))
      .finally(() => setLoading(false));
  }

  useEffect(loadDashboard, []);
  const stats = data?.import_stats;

  return <main>
    <section className="hero">
      <div>
        <small>MISSION CONTROL · PRIVATE LOCAL DATA</small>
        <h1>真实战绩，清晰进步</h1>
        <p>课程原题留在私有 SQLite；XP 只代表游戏表现，不是官方成绩。</p>
      </div>
      <a className="primary large" href="#/play">开始 10 题 Speed Run</a>
    </section>

    {loading && <div className="notice neutral">正在连接本地 Study Core…</div>}
    {error && <div className="notice danger">
      <span>未读取到私人数据：{error}</span><button onClick={loadDashboard}>重试</button>
    </div>}
    {data && <>
      <div className="cards metrics">
        <article className="tile"><span>已导入主题</span><strong>{stats?.topic_count ?? 0}</strong><small>根目录 Markdown</small></article>
        <article className="tile"><span>候选 MCQ</span><strong>{stats?.candidate_question_count ?? 0}</strong><small>未核验题不会入局</small></article>
        <article className="tile verified"><span>source_verified</span><strong>{stats?.source_verified_count ?? 0}</strong><small>本地原始页面机械对账</small></article>
        <article className="tile"><span>Official grade</span><strong>待确认</strong><small>游戏 XP 不会修改</small></article>
        <article className="tile"><span>Mastery</span><strong>{data.mastery_label}</strong><small>当前状态：{data.mastery}</small></article>
        <article className="tile"><span>最近同步 / 更新</span><strong className="date-value">{formatHelsinki(data.last_updated_at)}</strong><small>Europe/Helsinki</small></article>
      </div>

      <div className="result-grid">
        <RecordCard title="最近一局" record={data.recent_game} empty="还没有真实游戏记录。第一局会在服务端逐题保存。" />
        <RecordCard title="Personal Best" record={data.personal_best} empty="完成第一局后建立个人最佳。先看正确数，再看排名计时。" />
      </div>
      <p className="sync-note">最近导入：{formatHelsinki(data.last_imported_at)}。数据库保存 UTC；此处按 Europe/Helsinki 展示。</p>
    </>}
  </main>;
}

function RecordCard({ title, record, empty }: {
  title: string;
  record: DashboardRecord | null;
  empty: string;
}) {
  return <article className="panel">
    <div className="panel-title"><span>{title}</span>{record && <em>{assistanceLabel(record.assistance_mode)}</em>}</div>
    {record ? <>
      <strong className="score">{record.correct_count} / {record.question_count}</strong>
      <dl className="stat-list">
        <div><dt>实际用时</dt><dd>{formatDuration(record.raw_duration_ms)}</dd></div>
        <div><dt>排名计时</dt><dd>{formatDuration(record.ranked_duration_ms)}</dd></div>
        <div><dt>规则</dt><dd>v{record.ruleset_version}</dd></div>
      </dl>
      <small>{formatHelsinki(record.completed_at)}</small>
    </> : <p className="muted">{empty}</p>}
  </article>;
}

function Arena() {
  const [phase, setPhase] = useState<'booting' | 'idle' | 'playing' | 'finished'>('booting');
  const [config, setConfig] = useState<GameConfig | null>(null);
  const [assistanceMode, setAssistanceMode] = useState<AssistanceMode>('none');
  const [game, setGame] = useState<StartedGame | null>(null);
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<AttemptResult | null>(null);
  const [result, setResult] = useState<CompletedGame | null>(null);
  const [streak, setStreak] = useState(0);
  const [xp, setXp] = useState(0);
  const [baseRawMs, setBaseRawMs] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const questionStartedAt = useRef(0);
  const pendingAttempt = useRef<PendingAttempt | null>(null);
  const completionEventId = useRef<string | null>(null);
  const clock = useGameClock(
    phase === 'playing',
    baseRawMs,
    game?.time_multiplier ?? 1,
    game?.session_id ?? null,
  );

  useEffect(() => {
    let active = true;
    async function boot() {
      try {
        const loadedConfig = await apiRequest<GameConfig>('/api/v1/game-config');
        if (!active) return;
        setConfig(loadedConfig);
        const sessionId = localStorage.getItem(ACTIVE_SESSION_KEY);
        if (!sessionId) {
          setPhase('idle');
          return;
        }
        try {
          const restored = await apiRequest<RestoredGame>(
            `/api/v1/game-sessions/${sessionId}/result`,
          );
          if (!active) return;
          if (restored.status === 'completed') {
            localStorage.removeItem(ACTIVE_SESSION_KEY);
            setResult(restored as unknown as CompletedGame);
            setPhase('finished');
            return;
          }
          const restoredGame: StartedGame = restored;
          setGame(restoredGame);
          setAssistanceMode(restored.assistance_mode);
          setStreak(restored.max_streak);
          setXp(restored.xp_earned);
          setBaseRawMs(restored.raw_duration_ms);
          if (restored.attempts.length >= restored.question_count) {
            setIndex(restored.question_count - 1);
            setFeedback(restored.attempts.at(-1) ?? null);
          } else {
            setIndex(restored.attempts.length);
          }
          questionStartedAt.current = performance.now();
          setPhase('playing');
        } catch {
          localStorage.removeItem(ACTIVE_SESSION_KEY);
          setPhase('idle');
          setError('上次会话无法恢复，已保留服务端数据；可重新开始。');
        }
      } catch (reason) {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : '无法读取游戏配置');
        setPhase('idle');
      }
    }
    void boot();
    return () => { active = false; };
  }, []);

  const question = game?.questions[index];
  const visibleTime = game?.assistance_mode === 'zh_translation' ? clock.rankedMs : clock.rawMs;

  async function startGame() {
    setSaving(true);
    setError('');
    try {
      const started = await postJson<StartedGame>('/api/v1/game-sessions/start', {
        assistance_mode: assistanceMode,
      });
      localStorage.setItem(ACTIVE_SESSION_KEY, started.session_id);
      setGame(started);
      setIndex(0);
      setSelected(null);
      setFeedback(null);
      setResult(null);
      setStreak(0);
      setXp(0);
      setBaseRawMs(0);
      pendingAttempt.current = null;
      completionEventId.current = null;
      questionStartedAt.current = performance.now();
      setPhase('playing');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法开始游戏');
    } finally {
      setSaving(false);
    }
  }

  async function submitAnswer() {
    if (!game || !question || selected === null || feedback || saving) return;
    const payload = pendingAttempt.current ?? {
      eventId: crypto.randomUUID(),
      questionId: question.question_id,
      chosenOptionTokens: [selected],
      responseMs: Math.max(0, Math.round(performance.now() - questionStartedAt.current)),
    };
    pendingAttempt.current = payload;
    setSaving(true);
    setError('');
    try {
      const saved = await postJson<AttemptResult>(
        `/api/v1/game-sessions/${game.session_id}/attempts`,
        {
          event_id: payload.eventId,
          question_id: payload.questionId,
          chosen_option_tokens: payload.chosenOptionTokens,
          response_ms: payload.responseMs,
        },
      );
      setFeedback(saved);
      setStreak(saved.streak);
      setXp(saved.total_xp);
      pendingAttempt.current = null;
    } catch (reason) {
      setError(`本题尚未保存：${reason instanceof Error ? reason.message : '网络错误'}。请重试。`);
    } finally {
      setSaving(false);
    }
  }

  async function finishGame() {
    if (!game || saving) return;
    completionEventId.current ??= crypto.randomUUID();
    setSaving(true);
    setError('');
    try {
      const completed = await postJson<CompletedGame>(
        `/api/v1/game-sessions/${game.session_id}/complete`,
        { event_id: completionEventId.current },
      );
      localStorage.removeItem(ACTIVE_SESSION_KEY);
      setResult(completed);
      setBaseRawMs(completed.raw_duration_ms);
      setPhase('finished');
    } catch (reason) {
      setError(`整局尚未完成保存：${reason instanceof Error ? reason.message : '网络错误'}。请重试。`);
    } finally {
      setSaving(false);
    }
  }

  function advance() {
    if (!game || !feedback || saving) return;
    if (index + 1 === game.questions.length) {
      void finishGame();
      return;
    }
    setIndex((value) => value + 1);
    setSelected(null);
    setFeedback(null);
    setError('');
    pendingAttempt.current = null;
    questionStartedAt.current = performance.now();
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (phase !== 'playing' || !question || saving) return;
      const optionNumber = Number(event.key);
      if (
        !feedback
        && !pendingAttempt.current
        && Number.isInteger(optionNumber)
        && optionNumber >= 1
        && optionNumber <= question.options.length
      ) {
        setSelected(question.options[optionNumber - 1].option_token);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (feedback) advance();
        else if (selected !== null) void submitAnswer();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  if (phase === 'booting') {
    return <main className="arena-shell"><div className="notice neutral">正在恢复本地游戏状态…</div></main>;
  }

  if (phase === 'idle') {
    const translationAvailable = config?.assistance.zh_translation_available === true;
    return <main className="arena-shell">
      <section className="arena-intro">
        <small>LEARNING ARENA · RULESET V2</small>
        <h1>10 题 Speed Run</h1>
        <p>每局由服务端重新洗牌；逐题判分并确认保存后，才显示答案和 XP。</p>
        <ul>
          <li>正确数优先，之后比较排名计时</li>
          <li>数字键选择，Enter 提交 / 下一题</li>
          <li>刷新会恢复同一会话、题序与选项顺序</li>
        </ul>
        <fieldset className="assistance-picker">
          <legend>开局设置</legend>
          <label className={!translationAvailable ? 'unavailable' : ''}>
            <input
              type="checkbox"
              checked={assistanceMode === 'zh_translation'}
              disabled={!translationAvailable || saving}
              onChange={(event) => setAssistanceMode(
                event.currentTarget.checked ? 'zh_translation' : 'none',
              )}
            />
            <span>
              <b>中文翻译辅助</b>
              <small>使用辅助后，排名计时 ×1.3；原始英文始终保留。</small>
            </span>
            <em>{translationAvailable ? '已人工复核' : '中文辅助待复核'}</em>
          </label>
        </fieldset>
        {error && <div className="notice danger">{error}</div>}
        <button className="primary launch" onClick={startGame} disabled={saving || !config}>
          {saving ? '正在创建私有会话…' : '开始本局'}
        </button>
      </section>
    </main>;
  }

  if (phase === 'finished' && result) {
    return <main className="arena-shell">
      <section className="finish-card">
        <small>SESSION SAVED · SET {result.question_set_version} · RULES {result.ruleset_version}</small>
        <h1>{result.is_personal_best ? '新的 Personal Best！' : 'Speed Run 完成'}</h1>
        <strong className="final-score">{result.correct_count} / {result.question_count}</strong>
        <div className="finish-stats four">
          <div><span>实际用时</span><b>{formatDuration(result.raw_duration_ms)}</b></div>
          <div><span>辅助倍率</span><b>×{result.time_multiplier.toFixed(1)}</b></div>
          <div><span>排名计时</span><b>{formatDuration(result.ranked_duration_ms)}</b></div>
          <div><span>XP / 最大连胜</span><b>{result.xp_earned} / {result.max_streak}</b></div>
        </div>
        <div className="mode-banner">{assistanceLabel(result.assistance_mode)}</div>
        <div className="saved-banner">✓ GameSession 与 10 条 QuestionAttempt 已由服务端保存</div>
        <div className="actions">
          <button className="primary" onClick={startGame} disabled={saving}>重新挑战</button>
          <a className="secondary" href="#/dashboard">查看 Dashboard</a>
        </div>
        <p className="disclaimer">本局 XP 和速度不等于 Official grade，也不会自动更新 Mastery。</p>
      </section>
    </main>;
  }

  if (!game || !question) return null;
  const correctAnswers = feedback?.correct_option_tokens
    .map((token) => question.options.find((option) => option.option_token === token))
    .filter((option): option is GameOption => Boolean(option));
  const progressValue = feedback ? index + 1 : index;

  return <main className="arena-shell game-screen">
    <section className="game-hud" aria-label="本局状态">
      <div><span>TIME</span><strong>{formatDuration(visibleTime)}</strong></div>
      <div><span>STREAK</span><strong>◆ {streak}</strong></div>
      <div><span>XP</span><strong>{xp}</strong></div>
      <div className="assist-chip"><span>MODE</span><strong>{assistanceLabel(game.assistance_mode)}</strong></div>
    </section>
    <div className="progress-wrap">
      <div className="progress-label"><span>QUESTION {index + 1}</span><span>{index + 1} / {game.question_count}</span></div>
      <div className="capsule-progress" role="progressbar" aria-valuemin={0} aria-valuemax={game.question_count} aria-valuenow={progressValue}>
        <span style={{ width: `${(progressValue / game.question_count) * 100}%` }} />
      </div>
    </div>

    <section className="question-card">
      <div className="question-meta">
        <small>{question.question_type === 'single_choice' ? '选择一个答案' : '选择所有适用答案'}</small>
        <span>服务端判分</span>
      </div>
      <h1>{question.prompt}</h1>
      {question.prompt_zh && <p className="translation prompt-translation">{question.prompt_zh}</p>}
      <div className="answer-grid" role="radiogroup" aria-label="答案选项">
        {question.options.map((option, optionIndex) => <button
          key={option.option_token}
          type="button"
          role="radio"
          aria-checked={selected === option.option_token}
          className={optionFeedbackClass(option.option_token, selected, feedback)}
          disabled={Boolean(feedback) || saving || Boolean(pendingAttempt.current)}
          onClick={() => setSelected(option.option_token)}
        >
          <kbd>{optionIndex + 1}</kbd>
          <span className="option-copy">
            <b>{option.text}</b>
            {option.text_zh && <small className="translation">{option.text_zh}</small>}
          </span>
        </button>)}
      </div>

      {error && <div className="notice danger save-error">{error}</div>}
      {feedback && <div
        className={`feedback ${feedback.correct ? 'right success-feedback' : 'wrong'}`}
        aria-live="polite"
      >
        {feedback.correct && <>
          <span className="xp-float" aria-hidden="true">+{feedback.xp_earned} XP</span>
          <span className="sparkles" aria-hidden="true"><i /><i /><i /></span>
        </>}
        <h2>{feedback.correct ? `正确！连胜 ${feedback.streak}` : '本题未答对 · 连胜归零'}</h2>
        <div className="correct-answer-list">
          <b>正确答案</b>
          {correctAnswers?.map((option) => <p key={option.option_token}>
            {option.text}{option.text_zh && <small>{option.text_zh}</small>}
          </p>)}
        </div>
        <p>{feedback.explanation}</p>
        <small>来源：{feedback.source_ref} · 本题 +{feedback.xp_earned} XP · ✓ 已保存</small>
      </div>}

      <div className="action-dock">
        {!feedback ? <button className="primary submit" onClick={submitAnswer} disabled={selected === null || saving}>
          {saving ? '正在判分并保存…' : error ? '重试保存本题' : '提交答案'}
        </button> : <button className="primary submit" onClick={advance} disabled={saving}>
          {saving ? '正在完成整局保存…' : index + 1 === game.questions.length ? '完成并保存战绩' : '下一题'}
        </button>}
        <p className="keyboard-help">键盘：1–4 选择 · Enter 提交 / 下一题</p>
      </div>
    </section>
  </main>;
}

function App() {
  const hash = useHash();
  const play = hash.startsWith('#/play');
  return <>
    <header>
      <a className="brand" href="#/dashboard">◈ RAE LEARNING OS</a>
      <nav>
        <a className={!play ? 'current' : ''} href="#/dashboard">Dashboard</a>
        <a className={play ? 'current' : ''} href="#/play">Speed Run</a>
      </nav>
    </header>
    {play ? <Arena /> : <Dashboard />}
    <footer>v0.3 local slice · private_only questions · XP ≠ Official grade · Mastery remains unknown</footer>
  </>;
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>,
);
