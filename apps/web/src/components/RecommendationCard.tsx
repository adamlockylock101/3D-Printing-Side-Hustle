"use client";

import { useState } from "react";
import { Rationale } from "./Rationale";
import type { Recommendation } from "@/lib/types";

export function RecommendationCard({
  recommendation,
  selectedMaterialId,
  onSelectMaterial,
}: {
  recommendation: Recommendation;
  selectedMaterialId: string;
  onSelectMaterial: (materialId: string) => void;
}) {
  const [showRejected, setShowRejected] = useState(false);
  const settings = recommendation.print_settings as {
    walls?: number;
    infill_percent?: number;
    layer_height_mm?: number;
    note?: string;
  };

  return (
    <div className="space-y-6">
      <Rationale text={recommendation.rationale} />

      {recommendation.orientation_advice && (
        <div className="rounded-md border border-accent/30 bg-accentSoft px-4 py-3">
          <h3 className="text-sm font-semibold text-accent">How we&rsquo;ll orient it</h3>
          <p className="mt-1 text-sm leading-relaxed">{recommendation.orientation_advice}</p>
        </div>
      )}

      {recommendation.alternates.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold">Alternatives</h3>
          <p className="mt-1 text-sm text-muted">
            You can print in any of these instead. We&rsquo;ll note that you chose it.
          </p>
          <div className="mt-3 space-y-2">
            {[recommendation.primary, ...recommendation.alternates].map((material) => {
              const isRecommended = material.material_id === recommendation.primary.material_id;
              const isSelected = material.material_id === selectedMaterialId;
              return (
                <button
                  key={material.material_id}
                  type="button"
                  onClick={() => onSelectMaterial(material.material_id)}
                  className={`w-full rounded-md border px-4 py-3 text-left transition-colors ${
                    isSelected ? "border-accent bg-accentSoft" : "border-rule hover:border-accent"
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="font-medium">
                      {material.name}
                      {isRecommended && (
                        <span className="ml-2 text-xs font-normal text-accent">recommended</span>
                      )}
                    </span>
                    {!material.in_stock && (
                      <span className="text-xs text-warn">not in stock &mdash; adds lead time</span>
                    )}
                  </div>
                  {material.trade_off && (
                    <p className="mt-1 text-sm text-muted">{material.trade_off}</p>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {settings.walls !== undefined && (
        <div>
          <h3 className="text-sm font-semibold">Print settings</h3>
          <p className="mt-1 text-sm text-muted tabular">
            {settings.walls} perimeters &middot; {settings.infill_percent}% infill &middot;{" "}
            {settings.layer_height_mm} mm layers
          </p>
          {settings.note && <p className="mt-1 text-sm text-muted">{settings.note}</p>}
        </div>
      )}

      {recommendation.warnings.length > 0 && (
        <ul className="space-y-2">
          {recommendation.warnings.map((warning) => (
            <li key={warning} className="text-sm text-muted">
              {warning}
            </li>
          ))}
        </ul>
      )}

      {recommendation.rejected.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowRejected((open) => !open)}
            className="text-sm font-medium text-accent hover:underline"
          >
            {showRejected ? "Hide" : "Show"} what we ruled out (
            {recommendation.rejected.length})
          </button>
          {showRejected && (
            <ul className="mt-3 space-y-1.5 text-sm">
              {recommendation.rejected.map((item) => (
                <li key={item.material_id} className="flex gap-2">
                  <span className="w-32 shrink-0 font-medium">{item.name}</span>
                  <span className="text-muted">{item.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
