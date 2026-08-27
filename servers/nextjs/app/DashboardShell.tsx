"use client";

import { useState } from "react";
import DashboardSidebar from "./(presentation-generator)/(dashboard)/Components/DashboardSidebar";
import DashboardPage from "./(presentation-generator)/(dashboard)/dashboard/components/DashboardPage";

const DashboardShell = () => {
  const [workspaceCollapsed, setWorkspaceCollapsed] = useState(false);

  return (
    <div className="flex min-h-screen bg-white">
      <DashboardSidebar
        isWorkspaceCollapsed={workspaceCollapsed}
        onHomeToggle={() => setWorkspaceCollapsed((current) => !current)}
      />
      <div className="min-w-0 w-full">
        <DashboardPage workspaceSidebarCollapsed={workspaceCollapsed} />
      </div>
    </div>
  );
};

export default DashboardShell;
