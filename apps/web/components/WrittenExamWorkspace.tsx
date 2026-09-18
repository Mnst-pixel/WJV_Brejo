"use client";

import {useCallback, useEffect, useRef, useState} from "react";
import {StudentApiError, studentRequest} from "@/lib/student-api";

type Case = {id: string; title: string; area: string; duration_minutes: number; prompt: string; questions: {code: string; prompt: string}[]};
type Written = Case & {mode: "formal" | "training"; status: "active" | "submitted"; version: number; started_at: string; submitted_at: string | null; elapsed_seconds: number; responses: {target_code: string; text: string}[]; final_hash: string};
type Texts = Record<string, string>;
type Page<T> = {results: T[]; next: string | null};
type Preparation = {case_id: string; request_id: string; mode: "formal" | "training"};
const fromRecord = (record: Written): Texts => Object.fromEntries(record.responses.map(row => [row.target_code, row.text]));
const same = (a: Texts, b: Texts) => [...new Set([...Object.keys(a), ...Object.keys(b)])].every(key => (a[key] ?? "") === (b[key] ?? ""));
const cacheKey = (id: string) => `kairos_pending_written_${id}`;
const clearCache = (key: string) => {try {sessionStorage.removeItem(key);} catch { /* Confirmed server state remains authoritative. */ }};
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(value);
function safePage(next: string | null, path: string) {const url = new URL(next ?? path, window.location.origin); if (url.origin !== window.location.origin || url.pathname !== path) throw new Error("Página indisponível."); return url.pathname + url.search;}

function recovered(record: Written): {version: number; texts: Texts} | null {
  try {
    const raw = sessionStorage.getItem(cacheKey(record.id));
    if (!raw || raw.length > 1_000_000) return null;
    const value = JSON.parse(raw);
    const expected = ["piece", ...record.questions.map(row => row.code)];
    if (!Number.isInteger(value?.version) || !value.texts || typeof value.texts !== "object" || Array.isArray(value.texts) || Object.keys(value.texts).length !== expected.length) return null;
    if (expected.every(key => typeof value.texts[key] === "string" && value.texts[key].length <= 100000)) return value;
  } catch { /* Invalid local cache never replaces account state. */ }
  return null;
}

