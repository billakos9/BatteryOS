import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import Shell from "@/components/bos/Shell";
import Index from "./pages/Index.tsx";
import NotFound from "./pages/NotFound.tsx";
import Forecaster from "./pages/Forecaster.tsx";
import Optimizer from "./pages/Optimizer.tsx";
import Backtest from "./pages/Backtest.tsx";
import Assets from "./pages/Assets.tsx";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Index />} />
          <Route path="/forecaster" element={<Shell><Forecaster /></Shell>} />
          <Route path="/optimizer" element={<Shell><Optimizer /></Shell>} />
          <Route path="/backtest" element={<Shell><Backtest /></Shell>} />
          <Route path="/assets" element={<Shell><Assets /></Shell>} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
