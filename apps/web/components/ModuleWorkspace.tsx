"use client";

import {useCallback, useEffect, useRef, useState} from "react";

import {apiRequest} from "@/lib/browser-api";
import {moduleInfo} from "@/lib/modules";
import {useStudyPreferences} from "@/lib/use-study-preferences";
import {Icon, type IconName} from "./Icon";
import {QuestionPractice} from "./QuestionPractice";
import {SimulationWorkspace} from "./SimulationWorkspace";
import {WrittenExamWorkspace} from "./WrittenExamWorkspace";

export function ModuleWorkspace({module}: {module: string}) {
  const info = moduleInfo[module];
  return (
    <div className="workspace-page">
      <header className="workspace-heading"><span className="workspace-icon"><Icon name={info.icon}/></span><div><h1>{info.title}</h1><p>{info.description}</p></div></header>
      {module === "metas" && <GoalManager/>}
      {module === "arquivos" && <FileManager/>}
      {module === "consultor" && <Consultant/>}
      {module === "simulados" && <SimulationWorkspace/>}
      {module === "questoes" && <QuestionPractice/>}
      {module === "estudar" && <StudyWorkspace/>}
      {module === "segunda-fase" && <WrittenExamWorkspace/>}
      {module === "biblioteca" && <LibraryWorkspace/>}
      {module === "configuracoes" && <SettingsWorkspace/>}
    </div>
  );
}

type Goal = {id: string; title: string; description: string; progress: number};

function GoalManager() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [title, setTitle] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    fetch("/api/goals/", {credentials: "include"}).then(async (response) => {
      if (response.ok) {
        const payload = await response.json() as {results?: Goal[]} | Goal[];
        setGoals(Array.isArray(payload) ? payload : payload.results ?? []);
      }
    }).catch(() => undefined);
  }, []);

  async function createGoal(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    const response = await apiRequest("/api/goals/", {method: "POST", body: JSON.stringify({title, description: "", progress: 0})});
    if (response.ok) {
      const goal = await response.json() as Goal;
      setGoals((items) => [goal, ...items]);
      setTitle("");
      setNotice("Meta criada e salva.");
    } else setNotice("Não foi possível salvar a meta.");
  }

  return <div className="workspace-grid"><section className="work-panel"><h2>Nova meta</h2><form className="stack-form" onSubmit={createGoal}><label htmlFor="goal-title">O que você quer concluir?</label><input id="goal-title" onChange={(event) => setTitle(event.target.value)} placeholder="Ex.: revisar Ética até sexta" value={title}/><button className="primary-button" type="submit">Adicionar meta<Icon name="arrow"/></button><p aria-live="polite" className="form-notice">{notice}</p></form></section><section className="work-panel wide"><div className="work-panel-heading"><h2>Em andamento</h2><span>{goals.length} {goals.length === 1 ? "meta" : "metas"}</span></div><div className="open-list">{goals.length ? goals.map((goal) => <article className="open-row" key={goal.id}><span className="row-icon"><Icon name="target"/></span><div><h3>{goal.title}</h3><p>{goal.description || "Sem descrição adicional"}</p><div className="mini-progress"><span style={{width: `${goal.progress}%`}}/></div></div><strong>{goal.progress}%</strong></article>) : <EmptyState icon="target" title="Sua próxima meta começa aqui" text="Crie uma meta objetiva; o progresso ficará ligado à sua conta."/>}</div></section></div>;
}

type StoredFile = {id: string; original_name: string; size_bytes: number; scan_status: string; processing_status: string};
const fileStates: Record<string, string> = {receiving: "Recebendo", quarantined: "Aguardando verificação", processing: "Verificando e processando", retry_pending: "Nova tentativa programada", processed_pending_review: "Disponível para seu uso privado", rejected: "Arquivo recusado", processing_failed: "Não foi possível processar", upload_failed: "Envio incompleto", delete_pending: "Exclusão em andamento", deleted: "Excluído"};

