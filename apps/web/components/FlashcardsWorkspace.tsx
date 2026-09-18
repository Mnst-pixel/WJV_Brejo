"use client";

import {useCallback, useEffect, useRef, useState} from "react";
import {studentRequest} from "@/lib/student-api";
import "./flashcards.css";

type Fields = {front: string; back: string; source_reference: string; subject: string | null; topic: string | null};
type Card = Fields & {id: string; account_id: string; version: number; subject_name: string | null; next_review_at: string | null; archived_at: string | null};
type Review = {id: string; account_id: string; rating: number; reviewed_at: string; next_review_at: string; snapshot: {front?: string; back?: string; schedule?: string}};
type Command = {rating: number; expected_version: number; expected_owner: string; idempotency_key: string};
type Draft = {fields: Fields; card: Card | null; creation_key: string; pending: boolean; review: Command | null};
type Page<T> = {results: T[]; next: string | null; count: number};
type Subject = {id: string; name: string; topics: {id: string; name: string}[]};
const empty: Fields = {front: "", back: "", source_reference: "", subject: null, topic: null};
const fieldsOf = (card: Fields): Fields => ({front: card.front, back: card.back, source_reference: card.source_reference, subject: card.subject, topic: card.topic});
const equal = (a: Fields, b: Fields) => (Object.keys(empty) as (keyof Fields)[]).every(key => a[key] === b[key]);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const date = (value: string) => new Date(value).toLocaleString("pt-BR");
const storageKey = (account: string) => `kairos_pending_flashcard_${account}`;
const ratings = ["Não lembrei · 10 min", "Difícil · 1 dia", "Razoável · 3 dias", "Bem · 7 dias", "Com segurança · 14 dias"];

function recover(account: string): Draft | null {
  try {
    const raw = sessionStorage.getItem(storageKey(account)); if (!raw || raw.length > 200000) return null;
    const value = JSON.parse(raw) as Draft;
    const valid = (fields: Fields) => fields && typeof fields.front === "string" && fields.front.length <= 10000 && typeof fields.back === "string" && fields.back.length <= 20000 && typeof fields.source_reference === "string" && fields.source_reference.length <= 2000 && [fields.subject, fields.topic].every(id => id === null || uuid(id));
    if (!value || !valid(value.fields) || !uuid(value.creation_key) || typeof value.pending !== "boolean") return null;
    if (value.card && (!valid(value.card) || !uuid(value.card.id) || value.card.account_id !== account || !Number.isSafeInteger(value.card.version) || value.card.version < 1)) return null;
    if (value.review && (!value.card || !uuid(value.review.idempotency_key) || value.review.expected_owner !== account || value.review.expected_version !== value.card.version || !Number.isInteger(value.review.rating) || value.review.rating < 1 || value.review.rating > 5)) return null;
    return value;
  } catch {return null;}
}

function safePage(path: string, endpoint: string) {
  const url = new URL(path, window.location.origin);
  if (url.origin !== window.location.origin || url.pathname !== endpoint) throw Error("Página indisponível.");
  return url.pathname + url.search;
}

async function catalog() {
  const all: Subject[] = []; const seen = new Set<string>(); let path: string | null = "/api/subjects/";
  while (path) {
    path = safePage(path, "/api/subjects/");
    if (seen.has(path) || seen.size >= 100) throw Error("Não foi possível carregar as disciplinas.");
    seen.add(path);
    const page: Page<Subject> = await studentRequest(path); all.push(...page.results); path = page.next;
  }
  return all;
}

