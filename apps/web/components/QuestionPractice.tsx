"use client";

import {useCallback, useEffect, useRef, useState} from "react";
import {apiRequest} from "@/lib/browser-api";

type Question = {id: string; number: number; statement: string; subject_name: string; topic_name: string; exam_title: string; edition: string; year: number; alternatives: {id: string; label: string; text: string}[]};
type Result = {attempt: string; question: string; statement: string; correct: boolean | null; annulled: boolean; correct_alternative: string | null; rationale: string; legal_basis: string; source_url: string; reference_date: string | null; submitted_at: string};
type Subject = {id: string; name: string; topics: {id: string; name: string; parent: string | null}[]};
type Page<T> = {results: T[]; count: number; next: string | null};
type Marks = {favorite: boolean; review: boolean};
type Answer = {question: string; selected_alternative: string; request_id: string; elapsed_seconds: number};

class RequestError extends Error {
  constructor(message: string, readonly status: number) {super(message);}
}

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiRequest(path, init);
  if (!response.ok) {
    if (response.status === 409) throw new RequestError("Finalize o simulado em andamento ou confira a confirmação anterior antes de continuar.", response.status);
    if (response.status === 401 || response.status === 403) throw new RequestError("Acesso indisponível. Confira sua sessão ou a revisão do conteúdo.", response.status);
    throw new RequestError("Não foi possível confirmar a operação. Atualize a seleção ou tente novamente.", response.status);
  }
  return response.json() as Promise<T>;
}

function localPage(next: string, path: string) {
  const url = new URL(next, window.location.origin);
  if (url.origin !== window.location.origin || url.pathname !== path) throw new Error("Página indisponível.");
  return url.pathname + url.search;
}

