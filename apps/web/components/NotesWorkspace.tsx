"use client";

import {useCallback, useEffect, useRef, useState} from "react";
import {StudentApiError, studentRequest} from "@/lib/student-api";

type Fields = {title: string; body: string; subject: string | null; topic: string | null; content_version: string | null};
type Note = Fields & {id: string; account_id: string; version: number; subject_name: string | null; content_title: string | null; updated_at: string};
type Subject = {id: string; name: string; topics: {id: string; name: string}[]};
type Page<T> = {results: T[]; next: string | null; count: number};
type Draft = {fields: Fields; record: Note | null; creation_key: string; pending: boolean};
const empty: Fields = {title: "", body: "", subject: null, topic: null, content_version: null};
const fieldsOf = (note: Fields): Fields => ({title: note.title, body: note.body, subject: note.subject, topic: note.topic, content_version: note.content_version});
const same = (a: Fields, b: Fields) => (Object.keys(empty) as (keyof Fields)[]).every(key => a[key] === b[key]);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const storageKey = (id: string) => `kairos_pending_personal_note_${id}`;
function safePage(path: string) {const url = new URL(path, window.location.origin); if (url.origin !== window.location.origin || url.pathname !== "/api/notes/") throw Error("Página indisponível."); return url.pathname + url.search;}
async function subjectCatalog() {
  const values: Subject[] = []; const seen = new Set<string>(); let path: string | null = "/api/subjects/";
  while (path) {
    const url: URL = new URL(path, window.location.origin);
    if (url.origin !== window.location.origin || url.pathname !== "/api/subjects/" || seen.has(url.href) || seen.size >= 100) throw Error("O catálogo de disciplinas não pôde ser carregado.");
    seen.add(url.href);
    const page: Page<Subject> = await studentRequest<Page<Subject>>(url.pathname + url.search);
    values.push(...page.results); path = page.next;
  }
  return values;
}
function recover(identity: string): Draft | null {
  try {
    const raw = sessionStorage.getItem(storageKey(identity)); if (!raw || raw.length > 1000000) return null;
    const value = JSON.parse(raw) as Draft;
    const valid = (fields: Fields) => fields && typeof fields.title === "string" && fields.title.length <= 255 && typeof fields.body === "string" && fields.body.length <= 100000 && [fields.subject, fields.topic, fields.content_version].every(id => id === null || uuid(id));
    if (!value || !valid(value.fields) || !uuid(value.creation_key) || typeof value.pending !== "boolean") return null;
    if (value.record && (!valid(value.record) || !uuid(value.record.id) || value.record.account_id !== identity || !Number.isSafeInteger(value.record.version) || value.record.version < 1)) return null;
    return value;
  } catch {return null;}
}

