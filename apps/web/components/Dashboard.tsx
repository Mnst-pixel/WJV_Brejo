"use client";

import Link from "next/link";
import {useEffect, useMemo, useState} from "react";
import {useStudyTimer} from "@/lib/use-study-timer";
import {apiRequest} from "@/lib/browser-api";

import {Icon, type IconName} from "./Icon";

const journey: {label: string; icon: IconName; state: "done" | "current" | "future"}[] = [
  {label: "Estudar", icon: "book", state: "done"},
  {label: "Praticar", icon: "target", state: "done"},
  {label: "Simular", icon: "clipboard", state: "current"},
  {label: "Corrigir", icon: "search", state: "future"},
  {label: "Revisar", icon: "refresh", state: "future"},
  {label: "Evoluir", icon: "trend", state: "future"},
];

type AgendaGoal = {id: string; title: string; description: string; target_date: string | null; progress: number};

export function Dashboard({userName}: {userName: string}) {
  const {seconds, running, disabled, notice, toggle: toggleTimer, reset: resetTimer} = useStudyTimer();
  const [agenda, setAgenda] = useState<AgendaGoal[]>([]);
  const [agendaLoading, setAgendaLoading] = useState(true);
  const [agendaNotice, setAgendaNotice] = useState("");
  const [savingGoal, setSavingGoal] = useState<string | null>(null);

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

  return (
    <div className="dashboard">
      <div className="cave-backdrop" aria-hidden="true"/>
      <header className="dashboard-heading">
        <h1>Boa noite, {userName}</h1>
        <p>Retome de onde parou, com clareza.</p>
      </header>

      <div className="dashboard-layout">
        <section className="next-step" aria-labelledby="next-step-title">
          <div className="section-label">Próximo passo · demonstração</div>
          <h2 id="next-step-title">Ética Profissional</h2>
          <div aria-label="Exemplo demonstrativo: 45% concluído, sem relação com seu progresso" aria-valuemax={100} aria-valuemin={0} aria-valuenow={45} className="progress" role="progressbar"><span/></div>
          <p><strong>Exemplo: 45%</strong><span aria-hidden="true">·</span>9 de 20 tópicos ilustrativos</p>
          <Link className="primary-button" href="/estudar"><Icon name="book"/>Continuar estudo<Icon name="arrow"/></Link>
        </section>

        <section className="journey" aria-labelledby="journey-title">
          <h2 className="visually-hidden" id="journey-title">Exemplo demonstrativo de jornada</h2>
          <span className="section-label">Jornada ilustrativa</span>
          <div className="journey-track">
            {journey.map((step) => (
              <div className={`journey-step ${step.state}`} key={step.label}>
                <span className="journey-icon"><Icon name={step.icon}/>{step.state === "done" && <span className="step-check"><Icon name="check"/></span>}</span>
                <span>{step.label}</span>
              </div>
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
          <div className="performance-heading"><h2 id="performance-title">Desempenho · demonstração</h2><label>Período ilustrativo<select defaultValue="7" disabled><option value="7">7 dias</option><option value="30">30 dias</option></select></label></div>
          <p>Dados ilustrativos. Este gráfico ainda não representa suas respostas.</p>
          <div className="chart-legend"><span><i className="legend-solid"/>Questões respondidas</span><span><i className="legend-dashed"/>Questões corretas (%)</span></div>
          <svg aria-labelledby="chart-title chart-desc" className="performance-chart" role="img" viewBox="0 0 560 215">
            <title id="chart-title">Exemplo demonstrativo de desempenho</title><desc id="chart-desc">Valores e datas ilustrativos, sem relação com o histórico do aluno.</desc>
            <g className="grid-lines"><path d="M42 25H540M42 75H540M42 125H540M42 175H540"/></g>
            <path className="chart-area" d="M42 158 C85 146 98 158 130 134 S190 119 220 124 S280 105 310 100 S360 72 395 82 S455 88 480 94 S520 88 540 122 L540 175 L42 175Z"/>
            <path className="chart-line" d="M42 158 C85 146 98 158 130 134 S190 119 220 124 S280 105 310 100 S360 72 395 82 S455 88 480 94 S520 88 540 122"/>
            <path className="chart-dashed" d="M42 88 C100 77 140 80 190 86 S270 92 318 61 S390 48 432 68 S500 81 540 91"/>
            <g className="chart-labels"><text x="42" y="202">08/05</text><text x="125" y="202">09/05</text><text x="208" y="202">10/05</text><text x="291" y="202">11/05</text><text x="374" y="202">12/05</text><text x="457" y="202">13/05</text><text x="520" y="202">14/05</text></g>
          </svg>
        </section>

        <section className="legal-base" aria-label="Estado da base jurídica"><span className="legal-icon"><Icon name="scales"/></span><span><strong>Base jurídica</strong><small>Conteúdo com fontes e data de referência</small></span><span className="legal-date">Cobertura exibida por fonte</span><Link className="consult-button" href="/consultor"><Icon name="chat"/>Consultar Kairós</Link></section>
      </div>
    </div>
  );
}
