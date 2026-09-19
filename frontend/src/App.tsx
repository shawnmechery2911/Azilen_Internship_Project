import "./App.css";
import "./parity.css";
import { useEffect, useState } from "react";
import { getExceptions } from "./api";
import { Shell } from "./components/Shell";
import { ExceptionsScreen } from "./screens/Exceptions";
import { MappingReviewScreen } from "./screens/MappingReview";
import { OnboardingScreen } from "./screens/Onboarding";
import { OverviewScreen } from "./screens/Overview";
import { ProcessPanel } from "./components/ProcessPanel";
import { RulesScreen } from "./screens/Rules";

function App() {
  const [screen, setScreen] = useState("Overview");
  const [apiUp, setApiUp] = useState(true);
  const [queueAts, setQueueAts] = useState<string | null>(null);
  const [openCount, setOpenCount] = useState(0);
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
        .then((records) => {
          setApiUp(true);
          setOpenCount(records.filter((item) => item.status === "open").length);
        })
        .catch(() => setApiUp(false));
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, []);
  const navigate = (next: string, ats?: string) => {
    setQueueAts(ats ?? null);
    setScreen(next);
  };
  const content =
    screen === "Exceptions" ? (
      <ExceptionsScreen ats={queueAts} />
    ) : screen === "Onboard" ? (
      <OnboardingScreen onReview={openReview} />
    ) : screen === "Validation" ? (
      <RulesScreen />
    ) : screen === "Review" && review ? (
      <MappingReviewScreen {...review} onDone={() => setScreen("Overview")} />
    ) : (
      <>
        <OverviewScreen onNavigate={navigate} onReview={openReview} />
        <div className="page-wrap page-wrap-tight">
          <ProcessPanel onReview={openReview} />
        </div>
      </>
    );
  return (
    <Shell
      activeNav={screen === "Review" ? "Overview" : screen}
      onNavigate={navigate}
      apiUp={apiUp}
      openExceptions={openCount}
    >
      {content}
    </Shell>
  );
}

export default App;
