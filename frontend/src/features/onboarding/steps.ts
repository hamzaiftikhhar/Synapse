/** Step/stage metadata for the clinic onboarding flow.
 *
 * Fine-grained step slugs are what gets persisted as `Clinic.onboarding_step`
 * (the resume cursor). Stages are the coarser grouping shown as progress —
 * "Step 4 of 8" is not what a busy clinic owner needs to see.
 */

export const ONBOARDING_STAGES = [
  { key: "clinic", label: "Clinic" },
  { key: "team", label: "Team" },
  { key: "specialties", label: "Specialties" },
  { key: "services", label: "Services" },
  { key: "insurance", label: "Insurance" },
  { key: "availability", label: "Availability" },
  { key: "booking", label: "Booking" },
  { key: "review", label: "Review" },
] as const;

export type OnboardingStageKey = (typeof ONBOARDING_STAGES)[number]["key"];

export const ONBOARDING_STEPS = [
  { slug: "clinic", stage: "clinic" },
  { slug: "location", stage: "clinic" },
  { slug: "providers", stage: "team" },
  { slug: "specialties", stage: "specialties" },
  { slug: "services", stage: "services" },
  { slug: "insurance", stage: "insurance" },
  { slug: "hours", stage: "availability" },
  { slug: "availability", stage: "availability" },
  { slug: "booking", stage: "booking" },
  { slug: "review", stage: "review" },
  // Only ever reached when this clinic has a pending paid plan (provisioned
  // from a Get Started application) — complete_onboarding() routes here
  // instead of activating immediately. Plain self-serve clinics skip it.
  { slug: "billing", stage: "review" },
] as const satisfies ReadonlyArray<{ slug: string; stage: OnboardingStageKey }>;

export type OnboardingStepSlug = (typeof ONBOARDING_STEPS)[number]["slug"];

/** Clinics that started onboarding before the catalog page was split still
 * have `onboarding_step = "catalog"`. Land them on Specialties rather than
 * bouncing to the first step. */
const LEGACY_STEP_ALIASES: Record<string, OnboardingStepSlug> = {
  catalog: "specialties",
};

export function stageIndexForStep(slug: string): number {
  const step = ONBOARDING_STEPS.find((s) => s.slug === slug);
  if (!step) return 0;
  return ONBOARDING_STAGES.findIndex((s) => s.key === step.stage);
}

export function isOnboardingStepSlug(value: string | undefined | null): value is OnboardingStepSlug {
  return Boolean(value) && ONBOARDING_STEPS.some((s) => s.slug === value);
}

export function resolveOnboardingStepSlug(
  value: string | undefined | null
): OnboardingStepSlug {
  if (value && value in LEGACY_STEP_ALIASES) return LEGACY_STEP_ALIASES[value];
  return isOnboardingStepSlug(value) ? value : ONBOARDING_STEPS[0].slug;
}

/** Every step form uses this id so the shell's sticky footer Continue
 * button (outside the form in the DOM) can submit it via `form="..."`. */
export const ONBOARDING_FORM_ID = "onboarding-step-form";

/** Back navigation is wired at the shell/orchestrator level (footer button
 * calls the step engine's goBack directly) — step components only ever need
 * to advance forward, after their own save succeeds. */
export type OnboardingStepProps = {
  onNext: () => void;
};
