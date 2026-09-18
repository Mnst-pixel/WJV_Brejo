"use client";

import Link from "next/link";
import {useEffect, useMemo, useState} from "react";
import {useStudyTimer} from "@/lib/use-study-timer";
import {apiRequest} from "@/lib/browser-api";
import {studentRequest} from "@/lib/student-api";

import {Icon, type IconName} from "./Icon";

const journey: {label: string; icon: IconName; href: string}[] = [
  {label: "Estudar", icon: "book", href: "/estudar"},
  {label: "Praticar", icon: "target", href: "/questoes"},
  {label: "Simular", icon: "clipboard", href: "/simulados"},
  {label: "Redigir", icon: "note", href: "/segunda-fase"},
  {label: "Revisar", icon: "refresh", href: "/questoes?mode=wrong"},
  {label: "Planejar", icon: "trend", href: "/metas"},
];

type Learning = {formal_active: boolean; next_step: {title: string; reason: string; href: string} | null; metrics: {answered: number; correct: number; accuracy: number | null; registered_seconds: number; study_streak_in_period: number; completed_contents: number; published_contents: number; submitted_simulations: number; submitted_written: number; daily: {date: string; answered: number; correct: number}[]; subjects: {id: string; name: string; accuracy: number; answered: number}[]} | null};

type AgendaGoal = {id: string; title: string; description: string; target_date: string | null; progress: number};

