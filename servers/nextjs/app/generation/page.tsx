import { requireAppSession } from "@/utils/serverAuth";
import { ConfigurationInitializer } from "../ConfigurationInitializer";
import GenerationPageClient from "./GenerationPageClient";

export const metadata = {
  title: "e& Present | Presentation Studio",
  description: "Create an e& Etisalat presentation with AI.",
};

export default async function GenerationPage() {
  await requireAppSession();

  return (
    <ConfigurationInitializer>
      <GenerationPageClient />
    </ConfigurationInitializer>
  );
}
