"use client";

import {useEffect, useState} from "react";

import {apiRequest} from "@/lib/browser-api";
import {moduleInfo} from "@/lib/modules";
import {Icon, type IconName} from "./Icon";

export function ModuleWorkspace({module}: {module: string}) {
  const info = moduleInfo[module];
  return (
    <div className="workspace-page">
      <header className="workspace-heading"><span className="workspace-icon"><Icon name={info.icon}/></span><div><h1>{info.title}</h1><p>{info.description}</p></div></header>
      {module === "metas" && <GoalManager/>}
      {module === "arquivos" && <FileManager/>}
      {module === "consultor" && <Consultant/>}
      {module === "simulados" && <SimulationBuilder/>}
      {module === "questoes" && <QuestionPractice/>}
      {module === "estudar" && <StudyWorkspace/>}
      {module === "segunda-fase" && <SecondPhaseWorkspace/>}
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

function FileManager() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("");
  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    const data = new FormData(); data.append("file", file);
    setStatus("Enviando para quarentena…");
    const response = await apiRequest("/api/files/upload/", {method: "POST", body: data});
    setStatus(response.ok ? "Arquivo recebido. A verificação de segurança foi iniciada." : "O arquivo foi recusado. Confira tipo e tamanho.");
  }
  return <div className="workspace-grid"><section className="work-panel wide upload-panel"><span className="large-line-icon"><Icon name="upload"/></span><h2>Enviar documento</h2><p>PDF, DOCX, JPG, PNG ou TXT · limite de 25 MB. O download só é liberado após o antivírus.</p><form className="stack-form" onSubmit={upload}><label className="file-picker" htmlFor="document-upload"><span>{file?.name ?? "Selecionar arquivo"}</span><input accept=".pdf,.docx,.jpg,.jpeg,.png,.txt" id="document-upload" onChange={(event) => setFile(event.target.files?.[0] ?? null)} type="file"/></label><button className="primary-button" disabled={!file} type="submit">Enviar com segurança<Icon name="arrow"/></button><p aria-live="polite" className="form-notice">{status}</p></form></section><aside className="work-panel"><h2>Proteções aplicadas</h2><ul className="check-list"><li><Icon name="check"/>MIME verificado pelo conteúdo</li><li><Icon name="check"/>Quarentena e ClamAV</li><li><Icon name="check"/>Nome interno aleatório</li><li><Icon name="check"/>Acesso por URL temporária</li></ul></aside></div>;
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

function SimulationBuilder() {
  const [mode, setMode] = useState("formal");
  const explanations: Record<string, string> = {formal: "Assistente e gabarito bloqueados até a submissão.", training: "Pistas permitidas; explicações completas após responder.", free: "Explicações disponíveis durante todo o estudo."};
  return <div className="workspace-grid"><section className="work-panel wide"><h2>Configurar simulado</h2><fieldset className="mode-options"><legend>Modo</legend>{[["formal","Simulado formal"],["training","Treino"],["free","Estudo livre"]].map(([value,label]) => <label className={mode === value ? "mode-option selected" : "mode-option"} key={value}><input checked={mode === value} name="mode" onChange={() => setMode(value)} type="radio" value={value}/><span><strong>{label}</strong><small>{explanations[value]}</small></span></label>)}</fieldset><div className="form-grid"><label>Questões<select defaultValue="40"><option>20</option><option>40</option><option>80</option></select></label><label>Duração<select defaultValue="180"><option value="120">2 horas</option><option value="180">3 horas</option><option value="300">5 horas</option></select></label></div><button className="primary-button" type="button">Preparar simulado<Icon name="arrow"/></button></section><aside className="work-panel"><h2>Autosave</h2><p>Respostas, tempo e versão são registrados a cada checkpoint. Recarregar a página não apaga a tentativa.</p><span className="safe-status"><Icon name="check"/>Proteção ativa</span></aside></div>;
}

function QuestionPractice() {
  const [selected, setSelected] = useState("");
  return <div className="question-layout"><section className="question-sheet"><div className="question-meta"><span>Ética Profissional</span><span>Questão demonstrativa</span></div><h2>Selecione a alternativa que melhor corresponde ao enunciado versionado.</h2><div className="alternatives">{["A","B","C","D"].map((label) => <button className={selected === label ? "alternative selected" : "alternative"} key={label} onClick={() => setSelected(label)} type="button"><span>{label}</span>Alternativa de estudo {label}</button>)}</div><div className="question-actions"><button className="secondary-button" type="button">Pista</button><button className="primary-button" disabled={!selected} type="button">Responder<Icon name="arrow"/></button></div></section><aside className="source-rail"><h2>Referência</h2><p>A origem, a data da prova e a situação jurídica atual aparecem após a submissão.</p></aside></div>;
}

function StudyWorkspace() {
  return <div className="study-layout"><aside className="topic-rail"><h2>Matérias</h2>{["Ética Profissional","Constitucional","Administrativo","Civil"].map((item,index) => <button className={index === 0 ? "selected" : ""} key={item} type="button"><span>{String(index + 1).padStart(2,"0")}</span>{item}</button>)}</aside><article className="reading-surface"><span className="reading-source">Última revisão humana: pendente de conteúdo oficial</span><h2>Ética Profissional</h2><p>Este espaço reúne conteúdo versionado, tópicos, notas e referências. A versão publicada nunca substitui silenciosamente a anterior.</p><div className="reading-actions"><button type="button"><Icon name="note"/>Adicionar nota</button><button type="button"><Icon name="target"/>Criar meta</button><button type="button"><Icon name="chat"/>Consultar</button></div><EmptyState icon="book" title="Conteúdo em preparação" text="A importação do legado começa como não verificada e exige revisão humana antes de aparecer aqui."/></article></div>;
}

function SecondPhaseWorkspace() {
  return <div className="workspace-grid"><section className="work-panel wide"><h2>Editor de peça</h2><div className="piece-outline">{["Competência e endereçamento","Legitimidade","Preliminares","Fundamentos","Pedidos"].map((item,index) => <button key={item} type="button"><span>{index + 1}</span>{item}<Icon name="arrow"/></button>)}</div></section><aside className="work-panel"><h2>Gate de publicação</h2><ul className="check-list pending"><li>Peça determinável</li><li>Espelho versionado</li><li>Pontuação consistente</li><li>Fonte oficial</li><li>Revisão humana</li></ul></aside></div>;
}

function LibraryWorkspace() {
  return <section className="work-panel library-panel"><div className="library-search"><Icon name="search"/><label className="visually-hidden" htmlFor="library-query">Buscar na biblioteca</label><input id="library-query" placeholder="Buscar por tema, órgão ou referência…"/></div><div className="coverage-band"><Icon name="scales"/><span><strong>Cobertura mensurável</strong><small>Nenhuma jurisdição é declarada completa sem registro verificável.</small></span></div><EmptyState icon="library" title="Base pronta para fontes aprovadas" text="O painel exibirá documentos, períodos, falhas e porcentagem de cobertura por fonte."/></section>;
}

function SettingsWorkspace() {
  return <div className="workspace-grid"><section className="work-panel wide"><h2>Preferências de estudo</h2><label className="switch-row"><span><strong>Movimento reduzido</strong><small>Reduz animações não essenciais.</small></span><input type="checkbox"/></label><label className="switch-row"><span><strong>Densidade reduzida</strong><small>Aumenta o espaço entre controles.</small></span><input type="checkbox"/></label><label className="switch-row"><span><strong>Largura de leitura confortável</strong><small>Limita linhas longas de conteúdo.</small></span><input defaultChecked type="checkbox"/></label></section><aside className="work-panel"><h2>Privacidade</h2><button className="outline-button" type="button">Exportar meus dados</button><button className="outline-button danger" type="button">Solicitar exclusão</button></aside></div>;
}

function EmptyState({icon, title, text}: {icon: IconName; title: string; text: string}) {
  return <div className="empty-state"><span><Icon name={icon}/></span><h3>{title}</h3><p>{text}</p></div>;
}
