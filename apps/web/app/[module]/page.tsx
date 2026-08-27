import {notFound} from "next/navigation";

import {AppShell} from "@/components/AppShell";
import {ModuleWorkspace} from "@/components/ModuleWorkspace";
import {moduleInfo} from "@/lib/modules";
import {requireUser} from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function ModulePage({params}: {params: Promise<{module: string}>}) {
  const {module} = await params;
  if (!moduleInfo[module]) notFound();
  const user = await requireUser();
  return <AppShell userName={user.display_name || user.username}><ModuleWorkspace module={module}/></AppShell>;
}
