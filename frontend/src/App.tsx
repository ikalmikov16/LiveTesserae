import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { LandingPage } from "./pages/LandingPage";
import { NotFound } from "./pages/NotFound";
import "./App.css";

const MosaicEditor = lazy(() =>
  import("./pages/MosaicEditor").then((m) => ({ default: m.MosaicEditor }))
);

function LoadingScreen() {
  return (
    <div
      style={{
        width: "100%",
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--color-bg-primary, #0f0f0f)",
        color: "var(--color-text-secondary, #888)",
        fontSize: "1rem",
      }}
    >
      Loading editor…
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route
          path="/mosaic"
          element={
            <Suspense fallback={<LoadingScreen />}>
              <MosaicEditor />
            </Suspense>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
