"use client";

import {useCallback, useEffect, useRef, useState} from "react";
import {studentRequest} from "@/lib/student-api";
import "./goals.css";

const metrics = {questions: "Questões respondidas", study_minutes: "Minutos de estudo registrados", simulations: "Simulados concluídos", flashcard_reviews: "Revisões de flashcards", manual: "Conclusão manual"};
type Metric = keyof typeof metrics;
type Fields = {title: string; description: string; metric: Metric; target_value: string; start_date: string; target_date: string; subject: string; priority: number; progress: number; archived: boolean};
type Goal = {id: string; account_id: string; title: string; description: string; metric: Metric; target_value: number | null; start_date: string | null; target_date: string | null; subject: string | null; subject_name: string | null; priority: number; progress: number; achieved: boolean; measured_value: number; measured_at: string; version: number; archived_at: string | null};
type Draft = {fields: Fields; goal: Goal | null; key: string};
type Page<T> = {results: T[]; next: string | null; count: number};
type Subject = {id: string; name: string};
const uuid = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(v);
const localDay = () => {const date = new Date(); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;};
const empty = (): Fields => ({title: "", description: "", metric: "questions", target_value: "20", start_date: localDay(), target_date: localDay(), subject: "", priority: 2, progress: 0, archived: false});
const fieldsOf = (g: Goal): Fields => ({title: g.title, description: g.description, metric: g.metric, target_value: g.target_value === null ? "" : String(g.target_value), start_date: g.start_date || "", target_date: g.target_date || "", subject: g.subject || "", priority: g.priority, progress: g.metric === "manual" ? g.progress : 0, archived: !!g.archived_at});
const equal = (a: Fields, b: Fields) => (Object.keys(a) as (keyof Fields)[]).every(key => a[key] === b[key]);
const storageKey = (owner: string) => `kairos_pending_goal_${owner}`;
function validGoal(g: Goal, owner: string) {
  const bounded = (value: unknown, max: number) => typeof value === "string" && value.length <= max;
  const date = (value: unknown) => value === null || (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value));
  return uuid(g.id) && g.account_id === owner && Number.isSafeInteger(g.version) && g.version >= 1 &&
    bounded(g.title, 200) && bounded(g.description, 5000) && Object.hasOwn(metrics, g.metric) &&
    (g.target_value === null ? g.metric === "manual" : Number.isInteger(g.target_value) && g.target_value >= 1 && g.target_value <= 100000) &&
    date(g.start_date) && date(g.target_date) && (g.subject === null || uuid(g.subject)) && (g.subject_name === null || bounded(g.subject_name, 255)) &&
    [1, 2, 3].includes(g.priority) && Number.isInteger(g.progress) && g.progress >= 0 && g.progress <= 100 && typeof g.achieved === "boolean" &&
    Number.isFinite(g.measured_value) && g.measured_value >= 0 && typeof g.measured_at === "string" && Number.isFinite(Date.parse(g.measured_at)) &&
    (g.archived_at === null || (typeof g.archived_at === "string" && Number.isFinite(Date.parse(g.archived_at))));
}
function recover(owner: string): Draft | null {
  try {
    const raw = sessionStorage.getItem(storageKey(owner)); if (!raw || raw.length > 50000) return null;
    const d = JSON.parse(raw) as Draft; const f = d.fields;
    if (!f || typeof f.title !== "string" || f.title.length > 200 || typeof f.description !== "string" || f.description.length > 5000 || !Object.hasOwn(metrics, f.metric) || typeof f.target_value !== "string" || f.target_value.length > 6 || ![f.start_date, f.target_date].every(v => typeof v === "string" && (!v || /^\d{4}-\d{2}-\d{2}$/.test(v))) || (f.subject !== "" && !uuid(f.subject)) || ![1, 2, 3].includes(f.priority) || !Number.isInteger(f.progress) || f.progress < 0 || f.progress > 100 || typeof f.archived !== "boolean" || !uuid(d.key)) return null;
    if (d.goal && !validGoal(d.goal, owner)) return null;
    return d;
  } catch {return null;}
}
function safePage(path: string, endpoint: string) {
  const url = new URL(path, window.location.origin);
  if (url.origin !== window.location.origin || url.pathname !== endpoint) throw Error("Página indisponível.");
  return url.pathname + url.search;
}
async function subjects() {
  const rows: Subject[] = []; const seen = new Set<string>(); let path: string | null = "/api/subjects/";
  while (path) {
    path = safePage(path, "/api/subjects/");
    if (seen.has(path) || seen.size >= 100) throw Error("Não foi possível carregar as disciplinas.");
    seen.add(path); const page: Page<Subject> = await studentRequest(path); rows.push(...page.results); path = page.next;
  }
  return rows;
}