export function WrittenExamWorkspace() {
  const [catalog, setCatalog] = useState<Case[]>([]);
  const [catalogNext, setCatalogNext] = useState<string | null>(null);
  const [history, setHistory] = useState<Written[]>([]);
  const [historyNext, setHistoryNext] = useState<string | null>(null);
  const [record, setRecord] = useState<Written | null>(null);
  const current = useRef<Written | null>(null);
  const [texts, setTexts] = useState<Texts>({});
  const drafts = useRef<Texts>({});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const inFlight = useRef<Promise<boolean> | null>(null);
  const [paused, setPaused] = useState(false);
  const [conflict, setConflict] = useState<Written | null>(null);
  const conflicted = useRef(false);
  const [notice, setNotice] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [activeField, setActiveField] = useState("piece");
  const [now, setNow] = useState(0);
  const [identity, setIdentity] = useState<string | null>(null);
  const [preparation, setPreparation] = useState<Preparation | null>(null);
  const historyGeneration = useRef(0);
  const navigationGeneration = useRef(0);
  const editor = useRef<HTMLTextAreaElement>(null);
  const panel = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {if (record?.status === "submitted") heading.current?.focus();}, [record?.status]);
  const install = (value: Written) => {current.current = value; setRecord(value);};
  const localCopy = (value: Written, content: Texts) => {
    try {sessionStorage.setItem(cacheKey(value.id), JSON.stringify({version: value.version, texts: content}));}
    catch {setNotice("A cópia temporária não está disponível. Aguarde a confirmação do servidor antes de sair.");}
  };

  const loadHistory = useCallback(async (next: string | null = null) => {
    const generation = ++historyGeneration.current;
    const data = await studentRequest<Page<Written>>(safePage(next, "/api/phase2/submissions/"));
    if (generation !== historyGeneration.current) return;
    setHistory(items => next ? [...items, ...data.results.filter(row => !items.some(item => item.id === row.id))] : data.results); setHistoryNext(data.next);
  }, []);

  async function open(id: string) {
    if (dirty || inFlight.current) {setNotice("Confirme o salvamento antes de trocar de prova."); return;}
    const generation = ++navigationGeneration.current;
    setBusy(true); setNotice(""); setConfirm(false);
    try {
      const value = await studentRequest<Written>(`/api/phase2/submissions/${id}/`);
      if (generation !== navigationGeneration.current) return;
      install(value); setActiveField("piece"); setNow(Date.now()); setPaused(false); setConflict(null); conflicted.current = false;
      const cached = value.status === "active" ? recovered(value) : null;
      const restored = cached && !same(cached.texts, fromRecord(value));
      const content = restored ? cached.texts : fromRecord(value);
      drafts.current = content; setTexts(content); setDirty(!!restored);
      if (restored) {
        if (cached.version !== value.version) {setConflict(value); conflicted.current = true; setNotice("Há textos locais diferentes da versão do servidor. Escolha qual manter.");}
        else setNotice("Texto temporário recuperado; aguardando confirmação de salvamento.");
      } else clearCache(cacheKey(id));
      window.history.replaceState(null, "", `/app/segunda-fase?submissao=${id}`);
    } catch (error) {if (generation === navigationGeneration.current) setNotice((error as Error).message);}
    finally {if (generation === navigationGeneration.current) setBusy(false);}
  }

  useEffect(() => {
    let live = true;
    void Promise.allSettled([studentRequest<Page<Case>>("/api/phase2/cases/"), studentRequest<{id: string}>("/api/auth/me"), loadHistory()]).then(async results => {
      if (!live) return;
      if (results[0].status === "fulfilled") {setCatalog(results[0].value.results); setCatalogNext(results[0].value.next);}
      if (results[1].status === "fulfilled") {
        const id = results[1].value.id; setIdentity(id);
        try {
          const cached = JSON.parse(sessionStorage.getItem(`kairos_written_preparation_${id}`) ?? "null");
          if (cached && uuid(cached.case_id) && uuid(cached.request_id) && ["formal", "training"].includes(cached.mode)) setPreparation(cached);
        } catch { /* Account history remains available. */ }
      }
      for (const result of results) if (result.status === "rejected") setNotice((result.reason as Error).message);
      const id = new URLSearchParams(window.location.search).get("submissao");
      if (uuid(id)) await open(id);
    });
    return () => {live = false; historyGeneration.current += 1; navigationGeneration.current += 1;};
    // Restore the URL once; subsequent navigation is an explicit command.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadHistory]);

  const save = useCallback(async (): Promise<boolean> => {
    if (inFlight.current) return inFlight.current;
    const value = current.current;
    if (!value || value.status !== "active" || conflicted.current) return false;
    const content = {...drafts.current};
    if (same(content, fromRecord(value))) return true;
    setSaving(true); setPaused(false);
    const task = (async () => {
      try {
        const saved = await studentRequest<Written>(`/api/phase2/submissions/${value.id}/autosave/`, {method: "POST", body: JSON.stringify({version: value.version, responses: Object.entries(content).map(([target_code, text]) => ({target_code, text}))})});
        install(saved); const pending = !same(drafts.current, fromRecord(saved)); setDirty(pending);
        if (pending) localCopy(saved, drafts.current); else clearCache(cacheKey(value.id));
        setNotice("Texto salvo na sua conta."); return !pending;
      } catch (error) {
        setPaused(true);
        if (error instanceof StudentApiError && error.status === 409) {
          try {
            const latest = await studentRequest<Written>(`/api/phase2/submissions/${value.id}/`);
            if (same(content, fromRecord(latest))) {
              install(latest); const pending = !same(drafts.current, fromRecord(latest)); setDirty(pending); setPaused(false);
              if (pending) localCopy(latest, drafts.current); else clearCache(cacheKey(value.id));
              setNotice("Salvamento anterior confirmado no servidor."); return !pending;
            }
            setConflict(latest); conflicted.current = true;
            setNotice("A versão ou o prazo mudou. Seu texto local foi preservado para conferência.");
          } catch {setNotice("Não foi possível conferir a versão. Seu texto local foi preservado.");}
        } else setNotice("Salvamento não confirmado. Mantenha a página aberta e use Salvar agora.");
        return false;
      } finally {inFlight.current = null; setSaving(false);}
    })();
    inFlight.current = task; return task;
  }, []);

  useEffect(() => {if (!dirty || busy || saving || paused || conflict) return; const timer = window.setTimeout(() => {void save();}, 800); return () => window.clearTimeout(timer);}, [texts, dirty, busy, saving, paused, conflict, save]);
  useEffect(() => {if (!dirty) return; const warn = (event: BeforeUnloadEvent) => event.preventDefault(); window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);}, [dirty]);
  useEffect(() => {if (record?.status !== "active") return; const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer);}, [record]);

  async function start(value: Preparation) {
    if (!identity || busy || dirty || saving) return;
    setBusy(true); setPreparation(value); setNotice("");
    try {sessionStorage.setItem(`kairos_written_preparation_${identity}`, JSON.stringify(value));} catch {setNotice("Cópia temporária indisponível. Em caso de falha, confira o histórico antes de preparar outra prova.");}
    try {
      const created = await studentRequest<Written>("/api/phase2/submissions/", {method: "POST", body: JSON.stringify(value)});
      install(created); const content = fromRecord(created); drafts.current = content; setTexts(content); setDirty(false); setActiveField("piece"); setNow(Date.now());
      setConflict(null); conflicted.current = false; setPaused(false); setConfirm(false); setPreparation(null); clearCache(`kairos_written_preparation_${identity}`);
      window.history.replaceState(null, "", `/app/segunda-fase?submissao=${created.id}`); await loadHistory();
    } catch (error) {
      if (error instanceof StudentApiError && error.status < 500) {setPreparation(null); clearCache(`kairos_written_preparation_${identity}`);}
      setNotice((error as Error).message);
    } finally {setBusy(false);}
  }

  async function submit() {
    if (!record || busy || saving) return;
    setBusy(true);
    try {
      if (dirty && !await save()) return;
      const final = await studentRequest<Written>(`/api/phase2/submissions/${record.id}/submit/`, {method: "POST"});
      install(final); drafts.current = fromRecord(final); setTexts(drafts.current); setDirty(false); clearCache(cacheKey(record.id)); setConfirm(false);
      setNotice("Prova enviada. Seus textos foram preservados e não podem mais ser alterados. Correção ainda pendente."); await loadHistory();
    } catch (error) {setNotice((error as Error).message + " Você pode repetir o envio para confirmar a mesma submissão.");}
    finally {setBusy(false);}
  }

  const active = record?.status === "active";
  const remaining = record ? Math.max(0, record.duration_minutes * 60 - Math.max(record.elapsed_seconds, Math.floor((now - Date.parse(record.started_at)) / 1000))) : 0;
  const expired = active && record.mode === "formal" && remaining === 0;
  const fields = record ? [{code: "piece", prompt: record.prompt}, ...record.questions] : [];
  return <div className="written-workspace"><p className="form-notice" role="status">{notice}</p>
    {!record && <section className="work-panel"><h2>Escolha seu caso de segunda fase</h2>{preparation && <p><button className="primary-button" disabled={busy || !identity} onClick={() => void start(preparation)}>Confirmar preparação anterior</button></p>}
      {catalog.map(item => <article className="open-row" key={item.id}><div><h3>{item.title}</h3><p>{item.area} · {item.duration_minutes} minutos · {item.questions.length} discursivas</p></div><form onSubmit={event => {event.preventDefault(); const mode = new FormData(event.currentTarget).get("mode") === "formal" ? "formal" : "training"; void start({case_id: item.id, mode, request_id: crypto.randomUUID()});}}><label>Modo<select name="mode" disabled={!!preparation || busy}><option value="training">Treino de escrita</option><option value="formal">Simulado formal</option></select></label><button className="primary-button" disabled={!!preparation || busy || !identity}>Redigir prova</button></form></article>)}
      {!catalog.length && <p>Os casos revisados aparecerão aqui após publicação.</p>}{catalogNext && <button className="outline-button" onClick={() => void studentRequest<Page<Case>>(safePage(catalogNext, "/api/phase2/cases/")).then(data => {setCatalog(items => [...items, ...data.results.filter(row => !items.some(item => item.id === row.id))]); setCatalogNext(data.next);}).catch(error => setNotice(error.message))}>Mais casos</button>}</section>}
    {record && <section className="work-panel written-editor" ref={panel}><h2 ref={heading} tabIndex={-1}>{record.title}</h2><p>{record.area} · {active ? "Em andamento" : "Enviada para correção"}</p>
      {active && <><p>{record.mode === "formal" ? `Tempo restante: ${Math.floor(remaining / 60)}min ${remaining % 60}s` : "Treino de escrita sem prazo de envio"}</p><p>{saving ? "Salvando texto…" : dirty ? "Há texto aguardando salvamento" : "Todo o texto confirmado no servidor"}</p>{expired && <p role="alert">Tempo encerrado. Envie os textos confirmados no servidor.</p>}</>}
      {conflict && <section className="practice-result" role="alert"><h3>Confira as versões</h3><p>Seu texto local permanece no editor. Abra a versão do servidor abaixo antes de decidir.</p><details><summary>Ler versão salva no servidor</summary>{conflict.responses.map(row => <div key={row.target_code}><h4>{row.target_code === "piece" ? "Peça profissional" : row.target_code}</h4><p className="preserve-text">{row.text || "Em branco"}</p></div>)}</details><button className="outline-button" disabled={busy || saving} onClick={() => {install(conflict); const content = fromRecord(conflict); drafts.current = content; setTexts(content); setDirty(false); clearCache(cacheKey(conflict.id)); conflicted.current = false; setConflict(null); setPaused(false);}}>Usar texto do servidor</button><button className="outline-button" disabled={busy || saving || expired || conflict.status !== "active"} onClick={() => {install(conflict); localCopy(conflict, drafts.current); conflicted.current = false; setConflict(null); setPaused(false);}}>Manter meu texto local</button></section>}
      <nav className="exam-navigation" aria-label="Campos da prova escrita">{fields.map(field => <button type="button" key={field.code} aria-current={activeField === field.code ? "step" : undefined} onClick={() => {setActiveField(field.code); editor.current?.focus();}}>{field.code === "piece" ? "Peça profissional" : `Questão ${field.code.slice(1)}`}{texts[field.code]?.trim() ? " ✓" : ""}</button>)}</nav>
      <p className="preserve-text">{fields.find(field => field.code === activeField)?.prompt}</p>
      <label htmlFor="written-response">{activeField === "piece" ? "Sua peça profissional" : `Sua resposta à questão ${activeField.slice(1)}`}</label><textarea id="written-response" ref={editor} rows={active ? 20 : 8} maxLength={100000} readOnly={!active || !!expired || !!conflict || busy} value={texts[activeField] ?? ""} onChange={event => {const content = {...drafts.current, [activeField]: event.target.value}; drafts.current = content; setTexts(content); setDirty(!same(content, fromRecord(record))); localCopy(record, content);}}/>
      <p>{(texts[activeField] ?? "").length.toLocaleString("pt-BR")} caracteres · {(texts[activeField] ?? "").trim().split(/\s+/).filter(Boolean).length.toLocaleString("pt-BR")} palavras</p>
      <button className="outline-button" onClick={() => {if (document.fullscreenElement) void document.exitFullscreen().catch(() => setNotice("Não foi possível sair da tela cheia.")); else void panel.current?.requestFullscreen?.().catch(() => setNotice("Tela cheia indisponível neste navegador."));}}>Alternar tela cheia</button>
      {active && <div className="question-actions"><button className="secondary-button" disabled={!dirty || busy || saving || !!conflict} onClick={() => void save()}>Salvar agora</button><button className="primary-button" disabled={busy || saving || !!conflict} onClick={() => setConfirm(true)}>Enviar prova</button></div>}
      {active && confirm && <section className="practice-result"><h3>Confirmar envio da prova</h3><p>Após confirmar, a peça e as discursivas não poderão ser alteradas. Campos em branco também serão enviados.</p><button className="primary-button" disabled={busy || saving} onClick={() => void submit()}>Confirmar envio final</button><button className="outline-button" disabled={busy} onClick={() => setConfirm(false)}>Continuar redigindo</button></section>}
      {!active && <><p>Envio registrado em {new Date(record.submitted_at ?? record.started_at).toLocaleString("pt-BR")}. Correção pendente; nenhuma nota foi atribuída automaticamente.</p><button className="primary-button" disabled={busy} onClick={() => {setRecord(null); current.current = null; setNotice(""); window.history.replaceState(null, "", "/app/segunda-fase");}}>Escolher outro caso</button></>}
    </section>}
    <section className="work-panel"><h2>Suas provas escritas</h2><button className="outline-button" disabled={busy} onClick={() => void loadHistory().catch(error => setNotice(error.message))}>Atualizar provas</button>{history.map(item => <article className="open-row" key={item.id}><div><h3>{item.title}</h3><p>{item.status === "active" ? "Em andamento" : "Enviada"} · {new Date(item.started_at).toLocaleString("pt-BR")}</p></div><button className="outline-button" disabled={busy || dirty || saving} onClick={() => void open(item.id)}>{item.status === "active" ? "Retomar escrita" : "Ler envio"}</button></article>)}{historyNext && <button className="outline-button" disabled={busy} onClick={() => void loadHistory(historyNext).catch(error => setNotice(error.message))}>Provas anteriores</button>}</section>
  </div>;
}
