import Link from "next/link";
import Index from "./frontend/index";
export const metadata = {
  title: "Frontend Workspace | Presenton",
  description: "A standalone workspace for the custom frontend.",
};

/**
 * Standalone App Router entry point for the custom frontend.
 * Build the new experience here without inheriting the presentation app layout.
 */


export default function FrontendPage() {
  return (
    <div>
        <Index></Index>
    </div>
  );
}
