import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Navbar } from "./components/Navbar";
import { AnalysisPage } from "./pages/AnalysisPage";
import { DcaPage } from "./pages/DcaPage";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });

export function AppRoutes() {
  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-7xl px-4 py-4">
        <Routes>
          <Route path="/" element={<Navigate to="/analysis" replace />} />
          <Route path="/dca" element={<DcaPage />} />
          <Route path="/analysis" element={<AnalysisPage />} />
        </Routes>
      </main>
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
