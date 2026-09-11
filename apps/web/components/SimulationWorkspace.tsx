"use client";

import {useCallback, useEffect, useRef, useState} from "react";
import {StudentApiError, studentRequest} from "@/lib/student-api";

type Question = {question: string; statement: string; alternatives: {id: string; label: string; text: string}[]};
type Attempt = {id: string; title: string; mode: string; status: string; started_at: string; submitted_at: string | null; duration_minutes: number; elapsed_seconds: number; version: number; questions: Question[]; answers: {question: string; selected_alternative: string | null; marked_for_review: boolean}[]};
type ResultItem = {question: string; selected_alternative: string | null; correct_alternative: string | null; correct: boolean | null; rationale: string; subject_name: string; topic_name: string};
type Result = {correct: number; total: number; unscored: number; questions: ResultItem[]};
type Catalog = {id: string; title: string; edition: string; available: number; duration_minutes: number};
type Answer = {selected_alternative: string | null; marked_for_review: boolean};
type Answers = Record<string, Answer>;
type Cache = {version: number; answers: Answers};

const answersOf = (attempt: Attempt): Answers => Object.fromEntries(attempt.answers.map(answer => [answer.question, {selected_alternative: answer.selected_alternative, marked_for_review: answer.marked_for_review ?? false}]));
const sameAnswers = (left: Answers, right: Answers) => [...new Set([...Object.keys(left), ...Object.keys(right)])].every(key => (left[key]?.selected_alternative ?? null) === (right[key]?.selected_alternative ?? null) && (left[key]?.marked_for_review ?? false) === (right[key]?.marked_for_review ?? false));
const cacheKey = (id: string) => `kairos_pending_exam_${id}`;

function clearPending(id: string) {try {sessionStorage.removeItem(cacheKey(id));} catch { /* Server confirmation is authoritative even when browser storage is unavailable. */ }}

function safeNext(next: string, path: string) {
  const url = new URL(next, window.location.origin);
  if (url.origin !== window.location.origin || url.pathname !== path) throw new Error("Página de histórico indisponível.");
  return url.pathname + url.search;
}

function cachedStart(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.request_id === "string" && /^[0-9a-f-]{36}$/i.test(item.request_id) && typeof item.exam_phase === "string" &&
    typeof item.title === "string" && item.title.length <= 255 && ["formal", "training"].includes(String(item.mode)) &&
    Number.isInteger(item.quantity) && Number(item.quantity) >= 1 && Number(item.quantity) <= 200 &&
    Number.isInteger(item.duration_minutes) && Number(item.duration_minutes) >= 1 && Number(item.duration_minutes) <= 1440;
}

async function readResult(id: string) {
  const result = await studentRequest<Result>(`/api/attempts/${id}/results/`);
  if (!Array.isArray(result.questions)) throw new Error("Esta tentativa antiga não possui resultado congelado verificável.");
  return result;
}

function validCache(value: unknown, attempt: Attempt): value is Cache {
  if (!value || typeof value !== "object" || !("version" in value) || !("answers" in value) || !Number.isInteger(value.version) || !value.answers || typeof value.answers !== "object") return false;
  return Object.entries(value.answers).length <= 200 && Object.entries(value.answers).every(([id, answer]) => answer && typeof answer === "object" && typeof answer.marked_for_review === "boolean" && attempt.questions.some(question => question.question === id && (answer.selected_alternative === null || question.alternatives.some(item => item.id === answer.selected_alternative))));
}

