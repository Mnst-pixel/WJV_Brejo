"use client";

import Link from "next/link";
import {RichText} from "./RichText";
import {useCallback, useEffect, useRef, useState} from "react";
import {studentRequest} from "@/lib/student-api";

type Publication = {id: string; subject: string; current_version: {id: string; version_number: number; title: string; body: string; structured_data?: {rich_text?: unknown}; approval_date: string | null; reference_date: string | null; source_url: string; legal_status: string}};
type Page = {results: Publication[]; next: string | null; count: number};
type Reading = {content: Publication; subject_name: string; progress: {version: number; percent: number; needs_review: boolean; previous_percent: number}; history: {content_version_id: string; content_version__version_number: number; percent: number; recorded_at: string}[]};
const statuses: Record<string, string> = {current: "Vigente na data de referência", historical: "Material histórico", superseded: "Superado"};

function pagePath(value: string) {
  const url = new URL(value, window.location.origin);
  if (url.origin !== window.location.origin || url.pathname !== "/api/contents/") throw new Error("Página de conteúdo inválida.");
  return url.pathname + url.search;
}

export function ReadingWorkspace() {
  const [catalog, setCatalog] = useState<Page>({results: [], next: null, count: 0});
  const [reading, setReading] = useState<Reading | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [reconcile, setReconcile] = useState(false);
  const [percent, setPercent] = useState(0);
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const listGeneration = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);

  const open = useCallback(async (id: string, focus = true) => {
    const current = ++generation.current;
    setLoading(true); setNotice("");
    try {
      const data = await studentRequest<Reading>(`/api/study/reading/${encodeURIComponent(id)}/`);
      if (current !== generation.current) return false;
      setReading(data); setPercent(data.progress.percent); setReconcile(false);
      window.history.replaceState(null, "", "?conteudo=" + data.content.id);
      if (focus) window.requestAnimationFrame(() => heading.current?.focus());
      return true;
    } catch (error) {if (current === generation.current) {setReading(previous => previous?.content.id === id ? previous : null); setReconcile(true); setNotice((error as Error).message);} return false;}
    finally {if (current === generation.current) setLoading(false);}
  }, []);

  const list = useCallback(async (path = "/api/contents/", append = false) => {
    const current = ++listGeneration.current;
    try {
      const data = await studentRequest<Page>(pagePath(path));
      if (current === listGeneration.current) setCatalog(old => append ? {...data, results: [...old.results, ...data.results.filter(row => !old.results.some(item => item.id === row.id))]} : data);
    } catch (error) {if (current === listGeneration.current) setNotice((error as Error).message);}
  }, []);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      const id = new URLSearchParams(window.location.search).get("conteudo");
      await Promise.all([list(), id ? open(id, false) : Promise.resolve()]);
      if (active && !id) setLoading(false);
    });
    return () => {active = false; generation.current += 1; listGeneration.current += 1;};
  }, [list, open]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!reading || busy || loading || reconcile) return;
    setBusy(true); setNotice("");
    try {
      await studentRequest("/api/study/progress/", {method: "PUT", body: JSON.stringify({target_kind: "content", target_id: reading.content.id, content_version: reading.content.current_version.id, percent, position: 0, expected_version: reading.progress.version})});
      const refreshed = await open(reading.content.id, false);
      setNotice(refreshed ? "Progresso confirmado na sua conta." : "Progresso salvo, mas a leitura não pôde ser atualizada. Use Conferir progresso para recuperar o estado atual.");
    } catch {setReconcile(true); setNotice("O progresso não pôde ser confirmado ou foi alterado em outra aba. Use Conferir progresso antes de salvar novamente.");}
    finally {setBusy(false);}
  }

  return <div className="study-layout"><aside className="topic-rail"><h2>Conteúdos publicados</h2><form className="stack-form" onSubmit={event => {event.preventDefault(); const query = new FormData(event.currentTarget).get("q"); void list("/api/contents/?q=" + encodeURIComponent(String(query ?? "")));}}><label>Buscar leitura<input name="q" type="search" maxLength={200}/></label><button className="outline-button" type="submit">Buscar</button></form><p>{catalog.count} conteúdos encontrados</p>{catalog.results.map(item => <button type="button" aria-current={reading?.content.id === item.id ? "page" : undefined} className={reading?.content.id === item.id ? "selected" : ""} disabled={busy || loading} onClick={() => void open(item.id)} key={item.id}>{item.current_version.title}</button>)}{catalog.next && <button type="button" onClick={() => void list(catalog.next!, true)}>Mais conteúdos</button>}{!catalog.count && <p>Novas leituras aparecem após revisão e publicação.</p>}</aside>
    <article className="reading-surface" aria-busy={loading}><p role="status">{loading ? "Carregando publicação…" : notice}</p>{reading && !loading ? <><span className="reading-source">{reading.subject_name} · versão {reading.content.current_version.version_number}</span><h2 tabIndex={-1} ref={heading}>{reading.content.current_version.title}</h2><p>{statuses[reading.content.current_version.legal_status] ?? "Situação indicada pela revisão"}{reading.content.current_version.reference_date && ` · Referência: ${reading.content.current_version.reference_date}`}</p><p>Revisão humana: {reading.content.current_version.approval_date ? new Date(reading.content.current_version.approval_date).toLocaleDateString("pt-BR") : "Data indisponível"}</p><RichText text={reading.content.current_version.body} value={reading.content.current_version.structured_data?.rich_text} />{/^https:\/\//.test(reading.content.current_version.source_url) && <a target="_blank" rel="noopener noreferrer" href={reading.content.current_version.source_url}>Consultar fonte desta versão</a>}
      <section className="reading-progress"><h3>Seu progresso nesta publicação</h3>{reading.progress.needs_review && <p>Há uma nova publicação ou sua leitura anterior não possui versão confirmada ({reading.progress.previous_percent}%). Revise o texto antes de registrar o novo progresso.</p>}<form className="stack-form" onSubmit={save}><label>Leitura concluída (%)<input type="number" min={0} max={100} step={1} required disabled={busy || reconcile} value={percent} onChange={event => setPercent(Number(event.target.value))}/></label><div className="reading-actions"><button className="primary-button" disabled={busy || reconcile} type="submit">{busy ? "Salvando…" : "Salvar progresso"}</button><button className="outline-button" disabled={busy} type="button" onClick={() => void open(reading.content.id, false)}>Conferir progresso</button></div></form><p>Última confirmação: {reading.progress.percent}%.</p></section>
      <div className="reading-actions"><Link href={`/questoes?subject=${reading.content.subject}`}>Praticar esta disciplina</Link><Link href="/metas">Organizar minhas metas</Link></div>{!!reading.history.length && <details><summary>Leituras de versões anteriores</summary><ul>{reading.history.map(item => <li key={item.content_version_id}>Versão {item.content_version__version_number}: {item.percent}% · {new Date(item.recorded_at).toLocaleDateString("pt-BR")}</li>)}</ul></details>}
    </> : !loading && <><h2>Escolha sua próxima leitura</h2><p>Selecione um conteúdo publicado. A leitura e seu progresso ficam ligados à sua conta e à versão revisada.</p></>}</article></div>;
}