export function QuestionPractice() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subject, setSubject] = useState("");
  const [topic, setTopic] = useState("");
  const [mode, setMode] = useState("all");
  const [questions, setQuestions] = useState<Page<Question>>({results: [], count: 0, next: null});
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [history, setHistory] = useState<Page<Result>>({results: [], count: 0, next: null});
  const [markState, setMarkState] = useState<{question: Question | null; value: Marks}>({question: null, value: {favorite: false, review: false}});
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [uncertain, setUncertain] = useState(false);
  const pending = useRef<Answer | null>(null);
  const started = useRef(0);
  const generation = useRef(0);
  const historyGeneration = useRef(0);
  const question = questions.results[index];
  const marks = markState.value;
  const marksReady = markState.question === question;
  const heading = useRef<HTMLHeadingElement>(null);

  const load = useCallback(async (path = "/api/questions/") => {
    const current = ++generation.current;
    setLoading(true); setNotice("");
    try {
      const data = await read<Page<Question>>(path);
      if (current !== generation.current) return;
      setQuestions(data); setIndex(0); setSelected(""); setResult(null); started.current = Date.now();
    } catch (error) {if (current === generation.current) setNotice((error as Error).message);}
    finally {if (current === generation.current) setLoading(false);}
  }, []);

  const loadHistory = useCallback(async (next?: string) => {
    const current = ++historyGeneration.current;
    const data = await read<Page<Result>>(next ? localPage(next, "/api/practice/history/") : "/api/practice/history/");
    if (current !== historyGeneration.current) return;
    setHistory(old => next ? {...data, results: [...old.results, ...data.results.filter(row => !old.results.some(item => item.attempt === row.attempt))]} : data);
  }, []);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      const params = new URLSearchParams(window.location.search);
      const initial = new URLSearchParams();
      const initialSubject = params.get("subject") ?? "";
      const initialMode = params.get("mode") ?? "all";
      if (/^[0-9a-f-]{36}$/i.test(initialSubject)) {initial.set("subject", initialSubject); setSubject(initialSubject);}
      if (["all", "unseen", "answered", "wrong", "favorites", "review", "random"].includes(initialMode)) {initial.set("mode", initialMode); setMode(initialMode);}
      await load("/api/questions/?" + initial);
      try {
        let path: string | null = "/api/subjects/";
        const all: Subject[] = [];
        while (path && active) {
          const data: Page<Subject> = await read<Page<Subject>>(path);
          all.push(...data.results);
          path = data.next ? localPage(data.next, "/api/subjects/") : null;
        }
        if (active) {setSubjects(all); await loadHistory();}
      } catch (error) {if (active) setNotice((error as Error).message);}
    });
    return () => {active = false; generation.current += 1; historyGeneration.current += 1;};
  }, [load, loadHistory]);

  useEffect(() => {
    if (!question) return;
    let active = true;
    void read<Marks>(`/api/practice/questions/${question.id}/marks/`).then(data => {if (active) setMarkState({question, value: data});}).catch(error => {if (active) setNotice(error.message);});
    return () => {active = false;};
  }, [question]);

  async function answer(event: React.FormEvent) {
    event.preventDefault();
    if (!question || !selected || busy || result) return;
    setBusy(true); setNotice("");
    pending.current ??= {question: question.id, selected_alternative: selected, request_id: crypto.randomUUID(), elapsed_seconds: Math.min(3600, Math.max(0, Math.floor((Date.now() - started.current) / 1000)))};
    try {
      const value = await read<Result>("/api/practice/answers/", {method: "POST", body: JSON.stringify(pending.current)});
      setResult(value); pending.current = null; setUncertain(false);
      setNotice("Resposta salva no seu histórico.");
      await loadHistory();
    } catch (error) {
      if (error instanceof RequestError && error.status >= 400 && error.status < 500) pending.current = null;
      setUncertain(pending.current !== null);
      setNotice((error as Error).message + (pending.current ? " Use Confirmar novamente para consultar o mesmo envio, sem duplicar a resposta." : " Confira seu histórico antes de iniciar outro envio."));
    }
    finally {setBusy(false);}
  }

  async function mark(key: keyof Marks) {
    if (!question || busy || !marksReady) return;
    setBusy(true);
    try {
      const saved = await read<Marks>(`/api/practice/questions/${question.id}/marks/`, {method: "PUT", body: JSON.stringify({...marks, [key]: !marks[key]})});
      setMarkState({question, value: saved}); setNotice("Marcação salva na sua conta.");
    } catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }

  function next() {
    if (busy || uncertain) return;
    setSelected(""); setResult(null); setNotice(""); pending.current = null; started.current = Date.now();
    if (index + 1 < questions.results.length) setIndex(index + 1);
    else if (questions.next) void load(localPage(questions.next, "/api/questions/"));
    heading.current?.focus();
  }

  return <div className="practice-workspace">
    <section className="work-panel"><h2>Escolha seu treino</h2><form className="stack-form" onSubmit={event => {
      event.preventDefault(); if (busy || uncertain) return;
      const values = new FormData(event.currentTarget); const params = new URLSearchParams();
      for (const [key, value] of values) if (String(value)) params.set(key, String(value));
      void load("/api/questions/?" + params);
    }}><fieldset disabled={busy || uncertain || loading} className="practice-filters"><legend className="visually-hidden">Filtros do treino</legend>
      <label>Disciplina<select aria-label="Disciplina" name="subject" value={subject} onChange={event => {setSubject(event.target.value); setTopic("");}}><option value="">Todas as disciplinas</option>{subjects.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
      <label>Tema<select name="topic" value={topic} onChange={event => setTopic(event.target.value)}><option value="">Todos os temas</option>{subjects.find(item => item.id === subject)?.topics.filter(item => !item.parent).map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
      <label>Dificuldade<select name="difficulty"><option value="">Todas</option><option value="easy">Fácil</option><option value="medium">Intermediária</option><option value="hard">Difícil</option></select></label>
      <label>Seleção<select name="mode" value={mode} onChange={event => setMode(event.target.value)}><option value="all">Todas as questões</option><option value="unseen">Ainda não respondidas</option><option value="answered">Já respondidas</option><option value="wrong">Erros para revisar</option><option value="favorites">Favoritas</option><option value="review">Marcadas para revisão</option><option value="random">Aleatórias</option></select></label>
      <label>Ano<input name="year" type="number" min="1900" max="2200" placeholder="Todos"/></label><label>Buscar enunciado<input name="q" maxLength={200} type="search"/></label>
      <button className="primary-button" type="submit">Aplicar filtros</button>
    </fieldset></form></section>
    <p aria-live="polite" className="form-notice">{loading ? "Carregando questões publicadas…" : notice}</p>
    {!loading && !question && <section className="work-panel"><h2>Nenhuma questão nesta seleção</h2><p>Altere os filtros. Questões em preparação aparecem aqui após revisão e publicação.</p></section>}
    {!loading && question && <div className="question-layout"><section className="question-sheet"><div className="question-meta"><span>{question.subject_name}{question.topic_name && " · " + question.topic_name}</span><span>{question.exam_title} · {question.edition} · {question.year}</span></div>
      <h2 ref={heading} tabIndex={-1} className="preserve-text">{question.statement}</h2>
      <form onSubmit={answer}><fieldset className="practice-answers" disabled={busy || !!result || uncertain}><legend>Escolha uma alternativa</legend><div className="alternatives">{question.alternatives.map(item => <label className={selected === item.id ? "alternative selected" : "alternative"} key={item.id}><input type="radio" name="answer" value={item.id} checked={selected === item.id} onChange={() => setSelected(item.id)}/><span>{item.label}</span><span className="alternative-text">{item.text}</span></label>)}</div></fieldset><div className="question-actions"><button className="primary-button" type="submit" disabled={!selected || busy || !!result}>{busy ? "Salvando…" : uncertain ? "Confirmar novamente" : "Responder"}</button><button className="secondary-button" type="button" disabled={busy || uncertain || (index + 1 >= questions.results.length && !questions.next)} onClick={next}>Próxima questão</button></div></form>
      {result && <section className="practice-result" aria-live="polite"><h3>{result.annulled ? "Questão anulada" : result.correct === null ? "Resposta salva; pontuação pendente" : result.correct ? "Resposta correta" : "Vamos revisar esta questão"}</h3><p>Gabarito: {question.alternatives.find(item => item.id === result.correct_alternative)?.label ?? "Indisponível"}</p><p className="preserve-text">{result.rationale}</p>{result.legal_basis && <><h4>Fundamento jurídico</h4><p className="preserve-text">{result.legal_basis}</p></>}{result.source_url && /^https:\/\//.test(result.source_url) && <a href={result.source_url} target="_blank" rel="noopener noreferrer">Consultar fonte</a>}{result.reference_date && <p>Referência: {result.reference_date}</p>}</section>}
    </section><aside className="source-rail"><h2>Seu estudo</h2><p>{questions.count} questões encontradas. Respostas e marcações ficam associadas à sua conta.</p><div className="stack-form"><button type="button" className="outline-button" aria-pressed={marks.favorite} disabled={busy || !marksReady} onClick={() => void mark("favorite")}>{marks.favorite ? "Remover favorita" : "Salvar favorita"}</button><button type="button" className="outline-button" aria-pressed={marks.review} disabled={busy || !marksReady} onClick={() => void mark("review")}>{marks.review ? "Retirar da revisão" : "Marcar para revisão"}</button></div></aside></div>}
    <section className="work-panel"><div className="work-panel-heading"><h2>Seu histórico de treino</h2><button className="outline-button" type="button" disabled={busy} onClick={() => void loadHistory().catch(error => setNotice(error.message))}>Atualizar histórico</button></div><div className="open-list">{history.results.map(item => <article className="open-row" key={item.attempt}><div><h3>{item.statement}</h3><p>{item.correct === null ? "Revisão pendente" : item.correct ? "Acerto" : "Revisar"} · {new Date(item.submitted_at).toLocaleString("pt-BR")}</p><details><summary>Rever explicação</summary><p className="preserve-text">{item.rationale}</p></details></div></article>)}</div>{!history.count && <p>Suas respostas confirmadas aparecerão aqui.</p>}{history.next && <button className="outline-button" type="button" onClick={() => void loadHistory(history.next!).catch(error => setNotice(error.message))}>Mais respostas</button>}</section>
  </div>;
}
