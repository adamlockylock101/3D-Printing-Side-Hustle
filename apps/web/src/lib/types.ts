// Mirrors of the worker's pydantic schemas. Kept hand-written rather than generated so the
// storefront depends on a stable shape rather than on the worker's internals; if you'd rather
// generate them, the worker publishes an OpenAPI document at /openapi.json.

export type Lifecycle =
  | "prototype"
  | "fit_check"
  | "functional_prototype"
  | "end_use"
  | "cosmetic";

export type LoadType =
  | "none"
  | "tension"
  | "compression"
  | "bending"
  | "shear"
  | "impact"
  | "cyclic"
  | "clamping";

export type LeadTime = "relaxed" | "standard" | "rush";

export interface Requirements {
  lifecycle?: Lifecycle | null;
  load: {
    type?: LoadType | null;
    magnitude_n?: number | null;
    qualitative?: "light" | "moderate" | "heavy" | null;
    duration?: "momentary" | "intermittent" | "sustained" | null;
  };
  brittleness_tolerance?: string | null;
  thermal: {
    max_service_c?: number | null;
    min_service_c?: number | null;
    sunlight_hot_car?: boolean | null;
  };
  environment: {
    outdoor_uv?: boolean | null;
    moisture?: string | null;
    chemicals: string[];
    food_contact?: boolean | null;
    skin_contact?: boolean | null;
  };
  precision: {
    tolerance_mm?: number | null;
    tolerance_class?: string | null;
    fit_critical?: boolean | null;
    min_feature_mm?: number | null;
  };
  aesthetics: {
    visible?: boolean | null;
    colour?: string | null;
    finish?: string | null;
  };
  cost_sensitivity?: "low" | "medium" | "high" | null;
  lead_time: LeadTime;
  quantity: number;
  notes_freeform?: string | null;
  raw_text?: string | null;
}

export interface GeometryReport {
  bbox_mm: [number, number, number];
  volume_mm3: number;
  surface_area_mm2: number;
  triangle_count: number;
  is_watertight: boolean;
  min_wall_mm: number | null;
  overhang_fraction: number;
  footprint_mm2: number;
  height_to_footprint_ratio: number;
  fits_build_volume: boolean;
  warnings: string[];
  units_suspect: boolean;
}

export interface MaterialScore {
  material_id: string;
  name: string;
  score: number;
  drivers: string[];
  trade_off: string | null;
  cost_per_kg: number;
  in_stock: boolean;
}

export interface Recommendation {
  primary: MaterialScore;
  alternates: MaterialScore[];
  rejected: { material_id: string; name: string; reason: string }[];
  rationale: string;
  orientation_advice: string | null;
  print_settings: Record<string, unknown>;
  warnings: string[];
  table_version: string;
  escalate_to_resin: boolean;
  declined: boolean;
  declined_reason: string | null;
}

export interface CostLine {
  label: string;
  amount: number;
  detail: string | null;
}

export interface Quote {
  material_id: string;
  material_name: string;
  quantity: number;
  unit_price: number;
  total_price: number;
  currency: string;
  lines: CostLine[];
  print_minutes_each: number;
  filament_g_each: number;
  lead_time: LeadTime;
  estimated: boolean;
  requires_manual_review: boolean;
  manual_review_reason: string | null;
  minimum_applied: boolean;
  expires_hours: number;
}

export interface FollowUp {
  field: string;
  question: string;
  help_text: string | null;
  options: { value: string; label: string }[];
  input_type: string;
}

export interface AnalyseResponse {
  upload_id: string;
  filename: string;
  geometry: GeometryReport;
}

export interface IntakeResponse {
  requirements: Requirements;
  summary: string;
  assumptions: string[];
  extracted_by: string;
  follow_ups: FollowUp[];
  allowed: boolean;
  declined_reason: string | null;
}

export interface QuoteResponse {
  recommendation: Recommendation;
  quote: Quote | null;
  geometry: GeometryReport;
  overridden: boolean;
  override_acknowledgement: string | null;
}

export interface PublicConfig {
  currency: string;
  minimum_order: number;
  quote_valid_hours: number;
  rush_multipliers: Record<string, number>;
  shipping: {
    free_over: number;
    domestic_flat: number;
    pickup_available: boolean;
    international: boolean;
  };
  materials: { id: string; name: string; colours: string[] }[];
}
