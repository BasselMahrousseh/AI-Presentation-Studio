import { requireAppSession } from "@/utils/serverAuth";
import { ConfigurationInitializer } from "./ConfigurationInitializer";
import DashboardShell from "./DashboardShell";

export const metadata = {
  title: "e& Presentation Workspace",
  description: "Manage and create e& Etisalat presentations.",
};

export default async function HomePage() {
  await requireAppSession();

  return (
    <ConfigurationInitializer>
      <DashboardShell />
    </ConfigurationInitializer>
  );
}
