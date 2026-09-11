"use client";

import {useCallback, useState} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {NotesWorkspace} from "./NotesWorkspace";
import {ReadingWorkspace} from "./ReadingWorkspace";
import {FlashcardsWorkspace} from "./FlashcardsWorkspace";
import "./notes.css";

export function LibraryWorkspace() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = params.get("aba") === "notas" ? "notas" : params.get("aba") === "flashcards" ? "flashcards" : "leituras";
  const [pendingArea, setPendingArea] = useState({tab: "", dirty: false});
  const dirty = pendingArea.tab === tab && pendingArea.dirty;
  const setDirty = useCallback((value: boolean) => setPendingArea({tab, dirty: value}), [tab]);
  return <><nav className="reading-actions library-navigation" aria-label="Áreas da biblioteca">{(["leituras", "notas", "flashcards"] as const).map(value => <button key={value} type="button" className={tab === value ? "primary-button" : "outline-button"} aria-current={tab === value ? "page" : undefined} disabled={dirty || tab === value} onClick={() => router.replace("/biblioteca?aba=" + value)}>{value === "leituras" ? "Leituras publicadas" : value === "notas" ? "Minhas anotações" : "Meus flashcards"}</button>)}</nav>{dirty && <p role="status">Salve ou descarte as alterações antes de trocar de área.</p>}{tab === "leituras" && <ReadingWorkspace/>}{tab === "notas" && <NotesWorkspace onDirty={setDirty}/>}{tab === "flashcards" && <FlashcardsWorkspace onDirty={setDirty}/>}</>;
}
