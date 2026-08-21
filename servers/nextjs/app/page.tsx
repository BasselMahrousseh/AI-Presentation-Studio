import Index from "./frontend/index";
export const metadata = {
  title: "Presentation Studio",
  description: "Presentation Studio workspace.",
};

/**
 * Standalone App Router entry point for the custom frontend.
 * Build the new experience here without inheriting the presentation app layout.
 */


export default function FrontendPage() {
  return (
    <div>
      <Index />
    </div>
  );
}