export function GoalsWorkspace() {
  const [rows, setRows] = useState<Goal[]>([]);
  const [catalog, setCatalog] = useState<Subject[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [goal, setGoal] = useState<Goal | null>(null);
  const [fields, setFields] = useState<Fields>(empty);
  const [mode, setMode] = useState("active");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [listing, setListing] = useState(false);
  const [ready, setReady] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState<Goal | null>(null);
  const [retry, setRetry] = useState(0);
  const identity = useRef(""); const key = useRef(""); const draft = useRef<Draft | null>(null); const generation = useRef(0); const heading = useRef<HTMLHeadingElement>(null);
  function preserve(value: Draft) {
    draft.current = value;
    try {sessionStorage.setItem(storageKey(identity.current), JSON.stringify(value));}
    catch {setNotice("A recuperação temporária está indisponível. Salve na conta antes de sair.");}
  }
  function clear() {draft.current = null; try {sessionStorage.removeItem(storageKey(identity.current));} catch { /* Canonical state remains on the server. */ }}
  function install(value: Goal) {
    if (value.account_id !== identity.current) throw Error("A conta mudou. Recarregue a página.");
    setGoal(value); setFields(fieldsOf(value)); setDirty(false); setPending(false); setConflict(null); clear();
    setRows(items => items.map(item => item.id === value.id ? value : item));
  }
  const load = useCallback(async (path: string, append = false) => {
    const token = ++generation.current; setListing(true); setNext(null);
    try {
      const page = await studentRequest<Page<Goal>>(safePage(path, "/api/goals/"));
      if (token !== generation.current) return;
      if (page.results.some(value => value.account_id !== identity.current)) throw Error("A conta mudou. Recarregue a página.");
      setRows(items => append ? [...items, ...page.results.filter(row => !items.some(item => item.id === row.id))] : page.results); setNext(page.next);
    } finally {if (token === generation.current) setListing(false);}
  }, []);
  const listPath = () => "/api/goals/?" + new URLSearchParams({mode, q: query});
  useEffect(() => {
    let active = true; const requests = generation;
    void Promise.all([studentRequest<{id: string}>("/api/auth/me"), subjects()]).then(async ([user, items]) => {
      if (!active) return;
      identity.current = user.id; key.current = crypto.randomUUID(); setCatalog(items);
      const saved = recover(user.id);
      if (saved) {draft.current = saved; key.current = saved.key; setGoal(saved.goal); setFields(saved.fields); setDirty(true); setPending(true); setNotice("Rascunho recuperado. Confira o salvamento antes de continuar.");}
      setReady(true); await load("/api/goals/?mode=active");
    }).catch(error => {if (active) setNotice(error.message);});
    return () => {active = false; requests.current++;};
  }, [load, retry]);
  useEffect(() => {const guard = (event: BeforeUnloadEvent) => {if (dirty || pending) {event.preventDefault(); event.returnValue = "";}}; window.addEventListener("beforeunload", guard); return () => window.removeEventListener("beforeunload", guard);}, [dirty, pending]);
  function edit(values: Partial<Fields>) {const updated = {...fields, ...values}; setFields(updated); setDirty(true); preserve({fields: updated, goal, key: key.current});}
  function reset() {setGoal(null); setFields(empty()); setDirty(false); setPending(false); setConflict(null); clear(); key.current = crypto.randomUUID();}
  async function save(updated = fields) {
    if (busy || pending || !identity.current) return;
    setBusy(true); setPending(true); setFields(updated); preserve({fields: updated, goal, key: key.current}); setNotice("");
    const body = {title: updated.title.trim(), description: updated.description.trim(), metric: updated.metric, target_value: updated.metric === "manual" ? null : Number(updated.target_value), start_date: updated.metric === "manual" ? null : updated.start_date, target_date: updated.target_date || null, subject: updated.subject || null, priority: updated.priority,
      ...(updated.metric === "manual" ? {progress: updated.progress} : {}), expected_owner: identity.current, ...(goal ? {expected_version: goal.version, archived: updated.archived} : {creation_key: key.current})};
    // Reconciliation compares exactly the normalized request fields after an uncertain response.
    const normalized = {...updated, title: body.title, description: body.description, target_value: body.target_value === null ? "" : String(body.target_value), start_date: body.start_date || "", target_date: body.target_date || "", subject: body.subject || ""}; preserve({fields: normalized, goal, key: key.current}); setFields(normalized);
    try {const value = await studentRequest<Goal>(goal ? `/api/goals/${goal.id}/` : "/api/goals/", {method: goal ? "PATCH" : "POST", body: JSON.stringify(body)}); install(value); setNotice("Meta salva na sua conta."); await load(listPath());}
    catch (error) {setNotice((error as Error).message + " Confira o salvamento antes de repetir.");}
    finally {setBusy(false);}
  }
  async function current(value: Draft) {
    const row = value.goal ? await studentRequest<Goal>(`/api/goals/${value.goal.id}/`) : (await studentRequest<Page<Goal>>(`/api/goals/?mode=all&creation_key=${value.key}`)).results[0];
    if (row && row.account_id !== identity.current) throw Error("A conta mudou. Recarregue a página.");
    return row;
  }
  async function reconcile() {
    if (busy || !draft.current) return;
    setBusy(true);
    try {
      const value = draft.current; const row = await current(value);
      if (row && equal(fieldsOf(row), value.fields)) {install(row); setNotice("Salvamento confirmado no servidor.");}
      else if (row && (!value.goal || row.version !== value.goal.version)) {setConflict(row); setNotice("A versão salva mudou. Compare antes de continuar; seu rascunho foi preservado.");}
      else {setPending(false); setNotice("Rascunho ainda não confirmado. Confira os campos e salve quando desejar.");}
      await load(listPath());
    } catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }
  async function discard() {
    if (busy) return;
    setBusy(true);
    try {const row = draft.current ? await current(draft.current) : goal ? await studentRequest<Goal>(`/api/goals/${goal.id}/`) : null; if (row) install(row); else reset(); setNotice("Versão salva conferida. O rascunho local foi descartado."); await load(listPath());}
    catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }
  async function open(row: Goal) {
    if (busy || dirty || pending) return;
    setBusy(true);
    try {install(await studentRequest<Goal>(`/api/goals/${row.id}/`)); setNotice(""); heading.current?.focus();}
    catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }
  if (!ready) return <section className="work-panel"><p role="status">{notice || "Carregando suas metas…"}</p>{notice && <button type="button" className="outline-button" onClick={() => setRetry(v => v + 1)}>Tentar novamente</button>}</section>;
  return <div className="goals-workspace">
    <section className="work-panel"><h2>Suas metas</h2><p>Atividades confirmadas na conta alimentam o progresso. Você escolhe a quantidade e o prazo.</p>
      <form className="stack-form" onSubmit={event => {event.preventDefault(); void load(listPath()).catch(error => setNotice(error.message));}}>
        <div><label htmlFor="goals-mode">Exibir metas</label><select id="goals-mode" value={mode} disabled={listing || dirty || pending} onChange={event => setMode(event.target.value)}><option value="active">Todas as ativas</option><option value="incomplete">Em andamento</option><option value="achieved">Atingidas</option><option value="archived">Arquivadas</option></select></div>
        <div><label htmlFor="goals-search">Buscar metas</label><input id="goals-search" value={query} maxLength={150} onChange={event => setQuery(event.target.value)}/></div><button type="submit" className="outline-button" disabled={listing || dirty || pending}>Atualizar metas</button>
      </form><button type="button" className="primary-button" disabled={busy || dirty || pending} onClick={() => {reset(); heading.current?.focus();}}>Nova meta</button>
      <div className="goal-list">{rows.map(row => <button type="button" className="goal-row" key={row.id} disabled={busy || dirty || pending} onClick={() => void open(row)}><strong>{row.title}</strong><span>{row.archived_at ? "Arquivada" : row.achieved ? "Atingida" : "Em andamento"} · {row.progress}%</span><span>{row.subject_name || metrics[row.metric]}</span></button>)}</div>
      {!rows.length && !listing && <p>Nenhuma meta neste filtro.</p>}{next && <button type="button" className="outline-button" disabled={listing || dirty || pending} onClick={() => void load(next, true).catch(error => setNotice(error.message))}>Mais metas</button>}
    </section>
    <section className="work-panel"><h2 ref={heading} tabIndex={-1}>{goal ? "Editar meta" : "Planejar uma meta"}</h2>
      {goal && <div className="goal-measurement" aria-label="Progresso confirmado"><strong>{goal.progress}% {goal.achieved ? "· Meta atingida" : "· Em andamento"}</strong><progress max={100} value={goal.progress} aria-label="Progresso da meta"/>{goal.metric !== "manual" && <><p>{goal.measured_value.toLocaleString("pt-BR", {maximumFractionDigits: 2})} de {goal.target_value} · {metrics[goal.metric]}</p><p>Medição consultada em {new Date(goal.measured_at).toLocaleString("pt-BR")}. Atividades no período, incluindo os dias de início e fim.</p></>}{goal.archived_at && <p>Meta arquivada. Os registros de estudo continuam preservados.</p>}</div>}
      <form className="stack-form" onSubmit={event => {event.preventDefault(); void save();}}>
        <fieldset disabled={busy || pending}><legend>Objetivo e prazo</legend>
          <div><label htmlFor="goal-title">O que você quer alcançar?</label><input id="goal-title" required maxLength={200} value={fields.title} onChange={event => edit({title: event.target.value})}/></div>
          <div><label htmlFor="goal-description">Detalhes do plano</label><textarea id="goal-description" maxLength={5000} value={fields.description} onChange={event => edit({description: event.target.value})}/></div>
          <div><label htmlFor="goal-metric">O que acompanhar?</label><select id="goal-metric" value={fields.metric} disabled={!!goal} onChange={event => {const metric = event.target.value as Metric; edit({metric, subject: "", progress: 0, target_value: metric === "manual" ? "" : "20", start_date: metric === "manual" ? "" : localDay()});}}>{Object.entries(metrics).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
          {fields.metric !== "manual" ? <><div><label htmlFor="goal-quantity">Quantidade desejada</label><input id="goal-quantity" type="number" min={1} max={100000} step={1} required value={fields.target_value} onChange={event => edit({target_value: event.target.value})}/></div><div><label htmlFor="goal-start">Contar a partir de</label><input id="goal-start" type="date" required value={fields.start_date} onChange={event => edit({start_date: event.target.value})}/></div></> : <div><label htmlFor="goal-progress">Progresso informado por você (%)</label><input id="goal-progress" type="number" min={0} max={100} step={1} required value={fields.progress} onChange={event => edit({progress: Number(event.target.value)})}/></div>}
          <div><label htmlFor="goal-deadline">Prazo</label><input id="goal-deadline" type="date" required={fields.metric !== "manual"} min={fields.start_date || undefined} value={fields.target_date} onChange={event => edit({target_date: event.target.value})}/></div>
          {fields.metric === "questions" && <div><label htmlFor="goal-subject">Disciplina prioritária</label><select id="goal-subject" value={fields.subject} onChange={event => edit({subject: event.target.value})}><option value="">Todas as disciplinas</option>{catalog.map(subject => <option key={subject.id} value={subject.id}>{subject.name}</option>)}</select></div>}
          <div><label htmlFor="goal-priority">Prioridade</label><select id="goal-priority" value={fields.priority} onChange={event => edit({priority: Number(event.target.value)})}><option value={1}>Alta</option><option value={2}>Normal</option><option value={3}>Baixa</option></select></div>
        </fieldset>
        <p>{fields.metric === "study_minutes" ? "O tempo é o registrado nas atividades da conta; não comprova tempo efetivamente estudado." : fields.metric === "simulations" ? "Contamos simulados objetivos concluídos e provas formais da 2ª fase enviadas. Questões avulsas e treinos escritos não entram nesta meta." : fields.metric === "questions" ? "Contamos respostas em tentativas concluídas, pela classificação atual da disciplina. Tentativas abertas não entram na medição." : fields.metric === "flashcard_reviews" ? "Cada revisão confirmada de um cartão pessoal conta uma vez. Não é uma certificação de domínio jurídico." : "Você informa a porcentagem desta meta. As metas anteriores continuam neste formato."}</p>
        <button type="submit" className="primary-button" disabled={busy || pending || !fields.title.trim()}>Salvar meta</button>
      </form>
      <div className="button-row">{(dirty || pending) && <button type="button" className="outline-button" disabled={busy} onClick={() => void discard()}>Descartar rascunho e abrir versão salva</button>}{pending && <button type="button" className="primary-button" disabled={busy} onClick={() => void reconcile()}>Conferir salvamento da meta</button>}{goal && !dirty && !pending && <button type="button" className="outline-button" disabled={busy} onClick={() => void save({...fields, archived: !fields.archived})}>{goal.archived_at ? "Reativar meta" : "Arquivar meta"}</button>}</div>
      {conflict && <section className="goal-conflict" aria-label="Comparar meta salva"><h3>Versão que está salva na conta</h3><p>{conflict.title}</p><p>{conflict.description}</p><p>{metrics[conflict.metric]} · Quantidade: {conflict.target_value ?? "Manual"} · Início: {conflict.start_date || "Sem início"} · Prazo: {conflict.target_date || "Sem prazo"} · Prioridade: {({1: "Alta", 2: "Normal", 3: "Baixa"} as Record<number, string>)[conflict.priority]} · {conflict.subject_name || "Todas as disciplinas"} · {conflict.progress}% · {conflict.archived_at ? "Arquivada" : "Ativa"}</p><p>Compare os campos antes de salvar novamente.</p><button type="button" className="outline-button" disabled={busy} onClick={() => {setGoal(conflict); setConflict(null); setPending(false); setDirty(true); preserve({fields, goal: conflict, key: key.current}); setNotice("Seu rascunho foi mantido. Confira e salve uma nova versão quando desejar.");}}>Manter meu plano em edição</button></section>}
      <p role="status" className="form-notice">{notice}</p>
    </section>
  </div>;
}
