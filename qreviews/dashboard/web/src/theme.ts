import { createTheme, MantineColorsTuple, rem } from "@mantine/core";

// Single flame tuple that bridges the dark-mode (Sunset coral) and
// light-mode (Daybreak orange) primaries. Mantine picks shade 5 in dark
// mode and shade 6 in light mode via `primaryShade`.
const flame: MantineColorsTuple = [
  "#fff1e6", // 0
  "#ffe0cc", // 1
  "#ffc2a3", // 2
  "#ffa380", // 3
  "#ff8c66", // 4
  "#ff7a59", // 5 — Sunset coral (dark mode primary)
  "#f97316", // 6 — Daybreak orange (light mode primary)
  "#e35d0c", // 7
  "#b94808", // 8
  "#8b3506", // 9
];

// Dark scale used by Mantine in dark mode for internal surfaces. Index 7
// is the page background per Mantine convention.
const dark: MantineColorsTuple = [
  "#F4F7FF", // 0 — lightest ink
  "#D7DDF0",
  "#B6BFDA",
  "#8A93AE", // 3 — muted
  "#6F7894",
  "#515973",
  "#313A56",
  "#0E1426", // 7 — page background
  "#0A0F1F", // 8 — deeper
  "#060A18", // 9 — deepest
];

export const theme = createTheme({
  primaryColor: "flame",
  primaryShade: { light: 6, dark: 5 },
  defaultRadius: "sm",
  colors: {
    flame,
    dark,
  },
  fontFamily: '"IBM Plex Sans", system-ui, -apple-system, sans-serif',
  fontFamilyMonospace: '"IBM Plex Mono", ui-monospace, SFMono-Regular, monospace',
  headings: {
    fontFamily: '"Migra", "IBM Plex Serif", Georgia, serif',
    fontWeight: "800",
    sizes: {
      h1: { fontSize: rem(64), lineHeight: "1.05" },
      h2: { fontSize: rem(32), lineHeight: "1.15" },
      h3: { fontSize: rem(24), lineHeight: "1.2" },
    },
  },
  white: "#FFFFFF",
  black: "#0E1426",
});
