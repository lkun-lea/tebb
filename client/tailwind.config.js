import reendPreset from "reend-components/tailwind";

/** @type {import('tailwindcss').Config} */
export default {
  presets: [reendPreset],
  content: [
    "./index.html",
    "./client.html",
    "./src/**/*.{ts,tsx}",
    "./node_modules/reend-components/dist/**/*.{js,mjs}",
  ],
  theme: {
    extend: {
      fontWeight: {
        light: "var(--ui-weight-300)", normal: "var(--ui-weight-400)",
        medium: "var(--ui-weight-500)", semibold: "var(--ui-weight-600)",
        bold: "var(--ui-weight-700)", extrabold: "var(--ui-weight-800)", black: "var(--ui-weight-900)",
      },
      fontFamily: {
        sans: ["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei", "Noto Sans SC", "sans-serif"],
      },
    },
  },
};
