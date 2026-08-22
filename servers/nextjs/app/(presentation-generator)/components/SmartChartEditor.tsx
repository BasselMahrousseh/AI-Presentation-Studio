"use client";

import { Plus, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

export type SmartChartDraft = {
  canvasId: string;
  type: string;
  labels: string[];
  datasetLabel: string;
  values: number[];
  colors: string[];
};

const CHART_TYPES = [
  ["bar", "Bar"],
  ["line", "Line"],
  ["pie", "Pie"],
  ["doughnut", "Doughnut"],
] as const;

function copyDraft(draft: SmartChartDraft): SmartChartDraft {
  return {
    ...draft,
    labels: [...draft.labels],
    values: [...draft.values],
    colors: [...draft.colors],
  };
}

export default function SmartChartEditor({
  chart,
  onApply,
  onClose,
}: {
  chart: SmartChartDraft;
  onApply: (chart: SmartChartDraft) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(() => copyDraft(chart));

  useEffect(() => setDraft(copyDraft(chart)), [chart]);

  const updateRow = (index: number, field: "label" | "value" | "color", value: string) => {
    setDraft((current) => {
      const next = copyDraft(current);
      if (field === "label") next.labels[index] = value;
      if (field === "value") next.values[index] = Number(value) || 0;
      if (field === "color") next.colors[index] = value;
      return next;
    });
  };

  const addRow = () => {
    setDraft((current) => ({
      ...current,
      labels: [...current.labels, `Item ${current.labels.length + 1}`],
      values: [...current.values, 0],
      colors: [...current.colors, "#E60000"],
    }));
  };

  const removeRow = (index: number) => {
    if (draft.labels.length <= 1) return;
    setDraft((current) => ({
      ...current,
      labels: current.labels.filter((_, itemIndex) => itemIndex !== index),
      values: current.values.filter((_, itemIndex) => itemIndex !== index),
      colors: current.colors.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  return (
    <div className="fixed right-6 top-24 z-[100] w-[360px] rounded-2xl border border-[#E6E1DD] bg-white p-5 font-syne shadow-[0_18px_50px_rgba(18,18,22,0.2)]">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <p className="text-base font-bold text-[#18181B]">Edit chart</p>
          <p className="mt-1 text-xs leading-5 text-[#6B6870]">Changes update this Smart Mode slide before export.</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close chart editor"
          className="rounded-md p-1 text-[#6B6870] hover:bg-[#F5F3F1] hover:text-[#18181B]"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <label className="mb-3 block text-xs font-semibold text-[#35333A]">
        Chart type
        <select
          value={draft.type}
          onChange={(event) => setDraft((current) => ({ ...current, type: event.target.value }))}
          className="mt-1.5 h-9 w-full rounded-md border border-[#D7D1CC] bg-white px-2 text-sm font-normal outline-none focus:border-[#E60000]"
        >
          {CHART_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>

      <label className="mb-3 block text-xs font-semibold text-[#35333A]">
        Series name
        <input
          value={draft.datasetLabel}
          onChange={(event) => setDraft((current) => ({ ...current, datasetLabel: event.target.value }))}
          className="mt-1.5 h-9 w-full rounded-md border border-[#D7D1CC] px-2 text-sm font-normal outline-none focus:border-[#E60000]"
        />
      </label>

      <div className="max-h-[310px] overflow-y-auto pr-1">
        <div className="grid grid-cols-[1fr_72px_38px_26px] gap-2 px-1 pb-1 text-[10px] font-bold uppercase tracking-[0.08em] text-[#858188]">
          <span>Label</span><span>Value</span><span>Colour</span><span />
        </div>
        {draft.labels.map((label, index) => (
          <div key={`${index}-${label}`} className="mb-2 grid grid-cols-[1fr_72px_38px_26px] items-center gap-2">
            <input
              value={label}
              onChange={(event) => updateRow(index, "label", event.target.value)}
              aria-label={`Label ${index + 1}`}
              className="h-8 min-w-0 rounded-md border border-[#D7D1CC] px-2 text-xs outline-none focus:border-[#E60000]"
            />
            <input
              type="number"
              value={draft.values[index] ?? 0}
              onChange={(event) => updateRow(index, "value", event.target.value)}
              aria-label={`Value for ${label}`}
              className="h-8 min-w-0 rounded-md border border-[#D7D1CC] px-2 text-xs outline-none focus:border-[#E60000]"
            />
            <input
              type="color"
              value={draft.colors[index] ?? "#E60000"}
              onChange={(event) => updateRow(index, "color", event.target.value)}
              aria-label={`Colour for ${label}`}
              className="h-8 w-[38px] cursor-pointer rounded border border-[#D7D1CC] bg-white p-1"
            />
            <button
              type="button"
              onClick={() => removeRow(index)}
              disabled={draft.labels.length <= 1}
              aria-label={`Remove ${label}`}
              className="rounded p-1 text-[#8A878C] hover:bg-[#FFF0F0] hover:text-[#E60000] disabled:cursor-not-allowed disabled:opacity-30"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={addRow}
        className="mt-1 inline-flex items-center gap-1.5 text-xs font-semibold text-[#C00000] hover:text-[#E60000]"
      >
        <Plus className="h-3.5 w-3.5" /> Add data point
      </button>

      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="h-9 rounded-md px-3 text-sm font-semibold text-[#5E5A62] hover:bg-[#F5F3F1]">Cancel</button>
        <button
          type="button"
          onClick={() => onApply(draft)}
          className="h-9 rounded-md bg-[#E60000] px-3 text-sm font-bold text-white shadow-sm hover:bg-[#C90000]"
        >
          Apply chart
        </button>
      </div>
    </div>
  );
}
