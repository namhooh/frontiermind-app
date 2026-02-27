import MarketingHeader from "./components/MarketingHeader";
import HeroSection from "./components/HeroSection";
import ValuePropSection from "./components/ValuePropSection";
//import HowItWorksSection from "./components/HowItWorksSection";
import CTASection from "./components/CTASection";
import MarketingFooter from "./components/MarketingFooter";

export default function Home() {
  return (
    <>
      <MarketingHeader />
      <main>
        <HeroSection />
        <ValuePropSection />
        <CTASection />
      </main>
      <MarketingFooter />
    </>
  );
}
