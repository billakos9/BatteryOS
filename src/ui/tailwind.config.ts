import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./pages/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./app/**/*.{ts,tsx}", "./src/**/*.{ts,tsx}"],
  prefix: "",
  theme: {
    container: { center: true, padding: "2rem", screens: { "2xl": "1480px" } },
    extend: {
      fontFamily: {
        sans: ['"Inter Tight"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        serif: ['"Instrument Serif"', "Times New Roman", "serif"],
      },
      colors: {
        // Shadcn aliases
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },

        // BatteryOS semantic tokens
        "bg-0": "hsl(var(--bg-0))",
        "bg-1": "hsl(var(--bg-1))",
        "bg-2": "hsl(var(--bg-2))",
        "bg-3": "hsl(var(--bg-3))",
        "bg-4": "hsl(var(--bg-4))",
        "fg-0": "hsl(var(--fg-0))",
        "fg-1": "hsl(var(--fg-1))",
        "fg-2": "hsl(var(--fg-2))",
        "fg-3": "hsl(var(--fg-3))",
        "fg-4": "hsl(var(--fg-4))",
        line: "hsl(var(--line))",
        "line-strong": "hsl(var(--line-strong))",
        acc: "hsl(var(--acc))",
        "acc-dim": "hsl(var(--acc-dim))",
        amber: "hsl(var(--amber))",
        "amber-dim": "hsl(var(--amber-dim))",
        magenta: "hsl(var(--magenta))",
        "magenta-dim": "hsl(var(--magenta-dim))",
        blue: "hsl(var(--blue))",
        "blue-dim": "hsl(var(--blue-dim))",
        red: "hsl(var(--red))",
        "red-dim": "hsl(var(--red-dim))",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
        "ticker-scroll": { from: { transform: "translateX(0)" }, to: { transform: "translateX(-50%)" } },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "ticker-scroll": "ticker-scroll 60s linear infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
