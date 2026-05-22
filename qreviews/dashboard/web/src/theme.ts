import { createTheme, MantineColorsTuple, rem } from "@mantine/core";

const flame: MantineColorsTuple = [
  "#fff1ea",
  "#ffe0d0",
  "#ffbfa3",
  "#ff9c73",
  "#ff7e4c",
  "#ff6a3d",
  "#ff5e2f",
  "#e44d22",
  "#cc4319",
  "#a8330e",
];

// Override Mantine's "dark" scale with our Pacific Terminal navy palette.
// Index 7 is the page background per Mantine's dark theme conventions.
const navy: MantineColorsTuple = [
  "#E8ECF4", // 0 — lightest ink
  "#C9D0DE",
  "#A4ADBF",
  "#7F8AA0",
  "#5C6478", // 4 — muted
  "#3F4659",
  "#2A3145",
  "#0B1220", // 7 — page background
  "#080E1A", // 8 — deeper
  "#050912", // 9 — deepest
];

export const theme = createTheme({
  primaryColor: "flame",
  primaryShade: 5,
  defaultRadius: "sm",
  colors: {
    flame,
    dark: navy,
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
  white: "#E8ECF4",
  black: "#0B1220",
  other: {
    surface: "#121A2B",
    surfaceRaised: "#172037",
    hairline: "rgba(232, 236, 244, 0.08)",
    warn: "#F2C94C",
    danger: "#E0524A",
  },
});