function FileManager() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("");
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [nextPage, setNextPage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const listVersion = useRef(0);
  const input = useRef<HTMLInputElement>(null);

  const loadFiles = useCallback(async (next?: string) => {
    const version = ++listVersion.current;
    try {
      const url = new URL(next ?? "/api/files/", window.location.origin);
      if (url.origin !== window.location.origin || url.pathname !== "/api/files/") throw new Error();
      const response = await apiRequest(url.pathname + url.search);
      if (!response.ok) throw new Error();
      const payload = await response.json() as {results: StoredFile[]; next?: string | null} | StoredFile[];
      if (version !== listVersion.current) return;
      const rows = Array.isArray(payload) ? payload : payload.results;
      setFiles(items => next ? [...items.filter(item => !rows.some(row => row.id === item.id)), ...rows] : rows);
      setNextPage(Array.isArray(payload) ? null : payload.next ?? null);
    } catch {if (version === listVersion.current) setStatus("Não foi possível carregar os arquivos. Use Atualizar para tentar novamente.");}
    finally {if (version === listVersion.current) setLoading(false);}
  }, []);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {if (active) return loadFiles();});
    return () => {active = false; listVersion.current += 1;};
  }, [loadFiles]);

  const pendingIds = files.filter(item => ["receiving", "quarantined", "processing", "retry_pending"].includes(item.processing_status)).map(item => item.id).join(",");
  useEffect(() => {
    if (!pendingIds) return;
    let active = true;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void Promise.all(pendingIds.split(",").slice(0, 10).map(async id => {
        const response = await apiRequest(`/api/files/${id}/`);
        if (!response.ok) return;
        const updated = await response.json() as StoredFile;
        if (active) setFiles(items => items.map(item => item.id === updated.id ? updated : item));
      })).catch(() => {if (active) setStatus("A atualização automática está indisponível. Você pode tentar Atualizar.");});
    }, 5000);
    return () => {active = false; window.clearInterval(timer);};
  }, [pendingIds]);

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    const data = new FormData(); data.append("file", file);
    setBusy("upload");
    setStatus("Enviando para quarentena…");
    try {
      const response = await apiRequest("/api/files/upload/", {method: "POST", body: data});
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as {error?: {detail?: {file?: string[] | string; detail?: string}}} | null;
        const reason = payload?.error?.detail?.file ?? payload?.error?.detail?.detail;
        setStatus(typeof reason === "string" ? reason : Array.isArray(reason) ? reason.join(" ") : "O arquivo foi recusado. Confira seu plano, quota, tipo e tamanho.");
        return;
      }
      setFile(null);
      if (input.current) input.current.value = "";
      setStatus("Arquivo recebido. Acompanhe a verificação na lista abaixo.");
      await loadFiles();
    } catch {setStatus("O envio não pôde ser confirmado. Atualize a lista antes de tentar novamente.");}
    finally {setBusy(null);}
  }

  async function download(item: StoredFile) {
    if (busy) return;
    setBusy(item.id);
    setStatus("Preparando acesso temporário…");
    try {
      const response = await apiRequest(`/api/files/${item.id}/download/`);
      if (!response.ok) throw new Error();
      const payload = await response.json() as {url: string};
      const url = new URL(payload.url, window.location.origin);
      if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/files/")) throw new Error();
      window.location.assign(url.href);
      setStatus("Acesso temporário preparado.");
    } catch {setStatus("Não foi possível liberar o arquivo. Atualize o estado e tente novamente.");}
    finally {setBusy(null);}
  }

  async function remove(item: StoredFile) {
    if (busy) return;
    setBusy(item.id);
    try {
      const response = await apiRequest(`/api/files/${item.id}/`, {method: "DELETE"});
      if (!response.ok) throw new Error();
      setFiles(items => items.filter(row => row.id !== item.id));
      setStatus("Exclusão registrada. A limpeza segura pode levar alguns minutos.");
    } catch {setStatus("Não foi possível confirmar a exclusão. Atualize a lista antes de tentar novamente.");}
    finally {setBusy(null);}
  }

  return <div className="workspace-grid"><section className="work-panel wide upload-panel"><span className="large-line-icon"><Icon name="upload"/></span><h2>Enviar documento</h2><p>PDF, DOCX, JPG, PNG ou TXT · até 25 MB, conforme seu plano e quota. O download exige verificação de segurança e processamento concluídos.</p><form className="stack-form" onSubmit={upload}><label className="file-picker" htmlFor="document-upload"><span>{file?.name ?? "Selecionar arquivo"}</span><input ref={input} accept=".pdf,.docx,.jpg,.jpeg,.png,.txt" disabled={busy !== null} id="document-upload" onChange={(event) => setFile(event.target.files?.[0] ?? null)} type="file"/></label><button className="primary-button" disabled={!file || busy !== null} type="submit">{busy === "upload" ? "Enviando…" : "Enviar com segurança"}<Icon name="arrow"/></button><p aria-live="polite" className="form-notice">{status}</p></form></section><aside className="work-panel"><h2>Proteções aplicadas</h2><ul className="check-list"><li><Icon name="check"/>MIME verificado pelo conteúdo</li><li><Icon name="check"/>Quarentena e ClamAV</li><li><Icon name="check"/>Nome interno aleatório</li><li><Icon name="check"/>Acesso por URL temporária</li></ul></aside><section className="work-panel wide"><div className="work-panel-heading"><h2>Seus arquivos</h2><button className="outline-button" disabled={loading || busy !== null} onClick={() => void loadFiles()} type="button">{loading ? "Carregando…" : "Atualizar"}</button></div><div className="open-list">{files.map(item => <article className="open-row" key={item.id}><span className="row-icon"><Icon name="document"/></span><div><h3>{item.original_name}</h3><p>{(item.size_bytes / 1024 / 1024).toLocaleString("pt-BR", {maximumFractionDigits: 2})} MB · {fileStates[item.processing_status] ?? "Verificação pendente"}</p><button className="outline-button" disabled={busy !== null || loading || item.scan_status !== "clean" || item.processing_status !== "processed_pending_review"} onClick={() => void download(item)} type="button">Abrir arquivo</button><button className="outline-button danger" disabled={busy !== null || loading} onClick={() => void remove(item)} type="button">Excluir</button></div></article>)}{!loading && !files.length && <EmptyState icon="folder" title="Nenhum arquivo listado" text="Seus documentos enviados aparecerão aqui, associados à sua conta."/>}</div>{nextPage && <button className="outline-button" disabled={loading || busy !== null} onClick={() => void loadFiles(nextPage)} type="button">Carregar mais</button>}</section></div>;
}

