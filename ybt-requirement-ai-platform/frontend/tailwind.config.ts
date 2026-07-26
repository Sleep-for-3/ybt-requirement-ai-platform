import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#16232e",
        line: "#dfe6ee",
        mist: "#f4f7fa",
        pine: {
          DEFAULT: "#176b5f",
          50: "#eff9f6",
          100: "#d8efe9",
          200: "#b4ded4",
          300: "#83c5b7",
          400: "#4fa695",
          500: "#2d8a7a",
          600: "#176b5f",
          700: "#12564d",
          800: "#114540",
          900: "#0f3a36",
          950: "#07211e"
        },
        coral: {
          DEFAULT: "#b8513f",
          50: "#fbf3f1",
          100: "#f6e2de",
          200: "#eec6bf",
          300: "#e2a094",
          400: "#d27462",
          500: "#c05a45",
          600: "#b8513f",
          700: "#933f31",
          800: "#7a372d",
          900: "#66322b"
        },
        gold: {
          DEFAULT: "#a66b00",
          50: "#fdf8ec",
          100: "#f9edcb",
          200: "#f2d992",
          300: "#ebc159",
          400: "#e5ab32",
          500: "#d18f1b",
          600: "#a66b00",
          700: "#8a5310",
          800: "#734213",
          900: "#623714"
        }
      },
      boxShadow: {
        xs: "0 1px 2px rgba(16, 24, 40, 0.05)",
        card: "0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.07)",
        pop: "0 4px 6px -2px rgba(16, 24, 40, 0.05), 0 12px 16px -4px rgba(16, 24, 40, 0.1)"
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "PingFang SC",
          "HarmonyOS Sans SC",
          "Microsoft YaHei",
          "Helvetica Neue",
          "Arial",
          "sans-serif"
        ]
      }
    }
  },
  plugins: []
};

export default config;
