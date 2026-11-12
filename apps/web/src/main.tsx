import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type GameQuestion = {
  question_id: string;
  question_type: 'single_choice' | 'multiple_choice';
  prompt: string;
  options: string[];
};

type StartedGame = {
  session_id: string;
  question_set_id: string;
  question_set_version: string;
  ruleset_version: string;
  started_at: string;
  question_count: number;
  questions: GameQuestion[];
};

type AttemptResult = {
  attempt_id: string;
  event_id: string;
  question_id: string;
  correct: boolean;
  correct_options: number[];
  source_ref: string;
  explanation: string;
  explanation_status: 'pending_human_review' | 'verified';
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
  question_count: number;
  correct_count: number;
  max_streak: number;
  xp_earned: number;
  is_personal_best: boolean;
  saved: boolean;
};

type DashboardData = {
  timezone: 'Europe/Helsinki';
  import_stats: {
    topic_count: number;
    candidate_question_count: number;
    source_verified_count: number;
  };
  recent_game: CompletedGame | null;
  personal_best: CompletedGame | null;
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
  chosenOptions: number[];
  responseMs: number;
};

const configuredApi = (import.meta.env.VITE_AUTH_API_URL as string | undefined)?.replace(/\/$/, '');

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
      // The status code remains the useful fallback.
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

function formatDuration(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

function formatHelsinki(value: string | null): string {
  if (!value) return '尚无记录';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Europe/Helsinki',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
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

function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  function loadDashboard() {
    setLoading(true);
    setError('');
    apiRequest<DashboardData>('/api/v1/dashboard')
      .then(setData)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '无法读取 Dashboard'))
      .finally(() => setLoading(false));
  }

  useEffect(loadDashboard, []);
  const stats = data?.import_stats;

  return <main>
    <section className="hero">
      <div>
        <small>MISSION CONTROL · PRIVATE LOCAL DATA</small>
        <h1>真实战绩，不造假进度</h1>
        <p>课程原题留在私有 SQLite；XP 只代表游戏表现，不是官方成绩。</p>
      </div>
      <a className="primary large" href="#/play">开始 10 题 Speed Run</a>
    </section>

    {loading && <div className="notice neutral">正在连接本地 Study Core…</div>}
    {error && <div className="notice danger"><span>未读取到私人数据：{error}</span><button onClick={loadDashboard}>重试</button></div>}
    {data && <>
      <div className="cards metrics">
        <article className="tile"><span>已导入主题</span><strong>{stats?.topic_count ?? 0}</strong><small>根目录 Markdown</small></article>
        <article className="tile"><span>候选 MCQ</span><strong>{stats?.candidate_question_count ?? 0}</strong><small>尚未核验者不会入局</small></article>
        <article className="tile verified"><span>source_verified</span><strong>{stats?.source_verified_count ?? 0}</strong><small>本地原始页面机械对账</small></article>
        <article className="tile"><span>Official grade</span><strong>待确认</strong><small>游戏 XP 不会修改</small></article>
        <article className="tile"><span>Mastery</span><strong>{data.mastery_label}</strong><small>当前状态：{data.mastery}</small></article>
        <article className="tile"><span>最近同步 / 更新</span><strong className="date-value">{formatHelsinki(data.last_updated_at)}</strong><small>Europe/Helsinki</small></article>
      </div>

      <div className="result-grid">
        <article className="panel">
          <div className="panel-title"><span>最近一局</span>{data.recent_game && <em>已保存</em>}</div>
          {data.recent_game ? <>
            <strong className="score">{data.recent_game.correct_count} / {data.recent_game.question_count}</strong>
            <dl className="stat-list">
              <div><dt>总用时</dt><dd>{formatDuration(data.recent_game.duration_ms)}</dd></div>
              <div><dt>最大连胜</dt><dd>{data.recent_game.max_streak}</dd></div>
              <div><dt>XP</dt><dd>{data.recent_game.xp_earned}</dd></div>
            </dl>
            <small>{formatHelsinki(data.recent_game.completed_at)}</small>
          </> : <p className="muted">还没有真实游戏记录。第一局会在服务端逐题保存。</p>}
        </article>

        <article className="panel">
          <div className="panel-title"><span>Personal Best</span><em>同题集 / 同规则</em></div>
          {data.personal_best ? <>
            <strong className="score">{data.personal_best.correct_count} / 10</strong>
            <dl className="stat-list">
              <div><dt>用时</dt><dd>{formatDuration(data.personal_best.duration_ms)}</dd></div>
              <div><dt>题集版本</dt><dd>{data.personal_best.question_set_version}</dd></div>
              <div><dt>规则版本</dt><dd>{data.personal_best.ruleset_version}</dd></div>
            </dl>
          </> : <p className="muted">完成第一局后建立个人最佳。排序先看正确数，再看速度。</p>}
        </article>
      </div>

      <p className="sync-note">最近导入：{formatHelsinki(data.last_imported_at)}。所有时间在数据库中以 UTC 保存，此处按 Europe/Helsinki 展示。</p>
    </>}
  </main>;
}

