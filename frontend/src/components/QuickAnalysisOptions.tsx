import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { AnalysisOptions } from "@/lib/types";
import { DEFAULT_QUICK_SETTINGS, pickQuickSettings } from "@/lib/types";

interface Props {
  value: AnalysisOptions;
  onChange: (next: AnalysisOptions) => void;
  compact?: boolean;
}

function NumberField({
  label,
  hint,
  value,
  min,
  max,
  step,
  disabled,
  onCommit,
}: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  disabled?: boolean;
  onCommit: (n: number) => void;
}) {
  return (
    <div className={cn("space-y-1", disabled && "opacity-50")}>
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        min={min}
        max={max}
        step={step ?? 1}
        disabled={disabled}
        value={Number.isFinite(value) ? value : ""}
        onChange={(e) => {
          const next = Number(e.target.value);
          if (Number.isFinite(next)) onCommit(next);
        }}
        className="h-8 text-xs"
      />
      <p className="text-[10px] text-muted-foreground">{hint}</p>
    </div>
  );
}

function CheckField({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2 rounded-md border bg-background/60 px-2.5 py-2">
      <input
        type="checkbox"
        className="mt-0.5 h-3.5 w-3.5 accent-amber-700"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="min-w-0">
        <span className="block text-xs font-medium">{label}</span>
        <span className="block text-[10px] text-muted-foreground">{hint}</span>
      </span>
    </label>
  );
}

export default function QuickAnalysisCustomFields({ value, onChange, compact }: Props) {
  const settings = pickQuickSettings(value);
  const patch = (partial: Partial<AnalysisOptions>) => onChange({ ...value, ...partial });

  return (
    <div className={cn("space-y-3", compact ? "pt-2" : "pt-3")}>
      <p className="text-[10px] text-amber-800/80 dark:text-amber-300/80">
        입력 규칙만 바꿉니다. 시점·replicate 열은 유지되고 정량 산식은 그대로입니다.
        Custom Quick도 Full과 비교하거나 논문 primary로 쓰지 마세요.
      </p>
      <div className={cn("grid gap-2", compact ? "grid-cols-1" : "sm:grid-cols-2")}>
        <CheckField
          label="Keep all target PTM"
          hint="대상 UniMod precursor를 예산 없이 남깁니다. cap은 그대로입니다."
          checked={settings.quick_keep_all_ptm}
          onChange={(quick_keep_all_ptm) => patch({ quick_keep_all_ptm })}
        />
        <CheckField
          label="Keep unmodified pairs"
          hint="선택한 PTM과 같은 서열의 unmodified precursor (occupancy)."
          checked={settings.quick_keep_unmodified_pairs}
          onChange={(quick_keep_unmodified_pairs) => patch({ quick_keep_unmodified_pairs })}
        />
        <CheckField
          label="Include non-PTM proteins"
          hint="PTM에 안 묶인 PG를 검출률 순으로 추가합니다. PR은 넣지 않습니다."
          checked={settings.quick_include_non_ptm}
          onChange={(quick_include_non_ptm) => patch({ quick_include_non_ptm })}
        />
      </div>
      <div className={cn("grid gap-3", compact ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-4")}>
        <NumberField
          label="Max PTM precursors"
          hint="10–5000 · default 400"
          value={settings.quick_max_ptm_precursors}
          min={10}
          max={5000}
          disabled={settings.quick_keep_all_ptm}
          onCommit={(quick_max_ptm_precursors) => patch({ quick_max_ptm_precursors })}
        />
        <NumberField
          label="Per-protein cap"
          hint="0 = no cap · default 4"
          value={settings.quick_per_protein_cap}
          min={0}
          max={50}
          onCommit={(quick_per_protein_cap) => patch({ quick_per_protein_cap })}
        />
        <NumberField
          label="Min detection"
          hint="0–1 · default 0.50"
          value={settings.quick_min_detection_frac}
          min={0}
          max={1}
          step={0.05}
          onCommit={(quick_min_detection_frac) => patch({ quick_min_detection_frac })}
        />
        <NumberField
          label="Max non-PTM PG"
          hint="0–5000 · default 200"
          value={settings.quick_max_non_ptm_proteins}
          min={0}
          max={5000}
          disabled={!settings.quick_include_non_ptm}
          onCommit={(quick_max_non_ptm_proteins) => patch({ quick_max_non_ptm_proteins })}
        />
      </div>
      <button
        type="button"
        className="text-[10px] text-muted-foreground underline-offset-2 hover:underline"
        onClick={() => onChange({ ...value, ...DEFAULT_QUICK_SETTINGS })}
      >
        Reset to default (400 / 4 / 0.50, pairs on, non-PTM off)
      </button>
    </div>
  );
}
