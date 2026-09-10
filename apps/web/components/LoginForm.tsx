"use client";

import Image from "next/image";
import Link from "next/link";
import {useRouter} from "next/navigation";
import {useState, useSyncExternalStore} from "react";

import {apiRequest} from "@/lib/browser-api";
import {Icon} from "./Icon";

type LoginStage = "password" | "totp" | "setup" | "verify";

const subscribeReady = () => () => {};
const clientReady = () => true;
const serverReady = () => false;

export function LoginForm() {
  const router = useRouter();
  const ready = useSyncExternalStore(subscribeReady, clientReady, serverReady);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [stage, setStage] = useState<LoginStage>("password");
  const [secret, setSecret] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  function completeLogin() {
    // A fixed destination preserves the editorial journey without accepting arbitrary redirects.
    if (new URLSearchParams(window.location.search).get("editorial") === "1") {
      window.location.assign(new URL("/admin/editorial/", window.location.origin).href);
    } else router.push("/");
  }

  async function submitLogin(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setNotice("");
    const response = await apiRequest("/api/auth/login", {method: "POST", body: JSON.stringify({username, password, totp})});
    const payload = await response.json();
    if (response.ok) completeLogin();
    else if (payload.mfa_setup_required) {setStage("setup"); setNotice("Configure o segundo fator para proteger a conta administrativa.");}
    else if (payload.mfa_required) {setStage("totp"); setNotice("Digite o código do seu autenticador.");}
    else setNotice(payload.detail ?? "Não foi possível entrar.");
    setBusy(false);
  }

  async function startSetup() {
    setBusy(true);
    const response = await apiRequest("/api/auth/mfa/setup", {method: "POST", body: "{}"});
    const payload = await response.json();
    if (response.ok) {setSecret(payload.secret); setStage("verify"); setNotice("Adicione a chave no autenticador e confirme um código.");}
    else setNotice("Não foi possível iniciar a configuração MFA.");
    setBusy(false);
  }

  async function verifySetup(event: React.FormEvent) {
    event.preventDefault(); setBusy(true);
    const response = await apiRequest("/api/auth/mfa/verify", {method: "POST", body: JSON.stringify({totp})});
    if (response.ok) completeLogin();
    else setNotice("Código inválido. Aguarde o próximo código e tente novamente.");
    setBusy(false);
  }

  return <main className="login-page"><div className="login-cave" aria-hidden="true"/><section className="login-panel"><header className="login-brand"><Image alt="Símbolo do Kairós" height={74} priority src="/app/simbolo.png" width={66}/><span>Kairós</span></header><div className="login-copy"><h1>Entre no seu tempo de estudo.</h1><p>Seu progresso, notas e arquivos permanecem ligados somente à sua conta.</p></div>{stage === "setup" ? <div className="mfa-setup"><h2>Proteja sua conta</h2><p>Contas administrativas exigem um aplicativo autenticador.</p><button className="primary-button" disabled={busy || !ready} onClick={startSetup} type="button">Configurar MFA<Icon name="arrow"/></button></div> : stage === "verify" ? <form className="login-form" onSubmit={verifySetup}><label>Chave de configuração<input readOnly value={secret}/></label><label>Código de 6 dígitos<input disabled={!ready} autoComplete="one-time-code" inputMode="numeric" maxLength={6} onChange={(event) => setTotp(event.target.value)} required value={totp}/></label><button className="primary-button" disabled={busy || !ready} type="submit">Confirmar e entrar<Icon name="arrow"/></button></form> : <form className="login-form" onSubmit={submitLogin}><label>Usuário<input disabled={!ready} autoComplete="username" onChange={(event) => setUsername(event.target.value)} required value={username}/></label><label>Senha<input disabled={!ready} autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} required type="password" value={password}/></label>{stage === "totp" && <label>Código do autenticador<input disabled={!ready} autoComplete="one-time-code" autoFocus inputMode="numeric" maxLength={6} onChange={(event) => setTotp(event.target.value)} required value={totp}/></label>}<button className="primary-button" disabled={busy || !ready} type="submit">{busy ? "Verificando…" : "Entrar"}<Icon name="arrow"/></button><Link className="text-link" href="/redefinir-senha">Esqueci minha senha</Link></form>}<p aria-live="polite" className="login-notice">{notice}</p></section></main>;
}