function Arena() {
  const [phase, setPhase] = useState<'idle' | 'playing' | 'finished'>('idle');
  const [game, setGame] = useState<StartedGame | null>(null);
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<AttemptResult | null>(null);
  const [result, setResult] = useState<CompletedGame | null>(null);
  const [streak, setStreak] = useState(0);
  const [xp, setXp] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const questionStartedAt = useRef(0);
  const pendingAttempt = useRef<PendingAttempt | null>(null);
  const completionEventId = useRef<string | null>(null);

  useEffect(() => {
    if (phase !== 'playing' || !game) return;
    const tick = () => setElapsedMs(Date.now() - new Date(game.started_at).getTime());
    tick();
    const timer = window.setInterval(tick, 250);
    return () => window.clearInterval(timer);
  }, [phase, game]);

  const question = game?.questions[index];

  async function startGame() {
    setSaving(true);
    setError('');
    try {
      const started = await postJson<StartedGame>('/api/v1/game-sessions/start', {});
      setGame(started);
      setIndex(0);
      setSelected(null);
      setFeedback(null);
      setResult(null);
      setStreak(0);
      setXp(0);
      setElapsedMs(0);
      pendingAttempt.current = null;
      completionEventId.current = null;
      questionStartedAt.current = Date.now();
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
      chosenOptions: [selected],
      responseMs: Math.max(0, Date.now() - questionStartedAt.current),
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
          chosen_options: payload.chosenOptions,
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
      setResult(completed);
      setElapsedMs(completed.duration_ms);
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
    questionStartedAt.current = Date.now();
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (phase !== 'playing' || !question || saving) return;
      const option = Number(event.key);
      if (!feedback && !pendingAttempt.current && Number.isInteger(option) && option >= 1 && option <= question.options.length) {
        setSelected(option);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (feedback) advance();
        else if (selected !== null) void submitAnswer();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  if (phase === 'idle') {
    return <main className="arena-shell">
      <section className="arena-intro">
        <small>LEARNING ARENA · REAL PRIVATE MCQ</small>
        <h1>10 题 Speed Run</h1>
        <p>固定版本题组。每题由服务端判分并确认保存后，才显示答案和 XP。</p>
        <ul>
          <li>正确数优先，之后才比较速度</li>
          <li>答错会把连胜归零</li>
          <li>数字键选择，Enter 提交 / 下一题</li>
        </ul>
        {error && <div className="notice danger">{error}</div>}
        <button className="primary launch" onClick={startGame} disabled={saving}>{saving ? '正在创建私有会话…' : '一键开始'}</button>
      </section>
    </main>;
  }

  if (phase === 'finished' && result) {
    return <main className="arena-shell">
      <section className="finish-card">
        <small>SESSION SAVED · SET {result.question_set_version} · RULES {result.ruleset_version}</small>
        <h1>{result.is_personal_best ? '新的 Personal Best！' : 'Speed Run 完成'}</h1>
        <strong className="final-score">{result.correct_count} / {result.question_count}</strong>
        <div className="finish-stats">
          <div><span>总用时</span><b>{formatDuration(result.duration_ms)}</b></div>
          <div><span>最大连胜</span><b>{result.max_streak}</b></div>
          <div><span>XP</span><b>{result.xp_earned}</b></div>
        </div>
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
  const correctAnswers = feedback?.correct_options.map((number) => question.options[number - 1]);
  const progressValue = feedback ? index + 1 : index;

  return <main className="arena-shell">
    <section className="game-topbar">
      <div><span>TIME</span><strong>{formatDuration(elapsedMs)}</strong></div>
      <div><span>PROGRESS</span><strong>{index + 1} / {game.question_count}</strong></div>
      <div><span>STREAK</span><strong>🔥 {streak}</strong></div>
      <div><span>XP</span><strong>{xp}</strong></div>
    </section>
    <progress className="game-progress" max={game.question_count} value={progressValue} />

    <section className="question-card">
      <div className="question-meta">
        <small>QUESTION {index + 1}</small>
        <span>{question.question_type === 'single_choice' ? '单选' : '多选'}</span>
      </div>
      <h1>{question.prompt}</h1>
      <div className="answer-grid" role="radiogroup" aria-label="答案选项">
        {question.options.map((option, optionIndex) => {
          const number = optionIndex + 1;
          const isCorrect = feedback?.correct_options.includes(number);
          const isWrongChoice = feedback && selected === number && !feedback.correct;
          const className = [
            selected === number ? 'selected' : '',
            isCorrect ? 'correct-option' : '',
            isWrongChoice ? 'wrong-option' : '',
          ].filter(Boolean).join(' ');
          return <button
            key={number}
            type="button"
            role="radio"
            aria-checked={selected === number}
            className={className}
            disabled={Boolean(feedback) || saving || Boolean(pendingAttempt.current)}
            onClick={() => setSelected(number)}
          >
            <kbd>{number}</kbd><span>{option}</span>
          </button>;
        })}
      </div>

      {error && <div className="notice danger save-error">{error}</div>}
      {feedback && <div className={`feedback ${feedback.correct ? 'right' : 'wrong'}`}>
        <h2>{feedback.correct ? `✓ 正确 · 连胜 ${feedback.streak}` : '✕ 本题答错 · 连胜归零'}</h2>
        <p><b>正确答案：</b>{correctAnswers?.join('；')}</p>
        <p>{feedback.explanation}</p>
        <small>来源：{feedback.source_ref} · 本题 +{feedback.xp_earned} XP · ✓ 已保存</small>
      </div>}

      {!feedback ? <button className="primary submit" onClick={submitAnswer} disabled={selected === null || saving}>
        {saving ? '正在由服务端判分并保存…' : error ? '重试保存本题' : '提交答案'}
      </button> : <button className="primary submit" onClick={advance} disabled={saving}>
        {saving ? '正在完成整局保存…' : index + 1 === game.questions.length ? '完成并保存战绩' : '下一题'}
      </button>}
      <p className="keyboard-help">键盘：1–4 选择 · Enter 提交 / 下一题</p>
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

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
