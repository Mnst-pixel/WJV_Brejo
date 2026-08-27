import {AppShell} from "@/components/AppShell";
import {Dashboard} from "@/components/Dashboard";
import {requireUser} from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const user = await requireUser();
  const name = user.display_name || user.username;
  return <AppShell userName={name}><Dashboard userName={name}/></AppShell>;
}
