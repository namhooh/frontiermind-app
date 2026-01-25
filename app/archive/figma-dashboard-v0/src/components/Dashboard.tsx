import { useState } from "react";
import { Sidebar } from "./Sidebar";
import { MainContent } from "./MainContent";

export function Dashboard() {
  const [activeSection, setActiveSection] = useState("overview");

  return (
    <div className="flex h-screen bg-slate-50">
      <Sidebar activeSection={activeSection} onSectionChange={setActiveSection} />
      <MainContent activeSection={activeSection} onSectionChange={setActiveSection} />
    </div>
  );
}