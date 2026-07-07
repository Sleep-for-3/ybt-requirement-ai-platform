import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17212f",
        line: "#d6dde7",
        mist: "#f4f7fb",
        pine: "#176b5f",
        coral: "#b8513f",
        gold: "#a66b00"
      }
    }
  },
  plugins: []
};

export default config;
