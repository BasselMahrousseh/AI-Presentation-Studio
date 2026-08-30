"use client";

import { useState } from "react";
import DashboardSidebar from "./(presentation-generator)/(dashboard)/Components/DashboardSidebar";
import DashboardPage from "./(presentation-generator)/(dashboard)/dashboard/components/DashboardPage";
import EandLightOverlay from "./components/EandLightOverlay";

const DashboardShell = () => {
  const [workspaceCollapsed, setWorkspaceCollapsed] = useState(false);

  return (
    <div className="relative flex min-h-screen overflow-hidden bg-[#fcfcfe]">
      <EandLightOverlay />
      <DashboardSidebar
        isWorkspaceCollapsed={workspaceCollapsed}
        onHomeToggle={() => setWorkspaceCollapsed((current) => !current)}
      />
      <div className="relative min-w-0 w-full">
        <DashboardPage workspaceSidebarCollapsed={workspaceCollapsed} />
      </div>
    </div>
  );
};

export default DashboardShell;
