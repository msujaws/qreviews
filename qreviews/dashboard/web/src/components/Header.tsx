import { Select } from "@mantine/core";
import type { Group } from "../types";

interface Props {
  groups: Group[] | undefined;
  selected: string | null;
  onChange: (value: string | null) => void;
}

export function Header({ groups, selected, onChange }: Props) {
  const options = (groups ?? []).map((g) => ({ value: g.slug, label: g.slug }));

  return (
    <header className="pt-hairline-top border-b border-[var(--pt-hairline)]">
      <div className="mx-auto max-w-[1280px] px-8 py-6 flex items-center justify-between gap-8">
        <div className="flex items-center gap-5">
          <img
            src="/quail-logo.webp"
            alt="QualReviews quail mascot"
            width={88}
            height={88}
            className="shrink-0 drop-shadow-[0_4px_18px_rgba(255,106,61,0.25)]"
            style={{ imageRendering: "auto" }}
          />
          <div>
            <div className="pt-eyebrow mb-1">qreviews · v0.1</div>
            <h1
              className="pt-numeral text-[clamp(36px,5vw,52px)] leading-none"
              style={{ letterSpacing: "-0.025em" }}
            >
              QualReviews
            </h1>
            <div className="pt-mono text-[13px] text-[var(--pt-muted)] mt-2">
              autonomous phabricator review bot
            </div>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className="pt-eyebrow">reviewer · group</span>
          <Select
            data={options}
            value={selected}
            onChange={onChange}
            placeholder="all groups"
            clearable
            allowDeselect
            w={240}
            classNames={{
              input: "pt-mono",
            }}
          />
        </div>
      </div>
    </header>
  );
}
