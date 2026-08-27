"use client";

import Image from "next/image";
import Link from "next/link";
import {useSearchParams} from "next/navigation";
import {useState} from "react";

import {apiRequest} from "@/lib/browser-api";
import {Icon} from "./Icon";

export function PasswordResetForm() {
  const search = useSearchParams();
  const uid = search.get("uid") ?? "";
  const token = search.get("token") ?? "";
  const confirmation = Boolean(uid && token);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const response = await apiRequest(confirmation ? "/api/auth/password-reset/confirm" : "/api/auth/password-reset", {
      method: "POST",
      body: JSON.stringify(confirmation ? {uid, token, new_password: password} : {email}),
    });
    setNotice(response.ok ? (confirmation ? "Senha atualizada. Você já pode entrar." : "Se a conta existir, enviaremos as instruções.") : "Não foi possível concluir. Confira os dados ou solicite um novo link.");
  }

  return <main className="login-page"><div className="login-cave" aria-hidden="true"/><section className="login-panel"><header className="login-brand"><Image alt="Símbolo do Kairós" height={68} priority src="/app/simbolo.png" width={62}/><span>Kairós</span></header><div className="login-copy"><h1>{confirmation ? "Crie uma nova senha." : "Recupere seu acesso."}</h1><p>{confirmation ? "Use uma frase longa e exclusiva para o Kairós." : "O link será enviado somente se o SMTP estiver configurado e a conta existir."}</p></div><form className="login-form" onSubmit={submit}>{confirmation ? <label>Nova senha<input autoComplete="new-password" minLength={12} onChange={(event) => setPassword(event.target.value)} required type="password" value={password}/></label> : <label>E-mail da conta<input autoComplete="email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email}/></label>}<button className="primary-button" type="submit">{confirmation ? "Atualizar senha" : "Solicitar link"}<Icon name="arrow"/></button><Link className="text-link" href="/entrar">Voltar para entrar</Link></form><p aria-live="polite" className="login-notice">{notice}</p></section></main>;
}
