"use client";

import Link from "next/link";
import {useEffect, useMemo, useState} from "react";

import {Icon, type IconName} from "./Icon";

const journey: {label: string; icon: IconName; state: "done" | "current" | "future"}[] = [
  {label: "Estudar", icon: "book", state: "done"},
  {label: "Praticar", icon: "target", state: "done"},
  {label: "Simular", icon: "clipboard", state: "current"},
  {label: "Corrigir", icon: "search", state: "future"},
  {label: "Revisar", icon: "refresh", state: "future"},
  {label: "Evoluir", icon: "trend", state: "future"},
];

const initialAgenda = [
  {time: "19:30", title: "Revisar flashcards", detail: "Direito Administrativo", icon: "note" as IconName},
  {time: "20:30", title: "20 questões de Constitucional", detail: "Direitos Fundamentais", icon: "question" as IconName},
  {time: "21:15", title: "Bloco de concentração", detail: "25 min de foco", icon: "clock" as IconName},
];

export function Dashboard({userName}: {userName: string}) {
  const [seconds, setSeconds] = useState(25 * 60);
  const [running, setRunning] = useState(false);
  const [completed, setCompleted] = useState<number[]>([]);

  useEffect(() => {
    if (!running || seconds <= 0) return;
    const timer = window.setInterval(() => setSeconds((value) => value - 1), 1000);
    return () => window.clearInterval(timer);
  }, [running, seconds]);

  const clock = useMemo(() => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`, [seconds]);
  const timerActive = running && seconds > 0;
  const toggleTimer = () => {
    if (seconds === 0) {
      setSeconds(25 * 60);
      setRunning(true);
    } else {
      setRunning(!running);
    }
  };

  return (
    <div className="dashboard">
      <div className="cave-backdrop" aria-hidden="true"/>
      <header className="dashboard-heading">
        <h1>Boa noite, {userName}</h1>
        <p>Retome de onde parou, com clareza.</p>
      </header>

      <div className="dashboard-layout">
        <section className="next-step" aria-labelledby="next-step-title">
          <div className="section-label">Seu próximo passo</div>
          <h2 id="next-step-title">Ética Profissional</h2>
          <div aria-label="45% concluído" aria-valuemax={100} aria-valuemin={0} aria-valuenow={45} className="progress" role="progressbar"><span/></div>
          <p><strong>45% concluído</strong><span aria-hidden="true">·</span>9 de 20 tópicos</p>
          <Link className="primary-button" href="/estudar"><Icon name="book"/>Continuar estudo<Icon name="arrow"/></Link>
        </section>

        <section className="journey" aria-labelledby="journey-title">
          <h2 className="visually-hidden" id="journey-title">Sua jornada</h2>
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
          <h2 id="today-title">Hoje</h2>
          <div className="agenda-list">
            {initialAgenda.map((item, index) => (
              <button className={completed.includes(index) ? "agenda-item completed" : "agenda-item"} key={item.title} onClick={() => setCompleted((items) => items.includes(index) ? items.filter((itemIndex) => itemIndex !== index) : [...items, index])} type="button">
                <time>{item.time}</time><span className="agenda-icon"><Icon name={completed.includes(index) ? "check" : item.icon}/></span><span className="agenda-copy"><strong>{item.title}</strong><small>{item.detail}</small></span><Icon className="agenda-arrow" name="arrow"/>
              </button>
            ))}
          </div>
          <Link className="text-link" href="/metas">Ver agenda completa <Icon name="arrow"/></Link>
        </section>

        <section className="focus-panel" aria-labelledby="focus-title">
          <div><h2 id="focus-title">Foco <span>(Pomodoro)</span></h2><strong className="timer" aria-live="polite">{clock}</strong></div>
          <button aria-label={timerActive ? "Pausar foco" : "Iniciar foco"} className="timer-control" onClick={toggleTimer} type="button"><Icon name={timerActive ? "pause" : "play"}/></button>
          <button className="secondary-button" onClick={toggleTimer} type="button">{timerActive ? "Pausar foco" : seconds === 0 ? "Reiniciar foco" : "Iniciar foco"}</button>
          <button className="focus-settings" onClick={() => {setRunning(false); setSeconds(25 * 60);}} type="button"><Icon name="settings"/>Ajustes<span>25 minutos</span></button>
        </section>

        <section className="performance parchment-panel" aria-labelledby="performance-title">
          <div className="performance-heading"><h2 id="performance-title">Desempenho recente</h2><label>Período<select defaultValue="7"><option value="7">7 dias</option><option value="30">30 dias</option></select></label></div>
          <div className="chart-legend"><span><i className="legend-solid"/>Questões respondidas</span><span><i className="legend-dashed"/>Questões corretas (%)</span></div>
          <svg aria-labelledby="chart-title chart-desc" className="performance-chart" role="img" viewBox="0 0 560 215">
            <title id="chart-title">Desempenho nos últimos sete dias</title><desc id="chart-desc">As questões respondidas aumentaram durante a semana e recuaram levemente no último dia.</desc>
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