export function FlashcardsWorkspace({onDirty}: {onDirty: (value: boolean) => void}) {
  const [cards, setCards] = useState<Card[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [mode, setMode] = useState("due");
  const [query, setQuery] = useState("");
  const [card, setCard] = useState<Card | null>(null);
  const [fields, setFields] = useState<Fields>(empty);
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [listing, setListing] = useState(false);
  const [ready, setReady] = useState(false);
  const [retry, setRetry] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [editing, setEditing] = useState(true);
  const [notice, setNotice] = useState("");
  const [history, setHistory] = useState<Review[]>([]);
  const [historyNext, setHistoryNext] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Card | null>(null);
  const identity = useRef<string | null>(null);
  const creation = useRef("");
  const snapshot = useRef<Draft | null>(null);
  const generation = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);

  function preserve(value: Draft) {
    snapshot.current = value;
    if (identity.current) try {sessionStorage.setItem(storageKey(identity.current), JSON.stringify(value));}
    catch {setNotice("A recuperação temporária não está disponível. Salve no servidor antes de sair.");}
  }
  function clear() {
    snapshot.current = null;
    if (identity.current) try {sessionStorage.removeItem(storageKey(identity.current));} catch { /* Server remains canonical. */ }
  }
  function install(value: Card) {
    if (value.account_id !== identity.current) throw Error("A conta mudou. Recarregue a página.");
    setCard(value); setFields(fieldsOf(value)); setDirty(false); setPending(false); setConflict(null); setEditing(false); setRevealed(false); setHistory([]); setHistoryNext(null); clear();
    setCards(items => items.map(item => item.id === value.id ? value : item));
  }
  const load = useCallback(async (path: string, append = false) => {
    const token = ++generation.current; setListing(true); setNext(null);
    try {
      const page = await studentRequest<Page<Card>>(safePage(path, "/api/flashcards/"));
      if (token !== generation.current) return;
      if (page.results.some(row => row.account_id !== identity.current)) throw Error("A conta mudou. Recarregue a página.");
      setCards(items => append ? [...items, ...page.results.filter(row => !items.some(item => item.id === row.id))] : page.results); setNext(page.next);
    } finally {if (token === generation.current) setListing(false);}
  }, []);
  const listPath = () => "/api/flashcards/?" + new URLSearchParams({mode, q: query}).toString();
  useEffect(() => {
    let active = true; const requests = generation;
    void Promise.all([studentRequest<{id: string}>("/api/auth/me"), catalog()]).then(async ([user, available]) => {
      if (!active) return;
      identity.current = user.id; creation.current = crypto.randomUUID(); setSubjects(available);
      const saved = recover(user.id);
      if (saved) {
        setCard(saved.card); setFields(saved.fields); creation.current = saved.creation_key; snapshot.current = saved;
        setDirty(true); setPending(true); setEditing(true); setNotice("Rascunho recuperado. Confira o que já foi salvo antes de continuar.");
      }
      setReady(true); await load("/api/flashcards/?mode=due");
    }).catch(error => {if (active) setNotice((error as Error).message);});
    return () => {active = false; requests.current++;};
  }, [load, retry]);
  useEffect(() => {onDirty(dirty || pending);}, [dirty, pending, onDirty]);
  useEffect(() => {const guard = (event: BeforeUnloadEvent) => {if (dirty || pending) {event.preventDefault(); event.returnValue = "";}}; window.addEventListener("beforeunload", guard); return () => window.removeEventListener("beforeunload", guard);}, [dirty, pending]);

  function edit(values: Partial<Fields>) {
    const updated = {...fields, ...values}; setFields(updated); setDirty(true);
    preserve({fields: updated, card, creation_key: creation.current, pending: false, review: null});
  }
  async function save() {
    if (busy || !identity.current || pending) return;
    setBusy(true); setNotice(""); setPending(true);
    preserve({fields, card, creation_key: creation.current, pending: true, review: null});
    try {
      const value = await studentRequest<Card>(card ? `/api/flashcards/${card.id}/` : "/api/flashcards/", {method: card ? "PATCH" : "POST", body: JSON.stringify({...fields, expected_owner: identity.current, ...(card ? {expected_version: card.version} : {creation_key: creation.current})})});
      install(value); setNotice("Cartão salvo na sua conta."); await load(listPath());
    } catch (error) {setNotice((error as Error).message + " Confira o salvamento antes de repetir.");}
    finally {setBusy(false);}
  }
  async function reconcile() {
    const draft = snapshot.current; if (!draft || busy || !identity.current) return;
    setBusy(true);
    try {
      if (draft.review && draft.card) {
        const receipt = await studentRequest<Review>(`/api/flashcards/${draft.card.id}/review/`, {method: "POST", body: JSON.stringify(draft.review)});
        if (receipt.account_id !== identity.current) throw Error("A conta mudou.");
        const current = await studentRequest<Card>(`/api/flashcards/${draft.card.id}/`);
        install(current); setNotice("Revisão confirmada uma única vez. Próxima revisão: " + date(receipt.next_review_at));
      } else {
        const current = draft.card ? await studentRequest<Card>(`/api/flashcards/${draft.card.id}/`) : (await studentRequest<Page<Card>>(`/api/flashcards/?mode=all&creation_key=${draft.creation_key}`)).results[0];
        if (current && current.account_id !== identity.current) throw Error("A conta mudou.");
        if (current && equal(fieldsOf(current), draft.fields)) {install(current); setNotice("Salvamento confirmado no servidor.");}
        else if (current && (!draft.card || current.version !== draft.card.version)) {
          setConflict(current);
          setNotice("Existe outra versão salva. Seu rascunho permanece abaixo. Abra a versão do servidor para descartar o rascunho; nenhuma alteração foi sobrescrita.");
        } else {
          setPending(false); preserve({...draft, pending: false}); setNotice("O rascunho ainda não está salvo. Confira e salve quando desejar.");
        }
      }
      await load(listPath());
    } catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }
  async function open(value: Card) {
    if (busy || dirty || pending) return;
    setBusy(true); setNotice("");
    try {install(await studentRequest<Card>(`/api/flashcards/${value.id}/`)); heading.current?.focus();}
    catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }
  async function discard() {
    if (busy) return; setBusy(true);
    try {
      if (card) install(await studentRequest<Card>(`/api/flashcards/${card.id}/`));
      else {setFields(empty); setDirty(false); setPending(false); setConflict(null); setEditing(true); clear(); creation.current = crypto.randomUUID();}
      setNotice("Rascunho descartado; dados salvos continuam na conta.");
    } catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }
  async function review(rating: number) {
    if (!card || !revealed || busy || dirty || pending || !identity.current) return;
    const command: Command = {rating, expected_version: card.version, expected_owner: identity.current, idempotency_key: crypto.randomUUID()};
    setBusy(true); setPending(true); preserve({fields, card, creation_key: creation.current, pending: true, review: command});
    try {
      const receipt = await studentRequest<Review>(`/api/flashcards/${card.id}/review/`, {method: "POST", body: JSON.stringify(command)});
      if (receipt.account_id !== identity.current) throw Error("A conta mudou.");
      install(await studentRequest<Card>(`/api/flashcards/${card.id}/`));
      setNotice("Revisão salva. Próxima revisão: " + date(receipt.next_review_at)); await load(listPath());
    } catch (error) {setNotice((error as Error).message + " Confira a revisão antes de enviar outra avaliação.");}
    finally {setBusy(false);}
  }
  async function archive() {
    if (!card || busy || dirty || pending || !identity.current) return;
    setBusy(true);
    try {
      install(await studentRequest<Card>(`/api/flashcards/${card.id}/`, {method: "PATCH", body: JSON.stringify({archived: !card.archived_at, expected_version: card.version, expected_owner: identity.current})}));
      setNotice("Situação do cartão atualizada. O histórico foi preservado."); await load(listPath());
    } catch (error) {setNotice((error as Error).message + " Abra novamente o cartão para conferir sua situação.");}
    finally {setBusy(false);}
  }
  async function showHistory(path?: string) {
    if (!card || busy) return; setBusy(true);
    try {
      const endpoint = `/api/flashcards/${card.id}/history/`;
      const page = await studentRequest<Page<Review>>(safePage(path || endpoint, endpoint));
      if (page.results.some(row => row.account_id !== identity.current)) throw Error("A conta mudou.");
      setHistory(items => path ? [...items, ...page.results] : page.results); setHistoryNext(page.next);
      if (!page.count) setNotice("Este cartão ainda não possui revisões.");
    } catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }
  return <section className="flashcards-workspace" aria-label="Meus flashcards">
    <header><p className="eyebrow">MEMÓRIA E REVISÃO</p><h2 ref={heading} tabIndex={-1}>Meus flashcards</h2><p>Crie perguntas pessoais e tente lembrar antes de revelar a resposta. Sua avaliação organiza a próxima revisão; ela não valida a correção jurídica do texto.</p></header>
    {notice && <p role="status" className="form-notice">{notice}</p>}
    {!ready ? <button type="button" className="outline-button" onClick={() => setRetry(value => value + 1)}>Tentar carregar os cartões</button> : <div className="notes-layout">
      <aside className="work-panel"><h3>Seus cartões</h3><form className="stack-form" onSubmit={event => {event.preventDefault(); void load(listPath()).catch(error => setNotice(error.message));}}>
        <div><label htmlFor="flashcard-mode">Exibir</label><select id="flashcard-mode" value={mode} disabled={listing || dirty || pending} onChange={event => setMode(event.target.value)}><option value="due">Para revisar agora</option><option value="active">Todos os ativos</option><option value="archived">Arquivados</option></select></div>
        <div><label htmlFor="flashcard-search">Buscar nos cartões</label><input id="flashcard-search" value={query} maxLength={150} onChange={event => setQuery(event.target.value)}/></div><button type="submit" className="outline-button" disabled={listing || dirty || pending}>Filtrar cartões</button>
      </form><button type="button" className="primary-button" disabled={busy || dirty || pending} onClick={() => {setCard(null); setFields(empty); setEditing(true); setRevealed(false); setHistory([]); setHistoryNext(null); setNotice(""); clear(); creation.current = crypto.randomUUID();}}>Criar cartão</button>
        {cards.map(value => <button type="button" className="open-row" key={value.id} disabled={busy || dirty || pending} onClick={() => void open(value)}><span>{value.front}</span><small>{value.subject_name || "Sem disciplina"} · {value.archived_at ? "Arquivado" : value.next_review_at ? date(value.next_review_at) : "Ainda não revisado"}</small></button>)}
        {!listing && !cards.length && <p>Nenhum cartão neste filtro. Crie um cartão ou veja todos os ativos.</p>}
        {next && <button type="button" className="outline-button" disabled={listing || dirty || pending} onClick={() => void load(next, true).catch(error => setNotice(error.message))}>Mais cartões</button>}
      </aside>
      <div className="work-panel"><h3>{card ? "Seu cartão" : "Novo cartão"}</h3>
        {editing ? <form className="stack-form" onSubmit={event => {event.preventDefault(); void save();}}>
          <div><label htmlFor="flashcard-front">Pergunta</label><textarea id="flashcard-front" required maxLength={10000} value={fields.front} disabled={busy || pending} onChange={event => edit({front: event.target.value})}/></div>
          <div><label htmlFor="flashcard-back">Resposta</label><textarea id="flashcard-back" required maxLength={20000} value={fields.back} disabled={busy || pending} onChange={event => edit({back: event.target.value})}/></div>
          <div><label htmlFor="flashcard-subject">Disciplina</label><select id="flashcard-subject" value={fields.subject || ""} disabled={busy || pending} onChange={event => edit({subject: event.target.value || null, topic: null})}><option value="">Sem disciplina</option>{subjects.map(subject => <option key={subject.id} value={subject.id}>{subject.name}</option>)}</select></div>
          <div><label htmlFor="flashcard-topic">Tema</label><select id="flashcard-topic" value={fields.topic || ""} disabled={busy || pending || !fields.subject} onChange={event => edit({topic: event.target.value || null})}><option value="">Sem tema</option>{subjects.find(subject => subject.id === fields.subject)?.topics.map(topic => <option key={topic.id} value={topic.id}>{topic.name}</option>)}</select></div>
          <div><label htmlFor="flashcard-source">Referência pessoal</label><input id="flashcard-source" maxLength={2000} value={fields.source_reference} disabled={busy || pending} onChange={event => edit({source_reference: event.target.value})}/></div>
          <div className="button-row"><button type="submit" className="primary-button" disabled={busy || pending || !fields.front.trim() || !fields.back.trim()}>Salvar cartão</button>{(dirty || pending || card) && <button type="button" className="outline-button" disabled={busy} onClick={() => void discard()}>Descartar rascunho e abrir versão salva</button>}</div>
        </form> : card && <><p className="flashcard-text">{card.front}</p>{revealed ? <div className="flashcard-answer"><h4>Resposta pessoal</h4><p className="flashcard-text">{card.back}</p>{card.source_reference && <p className="flashcard-text">Referência informada por você: {card.source_reference}</p>}</div> : <button type="button" className="primary-button" disabled={busy || pending} onClick={() => setRevealed(true)}>Revelar resposta</button>}
          {revealed && !card.archived_at && <fieldset disabled={busy || pending}><legend>Como foi lembrar?</legend><div className="button-row">{ratings.map((label, index) => <button type="button" className="outline-button" key={label} onClick={() => void review(index + 1)}>{label}</button>)}</div></fieldset>}
          {card.next_review_at && <p>Próxima revisão: {date(card.next_review_at)}</p>}
          <div className="button-row"><button type="button" className="outline-button" disabled={busy || pending} onClick={() => setEditing(true)}>Editar cartão</button><button type="button" className="outline-button" disabled={busy || pending} onClick={() => void showHistory()}>Histórico de revisões</button><button type="button" className="outline-button" disabled={busy || pending} onClick={() => void archive()}>{card.archived_at ? "Reativar cartão" : "Arquivar cartão"}</button></div>
        </>}
        {pending && <div className="button-row"><button type="button" className="primary-button" disabled={busy} onClick={() => void reconcile()}>Conferir salvamento ou revisão</button>{!editing && <button type="button" className="outline-button" disabled={busy} onClick={() => void discard()}>Abrir versão salva e manter histórico</button>}</div>}
        {conflict && <section className="note-conflict" aria-label="Comparar cartão salvo"><h4>Versão que está salva na conta</h4><p className="flashcard-text">{conflict.front}</p><p className="flashcard-text">{conflict.back}</p><p className="flashcard-text">{conflict.source_reference}</p><p>Compare com seu rascunho acima. Manter seu texto permite editar e salvar explicitamente uma nova versão.</p><button type="button" className="outline-button" disabled={busy} onClick={() => {setCard(conflict); setPending(false); setDirty(true); preserve({fields, card: conflict, creation_key: creation.current, pending: false, review: null}); setConflict(null); setNotice("Seu texto foi mantido em edição. Confira as diferenças antes de salvar.");}}>Manter meu texto em edição</button></section>}
        {!!history.length && <section aria-label="Histórico de revisões"><h4>Revisões salvas</h4>{history.map(item => <details key={item.id}><summary>{date(item.reviewed_at)} · {ratings[item.rating - 1]}</summary><p>Próxima revisão registrada: {date(item.next_review_at)}</p>{item.snapshot.front ? <><p className="flashcard-text">{item.snapshot.front}</p><p className="flashcard-text">{item.snapshot.back}</p></> : <p>Revisão antiga, sem cópia histórica do texto.</p>}</details>)}{historyNext && <button type="button" className="outline-button" disabled={busy} onClick={() => void showHistory(historyNext)}>Mais revisões</button>}</section>}
      </div>
    </div>}
  </section>;
}
