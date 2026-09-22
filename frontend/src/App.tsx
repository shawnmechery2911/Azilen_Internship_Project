import "./App.css";
import "./parity.css";
import { useEffect, useState } from "react";
import { getExceptions } from "./api";
import { Shell } from "./components/Shell";
import { ExceptionsScreen } from "./screens/Exceptions";
import { MappingReviewScreen } from "./screens/MappingReview";
import { OnboardingScreen } from "./screens/Onboarding";
import { OverviewScreen } from "./screens/Overview";
import { PartnersScreen } from "./screens/Partners";
import { RulesScreen } from "./screens/Rules";
import { TestOrderScreen } from "./screens/TestOrder";

function App() {
  const [screen, setScreen] = useState("Overview");
  const [apiUp, setApiUp] = useState(true);
  const [queueAts, setQueueAts] = useState<string | null>(null);
  const [testAts, setTestAts] = useState<string | null>(null);
  const [ruleScope, setRuleScope] = useState<string | null>(null);
  const [openCount, setOpenCount] = useState(0);
  const [retired, setRetired] = useState(0);
  const [review, setReview] = useState<{
    ats: string;
    payloadType: string;
    version: number;
  } | null>(null);
  const openReview = (
    ats: string,
    payloadType: string,
    version: number,
    retiredSamples = 0,
  ) => {
    setReview({ ats, payloadType, version });
    setRetired(retiredSamples);
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
    if (next !== "Validation") setRuleScope(null);
    if (next !== "Test") setTestAts(null);
    setScreen(next);
  };
  /** Approving is the moment the destination fields are known, so that is
   *  where choosing what the partner must send belongs. */
  const afterApproval = (ats: string) => {
    setRuleScope(ats);
    setScreen("Validation");
  };
  const content =
    screen === "Exceptions" ? (
      <ExceptionsScreen ats={queueAts} />
    ) : screen === "Onboard" ? (
      <OnboardingScreen onReview={openReview} />
    ) : screen === "Partners" ? (
      <PartnersScreen
        onReview={openReview}
        onExceptions={(ats) => navigate("Exceptions", ats)}
        onTest={(ats) => {
          setTestAts(ats);
          setScreen("Test");
        }}
      />
    ) : screen === "Test" ? (
      <TestOrderScreen onReview={openReview} ats={testAts} />
    ) : screen === "Validation" ? (
      <RulesScreen scope={ruleScope} />
    ) : screen === "Review" && review ? (
      <MappingReviewScreen
        {...review}
        onDone={() => setScreen("Overview")}
        onApproved={afterApproval}
        retired={retired}
      />
    ) : (
      <OverviewScreen onNavigate={navigate} onReview={openReview} />
    );
  return (
    <Shell
      activeNav={screen === "Review" ? "Overview" : screen}
      onNavigate={navigate}
      crumb={screen === "Review" ? "Mapping review" : undefined}
      apiUp={apiUp}
      openExceptions={openCount}
    >
      {content}
    </Shell>
  );
}

export default App;
