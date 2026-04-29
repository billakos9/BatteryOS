// Static synthetic data has been removed. Every visualization in the UI
// must source its inputs from the FastAPI backend (see src/ui/src/lib/api.ts
// and src/ui/src/lib/backend.ts). This file is kept intentionally empty
// so that any straggling import surfaces as a clear build error.
//
// If you want a baseline placeholder for local development, mock the
// backend response in your test harness — never re-introduce baked-in
// numbers in this module.
export {};
