import "./App.css";
import "./parity.css";
import { useEffect, useState } from "react";
import { getExceptions } from "./api";
import { Shell } from "./components/Shell";
import { ExceptionsScreen } from "./screens/Exceptions";
import { MappingReviewScreen } from "./screens/MappingReview";
import { MappingsScreen } from "./screens/Mappings";
import { OnboardingScreen } from "./screens/Onboarding";
import { OverviewScreen } from "./screens/Overview";
import { ProcessPanel } from "./components/ProcessPanel";
import { RulesScreen } from "./screens/Rules";

function App() {
  const [screen, setScreen] = useState("Overview");
  const [apiUp, setApiUp] = useState(true);
  const [review, setReview] = useState<{
    ats: string;
    payloadType: string;
    version: number;
  } | null>(null);
  const openReview = (ats: string, payloadType: string, version: number) => {
    setReview({ ats, payloadType, version });
    setScreen("Review");
  };
  useEffect(() => {
    const refresh = () => {
      void getExceptions()
        .then(() => setApiUp(true))
        .catch(() => setApiUp(false));
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, []);
  const content =
    screen === "Exceptions" ? (
      <ExceptionsScreen />
    ) : screen === "Mappings" ? (
      <MappingsScreen onReview={openReview} />
    ) : screen === "Onboard" ? (
      <OnboardingScreen onReview={openReview} />
    ) : screen === "Validation" ? (
      <RulesScreen />
    ) : screen === "Review" && review ? (
      <MappingReviewScreen {...review} onDone={() => setScreen("Mappings")} />
    ) : (
      <>
        <ProcessPanel onReview={openReview} />
        <OverviewScreen onNavigate={setScreen} onReview={openReview} />
      </>
    );
  return (
    <Shell
      activeNav={screen === "Review" ? "Mappings" : screen}
      onNavigate={setScreen}
      apiUp={apiUp}
    >
      {content}
    </Shell>
  );
}

export default App;
