import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
  rule?: boolean;
}

export function Eyebrow({ children, rule = false }: Props) {
  return <div className={`pt-eyebrow ${rule ? "pt-eyebrow--rule" : ""}`}>{children}</div>;
}