function Consultant() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  async function ask(event: React.FormEvent) {
    event.preventDefault(); if (!question.trim()) return;
    setLoading(true); setAnswer("");
    const response = await apiRequest("/api/ai/consult", {method: "POST", body: JSON.stringify({question, action: "consult", context: {page: "consultor"}})});
    const payload = await response.json();
    setAnswer(response.ok ? payload.answer : payload.error?.detail?.detail ?? "Não foi possível consultar agora. Seus outros módulos continuam disponíveis.");
    setLoading(false);
  }
  return <div className="consult-layout"><section className="consult-thread"><div className="oracle-intro"><span><Icon name="scales"/></span><div><h2>Pesquisa assistida, não resposta sem fonte</h2><p>O Kairós procura evidência aprovada e informa quando ela não é suficiente.</p></div></div>{answer && <article aria-live="polite" className="assistant-answer"><strong>Kairós</strong><p>{answer}</p></article>}<form className="consult-form" onSubmit={ask}><label className="visually-hidden" htmlFor="legal-question">Pergunta jurídica</label><textarea id="legal-question" onChange={(event) => setQuestion(event.target.value)} placeholder="Digite sua dúvida jurídica…" rows={4} value={question}/><div><small>Verifique as fontes antes de usar a resposta.</small><button className="primary-button" disabled={loading} type="submit">{loading ? "Consultando…" : "Consultar"}<Icon name="arrow"/></button></div></form></section><aside className="source-rail"><h2>O que a resposta inclui</h2><ul className="check-list"><li><Icon name="check"/>Fonte e órgão</li><li><Icon name="check"/>Data de referência</li><li><Icon name="check"/>Situação temporal</li><li><Icon name="check"/>Nível de confiança</li></ul></aside></div>;
}