export function Dashboard({userName}: {userName: string}) {
  const {seconds, running, disabled, notice, toggle: toggleTimer, reset: resetTimer} = useStudyTimer();
  const [agenda, setAgenda] = useState<AgendaGoal[]>([]);
  const [agendaLoading, setAgendaLoading] = useState(true);
  const [agendaNotice, setAgendaNotice] = useState("");
  const [savingGoal, setSavingGoal] = useState<string | null>(null);
  const [days, setDays] = useState("7");
  const [learning, setLearning] = useState<Learning | null>(null);
  const [learningNotice, setLearningNotice] = useState("Carregando seu estudo…");

  useEffect(() => {
    const controller = new AbortController();
    void studentRequest<Learning>(`/api/study/dashboard/?days=${days}`, {signal: controller.signal}).then(data => {
      if (!controller.signal.aborted) {setLearning(data); setLearningNotice("");}
    }).catch(() => {if (!controller.signal.aborted) {setLearning(null); setLearningNotice("Não foi possível carregar o estudo. Selecione o período para tentar novamente.");}});
    return () => controller.abort();
  }, [days]);

  useEffect(() => {
    const controller = new AbortController();
    void apiRequest("/api/goals/", {signal: controller.signal}).then(async response => {
      if (!response.ok) throw new Error();
      const payload = await response.json() as {results?: AgendaGoal[]} | AgendaGoal[];
      if (!controller.signal.aborted) setAgenda((Array.isArray(payload) ? payload : payload.results ?? []).slice(0, 3));
    }).catch(() => {
      if (!controller.signal.aborted) setAgendaNotice("Não foi possível carregar suas metas. Recarregue a página para tentar novamente.");
    }).finally(() => {if (!controller.signal.aborted) setAgendaLoading(false);});
    return () => controller.abort();
  }, []);

  async function completeGoal(goal: AgendaGoal) {
    if (savingGoal || goal.progress === 100) return;
    setSavingGoal(goal.id);
    setAgendaNotice("");
    try {
      const response = await apiRequest(`/api/goals/${goal.id}/`, {method: "PATCH", body: JSON.stringify({progress: 100})});
      if (!response.ok) throw new Error();
      const saved = await response.json() as AgendaGoal;
      setAgenda(items => items.map(item => item.id === saved.id ? saved : item));
      setAgendaNotice("Meta concluída e salva na sua conta.");
    } catch {setAgendaNotice("Não foi possível confirmar a conclusão. Recarregue a página para conferir antes de tentar novamente.");}
    finally {setSavingGoal(null);}
  }

  const clock = useMemo(() => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`, [seconds]);
  const timerActive = running && seconds > 0;
  const metrics = learning?.metrics;
  const maximum = Math.max(1, ...metrics?.daily.map(day => day.answered) ?? []);
  const points = (field: "answered" | "correct") => metrics?.daily.map((day, index) => `${42 + index * 498 / Math.max(1, metrics.daily.length - 1)},${175 - day[field] * 150 / maximum}`).join(" ") ?? "";
  const completedPercent = metrics?.published_contents ? Math.round(metrics.completed_contents * 100 / metrics.published_contents) : 0;

  return (
    <div className="dashboard">
      <div className="cave-backdrop" aria-hidden="true"/>
      <header className="dashboard-heading">
        <h1>Olá, {userName}</h1>
        <p>Retome de onde parou, com clareza.</p>
      </header>

      <div className="dashboard-layout">
        <section className="next-step" aria-labelledby="next-step-title">
          <div className="section-label">Próximo passo</div>
          <h2 id="next-step-title">{learning?.next_step?.title ?? "Sua jornada de estudo"}</h2>
          <p role="status">{learningNotice || learning?.next_step?.reason}</p>
          {metrics && <><div aria-label="Conteúdos concluídos na publicação atual" aria-valuemax={100} aria-valuemin={0} aria-valuenow={completedPercent} className="progress" role="progressbar"><span style={{width: `${completedPercent}%`}}/></div><p>{metrics.completed_contents} de {metrics.published_contents} leituras concluídas na versão atual</p></>}
          <Link className="primary-button" href={learning?.next_step?.href ?? "/estudar"}><Icon name="book"/>Continuar estudo<Icon name="arrow"/></Link>
        </section>

        <section className="journey" aria-labelledby="journey-title">
          <h2 className="visually-hidden" id="journey-title">Acessos à sua jornada</h2>
          <span className="section-label">Sua jornada</span>
          <div className="journey-track">
            {journey.map((step) => (
              <Link className="journey-step" href={step.href} key={step.label}>
                <span className="journey-icon"><Icon name={step.icon}/></span>
                <span>{step.label}</span>
              </Link>
            ))}
          </div>
        </section>

        <section className="today parchment-panel" aria-labelledby="today-title">
          <h2 id="today-title">Minhas metas</h2>
          <div className="agenda-list">
            {agendaLoading && <p aria-live="polite">Carregando suas metas…</p>}
            {!agendaLoading && !agenda.length && !agendaNotice && <p>Você ainda não tem metas. Crie a primeira para organizar seu estudo.</p>}
            {agenda.map(item => (
              <button aria-label={item.progress === 100 ? `Meta concluída: ${item.title}` : `Concluir meta: ${item.title}`} className={item.progress === 100 ? "agenda-item completed" : "agenda-item"} disabled={savingGoal !== null || item.progress === 100} key={item.id} onClick={() => void completeGoal(item)} type="button">
                <time dateTime={item.target_date ?? undefined}>{item.target_date ? new Date(`${item.target_date}T12:00:00`).toLocaleDateString("pt-BR", {day: "2-digit", month: "2-digit"}) : "—"}</time><span className="agenda-icon"><Icon name={item.progress === 100 ? "check" : "target"}/></span><span className="agenda-copy"><strong>{item.title}</strong><small>{savingGoal === item.id ? "Salvando…" : `${item.progress}% · ${item.description || "Meta pessoal"}`}</small></span><Icon className="agenda-arrow" name="arrow"/>
              </button>
            ))}
          </div>
          <p aria-live="polite" className="form-notice">{agendaNotice}</p>
          <Link className="text-link" href="/metas">Ver todas as metas <Icon name="arrow"/></Link>
        </section>

        <section className="focus-panel" aria-labelledby="focus-title">
          <div><h2 id="focus-title">Foco <span>(Pomodoro)</span></h2><strong className="timer" aria-live="polite">{clock}</strong></div>
          <button disabled={disabled} aria-label={timerActive ? "Pausar foco" : "Iniciar foco"} className="timer-control" onClick={toggleTimer} type="button"><Icon name={timerActive ? "pause" : "play"}/></button>
          <button disabled={disabled} className="secondary-button" onClick={toggleTimer} type="button">{timerActive ? "Pausar foco" : seconds === 0 ? "Reiniciar foco" : "Iniciar foco"}</button>
          <button disabled={disabled} className="focus-settings" onClick={resetTimer} type="button"><Icon name="settings"/>Ajustes<span>25 minutos</span></button>
          <p aria-live="polite">{notice}</p>
        </section>

        <section className="performance parchment-panel" aria-labelledby="performance-title">
          <div className="performance-heading"><h2 id="performance-title">Meu desempenho</h2><label>Período<select aria-label="Período" value={days} onChange={event => {setDays(event.target.value); setLearning(null); setLearningNotice("Carregando seu estudo…");}}><option value="7">7 dias</option><option value="30">30 dias</option><option value="90">90 dias</option></select></label></div>
          {learning?.formal_active && <p>Finalize o simulado formal para consultar resultados e recomendações de revisão.</p>}
          {metrics && <><p>{metrics.answered ? `${metrics.correct} acertos em ${metrics.answered} respostas (${metrics.accuracy}%).` : "Suas respostas confirmadas aparecerão aqui."} {metrics.submitted_simulations} simulados e {metrics.submitted_written} provas escritas enviados.</p><p>{Math.round(metrics.registered_seconds / 60)} minutos registrados · {metrics.study_streak_in_period} dias seguidos de atividade dentro do período.</p>
          <div className="chart-legend"><span><i className="legend-solid"/>Questões respondidas</span><span><i className="legend-dashed"/>Questões corretas</span></div>
          <svg aria-labelledby="chart-title chart-desc" className="performance-chart" role="img" viewBox="0 0 560 215">
            <title id="chart-title">Respostas por dia</title><desc id="chart-desc">Quantidade de respostas e acertos, de zero a {maximum}. Valores completos na tabela abaixo.</desc>
            <g className="grid-lines"><path d="M42 25H540M42 75H540M42 125H540M42 175H540"/></g>
            <polyline className="chart-line" fill="none" points={points("answered")}/>
            <polyline className="chart-dashed" fill="none" points={points("correct")}/>
            <g className="chart-labels"><text x="5" y="30">{maximum}</text><text x="20" y="175">0</text><text x="42" y="202">{metrics.daily[0]?.date.slice(5).split("-").reverse().join("/")}</text><text x="495" y="202">{metrics.daily.at(-1)?.date.slice(5).split("-").reverse().join("/")}</text></g>
          </svg><details><summary>Ver valores por dia e disciplina</summary><table className="learning-table"><caption>Respostas no período</caption><thead><tr><th scope="col">Dia</th><th scope="col">Respostas</th><th scope="col">Acertos</th></tr></thead><tbody>{metrics.daily.map(day => <tr key={day.date}><th scope="row">{day.date.split("-").reverse().join("/")}</th><td>{day.answered}</td><td>{day.correct}</td></tr>)}</tbody></table><ul>{metrics.subjects.map(subject => <li key={subject.id}>{subject.name}: {subject.accuracy}% em {subject.answered} respostas</li>)}</ul></details></>}
        </section>

        <section className="legal-base" aria-label="Estado da base jurídica"><span className="legal-icon"><Icon name="scales"/></span><span><strong>Base jurídica</strong><small>Conteúdo com fontes e data de referência</small></span><span className="legal-date">Cobertura exibida por fonte</span><Link className="consult-button" href="/consultor"><Icon name="chat"/>Consultar Kairós</Link></section>
      </div>
    </div>
  );
}
