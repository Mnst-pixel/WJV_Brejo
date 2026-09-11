"use client";

import {useState} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {NotesWorkspace} from "./NotesWorkspace";
import {ReadingWorkspace} from "./ReadingWorkspace";
import "./notes.css";

export function LibraryWorkspace() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = params.get("aba") === "notas" ? "notas" : "leituras";
  const [dirty, setDirty] = useState(false);
  return <><nav className="reading-actions library-navigation" aria-label="Áreas da biblioteca">{(["leituras", "notas"] as const).map(value => <button key={value} type="button" className={tab === value ? "primary-button" : "outline-button"} aria-current={tab === value ? "page" : undefined} disabled={dirty || tab === value} onClick={() => router.replace("/biblioteca?aba=" + value)}>{value === "leituras" ? "Leituras publicadas" : "Minhas anotações"}</button>)}</nav>{dirty && <p role="status">Salve ou descarte as alterações da anotação antes de trocar de área.</p>}{tab === "leituras" && <ReadingWorkspace/>}{tab === "notas" && <NotesWorkspace onDirty={setDirty}/>}</>;
}