export function SimulationWorkspace() {
  const [catalog, setCatalog] = useState<Catalog[]>([]);
  const [subjectOptions, setSubjectOptions] = useState<{id: string; name: string}[]>([]);
  const [subjectNext, setSubjectNext] = useState<string | null>(null);
  const [history, setHistory] = useState<Attempt[]>([]);
  const [historyNext, setHistoryNext] = useState<string | null>(null);
  const historyGeneration = useRef(0);
  const preparationKey = useRef<string | null>(null);
  const [identityReady, setIdentityReady] = useState(false);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const current = useRef<Attempt | null>(null);
  const [draft, setDraft] = useState<Answers>({});
  const draftRef = useRef<Answers>({});
  const [questionIndex, setQuestionIndex] = useState(0);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [conflict, setConflict] = useState<Attempt | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [now, setNow] = useState(0);
  const [dirty, setDirty] = useState(false);
  const savingRef = useRef<Promise<boolean> | null>(null);
  const conflictRef = useRef(false);
  const pendingStart = useRef<Record<string, unknown> | null>(null);
  const [uncertainStart, setUncertainStart] = useState(false);
  const [phase, setPhase] = useState("");
  const resultHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {if (result) resultHeading.current?.focus();}, [result]);

  function storePending(record: Attempt, values: Answers) {
    try {sessionStorage.setItem(cacheKey(record.id), JSON.stringify({version: record.version, answers: values}));}
    catch {setNotice("O navegador não permite cópia temporária. Aguarde a confirmação do salvamento antes de sair.");}
  }

  function install(record: Attempt) {current.current = record; setAttempt(record);}

  const loadHistory = useCallback(async (next?: string) => {
    const generation = ++historyGeneration.current;
    const data = await studentRequest<{results: Attempt[]; next: string | null}>(next ? safeNext(next, "/api/attempts/") : "/api/attempts/?purpose=simulation");
    if (generation !== historyGeneration.current) return;
    setHistory(items => next ? [...items, ...data.results.filter(row => !items.some(item => item.id === row.id))] : data.results);
    setHistoryNext(data.next);
  }, []);

  async function openAttempt(id: string) {
    if (savingRef.current || dirty) {setNotice("Salve suas respostas antes de abrir outra tentativa."); return;}
    setBusy(true); setNotice(""); setResult(null); setConfirm(false); setConflict(null); setSaveFailed(false); conflictRef.current = false;
    try {
      const record = await studentRequest<Attempt>(`/api/attempts/${encodeURIComponent(id)}/`);
      install(record); setQuestionIndex(0); setNow(Date.now());
      let values = answersOf(record);
      if (record.status === "active") {
        let cached: unknown;
        try {cached = JSON.parse(sessionStorage.getItem(cacheKey(id)) ?? "null");} catch {cached = null;}
        if (validCache(cached, record) && !sameAnswers(cached.answers, values)) {
          values = cached.answers;
          if (cached.version !== record.version) {setConflict(record); conflictRef.current = true; setNotice("Há respostas temporárias diferentes das salvas no servidor. Escolha qual versão manter.");}
          else setNotice("Respostas temporárias recuperadas; aguardando confirmação do servidor.");
        } else clearPending(id);
      } else {
        clearPending(id);
        setResult(await readResult(id));
      }
      draftRef.current = values; setDraft(values); setDirty(!sameAnswers(values, answersOf(record)));
      window.history.replaceState(null, "", `/app/simulados?tentativa=${record.id}`);
    } catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      const results = await Promise.allSettled([
        studentRequest<{results: Catalog[]}>("/api/simulation-catalog/"),
        studentRequest<{id: string}>("/api/auth/me"), loadHistory(),
        studentRequest<{results: {id: string; name: string}[]; next: string | null}>("/api/subjects/"),
      ]);
      if (!active) return;
      const [catalogResult, identity] = results;
      if (catalogResult.status === "fulfilled") {setCatalog(catalogResult.value.results); setPhase(catalogResult.value.results[0]?.id ?? "");}
      if (identity.status === "fulfilled") {
        preparationKey.current = `kairos_pending_preparation_${identity.value.id}`;
        setIdentityReady(true);
        try {
          const raw = sessionStorage.getItem(preparationKey.current);
          const pending: unknown = raw && raw.length < 10000 ? JSON.parse(raw) : null;
          if (cachedStart(pending)) {pendingStart.current = pending; setUncertainStart(true); setNotice("Há uma preparação sem confirmação. Use Confirmar preparação anterior para recuperar o mesmo envio.");}
        } catch { /* Without cache, the owned history remains available. */ }
      }
      const disciplines = results[3];
      if (disciplines.status === "fulfilled") {setSubjectOptions(disciplines.value.results); setSubjectNext(disciplines.value.next);}
      for (const result of results) if (result.status === "rejected") setNotice((result.reason as Error).message);
      const id = new URLSearchParams(window.location.search).get("tentativa");
      if (id && /^[0-9a-f-]{36}$/i.test(id)) await openAttempt(id);
    });
    return () => {active = false; historyGeneration.current += 1;};
    // The initial URL is restored once; subsequent navigation is an explicit command.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadHistory]);

  useEffect(() => {
    if (!attempt || attempt.status !== "active") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [attempt]);

  const save = useCallback(async (): Promise<boolean> => {
    if (savingRef.current) return savingRef.current;
    const record = current.current;
    if (!record || record.status !== "active" || conflictRef.current) return false;
    const values = {...draftRef.current};
    if (sameAnswers(values, answersOf(record))) return true;
    setSaving(true);
    setSaveFailed(false);
    const task = (async () => {
      try {
        const elapsed = Math.min(record.duration_minutes * 60, Math.max(record.elapsed_seconds, Math.floor((Date.now() - Date.parse(record.started_at)) / 1000)));
        const saved = await studentRequest<Attempt>(`/api/attempts/${record.id}/autosave/`, {method: "POST", body: JSON.stringify({version: record.version,
          elapsed_seconds: elapsed, answers: record.questions.map(question => ({question: question.question, ...(values[question.question] ?? {selected_alternative: null, marked_for_review: false})}))})});
        install(saved);
        const unsaved = !sameAnswers(draftRef.current, answersOf(saved));
        setDirty(unsaved);
        if (unsaved) storePending(saved, draftRef.current); else clearPending(record.id);
        setNotice("Respostas salvas na sua conta.");
        return !unsaved;
      } catch (error) {
        setSaveFailed(true);
        if (error instanceof StudentApiError && error.status === 409) {
          try {
            const latest = await studentRequest<Attempt>(`/api/attempts/${record.id}/`);
            if (sameAnswers(values, answersOf(latest))) {
              install(latest); const unsaved = !sameAnswers(draftRef.current, answersOf(latest)); setDirty(unsaved);
              if (unsaved) storePending(latest, draftRef.current); else clearPending(record.id);
              setSaveFailed(false);
              setNotice("Salvamento anterior confirmado no servidor."); return !unsaved;
            }
            setConflict(latest); conflictRef.current = true;
            setNotice("O servidor possui outra versão ou o prazo terminou. Suas respostas temporárias foram preservadas.");
          } catch {setNotice("Não foi possível conferir a versão do servidor. Suas respostas temporárias foram preservadas.");}
        } else setNotice("Salvamento não confirmado. Mantenha esta página aberta e use Salvar agora para tentar novamente.");
        return false;
      } finally {setSaving(false); savingRef.current = null;}
    })();
    savingRef.current = task;
    return task;
  }, []);

  useEffect(() => {
    if (!dirty || conflict || saving || busy || saveFailed) return;
    const timer = window.setTimeout(() => {void save();}, 650);
    return () => window.clearTimeout(timer);
  }, [draft, dirty, conflict, saving, busy, saveFailed, save]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {event.preventDefault();};
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function start(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || dirty || !identityReady) return;
    const form = new FormData(event.currentTarget);
    pendingStart.current ??= {exam_phase: form.get("exam_phase"), title: form.get("title"), quantity: Number(form.get("quantity")),
      duration_minutes: Number(form.get("duration_minutes")), difficulty: form.get("difficulty"), subjects: form.getAll("subjects"), randomize: form.get("randomize") === "on", mode: form.get("mode"), request_id: crypto.randomUUID()};
    setBusy(true); setNotice("");
    try {if (preparationKey.current) sessionStorage.setItem(preparationKey.current, JSON.stringify(pendingStart.current));}
    catch {setNotice("A cópia temporária não está disponível. Em caso de falha, confira Seus simulados antes de iniciar outro envio.");}
    try {
      const record = await studentRequest<Attempt>("/api/simulation-start/", {method: "POST", body: JSON.stringify(pendingStart.current)});
      pendingStart.current = null; setUncertainStart(false); install(record); const values = answersOf(record); setDraft(values); draftRef.current = values; setDirty(false); setNow(Date.now());
      try {if (preparationKey.current) sessionStorage.removeItem(preparationKey.current);} catch { /* Replay remains idempotent if cache removal is unavailable. */ }
      setQuestionIndex(0); setResult(null); setConflict(null); setSaveFailed(false); conflictRef.current = false;
      window.history.replaceState(null, "", `/app/simulados?tentativa=${record.id}`);
      if (record.status !== "active") setResult(await readResult(record.id));
      await loadHistory();
    } catch (error) {
      if (error instanceof StudentApiError && error.status < 500) {
        pendingStart.current = null;
        try {if (preparationKey.current) sessionStorage.removeItem(preparationKey.current);} catch { /* Retry after reload revalidates the server command. */ }
      }
      setUncertainStart(pendingStart.current !== null); setNotice((error as Error).message);
    } finally {setBusy(false);}
  }

  async function submit() {
    if (!attempt || busy) return;
    setBusy(true);
    try {
      if (dirty && !await save()) return;
      const submitted = await studentRequest<Attempt>(`/api/attempts/${attempt.id}/submit/`, {method: "POST"});
      install(submitted); setDirty(false); setConfirm(false); clearPending(attempt.id);
      setResult(await readResult(attempt.id));
      setNotice("Simulado finalizado. As respostas enviadas não podem mais ser alteradas."); await loadHistory();
    } catch (error) {setNotice((error as Error).message + (current.current?.status === "active" ? " Você pode repetir a finalização para confirmar o mesmo envio." : " O envio foi registrado; use Ver resultado para carregar a correção novamente."));}
    finally {setBusy(false);}
  }

  function resolveConflict(useLocal: boolean) {
    if (!conflict || saving || busy) return;
    install(conflict);
    if (!useLocal) {const values = answersOf(conflict); draftRef.current = values; setDraft(values); setDirty(false); clearPending(conflict.id);}
    else storePending(conflict, draftRef.current);
    conflictRef.current = false; setConflict(null); setSaveFailed(false); setNotice(useLocal ? "Suas respostas serão reenviadas com a versão atual." : "Respostas do servidor carregadas.");
  }

  const duration = (attempt?.duration_minutes ?? 0) * 60;
  const elapsed = attempt ? Math.max(attempt.elapsed_seconds, Math.floor((now - Date.parse(attempt.started_at)) / 1000)) : 0;
  const remaining = Math.max(0, duration - elapsed);
  const expired = attempt?.mode === "formal" && remaining === 0;
  const question = attempt?.questions[questionIndex];
  const answered = Object.values(draft).filter(item => item.selected_alternative).length;
  const active = attempt?.status === "active";
  const subjects = result?.questions.reduce<Record<string, {total: number; correct: number}>>((groups, item) => {
    const key = item.subject_name || "Sem disciplina informada"; groups[key] ??= {total: 0, correct: 0}; groups[key].total += 1; groups[key].correct += Number(item.correct === true); return groups;
  }, {});

  return <div className="simulation-workspace">
    <p className="form-notice" role="status">{notice}</p>
    {!attempt && <section className="work-panel"><h2>Preparar simulado de 1ª fase</h2><form onSubmit={start}><fieldset disabled={busy || uncertainStart} className="practice-filters">
      <legend className="visually-hidden">Configuração do simulado</legend><label>Prova ou caderno<select name="exam_phase" required value={phase} onChange={event => setPhase(event.target.value)}>{catalog.map(item => <option key={item.id} value={item.id}>{item.title} · {item.edition} · {item.available} questões</option>)}</select></label>
      <label>Nome do simulado<input name="title" defaultValue="Meu simulado" maxLength={255} required/></label><label>Quantidade<input name="quantity" type="number" defaultValue={1} min={1} max={200} required/></label><label>Duração em minutos<input name="duration_minutes" type="number" defaultValue={60} min={1} max={1440} required/></label>
      <label>Disciplinas (opcional)<select name="subjects" multiple size={4}>{subjectOptions.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><small>Sem seleção: todas as disciplinas do caderno.</small></label>
      {subjectNext && <button type="button" className="outline-button" onClick={() => {
        void studentRequest<{results: {id: string; name: string}[]; next: string | null}>(safeNext(subjectNext, "/api/subjects/")).then(data => {
          setSubjectOptions(items => [...items, ...data.results.filter(row => !items.some(item => item.id === row.id))]); setSubjectNext(data.next);
        }).catch(error => setNotice(error.message));
      }}>Mais disciplinas</button>}
      <label>Dificuldade<select name="difficulty"><option value="">Todas</option><option value="easy">Fácil</option><option value="medium">Intermediária</option><option value="hard">Difícil</option></select></label><label>Modo<select name="mode"><option value="formal">Simulado formal</option><option value="training">Treino com tempo livre</option></select></label><label className="check-label"><input type="checkbox" name="randomize" defaultChecked/>Embaralhar questões</label>
    </fieldset><button className="primary-button" type="submit" disabled={busy || !identityReady || (!catalog.length && !uncertainStart)}>{uncertainStart ? "Confirmar preparação anterior" : "Iniciar simulado"}</button>{!catalog.length && <p>Publique questões revisadas para disponibilizar uma prova ou caderno.</p>}</form></section>}
    {attempt && <section className="work-panel"><div className="work-panel-heading"><h2>{attempt.title}</h2><span>{active ? `${answered}/${attempt.questions.length} respondidas` : "Finalizado"}</span></div>
      {active && <><p className="exam-clock" aria-label="Tempo restante">{String(Math.floor(remaining / 3600)).padStart(2, "0")}:{String(Math.floor(remaining / 60) % 60).padStart(2, "0")}:{String(remaining % 60).padStart(2, "0")}</p><p>{saving ? "Salvando…" : dirty ? "Há respostas aguardando salvamento" : "Todas as respostas confirmadas no servidor"}</p>{expired && <p role="alert">Tempo encerrado. Finalize com as respostas confirmadas no servidor.</p>}
      {conflict && <section className="practice-result" role="alert"><h3>Confira as versões antes de continuar</h3><p>Servidor: {conflict.answers.filter(item => item.selected_alternative).length} respostas. Nesta página: {answered} respostas.</p><button type="button" className="outline-button" onClick={() => resolveConflict(false)}>Usar respostas do servidor</button><button type="button" className="outline-button" disabled={expired || conflict.status !== "active"} onClick={() => resolveConflict(true)}>Manter minhas respostas</button></section>}
      <nav className="exam-navigation" aria-label="Questões do simulado">{attempt.questions.map((item, index) => <button type="button" key={item.question} aria-current={index === questionIndex ? "step" : undefined} aria-label={`Questão ${index + 1}, ${draft[item.question]?.selected_alternative ? "respondida" : "não respondida"}`} onClick={() => setQuestionIndex(index)}>{index + 1}{draft[item.question]?.selected_alternative && " ✓"}{draft[item.question]?.marked_for_review && " ◇"}</button>)}</nav>
      {question && <fieldset className="practice-answers" disabled={busy || expired || !!conflict}><legend>Questão {questionIndex + 1}</legend><h3 className="preserve-text">{question.statement}</h3><div className="alternatives">{question.alternatives.map(item => <label className={draft[question.question]?.selected_alternative === item.id ? "alternative selected" : "alternative"} key={item.id}><input type="radio" name="exam-answer" checked={draft[question.question]?.selected_alternative === item.id} onChange={() => {
        const values = {...draftRef.current, [question.question]: {selected_alternative: item.id, marked_for_review: draftRef.current[question.question]?.marked_for_review ?? false}}; draftRef.current = values; setDraft(values); setDirty(!sameAnswers(values, answersOf(attempt))); storePending(attempt, values);
      }}/><span>{item.label}</span><span className="alternative-text">{item.text}</span></label>)}</div></fieldset>}
      {question && <button className="outline-button" type="button" disabled={busy || expired || !!conflict} aria-pressed={draft[question.question]?.marked_for_review ?? false} onClick={() => {
        const previous = draftRef.current[question.question] ?? {selected_alternative: null, marked_for_review: false};
        const values = {...draftRef.current, [question.question]: {...previous, marked_for_review: !previous.marked_for_review}};
        draftRef.current = values; setDraft(values); setDirty(!sameAnswers(values, answersOf(attempt))); storePending(attempt, values);
      }}>{draft[question.question]?.marked_for_review ? "Retirar marca de revisão" : "Revisar esta questão antes de enviar"}</button>}
      <div className="question-actions"><button className="secondary-button" type="button" disabled={busy || saving || !!conflict || !dirty} onClick={() => void save()}>Salvar agora</button><button className="primary-button" type="button" disabled={busy || saving || !!conflict} onClick={() => setConfirm(true)}>Finalizar simulado</button></div>
      {confirm && <section className="practice-result"><h3>Confirmar envio final</h3><p>Você respondeu {answered} de {attempt.questions.length} questões. Após o envio, as respostas ficam imutáveis.</p><button className="primary-button" type="button" disabled={busy || saving} onClick={() => void submit()}>Confirmar finalização</button><button className="outline-button" type="button" disabled={busy} onClick={() => setConfirm(false)}>Continuar respondendo</button></section>}</>}
      {result && <section className="practice-result"><h3 ref={resultHeading} tabIndex={-1}>Resultado do simulado</h3><p className="exam-score">{result.correct} de {result.total} acertos</p><p>{result.unscored ? `${result.unscored} questões aguardam pontuação verificável.` : "Pontuação calculada pelo servidor com o gabarito congelado no início."}</p><ul>{Object.entries(subjects ?? {}).map(([name, score]) => <li key={name}>{name}: {score.correct}/{score.total}</li>)}</ul>{result.questions.map((item, index) => <details key={item.question}><summary>Questão {index + 1}: {item.correct === null ? "Revisão pendente" : item.correct ? "Acerto" : "Revisar"}</summary><p className="preserve-text">{attempt.questions.find(row => row.question === item.question)?.statement}</p><p>Gabarito: {attempt.questions.find(row => row.question === item.question)?.alternatives.find(row => row.id === item.correct_alternative)?.label ?? "Indisponível"}</p><p className="preserve-text">{item.rationale}</p></details>)}</section>}
    </section>}
    {attempt && !active && <button className="primary-button" type="button" disabled={busy} onClick={() => {
      current.current = null; setAttempt(null); setResult(null); setDraft({}); draftRef.current = {}; setDirty(false);
      pendingStart.current = null; setUncertainStart(false); setNotice("");
      try {if (preparationKey.current) sessionStorage.removeItem(preparationKey.current);} catch { /* The next explicit start replaces the prior envelope. */ }
      window.history.replaceState(null, "", "/app/simulados");
    }}>Preparar outro simulado</button>}
    <section className="work-panel"><h2>Seus simulados</h2><button type="button" className="outline-button" disabled={busy} onClick={() => void loadHistory().catch(error => setNotice(error.message))}>Atualizar simulados</button><div className="open-list">{history.map(item => <article className="open-row" key={item.id}><div><h3>{item.title}</h3><p>{item.status === "active" ? "Em andamento" : "Finalizado"} · {new Date(item.started_at).toLocaleString("pt-BR")}</p></div><button type="button" className="outline-button" disabled={busy || dirty || saving} onClick={() => void openAttempt(item.id)}>{item.status === "active" ? "Retomar" : "Ver resultado"}</button></article>)}</div>{historyNext && <button type="button" className="outline-button" disabled={busy} onClick={() => void loadHistory(historyNext).catch(error => setNotice(error.message))}>Simulados anteriores</button>}</section>
  </div>;
}
