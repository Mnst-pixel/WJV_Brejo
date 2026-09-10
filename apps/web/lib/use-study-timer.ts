"use client";
import {useEffect, useState} from "react";
import {apiRequest} from "./browser-api";

type Panel = {id?: string; version: number; pomodoro_status: "idle" | "running" | "paused"; effective_remaining_seconds: number; study_session_id: string | null};

export function useStudyTimer() {
  const [panel, setPanel] = useState<Panel | null>(null);
  const [seconds, setSeconds] = useState(1500);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const running = panel?.pomodoro_status === "running" && seconds > 0;
  useEffect(() => {
    let active = true;
    void apiRequest("/api/study/panel/").then(async response => {
      if (!response.ok) throw new Error();
      const current = await response.json() as Panel;
      if (active) {setPanel(current); setSeconds(current.effective_remaining_seconds);}
    }).catch(() => {if (active) setNotice("Não foi possível retomar o cronômetro.");});
    return () => {active = false;};
  }, []);
  useEffect(() => {
    if (!panel || panel.pomodoro_status !== "running") return;
    const endsAt = Date.now() + panel.effective_remaining_seconds * 1000;
    const timer = window.setInterval(() => setSeconds(Math.max(0, Math.ceil((endsAt - Date.now()) / 1000))), 500);
    return () => window.clearInterval(timer);
  }, [panel]);

  async function change(reset = false) {
    if (!panel || busy) return;
    setBusy(true);
    try {
      const response = await apiRequest("/api/study/panel/", {method: "PUT", body: JSON.stringify({
        last_panel: "dashboard", pomodoro_status: reset ? "idle" : running ? "paused" : "running",
        remaining_seconds: reset || seconds === 0 ? 1500 : seconds, expected_version: panel.version,
        study_session: panel.study_session_id,
      })});
      if (response.status === 409) {
        const current = await apiRequest("/api/study/panel/");
        if (!current.ok) throw new Error();
        const value = await current.json() as Panel;
        setPanel(value); setSeconds(value.effective_remaining_seconds);
        setNotice("O cronômetro foi alterado em outra janela. Estado atualizado.");
      } else {
        if (!response.ok) throw new Error();
        const value = await response.json() as Panel;
        setPanel(value); setSeconds(value.effective_remaining_seconds); setNotice("Salvo na sua conta.");
      }
    } catch {setNotice("Não foi possível salvar o cronômetro. Tente novamente.");}
    finally {setBusy(false);}
  }
  return {seconds, running, disabled: !panel || busy, notice, toggle: () => change(), reset: () => change(true)};
}
