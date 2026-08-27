import {Suspense} from "react";

import {PasswordResetForm} from "@/components/PasswordResetForm";

export default function ResetPage() {
  return <Suspense fallback={<main className="login-page">Carregando…</main>}><PasswordResetForm/></Suspense>;
}
