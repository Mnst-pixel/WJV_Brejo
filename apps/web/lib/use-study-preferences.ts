"use client";

import {useEffect, useState} from "react";
import {apiRequest} from "./browser-api";

export type StudyPreferences = {reduced_motion?: boolean; reduced_density?: boolean; comfortable_reading?: boolean; focus_mode?: boolean; text_scale?: number};

export function useStudyPreferences() {
  const [preferences, setPreferences] = useState<StudyPreferences>({});
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    const sync = () => {void apiRequest("/api/auth/me").then(async response => {
      if (!response.ok) throw new Error();
      const value = await response.json();
      if (active) {setPreferences(value.preferences ?? {}); setReady(true);}
    }).catch(() => {if (active) setNotice("Não foi possível carregar suas preferências.");});};
    sync();
    window.addEventListener("kairos-preferences", sync);
    return () => {active = false; window.removeEventListener("kairos-preferences", sync);};
  }, []);

  async function save(change: StudyPreferences) {
    if (!ready || saving) return;
    setSaving(true);
    try {
      const response = await apiRequest("/api/auth/me", {method: "PATCH", body: JSON.stringify({preferences: change})});
      if (!response.ok) throw new Error();
      setPreferences((await response.json()).preferences);
      setNotice("Preferências salvas na sua conta.");
      window.dispatchEvent(new Event("kairos-preferences"));
    } catch {setNotice("Não foi possível salvar. Tente novamente.");}
    finally {setSaving(false);}
  }
  return {preferences, save, disabled: !ready || saving, notice};
}