function StudyWorkspace() {
  return <div className="study-layout"><aside className="topic-rail"><h2>Matérias</h2>{["Ética Profissional","Constitucional","Administrativo","Civil"].map((item,index) => <button className={index === 0 ? "selected" : ""} key={item} type="button"><span>{String(index + 1).padStart(2,"0")}</span>{item}</button>)}</aside><article className="reading-surface"><span className="reading-source">Última revisão humana: pendente de conteúdo oficial</span><h2>Ética Profissional</h2><p>Este espaço reúne conteúdo versionado, tópicos, notas e referências. A versão publicada nunca substitui silenciosamente a anterior.</p><div className="reading-actions"><button type="button"><Icon name="note"/>Adicionar nota</button><button type="button"><Icon name="target"/>Criar meta</button><button type="button"><Icon name="chat"/>Consultar</button></div><EmptyState icon="book" title="Conteúdo em preparação" text="A importação do legado começa como não verificada e exige revisão humana antes de aparecer aqui."/></article></div>;
}

function LibraryWorkspace() {
  return <section className="work-panel library-panel"><div className="library-search"><Icon name="search"/><label className="visually-hidden" htmlFor="library-query">Buscar na biblioteca</label><input id="library-query" placeholder="Buscar por tema, órgão ou referência…"/></div><div className="coverage-band"><Icon name="scales"/><span><strong>Cobertura mensurável</strong><small>Nenhuma jurisdição é declarada completa sem registro verificável.</small></span></div><EmptyState icon="library" title="Base pronta para fontes aprovadas" text="O painel exibirá documentos, períodos, falhas e porcentagem de cobertura por fonte."/></section>;
}

function SettingsWorkspace() {
  const {preferences, save, disabled, notice} = useStudyPreferences();
  const [integrations, setIntegrations] = useState<Record<string, {state: string; external_blocker: boolean}> | null>(null);
  const [integrationNotice, setIntegrationNotice] = useState("Carregando estado das integrações…");
  useEffect(() => {
    const controller = new AbortController();
    void apiRequest("/api/integrations/status/", {signal: controller.signal}).then(async response => {
      if (!response.ok) throw new Error();
      const payload = await response.json();
      if (!controller.signal.aborted) {setIntegrations(payload); setIntegrationNotice("");}
    }).catch(() => {if (!controller.signal.aborted) setIntegrationNotice("Não foi possível consultar as integrações. Recarregue a página para tentar novamente.");});
    return () => controller.abort();
  }, []);
  const names: Record<string, string> = {smtp: "E-mail", inlabs: "Diário Oficial (INLABS)", datajud: "DataJud", offhost: "Backup externo"};
  return <div className="workspace-grid"><section className="work-panel wide"><h2>Preferências de estudo</h2><label className="switch-row"><span><strong>Movimento reduzido</strong><small>Reduz animações não essenciais.</small></span><input checked={preferences.reduced_motion ?? false} disabled={disabled} onChange={event => void save({reduced_motion: event.target.checked})} type="checkbox"/></label><label className="switch-row"><span><strong>Densidade reduzida</strong><small>Aumenta o espaço entre controles.</small></span><input checked={preferences.reduced_density ?? false} disabled={disabled} onChange={event => void save({reduced_density: event.target.checked})} type="checkbox"/></label><label className="switch-row"><span><strong>Largura de leitura confortável</strong><small>Limita linhas longas de conteúdo.</small></span><input checked={preferences.comfortable_reading ?? false} disabled={disabled} onChange={event => void save({comfortable_reading: event.target.checked})} type="checkbox"/></label><p aria-live="polite" className="form-notice">{notice}</p></section><aside className="work-panel"><h2>Privacidade</h2><button className="outline-button" disabled type="button">Exportar meus dados</button><button className="outline-button danger" disabled type="button">Solicitar exclusão</button><p>Estas solicitações ainda não estão disponíveis por esta tela.</p></aside><section className="work-panel wide"><h2>Integrações</h2><p>Uma integração pendente não impede o uso dos módulos independentes.</p><p aria-live="polite" className="form-notice">{integrationNotice}</p>{integrations && <ul className="check-list">{Object.entries(names).map(([key, label]) => <li key={key}><span><strong>{label}</strong> · {integrations[key]?.state === "configured_unverified" ? "Configurada; validação operacional pendente" : integrations[key]?.state === "unconfigured" ? "Aguardando configuração externa" : "Estado indisponível"}</span></li>)}</ul>}</section></div>;
}

function EmptyState({icon, title, text}: {icon: IconName; title: string; text: string}) {
  return <div className="empty-state"><span><Icon name={icon}/></span><h3>{title}</h3><p>{text}</p></div>;
}
