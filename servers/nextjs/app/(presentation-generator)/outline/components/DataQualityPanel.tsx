"use client";

import React, { useState } from "react";
import { AlertTriangle, Check, ChevronDown, ChevronUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { QualityFlagGroup } from "@/store/slices/presentationGeneration";

interface DataQualityPanelProps {
  groups: QualityFlagGroup[];
  onAcknowledge: (groupKey: string) => void;
  acknowledgingGroupKey: string | null;
}

const DataQualityPanel: React.FC<DataQualityPanelProps> = ({
  groups,
  onAcknowledge,
  acknowledgingGroupKey,
}) => {
  const [expandedGroupKey, setExpandedGroupKey] = useState<string | null>(null);

  if (groups.length === 0) {
    return null;
  }

  const pendingCount = groups.filter((group) => !group.acknowledged).length;

  return (
    <div className="mb-6 rounded-lg border border-[#F2CDD1] bg-[#FFF9F0] p-4 sm:p-5">
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle size={18} className="shrink-0 text-[#B45309]" />
        <h3 className="font-syne text-sm font-semibold text-[#172a5c]">
          Data Quality
          {pendingCount > 0
            ? ` — ${pendingCount} group${pendingCount === 1 ? "" : "s"} need review`
            : " — all reviewed"}
        </h3>
      </div>

      <div className="flex flex-col gap-3">
        {groups.map((group) => {
          const isExpanded = expandedGroupKey === group.group_key;
          const isAcknowledging = acknowledgingGroupKey === group.group_key;

          return (
            <div
              key={group.group_key}
              className={cn(
                "rounded-md border bg-white p-3",
                group.acknowledged ? "border-[#D9E0EA]" : "border-[#F2CDD1]"
              )}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-[#172a5c]">
                    {group.source_file}
                  </p>
                  <p className="text-sm text-[#526078]">{group.summary}</p>
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  {group.acknowledged ? (
                    <span className="flex items-center gap-1 text-sm font-medium text-[#2E7D32]">
                      <Check size={16} />
                      Acknowledged
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      disabled={isAcknowledging}
                      onClick={() => onAcknowledge(group.group_key)}
                      className="h-8 rounded-md bg-[#172a5c] px-3 text-xs font-semibold text-white hover:bg-[#0f1e45]"
                    >
                      {group.items.length > 1
                        ? "Keep all as static images"
                        : "Keep as static image"}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setExpandedGroupKey(isExpanded ? null : group.group_key)
                    }
                    className="h-8 rounded-md border-[#D9E0EA] px-3 text-xs font-semibold text-[#172a5c] hover:bg-[#F3F6FA]"
                  >
                    Review {group.items.length}{" "}
                    {group.items.length === 1 ? "item" : "items"}
                    {isExpanded ? (
                      <ChevronUp size={14} className="ml-1" />
                    ) : (
                      <ChevronDown size={14} className="ml-1" />
                    )}
                  </Button>
                </div>
              </div>

              {isExpanded && (
                <ul className="mt-3 flex flex-col gap-2 border-t border-[#EDEEEF] pt-3">
                  {group.items.map((item, index) => (
                    <li
                      key={`${group.group_key}-${index}`}
                      className="text-sm text-[#526078]"
                    >
                      <span className="font-semibold text-[#172a5c]">
                        {item.location}
                        {item.visual_label ? ` — ${item.visual_label}` : ""}
                      </span>
                      <span className="block">{item.detail}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DataQualityPanel;
