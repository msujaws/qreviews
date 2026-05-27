import { ActionIcon } from "@mantine/core";
import { IconMoon, IconSun } from "@tabler/icons-react";

import { useColorScheme } from "../ThemeProvider";

export function ThemeToggle() {
  const { colorScheme, toggle } = useColorScheme();
  const isDark = colorScheme === "dark";
  const nextLabel = isDark ? "light" : "dark";

  return (
    <ActionIcon
      variant="subtle"
      size="lg"
      onClick={toggle}
      aria-label={`Switch to ${nextLabel} mode`}
      title={`Switch to ${nextLabel} mode`}
      style={{ color: "var(--pt-muted)" }}
    >
      {isDark ? <IconSun size={18} stroke={1.6} /> : <IconMoon size={18} stroke={1.6} />}
    </ActionIcon>
  );
}
