import { OverviewSection } from "./sections/OverviewSection";
import { IntegrationStatusSection } from "./sections/IntegrationStatusSection";
import { GenerationSection } from "./sections/GenerationSection";
import { PricingSection } from "./sections/PricingSection";
import { RegulationsSection } from "./sections/RegulationsSection";
import { ContractsSection } from "./sections/ContractsSection";
import { IntegrationsSection } from "./sections/IntegrationsSection";
import { CalendarSection } from "./sections/CalendarSection";
import { SettingsSection } from "./sections/SettingsSection";
import { PPASummarySection } from "./sections/PPASummarySection";

interface MainContentProps {
  activeSection: string;
  onSectionChange: (section: string) => void;
}

export function MainContent({ activeSection, onSectionChange }: MainContentProps) {
  return (
    <div className="flex-1 overflow-auto">
      {activeSection === "overview" && <OverviewSection onSectionChange={onSectionChange} />}
      {activeSection === "integration-status" && <IntegrationStatusSection onSectionChange={onSectionChange} />}
      {activeSection === "generation" && <GenerationSection onSectionChange={onSectionChange} />}
      {activeSection === "pricing" && <PricingSection onSectionChange={onSectionChange} />}
      {activeSection === "regulations" && <RegulationsSection onSectionChange={onSectionChange} />}
      {activeSection === "contracts" && <ContractsSection onSectionChange={onSectionChange} />}
      {activeSection === "integrations" && <IntegrationsSection />}
      {activeSection === "calendar" && <CalendarSection />}
      {activeSection === "settings" && <SettingsSection />}
      {activeSection === "ppa-summary" && <PPASummarySection onSectionChange={onSectionChange} />}
    </div>
  );
}