export function NotesWorkspace({onDirty}: {onDirty: (dirty: boolean) => void}) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [listing, setListing] = useState(false);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [record, setRecord] = useState<Note | null>(null);
  const [fields, setFields] = useState<Fields>(empty);
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [retry, setRetry] = useState(0);
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState<Note | null>(null);
  const identity = useRef<string | null>(null);
  const creation = useRef("");
  const snapshot = useRef<Draft | null>(null);
  const generation = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);

  const clear = () => {if (identity.current) {try {sessionStorage.removeItem(storageKey(identity.current));} catch { /* Confirmed server data remains canonical. */ }}};
  function preserve(value: Draft) {
    snapshot.current = value;
    if (identity.current) try {sessionStorage.setItem(storageKey(identity.current), JSON.stringify(value));}
    catch {setNotice("A cópia temporária não está disponível. Salve no servidor antes de sair.");}
  }
  function install(note: Note) {
    if (note.account_id !== identity.current) throw Error("A conta da sessão mudou. Recarregue a página antes de continuar.");
    setRecord(note); setFields(fieldsOf(note)); setDirty(false); setPending(false); setConflict(null); snapshot.current = null; clear();
    setNotes(items => [note, ...items.filter(item => item.id !== note.id)]);
    window.history.replaceState(null, "", "?aba=notas&nota=" + note.id);
  }
  const load = useCallback(async (path = "/api/notes/", append = false) => {
    const current = ++generation.current;
    setListing(true); setNext(null);
    try {
      const data = await studentRequest<Page<Note>>(safePage(path));
      if (current !== generation.current) return;
      if (identity.current && data.results.some(note => note.account_id !== identity.current)) throw Error("A conta da sessão mudou. Recarregue a página.");
      setNotes(items => append ? [...items, ...data.results.filter(row => !items.some(item => item.id === row.id))] : data.results); setNext(data.next);
    } finally {if (current === generation.current) setListing(false);}
  }, []);
  useEffect(() => {
    let active = true;
    const requests = generation;
    void Promise.all([studentRequest<{id: string}>("/api/auth/me"), subjectCatalog()]).then(async ([user, catalog]) => {
      if (!active) return;
      identity.current = user.id; setSubjects(catalog); creation.current = crypto.randomUUID();
      const saved = recover(user.id); const params = new URLSearchParams(window.location.search);
      if (saved) {
        setRecord(saved.record); setFields(saved.fields); creation.current = saved.creation_key; snapshot.current = saved;
        setDirty(true); setPending(true); setNotice("Rascunho recuperado. Confira a versão salva antes de continuar.");
      } else if (uuid(params.get("nota"))) {
        const note = await studentRequest<Note>(`/api/notes/${params.get("nota")}/`);
        if (active) install(note);
      } else if (uuid(params.get("leitura")) && uuid(params.get("disciplina"))) {
        const initial = {...empty, title: (params.get("titulo") || "Anotação de leitura").slice(0, 255), subject: params.get("disciplina"), content_version: params.get("leitura")};
        setFields(initial); setDirty(true); preserve({fields: initial, record: null, creation_key: creation.current, pending: false});
      }
      if (!active) return;
      setReady(true);
      await load();
    }).catch(error => {if (active) setNotice((error as Error).message);});
    return () => {active = false; requests.current++;};
  // Mount owns the initial URL and account recovery; later changes are explicit actions.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, retry]);
  useEffect(() => {onDirty(dirty);}, [dirty, onDirty]);
  useEffect(() => {const guard = (event: BeforeUnloadEvent) => {if (dirty) {event.preventDefault(); event.returnValue = "";}}; window.addEventListener("beforeunload", guard); return () => window.removeEventListener("beforeunload", guard);}, [dirty]);

  function edit(value: Partial<Fields>) {
    const updated = {...fields, ...value}; setFields(updated); setDirty(true);
    preserve({record, fields: updated, creation_key: creation.current, pending: false});
  }
  async function reconcile() {
    const draft = snapshot.current; if (!draft || busy || !identity.current) return;
    setBusy(true); setNotice("");
    try {
      const found = draft.record ? await studentRequest<Note>(`/api/notes/${draft.record.id}/`) : (await studentRequest<Page<Note>>(`/api/notes/?creation_key=${draft.creation_key}`)).results[0];
      if (!found) {setPending(false); preserve({...draft, pending: false}); setNotice("A criação ainda não foi confirmada. Você pode salvar o rascunho preservado."); return;}
      if (found.account_id !== identity.current) throw Error("A conta da sessão mudou. Recarregue a página.");
      if (same(found, draft.fields)) {install(found); setNotice("A anotação está confirmada na sua conta.");}
      else if (draft.record && found.version === draft.record.version && !draft.pending) {setRecord(found); setPending(false); preserve({...draft, record: found, pending: false}); setNotice("Versão conferida. Suas alterações locais aguardam Salvar anotação.");}
      else {setConflict(found); setPending(false); setNotice("Há uma versão diferente no servidor. Compare antes de decidir.");}
    } catch (error) {setNotice((error as Error).message);}
    finally {setBusy(false);}
  }
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!identity.current || busy || pending || conflict || !ready) return;
    const values = {...fields, title: fields.title.trim()}; if (!values.title) return;
    const draft = {record, fields: values, creation_key: creation.current, pending: true};
    setFields(values); preserve(draft); setPending(true); setBusy(true); setNotice("");
    try {
      const payload = {...values, expected_owner: identity.current, ...(record ? {expected_version: record.version} : {creation_key: creation.current})};
      const saved = await studentRequest<Note>(record ? `/api/notes/${record.id}/` : "/api/notes/", {method: record ? "PATCH" : "POST", body: JSON.stringify(payload)});
      if (saved.account_id !== identity.current) throw Error("A conta da sessão mudou. Recarregue a página.");
      if (same(saved, values)) {install(saved); setNotice("Anotação salva na sua conta.");}
      else {setConflict(saved); setPending(false); setNotice("A criação já existia e foi editada. Compare a versão atual.");}
    } catch (error) {
      if (error instanceof StudentApiError && error.status < 500 && error.status !== 409) {setPending(false); preserve({...draft, pending: false});}
      setNotice(error instanceof StudentApiError && error.status === 400 ? "Confira título, disciplina, tema e vínculo com a leitura antes de salvar." : (error as Error).message);
    } finally {setBusy(false);}
  }
  async function open(id: string) {
    if (dirty || busy) return; setBusy(true); setNotice("");
    try {install(await studentRequest<Note>(`/api/notes/${id}/`)); heading.current?.focus();}
    catch (error) {setNotice((error as Error).message);} finally {setBusy(false);}
  }
  async function discard() {
    if (!window.confirm("Descartar apenas as alterações locais? A versão salva permanecerá na sua conta.")) return;
    setBusy(true);
    try {
      const found = record ? await studentRequest<Note>(`/api/notes/${record.id}/`) : (await studentRequest<Page<Note>>(`/api/notes/?creation_key=${creation.current}`)).results[0];
      if (found) install(found);
      else {setFields(empty); setDirty(false); setPending(false); setConflict(null); snapshot.current = null; clear(); creation.current = crypto.randomUUID(); window.history.replaceState(null, "", "?aba=notas");}
      await load(); setNotice("Alterações locais descartadas. A lista foi conferida no servidor.");
    } catch (error) {setNotice((error as Error).message);} finally {setBusy(false);}
  }
  const disabled = busy || pending || !!conflict || !ready;
  return <div className="notes-layout">{!ready && <button type="button" className="outline-button" onClick={() => setRetry(value => value + 1)}>Tentar carregar novamente</button>}<section className="work-panel"><h2>Minhas anotações</h2><form className="stack-form" onSubmit={event => {event.preventDefault(); void load("/api/notes/?q=" + encodeURIComponent(query)).catch(error => setNotice(error.message));}}><label htmlFor="notes-search">Buscar nas minhas notas</label><input id="notes-search" maxLength={150} value={query} onChange={event => setQuery(event.target.value)}/><button className="outline-button" disabled={!ready || listing}>Buscar anotações</button></form><button className="primary-button" disabled={dirty || busy || !ready} onClick={() => {setRecord(null); setFields(empty); setConflict(null); creation.current = crypto.randomUUID(); window.history.replaceState(null, "", "?aba=notas"); heading.current?.focus();}}>Nova anotação</button><div className="open-list">{notes.map(note => <article className="open-row" key={note.id}><div><h3>{note.title}</h3><p>{note.subject_name || "Sem disciplina"} · versão {note.version}</p><button className="outline-button" disabled={dirty || busy} onClick={() => void open(note.id)}>Abrir {note.title}</button></div></article>)}</div>{!notes.length && ready && <p>Nenhuma anotação encontrada.</p>}{next && !listing && <button className="outline-button" onClick={() => void load(next, true).catch(error => setNotice(error.message))}>Carregar mais anotações</button>}</section>
    <section className="work-panel"><h2 ref={heading} tabIndex={-1}>{record ? "Editar anotação" : "Nova anotação"}</h2><p role="status">{notice || (!ready ? "Carregando sua biblioteca…" : "Salve para confirmar as alterações na sua conta.")}</p>{pending && <button className="primary-button" disabled={busy} onClick={() => void reconcile()}>Conferir versão salva</button>}{conflict && <section className="note-conflict"><h3>Versão salva no servidor</h3><p>{conflict.title} · versão {conflict.version}</p><pre>{conflict.body}</pre><div className="button-row"><button className="outline-button" onClick={() => {install(conflict); setNotice("Versão do servidor carregada.");}}>Usar versão salva</button><button className="outline-button" onClick={() => {setRecord(conflict); setConflict(null); setPending(false); preserve({record: conflict, fields, creation_key: creation.current, pending: false}); setNotice("Sua versão foi preservada no editor. Confira e use Salvar anotação para confirmar a substituição.");}}>Manter meu texto para revisar</button></div></section>}
    <form className="stack-form" onSubmit={save}><label htmlFor="note-title">Título da anotação</label><input id="note-title" required maxLength={255} disabled={disabled} value={fields.title} onChange={event => edit({title: event.target.value})}/><label htmlFor="note-subject">Disciplina da anotação</label><select id="note-subject" disabled={disabled || !!fields.content_version} value={fields.subject ?? ""} onChange={event => edit({subject: event.target.value || null, topic: null})}><option value="">Sem disciplina</option>{subjects.map(subject => <option key={subject.id} value={subject.id}>{subject.name}</option>)}</select><label htmlFor="note-topic">Tema da anotação</label><select id="note-topic" disabled={disabled || !fields.subject} value={fields.topic ?? ""} onChange={event => edit({topic: event.target.value || null})}><option value="">Sem tema</option>{subjects.find(subject => subject.id === fields.subject)?.topics.map(topic => <option key={topic.id} value={topic.id}>{topic.name}</option>)}</select>{fields.content_version && <p>Vinculada à publicação estudada{record?.content_title ? `: ${record.content_title}` : ". A referência será conferida ao salvar."} <button type="button" className="outline-button" disabled={disabled} onClick={() => edit({content_version: null})}>Desvincular leitura</button></p>}<label htmlFor="note-body">Texto da anotação</label><textarea id="note-body" rows={16} maxLength={100000} disabled={disabled} value={fields.body} onChange={event => edit({body: event.target.value})}/><p>{fields.body.length.toLocaleString("pt-BR")} caracteres · notas privadas, sem publicação automática.</p><div className="button-row"><button className="primary-button" disabled={disabled || !dirty}>Salvar anotação</button>{dirty && <button type="button" className="outline-button" disabled={busy} onClick={discard}>Descartar alterações locais</button>}</div></form></section></div>;
}
