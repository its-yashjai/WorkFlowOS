import { MotionConfig } from "framer-motion";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Huddle from "./apps/Huddle";
import Ledger from "./apps/Ledger";
import Mailbox from "./apps/Mailbox";
import Blueprint from "./components/Blueprint";
import Shell from "./components/Shell";
import { AppProvider } from "./lib/store";
import Activity from "./pages/Activity";
import Home from "./pages/Home";
import RunPage from "./pages/RunPage";
import WorkflowPage from "./pages/WorkflowPage";

export default function App() {
  const automation = new URLSearchParams(location.search).get("actor") === "automation";
  const routes = (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/workflow/:id" element={<WorkflowPage />} />
      <Route path="/run/:id" element={<RunPage />} />
      <Route path="/activity" element={<Activity />} />
      <Route path="/apps/mail" element={<Mailbox />} />
      <Route path="/apps/crm" element={<Ledger />} />
      <Route path="/apps/chat" element={<Huddle />} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
  return (
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <Blueprint />
        <AppProvider>{automation ? <div className="relative z-10">{routes}</div> : <Shell>{routes}</Shell>}</AppProvider>
      </BrowserRouter>
    </MotionConfig>
  );
}
