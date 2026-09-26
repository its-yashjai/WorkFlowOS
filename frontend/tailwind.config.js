/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0A0E1A", 2: "#10172A", 3: "#172139", 4: "#1F2C4A" },
        paper: "#ECF1FF",
        mist: "#9FB0CF",
        faint: "#6A7A99",
        hand: "#FFB547",   // things YOU do (manual)
        flow: "#34D6C4",   // things the machine does (automated)
        volt: "#7C8CFF",   // primary actions
        ok: "#5BE49B",
        bad: "#FF6B6B",
      },
      fontFamily: {
        display: ['"Bricolage Grotesque Variable"', "system-ui", "sans-serif"],
        sans: ['"Instrument Sans Variable"', "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
