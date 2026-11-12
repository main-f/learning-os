import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Summary = {
  task_total: number; task_completed: number; imported_source_count: number;
  recorded_learning_sessions: number; minutes_until_sleep_boundary: number;
  net_available_study_minutes: number | null; official_grade: number | null;
  estimated_grade: number | null; exam_deadline: string | null;
  status_note: string; last_updated_at: string;
};
const example: Summary = {
  task_total: 0, task_completed: 0, imported_source_count: 0,
  recorded_learning_sessions: 0, minutes_until_sleep_boundary: 0,
  net_available_study_minutes: null, official_grade: null, estimated_grade: null,
  exam_deadline: null, status_note: '展示模式：此页面没有连接私人学习数据库',
  last_updated_at: ''
};

const questions = [
  { q: 'CIA 三元组中的 I 代表什么？', options: ['Integrity', 'Identity', 'Internet', 'Inspection'], correct: 0,
    why: 'CIA = Confidentiality, Integrity, Availability；Integrity 指完整性。' },
  { q: 'DDoS 中的 Distributed 主要指什么？', options: ['只有一个客户端', '来自多个攻击来源', '多个目标数据库', '无需联网'], correct: 1,
    why: 'Distributed 表示来自多个分散来源的流量或请求参与攻击。' },
  { q: '以下哪个是多因素认证的例子？', options: ['两个不同密码', '密码加硬件安全密钥', '两次输入同一密码', '只使用用户名'], correct: 1,
    why: '密码属于知识因素，安全密钥属于持有因素。' },
];

function useHash(): string {
  const [hash,setHash] = useState(window.location.hash || '#/dashboard');
  useEffect(() => { const update=()=>setHash(window.location.hash || '#/dashboard'); window.addEventListener('hashchange',update); return()=>window.removeEventListener('hashchange',update) },[]);
  return hash;
}

function Dashboard() {
  const [data,setData]=useState<Summary>(example);
  const [connected,setConnected]=useState(false);
  useEffect(()=>{
    let active=true;
    // Public Pages intentionally have no private API URL by default.
    const endpoint=import.meta.env.DEV ? '/api/v1/summary' : import.meta.env.VITE_AUTH_API_URL;
    if (!endpoint) return;
    fetch(endpoint).then(r=>{if(!r.ok) throw new Error();return r.json()}).then(d=>{
      if(active){setData(d);setConnected(true)}
    }).catch(()=>{if(active)setConnected(false)});
    return ()=>{active=false};
  },[]);
  const ratio=data.task_total ? Math.round(100*data.task_completed/data.task_total) : 0;
  return <main>
    <div className="intro"><small>MISSION CONTROL · CYBER SECURITY</small><h1>学习指挥中心</h1><p>只看真正发生的进度，不用虚构的成绩制造焦虑。</p></div>
    <div className="notice">{connected?'本地学习数据库已连接':'未连接私人数据库：展示模式（不会公布真实成绩）'}</div>
    <div className="cards">
      <div className="tile"><span>任务完成</span><strong>{data.task_completed} / {data.task_total}</strong><progress max={100} value={ratio} /></div>
      <div className="tile"><span>官方成绩</span><strong>{data.official_grade ?? '待确认'}</strong><small>与知识测评独立</small></div>
      <div className="tile"><span>预计知识水平</span><strong>{data.estimated_grade ?? '尚未测评'}</strong><small>从实际闭卷测试得出</small></div>
      <div className="tile"><span>考试日期</span><strong>{data.exam_deadline ?? '待核实'}</strong><small>不会使用过期计划日期</small></div>
      <div className="tile"><span>学习资料主题</span><strong>{data.imported_source_count}</strong><small>仅本地导入元数据</small></div>
      <div className="tile"><span>非演示学习打卡</span><strong>{data.recorded_learning_sessions}</strong><small>自报记录，尚未验证掌握</small></div>
    </div>
    <div className="feature"><h2>今日学习</h2><p>{connected ? '先完成今天的最小学习任务；之后再逐步加入自适应规划。' : '连接本地 Study Core 后显示真实任务。'}</p><a className="primary" href="#/play">进入 Learning Arena</a></div>
    <div className="feature"><h2>时间边界</h2><p>距计划睡眠边界：{connected?`${data.minutes_until_sleep_boundary} 分钟`:'待连接'}</p><p>净可用学习时间：{data.net_available_study_minutes ?? '待关联实际日程'}</p><small>距离睡眠时间 ≠ 可用学习时间，不能挤占睡眠。</small></div>
  </main>;
}

function Arena(){
  const [index,setIndex]=useState(0);
  const [answer,setAnswer]=useState<number|null>(null);
  const [score,setScore]=useState(0);
  const [done,setDone]=useState(false);
  const [begin,setBegin]=useState(Date.now());
  const [message,setMessage]=useState('');
  const q=questions[index];
  function advance(){
    if(answer===null)return;
    const nextScore=score+(answer===q.correct?1:0);
    setScore(nextScore);
    if(index+1 === questions.length){
      setDone(true);
      setMessage('演示已结束：此分数只属于游戏演示，不计入官方成绩或知识掌握度。');
      const endpoint=import.meta.env.DEV ? '/api/v1/sessions' : import.meta.env.VITE_AUTH_API_WRITE_URL;
      if (endpoint) fetch(endpoint, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        task_id:'cybersecurity-start',duration_minutes:Math.max(1,Math.round((Date.now()-begin)/60000)),
        evidence_note:`Completed demonstration quiz: ${nextScore}/${questions.length}`,
        activity_type:'demo_game'})}).catch(()=>{});
    }else{setIndex(index+1);setAnswer(null)}
  }
  function again(){setIndex(0);setAnswer(null);setScore(0);setDone(false);setBegin(Date.now());setMessage('')}
  return <main>
    <div className="intro"><small>LEARNING ARENA · DEMO</small><h1>安全知识挑战</h1><p>先验证“玩起来”的体验，再接入真实且已校验的课程题库。</p></div>
    <div className="notice">这是 3 道原创演示题，不属于课程原题。不会将演示 XP 误算为正式学习成绩。</div>
    {done ? <div className="feature finished"><h2>挑战完成！</h2><strong>{score} / {questions.length}</strong><p>{message}</p><button onClick={again}>重新挑战</button></div> :
      <div className="feature"><div className="questionbar"><small>ROUND {index+1} / {questions.length}</small><span>正确 {score}</span></div><h2>{q.q}</h2>
      <div className="options">{q.options.map((item,i)=><button key={item} className={answer===i?'selected':''} disabled={answer!==null} onClick={()=>setAnswer(i)}>{item}</button>)}</div>
      {answer!==null && <div className="explain"><b>{answer===q.correct?'✓ 正确！':'还没答对，再看概念解释。'}</b><p>{q.why}</p></div>}
      <button className="primary" onClick={advance} disabled={answer===null}>{index+1===questions.length?'查看战绩':'下一道'}</button></div>}
    <p className="endnote">下一阶段接入 `cybersecurity_codex` 中已核验的 MCQ、计时、个人纪录与错题复习。</p>
  </main>;
}

function App(){
  const hash=useHash();
  const play=hash.startsWith('#/play');
  return <><header><div className="brand">◈ RAE LEARNING OS</div><nav><a className={!play?'current':''} href="#/dashboard">Mission Control</a><a className={play?'current':''} href="#/play">Learning Arena</a></nav></header>{play?<Arena/>:<Dashboard/>}<footer>Prototype v0.1 · 本地优先 · 学习数据与生活助手隔离</footer></>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
