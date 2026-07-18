/**
 * In-memory fixture "database" standing in for Postgres (ADR 0001) until the
 * real FastAPI backend exists. Shapes here approximate DB rows (snake_ish
 * concepts, one record per table) -- `read-models.ts` joins these into the
 * camelCase DTOs the UI actually renders (`lib/types.ts`), the same way a
 * real read-model service would join repository rows into a DTO.
 *
 * # ASSUMPTION: single demo organization ("Meridian Property Group" / Dana
 * Alvarez), matching the "single user per org in v1" assumption in ADR 0001.
 * Data resets on dev-server restart -- there is no persistence layer here.
 */

import type {
  ComparisonSeverity,
  CoverageType,
  DocSource,
  DocStatus,
  EmailDirection,
  EscalationKind,
  EscalationStatus,
  EventSeverity,
  EventType,
  PropertyType,
  RunState,
  RunStatus,
  ValidationResult,
  VendorRole,
} from "../types";

// ---------------------------------------------------------------------------
// Organization / properties
// ---------------------------------------------------------------------------

export const ORG_ID = "org_meridian";

export const organization = {
  id: ORG_ID,
  name: "Meridian Property Group",
  agentEnabled: true,
  settings: {
    renewalLeadDays: 30,
    followupIntervalDays: 4,
    maxOutreach: 3,
    maxLlmPerDoc: 5,
    confidenceThreshold: 0.8,
    budgetCostCapCents: 200,
    responseDeadlineDays: 14,
  },
};

export interface PropertyRecord {
  id: string;
  organizationId: string;
  name: string;
  line1: string;
  city: string;
  state: string;
  county: string;
  postalCode: string;
  hoaName: string | null;
  propertyType: PropertyType;
}

export const properties: PropertyRecord[] = [
  {
    id: "prop_rincon",
    organizationId: ORG_ID,
    name: "Rincon Hill Apartments",
    line1: "425 Beale St",
    city: "San Francisco",
    state: "CA",
    county: "San Francisco",
    postalCode: "94105",
    hoaName: null,
    propertyType: "multi_family",
  },
  {
    id: "prop_oakview",
    organizationId: ORG_ID,
    name: "Oakview Commons",
    line1: "2200 Harrison St",
    city: "Oakland",
    state: "CA",
    county: "Alameda",
    postalCode: "94612",
    hoaName: "Oakview Commons HOA",
    propertyType: "condo",
  },
  {
    id: "prop_sunset",
    organizationId: ORG_ID,
    name: "Sunset Row Homes",
    line1: "1180 Noriega St",
    city: "San Francisco",
    state: "CA",
    county: "San Francisco",
    postalCode: "94122",
    hoaName: null,
    propertyType: "single_family",
  },
];

// ---------------------------------------------------------------------------
// compliance_requirements -- curated KB (tier c), each row cited + verified
// ---------------------------------------------------------------------------

export interface ComplianceRequirementRecord {
  id: string;
  organizationId: string;
  jurisdictionState: string;
  jurisdictionCity: string | null;
  jurisdictionHoa: string | null;
  propertyType: PropertyType | null;
  vendorRole: VendorRole | null;
  coverageType: CoverageType;
  minEachOccurrence: number | null;
  minAggregate: number | null;
  requiresAdditionalInsured: boolean;
  requiresWaiverOfSubrogation: boolean;
  requiresPrimaryNoncontributory: boolean;
  minPolicyNotes: string | null;
  sourceCitation: string;
  sourceUrl: string | null;
  lastVerifiedAt: string;
  verifiedBy: string;
  active: boolean;
}

export const complianceRequirements: ComplianceRequirementRecord[] = [
  {
    id: "cr_ca_gl_base",
    organizationId: ORG_ID,
    jurisdictionState: "CA",
    jurisdictionCity: null,
    jurisdictionHoa: null,
    propertyType: null,
    vendorRole: null,
    coverageType: "general_liability",
    minEachOccurrence: 1_000_000,
    minAggregate: 2_000_000,
    requiresAdditionalInsured: true,
    requiresWaiverOfSubrogation: false,
    requiresPrimaryNoncontributory: true,
    minPolicyNotes: "Baseline GL floor for any vendor performing on-site work at a managed property.",
    sourceCitation: "Meridian PM vendor policy v3, §2.1 (statewide baseline)",
    sourceUrl: null,
    lastVerifiedAt: "2026-01-12T00:00:00Z",
    verifiedBy: "Dana Alvarez",
    active: true,
  },
  {
    id: "cr_ca_wc",
    organizationId: ORG_ID,
    jurisdictionState: "CA",
    jurisdictionCity: null,
    jurisdictionHoa: null,
    propertyType: null,
    vendorRole: null,
    coverageType: "workers_comp",
    minEachOccurrence: 1_000_000,
    minAggregate: null,
    requiresAdditionalInsured: false,
    requiresWaiverOfSubrogation: true,
    requiresPrimaryNoncontributory: false,
    minPolicyNotes: "Statutory in California for any employer with employees performing the work.",
    sourceCitation: "CA Labor Code § 3700",
    sourceUrl: "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=LAB&sectionNum=3700",
    lastVerifiedAt: "2026-01-12T00:00:00Z",
    verifiedBy: "Dana Alvarez",
    active: true,
  },
  {
    id: "cr_sf_gl_uplift",
    organizationId: ORG_ID,
    jurisdictionState: "CA",
    jurisdictionCity: "San Francisco",
    jurisdictionHoa: null,
    propertyType: null,
    vendorRole: null,
    coverageType: "general_liability",
    minEachOccurrence: 2_000_000,
    minAggregate: 4_000_000,
    requiresAdditionalInsured: true,
    requiresWaiverOfSubrogation: false,
    requiresPrimaryNoncontributory: true,
    minPolicyNotes: "SF properties carry a higher GL floor than the state baseline; supersedes cr_ca_gl_base for SF.",
    sourceCitation: "SF Admin Code Ch. 38 (contractor insurance minimums), as applied by Meridian PM policy v3 §2.2",
    sourceUrl: null,
    lastVerifiedAt: "2026-02-01T00:00:00Z",
    verifiedBy: "Dana Alvarez",
    active: true,
  },
  {
    id: "cr_ca_auto",
    organizationId: ORG_ID,
    jurisdictionState: "CA",
    jurisdictionCity: null,
    jurisdictionHoa: null,
    propertyType: null,
    vendorRole: null,
    coverageType: "auto_liability",
    minEachOccurrence: 1_000_000,
    minAggregate: null,
    requiresAdditionalInsured: false,
    requiresWaiverOfSubrogation: false,
    requiresPrimaryNoncontributory: false,
    minPolicyNotes: "Required for vendors operating a vehicle on or between property sites.",
    sourceCitation: "CA Vehicle Code § 16056 (financial responsibility) + Meridian PM policy v3 §2.3",
    sourceUrl: null,
    lastVerifiedAt: "2026-01-12T00:00:00Z",
    verifiedBy: "Dana Alvarez",
    active: true,
  },
  {
    id: "cr_gc_umbrella",
    organizationId: ORG_ID,
    jurisdictionState: "CA",
    jurisdictionCity: null,
    jurisdictionHoa: null,
    propertyType: null,
    vendorRole: "general_contractor",
    coverageType: "umbrella_excess",
    minEachOccurrence: 2_000_000,
    minAggregate: 2_000_000,
    requiresAdditionalInsured: true,
    requiresWaiverOfSubrogation: false,
    requiresPrimaryNoncontributory: false,
    minPolicyNotes: "General contractors carry umbrella excess given scope of on-site structural work.",
    sourceCitation: "Meridian PM vendor policy v3, §2.5 (GC-specific uplift)",
    sourceUrl: null,
    lastVerifiedAt: "2026-01-12T00:00:00Z",
    verifiedBy: "Dana Alvarez",
    active: true,
  },
  {
    id: "cr_roofer_umbrella",
    organizationId: ORG_ID,
    jurisdictionState: "CA",
    jurisdictionCity: null,
    jurisdictionHoa: null,
    propertyType: null,
    vendorRole: "roofer",
    coverageType: "umbrella_excess",
    minEachOccurrence: 1_000_000,
    minAggregate: 1_000_000,
    requiresAdditionalInsured: true,
    requiresWaiverOfSubrogation: false,
    requiresPrimaryNoncontributory: false,
    minPolicyNotes: "Elevated-risk trade; umbrella required above the GL/WC baseline.",
    sourceCitation: "Meridian PM vendor policy v3, §2.6 (high-risk trade uplift)",
    sourceUrl: null,
    lastVerifiedAt: "2026-01-12T00:00:00Z",
    verifiedBy: "Dana Alvarez",
    active: true,
  },
  {
    id: "cr_pest_professional",
    organizationId: ORG_ID,
    jurisdictionState: "CA",
    jurisdictionCity: null,
    jurisdictionHoa: null,
    propertyType: null,
    vendorRole: "pest_control",
    coverageType: "professional_liability",
    minEachOccurrence: 1_000_000,
    minAggregate: 1_000_000,
    requiresAdditionalInsured: false,
    requiresWaiverOfSubrogation: false,
    requiresPrimaryNoncontributory: false,
    minPolicyNotes: "Chemical-application trades carry professional/pollution liability.",
    sourceCitation: "CA Business & Professions Code § 8560 et seq., structural pest control licensing",
    sourceUrl: null,
    lastVerifiedAt: "2025-11-04T00:00:00Z",
    verifiedBy: "Dana Alvarez",
    active: true,
  },
  // Note: intentionally NO row for general_contractor in Oakland (jurisdictionHoa
  // "Oakview Commons HOA") -- backs the retrieval-fallback / no_requirements_on_file
  // demo for Titan General Contracting below.
];

// ---------------------------------------------------------------------------
// Vendors + materialized vendor_coverage_requirements
// ---------------------------------------------------------------------------

export interface VendorRecord {
  id: string;
  organizationId: string;
  name: string;
  primaryEmail: string | null;
  vendorRole: VendorRole;
  status: "active" | "inactive";
  primaryPropertyId: string | null;
  notes: string | null;
}

export const vendors: VendorRecord[] = [
  {
    id: "ven_hernandez",
    organizationId: ORG_ID,
    name: "Hernandez Plumbing",
    primaryEmail: "office@hernandezplumbing.example",
    vendorRole: "plumber",
    status: "active",
    primaryPropertyId: "prop_rincon",
    notes: "On call for Rincon Hill; responsive, renews on time most cycles.",
  },
  {
    id: "ven_silverstate",
    organizationId: ORG_ID,
    name: "Silver State Electric",
    primaryEmail: "accounts@silverstateelectric.example",
    vendorRole: "electrician",
    status: "active",
    primaryPropertyId: "prop_sunset",
    notes: null,
  },
  {
    id: "ven_bayarea_hvac",
    organizationId: ORG_ID,
    name: "Bay Area HVAC Co",
    primaryEmail: "billing@bayareahvac.example",
    vendorRole: "hvac",
    status: "active",
    primaryPropertyId: "prop_rincon",
    notes: null,
  },
  {
    id: "ven_martinez",
    organizationId: ORG_ID,
    name: "Martinez Landscaping",
    primaryEmail: "j.martinez@martinezland.example",
    vendorRole: "landscaper",
    status: "active",
    primaryPropertyId: "prop_oakview",
    notes: "Services Oakview Commons grounds weekly.",
  },
  {
    id: "ven_coastal",
    organizationId: ORG_ID,
    name: "Coastal Cleaning Crew",
    primaryEmail: "hello@coastalcleaningcrew.example",
    vendorRole: "cleaner",
    status: "active",
    primaryPropertyId: "prop_sunset",
    notes: null,
  },
  {
    id: "ven_apex_roofing",
    organizationId: ORG_ID,
    name: "Apex Roofing",
    primaryEmail: "certs@apexroofing.example",
    vendorRole: "roofer",
    status: "active",
    primaryPropertyId: "prop_rincon",
    notes: null,
  },
  {
    id: "ven_cleanpro",
    organizationId: ORG_ID,
    name: "CleanPro Services",
    primaryEmail: "info@cleanproservices.example",
    vendorRole: "cleaner",
    status: "active",
    primaryPropertyId: "prop_oakview",
    notes: null,
  },
  {
    id: "ven_guardian_pest",
    organizationId: ORG_ID,
    name: "Guardian Pest Control",
    primaryEmail: "renewals@guardianpest.example",
    vendorRole: "pest_control",
    status: "active",
    primaryPropertyId: "prop_sunset",
    notes: "Slow to respond historically -- flagged in prior cycle too.",
  },
  {
    id: "ven_titan_gc",
    organizationId: ORG_ID,
    name: "Titan General Contracting",
    primaryEmail: "insurance@titangc.example",
    vendorRole: "general_contractor",
    status: "active",
    primaryPropertyId: "prop_oakview",
    notes: "New vendor, onboarded for the Oakview Commons deck rebuild.",
  },
  {
    id: "ven_ridgeline_hvac",
    organizationId: ORG_ID,
    name: "Ridgeline HVAC & Air",
    primaryEmail: "ops@ridgelinehvac.example",
    vendorRole: "hvac",
    status: "active",
    primaryPropertyId: "prop_oakview",
    notes: null,
  },
];

export interface VendorCoverageRequirementRecord {
  id: string;
  organizationId: string;
  vendorId: string;
  coverageType: CoverageType;
  minEachOccurrence: number | null;
  minAggregate: number | null;
  requiresAdditionalInsured: boolean;
  requiresWaiverOfSubrogation: boolean;
  requiresPrimaryNoncontributory: boolean;
  sourceComplianceRequirementId: string | null;
  confirmedByPm: boolean;
}

function reqLine(
  vendorId: string,
  cr: ComplianceRequirementRecord,
  overrides: Partial<VendorCoverageRequirementRecord> = {},
): VendorCoverageRequirementRecord {
  return {
    id: `vcr_${vendorId}_${cr.coverageType}`,
    organizationId: ORG_ID,
    vendorId,
    coverageType: cr.coverageType,
    minEachOccurrence: cr.minEachOccurrence,
    minAggregate: cr.minAggregate,
    requiresAdditionalInsured: cr.requiresAdditionalInsured,
    requiresWaiverOfSubrogation: cr.requiresWaiverOfSubrogation,
    requiresPrimaryNoncontributory: cr.requiresPrimaryNoncontributory,
    sourceComplianceRequirementId: cr.id,
    confirmedByPm: true,
    ...overrides,
  };
}

const crSfGl = complianceRequirements.find((c) => c.id === "cr_sf_gl_uplift")!;
const crCaGl = complianceRequirements.find((c) => c.id === "cr_ca_gl_base")!;
const crCaWc = complianceRequirements.find((c) => c.id === "cr_ca_wc")!;
const crCaAuto = complianceRequirements.find((c) => c.id === "cr_ca_auto")!;
const crGcUmbrella = complianceRequirements.find((c) => c.id === "cr_gc_umbrella")!;
const crRooferUmbrella = complianceRequirements.find((c) => c.id === "cr_roofer_umbrella")!;
const crPestProfessional = complianceRequirements.find((c) => c.id === "cr_pest_professional")!;

export const vendorCoverageRequirements: VendorCoverageRequirementRecord[] = [
  // Hernandez Plumbing -- SF property, GL + WC + auto
  reqLine("ven_hernandez", crSfGl),
  reqLine("ven_hernandez", crCaWc),
  reqLine("ven_hernandez", crCaAuto),

  // Silver State Electric -- SF property, GL + WC
  reqLine("ven_silverstate", crSfGl),
  reqLine("ven_silverstate", crCaWc),

  // Bay Area HVAC -- SF property, GL + WC + auto
  reqLine("ven_bayarea_hvac", crSfGl),
  reqLine("ven_bayarea_hvac", crCaWc),
  reqLine("ven_bayarea_hvac", crCaAuto),

  // Martinez Landscaping -- Oakland/HOA property, state baseline GL + WC
  reqLine("ven_martinez", crCaGl),
  reqLine("ven_martinez", crCaWc),

  // Coastal Cleaning Crew -- SF property, GL + WC
  reqLine("ven_coastal", crSfGl),
  reqLine("ven_coastal", crCaWc),

  // Apex Roofing -- SF property, GL + WC + umbrella (high-risk uplift)
  reqLine("ven_apex_roofing", crSfGl),
  reqLine("ven_apex_roofing", crCaWc),
  reqLine("ven_apex_roofing", crRooferUmbrella),

  // CleanPro Services -- Oakland/HOA, state baseline GL + WC
  reqLine("ven_cleanpro", crCaGl),
  reqLine("ven_cleanpro", crCaWc),

  // Guardian Pest Control -- SF property, GL + WC + professional liability
  reqLine("ven_guardian_pest", crSfGl),
  reqLine("ven_guardian_pest", crCaWc),
  reqLine("ven_guardian_pest", crPestProfessional),

  // Titan General Contracting -- Oakland/HOA property. GL + WC resolved fine,
  // but the GC umbrella line has NO matching KB row for this HOA/vendor-role
  // combination -> null source, backs the no_requirements_on_file escalation.
  reqLine("ven_titan_gc", crCaGl),
  reqLine("ven_titan_gc", crCaWc),
  {
    id: "vcr_ven_titan_gc_umbrella_excess",
    organizationId: ORG_ID,
    vendorId: "ven_titan_gc",
    coverageType: "umbrella_excess",
    minEachOccurrence: crGcUmbrella.minEachOccurrence,
    minAggregate: crGcUmbrella.minAggregate,
    requiresAdditionalInsured: crGcUmbrella.requiresAdditionalInsured,
    requiresWaiverOfSubrogation: crGcUmbrella.requiresWaiverOfSubrogation,
    requiresPrimaryNoncontributory: crGcUmbrella.requiresPrimaryNoncontributory,
    sourceComplianceRequirementId: null, // unbacked -- retrieval found nothing for this jurisdiction
    confirmedByPm: false,
  },

  // Ridgeline HVAC -- Oakland/HOA property, state baseline GL + WC + auto
  reqLine("ven_ridgeline_hvac", crCaGl),
  reqLine("ven_ridgeline_hvac", crCaWc),
  reqLine("ven_ridgeline_hvac", crCaAuto),
];

// ---------------------------------------------------------------------------
// coi_documents / coi_extractions / coi_validations
// ---------------------------------------------------------------------------

export interface CoiDocumentRecord {
  id: string;
  organizationId: string;
  vendorId: string;
  runId: string | null;
  storagePath: string;
  originalFilename: string;
  contentType: string;
  versionNumber: number;
  supersedesDocumentId: string | null;
  status: DocStatus;
  validFrom: string | null;
  validTo: string | null;
  isCurrent: boolean;
  source: DocSource;
  receivedAt: string;
}

export interface CoiExtractionRecord {
  id: string;
  organizationId: string;
  runId: string;
  coiDocumentId: string;
  extracted: {
    insuredName: string;
    lines: Array<{
      coverageType: CoverageType;
      eachOccurrence: number | null;
      aggregate: number | null;
      additionalInsured: boolean | null;
      waiverOfSubrogation: boolean | null;
      primaryNoncontributory: boolean | null;
    }>;
    policyValidFrom: string;
    policyValidTo: string;
  };
  fieldConfidence: Record<string, number>;
  overallConfidence: number;
  model: string;
  promptHash: string;
  inputTokens: number;
  outputTokens: number;
  costCents: number;
  isCurrent: boolean;
  createdAt: string;
}

export interface LineResult {
  vendorCoverageRequirementId: string;
  sourceComplianceRequirementId: string | null;
  coverageType: CoverageType;
  parsedEachOccurrence: number | null;
  parsedAggregate: number | null;
  parsedAdditionalInsured: boolean | null;
  parsedWaiverOfSubrogation: boolean | null;
  parsedPrimaryNoncontributory: boolean | null;
  pass: boolean;
  severity: ComparisonSeverity;
  note: string | null;
}

export interface CoiValidationRecord {
  id: string;
  organizationId: string;
  runId: string;
  coiExtractionId: string;
  result: ValidationResult;
  lineResults: LineResult[];
  flags: Array<{ code: string; message: string; severity: ComparisonSeverity }>;
  faithfulnessOk: boolean;
  createdAt: string;
}

export const coiDocuments: CoiDocumentRecord[] = [
  {
    id: "doc_hernandez_v3",
    organizationId: ORG_ID,
    vendorId: "ven_hernandez",
    runId: "run_hernandez_2026a",
    storagePath: "/mock-documents/hernandez-plumbing-coi-2026.pdf",
    originalFilename: "Hernandez_Plumbing_COI_2026.pdf",
    contentType: "application/pdf",
    versionNumber: 3,
    supersedesDocumentId: "doc_hernandez_v2",
    status: "filed",
    validFrom: "2026-03-15",
    validTo: "2027-03-15",
    isCurrent: true,
    source: "email_inbound",
    receivedAt: "2026-07-15T18:22:00Z",
  },
  {
    id: "doc_silverstate_v2",
    organizationId: ORG_ID,
    vendorId: "ven_silverstate",
    runId: null,
    storagePath: "/mock-documents/silver-state-electric-coi-2025.pdf",
    originalFilename: "SilverState_COI_2025.pdf",
    contentType: "application/pdf",
    versionNumber: 2,
    supersedesDocumentId: null,
    status: "filed",
    validFrom: "2025-10-01",
    validTo: "2026-10-01",
    isCurrent: true,
    source: "onboarding_import",
    receivedAt: "2025-09-20T14:00:00Z",
  },
  {
    id: "doc_bayarea_v2",
    organizationId: ORG_ID,
    vendorId: "ven_bayarea_hvac",
    runId: null,
    storagePath: "/mock-documents/bay-area-hvac-coi-2025.pdf",
    originalFilename: "BayAreaHVAC_COI_2025.pdf",
    contentType: "application/pdf",
    versionNumber: 2,
    supersedesDocumentId: null,
    status: "filed",
    validFrom: "2025-08-10",
    validTo: "2026-08-10",
    isCurrent: true,
    source: "email_inbound",
    receivedAt: "2025-08-05T09:00:00Z",
  },
  {
    id: "doc_martinez_v2",
    organizationId: ORG_ID,
    vendorId: "ven_martinez",
    runId: null,
    storagePath: "/mock-documents/martinez-landscaping-coi-2025.pdf",
    originalFilename: "Martinez_Landscaping_COI_2025.pdf",
    contentType: "application/pdf",
    versionNumber: 2,
    supersedesDocumentId: null,
    status: "filed",
    validFrom: "2025-07-20",
    validTo: "2026-07-20",
    isCurrent: true,
    source: "email_inbound",
    receivedAt: "2025-07-15T11:00:00Z",
  },
  {
    id: "doc_coastal_v2",
    organizationId: ORG_ID,
    vendorId: "ven_coastal",
    runId: "run_coastal_2026a",
    storagePath: "/mock-documents/coastal-cleaning-coi-2026-draft.pdf",
    originalFilename: "Coastal_Cleaning_COI_2026.pdf",
    contentType: "application/pdf",
    versionNumber: 2,
    supersedesDocumentId: "doc_coastal_v1",
    status: "parsing",
    validFrom: null,
    validTo: null,
    isCurrent: false,
    source: "email_inbound",
    receivedAt: "2026-07-18T08:41:00Z",
  },
  {
    id: "doc_apex_v1",
    organizationId: ORG_ID,
    vendorId: "ven_apex_roofing",
    runId: null,
    storagePath: "/mock-documents/apex-roofing-coi-2025.pdf",
    originalFilename: "Apex_Roofing_COI_2025.pdf",
    contentType: "application/pdf",
    versionNumber: 1,
    supersedesDocumentId: null,
    status: "filed",
    validFrom: "2025-07-01",
    validTo: "2026-07-01",
    isCurrent: true,
    source: "email_inbound",
    receivedAt: "2025-06-28T10:00:00Z",
  },
  {
    id: "doc_cleanpro_v1",
    organizationId: ORG_ID,
    vendorId: "ven_cleanpro",
    runId: null,
    storagePath: "/mock-documents/cleanpro-coi-2025.pdf",
    originalFilename: "CleanPro_COI_2025.pdf",
    contentType: "application/pdf",
    versionNumber: 1,
    supersedesDocumentId: null,
    status: "filed",
    validFrom: "2025-06-20",
    validTo: "2026-06-20",
    isCurrent: true,
    source: "email_inbound",
    receivedAt: "2025-06-15T10:00:00Z",
  },
  {
    id: "doc_apex_v2",
    organizationId: ORG_ID,
    vendorId: "ven_apex_roofing",
    runId: "run_apex_2026a",
    storagePath: "/mock-documents/apex-roofing-coi-2026.pdf",
    originalFilename: "Apex_Roofing_COI_2026.pdf",
    contentType: "application/pdf",
    versionNumber: 2,
    supersedesDocumentId: "doc_apex_v1",
    status: "parsed",
    validFrom: "2026-07-01",
    validTo: "2027-07-01",
    isCurrent: false,
    source: "email_inbound",
    receivedAt: "2026-07-16T13:05:00Z",
  },
  {
    id: "doc_cleanpro_v2",
    organizationId: ORG_ID,
    vendorId: "ven_cleanpro",
    runId: "run_cleanpro_2026a",
    storagePath: "/mock-documents/cleanpro-coi-2026-scan.pdf",
    originalFilename: "CleanPro_COI_scan.pdf",
    contentType: "application/pdf",
    versionNumber: 2,
    supersedesDocumentId: "doc_cleanpro_v1",
    status: "parsed",
    validFrom: "2026-06-20",
    validTo: "2027-06-20",
    isCurrent: false,
    source: "email_inbound",
    receivedAt: "2026-07-14T16:30:00Z",
  },
];

export const coiExtractions: CoiExtractionRecord[] = [
  {
    id: "ext_hernandez_v3",
    organizationId: ORG_ID,
    runId: "run_hernandez_2026a",
    coiDocumentId: "doc_hernandez_v3",
    extracted: {
      insuredName: "Hernandez Plumbing Inc.",
      lines: [
        { coverageType: "general_liability", eachOccurrence: 2_000_000, aggregate: 4_000_000, additionalInsured: true, waiverOfSubrogation: null, primaryNoncontributory: true },
        { coverageType: "workers_comp", eachOccurrence: 1_000_000, aggregate: null, additionalInsured: null, waiverOfSubrogation: true, primaryNoncontributory: null },
        { coverageType: "auto_liability", eachOccurrence: 1_000_000, aggregate: null, additionalInsured: null, waiverOfSubrogation: null, primaryNoncontributory: null },
      ],
      policyValidFrom: "2026-03-15",
      policyValidTo: "2027-03-15",
    },
    fieldConfidence: { general_liability: 0.97, workers_comp: 0.95, auto_liability: 0.94 },
    overallConfidence: 0.96,
    model: "claude-sonnet-4-5",
    promptHash: "sha256:8f1c…d2a0",
    inputTokens: 3120,
    outputTokens: 410,
    costCents: 4,
    isCurrent: true,
    createdAt: "2026-07-15T18:24:10Z",
  },
  {
    id: "ext_apex_v2",
    organizationId: ORG_ID,
    runId: "run_apex_2026a",
    coiDocumentId: "doc_apex_v2",
    extracted: {
      insuredName: "Apex Roofing LLC",
      lines: [
        { coverageType: "general_liability", eachOccurrence: 1_000_000, aggregate: 2_000_000, additionalInsured: false, waiverOfSubrogation: null, primaryNoncontributory: false },
        { coverageType: "workers_comp", eachOccurrence: 1_000_000, aggregate: null, additionalInsured: null, waiverOfSubrogation: true, primaryNoncontributory: null },
        { coverageType: "umbrella_excess", eachOccurrence: 1_000_000, aggregate: 1_000_000, additionalInsured: false, waiverOfSubrogation: null, primaryNoncontributory: null },
      ],
      policyValidFrom: "2026-07-01",
      policyValidTo: "2027-07-01",
    },
    fieldConfidence: { general_liability: 0.93, workers_comp: 0.96, umbrella_excess: 0.9 },
    overallConfidence: 0.93,
    model: "claude-sonnet-4-5",
    promptHash: "sha256:2b77…f119",
    inputTokens: 3340,
    outputTokens: 455,
    costCents: 4,
    isCurrent: true,
    createdAt: "2026-07-16T13:07:44Z",
  },
  {
    id: "ext_cleanpro_v2",
    organizationId: ORG_ID,
    runId: "run_cleanpro_2026a",
    coiDocumentId: "doc_cleanpro_v2",
    extracted: {
      insuredName: "CleanPro Services (scan -- name partially legible)",
      lines: [
        { coverageType: "general_liability", eachOccurrence: 1_000_000, aggregate: 2_000_000, additionalInsured: true, waiverOfSubrogation: null, primaryNoncontributory: true },
        { coverageType: "workers_comp", eachOccurrence: null, aggregate: null, additionalInsured: null, waiverOfSubrogation: null, primaryNoncontributory: null },
      ],
      policyValidFrom: "2026-06-20",
      policyValidTo: "2027-06-20",
    },
    fieldConfidence: { general_liability: 0.88, workers_comp: 0.41 },
    overallConfidence: 0.64,
    model: "claude-sonnet-4-5",
    promptHash: "sha256:9a04…3cde",
    inputTokens: 2890,
    outputTokens: 380,
    costCents: 4,
    isCurrent: true,
    createdAt: "2026-07-14T16:33:02Z",
  },
];

export const coiValidations: CoiValidationRecord[] = [
  {
    id: "val_hernandez_v3",
    organizationId: ORG_ID,
    runId: "run_hernandez_2026a",
    coiExtractionId: "ext_hernandez_v3",
    result: "pass",
    lineResults: [
      { vendorCoverageRequirementId: "vcr_ven_hernandez_general_liability", sourceComplianceRequirementId: "cr_sf_gl_uplift", coverageType: "general_liability", parsedEachOccurrence: 2_000_000, parsedAggregate: 4_000_000, parsedAdditionalInsured: true, parsedWaiverOfSubrogation: null, parsedPrimaryNoncontributory: true, pass: true, severity: "info", note: null },
      { vendorCoverageRequirementId: "vcr_ven_hernandez_workers_comp", sourceComplianceRequirementId: "cr_ca_wc", coverageType: "workers_comp", parsedEachOccurrence: 1_000_000, parsedAggregate: null, parsedAdditionalInsured: null, parsedWaiverOfSubrogation: true, parsedPrimaryNoncontributory: null, pass: true, severity: "info", note: null },
      { vendorCoverageRequirementId: "vcr_ven_hernandez_auto_liability", sourceComplianceRequirementId: "cr_ca_auto", coverageType: "auto_liability", parsedEachOccurrence: 1_000_000, parsedAggregate: null, parsedAdditionalInsured: null, parsedWaiverOfSubrogation: null, parsedPrimaryNoncontributory: null, pass: true, severity: "info", note: null },
    ],
    flags: [],
    faithfulnessOk: true,
    createdAt: "2026-07-15T18:25:30Z",
  },
  {
    id: "val_apex_v2",
    organizationId: ORG_ID,
    runId: "run_apex_2026a",
    coiExtractionId: "ext_apex_v2",
    result: "fail",
    lineResults: [
      { vendorCoverageRequirementId: "vcr_ven_apex_roofing_general_liability", sourceComplianceRequirementId: "cr_sf_gl_uplift", coverageType: "general_liability", parsedEachOccurrence: 1_000_000, parsedAggregate: 2_000_000, parsedAdditionalInsured: false, parsedWaiverOfSubrogation: null, parsedPrimaryNoncontributory: false, pass: false, severity: "error", note: "Each-occurrence limit is $1,000,000, below the $2,000,000 SF minimum. Certificate also does not list Meridian Property Group as additional insured." },
      { vendorCoverageRequirementId: "vcr_ven_apex_roofing_workers_comp", sourceComplianceRequirementId: "cr_ca_wc", coverageType: "workers_comp", parsedEachOccurrence: 1_000_000, parsedAggregate: null, parsedAdditionalInsured: null, parsedWaiverOfSubrogation: true, parsedPrimaryNoncontributory: null, pass: true, severity: "info", note: null },
      { vendorCoverageRequirementId: "vcr_ven_apex_roofing_umbrella_excess", sourceComplianceRequirementId: "cr_roofer_umbrella", coverageType: "umbrella_excess", parsedEachOccurrence: 1_000_000, parsedAggregate: 1_000_000, parsedAdditionalInsured: false, parsedWaiverOfSubrogation: null, parsedPrimaryNoncontributory: null, pass: true, severity: "info", note: null },
    ],
    flags: [
      { code: "limit_below_minimum", message: "General liability each-occurrence limit ($1,000,000) is below the required $2,000,000 for San Francisco properties.", severity: "error" },
      { code: "missing_additional_insured", message: "Meridian Property Group is not listed as additional insured on the general liability line.", severity: "error" },
    ],
    faithfulnessOk: true,
    createdAt: "2026-07-16T13:08:20Z",
  },
  {
    id: "val_cleanpro_v2",
    organizationId: ORG_ID,
    runId: "run_cleanpro_2026a",
    coiExtractionId: "ext_cleanpro_v2",
    result: "fail",
    lineResults: [
      { vendorCoverageRequirementId: "vcr_ven_cleanpro_general_liability", sourceComplianceRequirementId: "cr_ca_gl_base", coverageType: "general_liability", parsedEachOccurrence: 1_000_000, parsedAggregate: 2_000_000, parsedAdditionalInsured: true, parsedWaiverOfSubrogation: null, parsedPrimaryNoncontributory: true, pass: true, severity: "info", note: null },
      { vendorCoverageRequirementId: "vcr_ven_cleanpro_workers_comp", sourceComplianceRequirementId: "cr_ca_wc", coverageType: "workers_comp", parsedEachOccurrence: null, parsedAggregate: null, parsedAdditionalInsured: null, parsedWaiverOfSubrogation: null, parsedPrimaryNoncontributory: null, pass: false, severity: "error", note: "Workers' comp field confidence (0.41) fell below threshold on this scan -- treated as unread, not guessed." },
    ],
    flags: [
      { code: "low_confidence_extraction", message: "Workers' comp figures could not be read reliably from the submitted scan (confidence 0.41, threshold 0.80). Requesting a clearer copy.", severity: "error" },
    ],
    faithfulnessOk: true,
    createdAt: "2026-07-14T16:34:12Z",
  },
];

// ---------------------------------------------------------------------------
// runs
// ---------------------------------------------------------------------------

export interface RunRecord {
  id: string;
  organizationId: string;
  vendorId: string;
  coiDocumentId: string | null;
  state: RunState;
  status: RunStatus;
  trigger: "renewal_due" | "manual";
  dueDate: string;
  nextActionAt: string | null;
  outreachEmailCount: number;
  llmCallCount: number;
  costCentsSpent: number;
  budgetCostCapCents: number;
  startedAt: string;
  updatedAt: string;
  completedAt: string | null;
}

export const runs: RunRecord[] = [
  {
    id: "run_hernandez_2026a",
    organizationId: ORG_ID,
    vendorId: "ven_hernandez",
    coiDocumentId: "doc_hernandez_v3",
    state: "monitoring",
    status: "active",
    trigger: "renewal_due",
    dueDate: "2027-02-13",
    nextActionAt: null,
    outreachEmailCount: 1,
    llmCallCount: 1,
    costCentsSpent: 4,
    budgetCostCapCents: 200,
    startedAt: "2026-06-16T09:00:00Z",
    updatedAt: "2026-07-15T18:26:05Z",
    completedAt: "2026-07-15T18:26:05Z",
  },
  {
    id: "run_silverstate_monitoring",
    organizationId: ORG_ID,
    vendorId: "ven_silverstate",
    coiDocumentId: "doc_silverstate_v2",
    state: "monitoring",
    status: "active",
    trigger: "renewal_due",
    dueDate: "2026-10-01",
    nextActionAt: null,
    outreachEmailCount: 0,
    llmCallCount: 0,
    costCentsSpent: 0,
    budgetCostCapCents: 200,
    startedAt: "2025-10-01T09:00:00Z",
    updatedAt: "2025-10-01T09:00:00Z",
    completedAt: null,
  },
  {
    id: "run_bayarea_2026a",
    organizationId: ORG_ID,
    vendorId: "ven_bayarea_hvac",
    coiDocumentId: null,
    state: "renewal_due_soon",
    status: "active",
    trigger: "renewal_due",
    dueDate: "2026-08-10",
    nextActionAt: "2026-07-18T15:00:00Z",
    outreachEmailCount: 0,
    llmCallCount: 0,
    costCentsSpent: 0,
    budgetCostCapCents: 200,
    startedAt: "2026-07-11T15:00:00Z",
    updatedAt: "2026-07-18T09:00:00Z",
    completedAt: null,
  },
  {
    id: "run_martinez_2026a",
    organizationId: ORG_ID,
    vendorId: "ven_martinez",
    coiDocumentId: null,
    state: "awaiting_vendor_response",
    status: "active",
    trigger: "renewal_due",
    dueDate: "2026-07-20",
    nextActionAt: "2026-07-20T09:00:00Z",
    outreachEmailCount: 2,
    llmCallCount: 0,
    costCentsSpent: 0,
    budgetCostCapCents: 200,
    startedAt: "2026-06-20T09:00:00Z",
    updatedAt: "2026-07-16T09:00:00Z",
    completedAt: null,
  },
  {
    id: "run_coastal_2026a",
    organizationId: ORG_ID,
    vendorId: "ven_coastal",
    coiDocumentId: "doc_coastal_v2",
    state: "parsing",
    status: "active",
    trigger: "renewal_due",
    dueDate: "2026-07-21",
    nextActionAt: null,
    outreachEmailCount: 1,
    llmCallCount: 1,
    costCentsSpent: 4,
    budgetCostCapCents: 200,
    startedAt: "2026-06-21T09:00:00Z",
    updatedAt: "2026-07-18T08:42:15Z",
    completedAt: null,
  },
  {
    id: "run_apex_2026a",
    organizationId: ORG_ID,
    vendorId: "ven_apex_roofing",
    coiDocumentId: "doc_apex_v2",
    state: "needs_human_review",
    status: "active",
    trigger: "renewal_due",
    dueDate: "2026-08-01",
    nextActionAt: null,
    outreachEmailCount: 1,
    llmCallCount: 1,
    costCentsSpent: 4,
    budgetCostCapCents: 200,
    startedAt: "2026-07-02T09:00:00Z",
    updatedAt: "2026-07-16T13:08:20Z",
    completedAt: null,
  },
  {
    id: "run_cleanpro_2026a",
    organizationId: ORG_ID,
    vendorId: "ven_cleanpro",
    coiDocumentId: "doc_cleanpro_v2",
    state: "needs_human_review",
    status: "active",
    trigger: "renewal_due",
    dueDate: "2026-07-25",
    nextActionAt: null,
    outreachEmailCount: 1,
    llmCallCount: 1,
    costCentsSpent: 4,
    budgetCostCapCents: 200,
    startedAt: "2026-06-25T09:00:00Z",
    updatedAt: "2026-07-14T16:34:12Z",
    completedAt: null,
  },
  {
    id: "run_guardian_2026a",
    organizationId: ORG_ID,
    vendorId: "ven_guardian_pest",
    coiDocumentId: null,
    state: "escalated_to_pm",
    status: "active",
    trigger: "renewal_due",
    dueDate: "2026-07-10",
    nextActionAt: null,
    outreachEmailCount: 3,
    llmCallCount: 0,
    costCentsSpent: 0,
    budgetCostCapCents: 200,
    startedAt: "2026-06-10T09:00:00Z",
    updatedAt: "2026-07-17T09:00:00Z",
    completedAt: null,
  },
  {
    id: "run_titan_2026a",
    organizationId: ORG_ID,
    vendorId: "ven_titan_gc",
    coiDocumentId: "doc_titan_v1",
    state: "escalated_to_pm",
    status: "active",
    trigger: "manual",
    dueDate: "2026-07-30",
    nextActionAt: null,
    outreachEmailCount: 1,
    llmCallCount: 1,
    costCentsSpent: 4,
    budgetCostCapCents: 200,
    startedAt: "2026-07-08T09:00:00Z",
    updatedAt: "2026-07-15T10:12:00Z",
    completedAt: null,
  },
  {
    id: "run_ridgeline_2026a",
    organizationId: ORG_ID,
    vendorId: "ven_ridgeline_hvac",
    coiDocumentId: null,
    state: "errored",
    status: "errored",
    trigger: "renewal_due",
    dueDate: "2026-07-28",
    nextActionAt: null,
    outreachEmailCount: 1,
    llmCallCount: 0,
    costCentsSpent: 0,
    budgetCostCapCents: 200,
    startedAt: "2026-07-05T09:00:00Z",
    updatedAt: "2026-07-17T11:02:00Z",
    completedAt: null,
  },
];

// Extra document for Titan (no extraction/validation rows -- it never reached
// validating cleanly; it hit the retrieval fallback instead).
coiDocuments.push({
  id: "doc_titan_v1",
  organizationId: ORG_ID,
  vendorId: "ven_titan_gc",
  runId: "run_titan_2026a",
  storagePath: "/mock-documents/titan-gc-coi-2026.pdf",
  originalFilename: "Titan_GC_COI_2026.pdf",
  contentType: "application/pdf",
  versionNumber: 1,
  supersedesDocumentId: null,
  status: "parsed",
  validFrom: "2026-07-01",
  validTo: "2027-07-01",
  isCurrent: false,
  source: "email_inbound",
  receivedAt: "2026-07-14T12:00:00Z",
});

// ---------------------------------------------------------------------------
// escalations
// ---------------------------------------------------------------------------

export interface EscalationRecord {
  id: string;
  organizationId: string;
  runId: string;
  vendorId: string;
  kind: EscalationKind;
  reasonCode: string;
  severity: EventSeverity;
  summary: string;
  details: Record<string, unknown>;
  status: EscalationStatus;
  resolution: "approved" | "rejected" | "revision_requested" | "acknowledged" | null;
  createdAt: string;
  resolvedAt: string | null;
}

export const escalations: EscalationRecord[] = [
  {
    id: "esc_apex",
    organizationId: ORG_ID,
    runId: "run_apex_2026a",
    vendorId: "ven_apex_roofing",
    kind: "needs_human_review",
    reasonCode: "validation_failed",
    severity: "error",
    summary:
      "Apex Roofing's renewed certificate falls short on two counts: the general liability each-occurrence limit is $1,000,000 against a $2,000,000 San Francisco minimum, and Meridian Property Group is not listed as additional insured. Workers' comp and umbrella lines both check out.",
    details: { validationId: "val_apex_v2" },
    status: "open",
    resolution: null,
    createdAt: "2026-07-16T13:08:25Z",
    resolvedAt: null,
  },
  {
    id: "esc_cleanpro",
    organizationId: ORG_ID,
    runId: "run_cleanpro_2026a",
    vendorId: "ven_cleanpro",
    kind: "needs_human_review",
    reasonCode: "low_confidence_extraction",
    severity: "warn",
    summary:
      "CleanPro's certificate came in as a low-quality scan. General liability read clearly, but the workers' comp figures couldn't be extracted with confidence (0.41 vs. the 0.80 threshold) -- Rowan didn't guess, it's flagging for a clearer copy or manual read.",
    details: { extractionId: "ext_cleanpro_v2" },
    status: "open",
    resolution: null,
    createdAt: "2026-07-14T16:34:15Z",
    resolvedAt: null,
  },
  {
    id: "esc_guardian",
    organizationId: ORG_ID,
    runId: "run_guardian_2026a",
    vendorId: "ven_guardian_pest",
    kind: "escalated_to_pm",
    reasonCode: "no_response",
    severity: "warn",
    summary:
      "Guardian Pest Control hasn't responded after 3 outreach emails over 2 weeks (last sent 7/13). Coverage expired 7/10. Rowan has stopped emailing -- this needs your call: keep chasing, reach them another way, or pause the vendor.",
    details: { outreachEmailCount: 3, dueDate: "2026-07-10" },
    status: "open",
    resolution: null,
    createdAt: "2026-07-17T09:00:05Z",
    resolvedAt: null,
  },
  {
    id: "esc_titan",
    organizationId: ORG_ID,
    runId: "run_titan_2026a",
    vendorId: "ven_titan_gc",
    kind: "escalated_to_pm",
    reasonCode: "no_requirements_on_file",
    severity: "error",
    summary:
      "Titan General Contracting's certificate parsed fine, but Rowan can't validate the umbrella/excess line -- there's no verified coverage requirement on file for a general contractor at an Oakland HOA property. Rowan won't guess a minimum; add the requirement (or confirm it doesn't apply) to unblock.",
    details: { missingCoverageType: "umbrella_excess", jurisdiction: "Oakland, CA / Oakview Commons HOA", vendorRole: "general_contractor" },
    status: "open",
    resolution: null,
    createdAt: "2026-07-15T10:12:05Z",
    resolvedAt: null,
  },
];

// ---------------------------------------------------------------------------
// email_messages
// ---------------------------------------------------------------------------

export interface EmailMessageRecord {
  id: string;
  organizationId: string;
  runId: string;
  vendorId: string;
  direction: EmailDirection;
  providerMessageId: string | null;
  subject: string;
  toEmail: string;
  fromEmail: string;
  status: "queued" | "sent" | "delivered" | "bounced" | "received";
  attachmentsCount: number;
  createdAt: string;
}

export const emailMessages: EmailMessageRecord[] = [
  { id: "em_hernandez_1", organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", direction: "outbound", providerMessageId: "resend_9f2a", subject: "Time to renew your Certificate of Insurance -- Hernandez Plumbing", toEmail: "office@hernandezplumbing.example", fromEmail: "rowan@meridianpg.example", status: "delivered", attachmentsCount: 0, createdAt: "2026-06-16T09:01:00Z" },
  { id: "em_hernandez_2", organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", direction: "inbound", providerMessageId: null, subject: "RE: Time to renew your Certificate of Insurance -- Hernandez Plumbing", toEmail: "rowan@meridianpg.example", fromEmail: "office@hernandezplumbing.example", status: "received", attachmentsCount: 1, createdAt: "2026-07-15T18:22:00Z" },
];

// ---------------------------------------------------------------------------
// agent_events -- the append-only trace, per run
// ---------------------------------------------------------------------------

export interface AgentEventRecord {
  id: string;
  organizationId: string;
  runId: string | null;
  vendorId: string | null;
  eventType: EventType;
  name: string;
  severity: EventSeverity;
  fromState: RunState | null;
  toState: RunState | null;
  toolName: string | null;
  llmModel: string | null;
  promptHash: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
  costCents: number | null;
  latencyMs: number | null;
  payload: Record<string, unknown>;
  createdAt: string;
}

let eventSeq = 0;
function evt(e: Omit<AgentEventRecord, "id">): AgentEventRecord {
  eventSeq += 1;
  return { id: `evt_${eventSeq}`, ...e };
}

export const agentEvents: AgentEventRecord[] = [
  // ---- Hernandez Plumbing: full happy-path cycle, just filed ----
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "monitoring", toState: "renewal_due_soon", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "now >= due_date - RENEWAL_LEAD_DAYS", trigger: "scheduler" }, createdAt: "2026-06-16T09:00:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "tool_call", name: "tool.send_email", severity: "info", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 812, payload: { template_id: "first_outreach", to: "office@hernandezplumbing.example", provider_message_id: "resend_9f2a", idempotency_key: "sha256:run_hernandez_2026a|first_outreach|0" }, createdAt: "2026-06-16T09:01:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "renewal_due_soon", toState: "first_outreach_sent", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "outreach sent OK, within budget" }, createdAt: "2026-06-16T09:01:02Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "first_outreach_sent", toState: "awaiting_vendor_response", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "send_email returned provider id", next_action_at: "2026-06-20T09:01:02Z" }, createdAt: "2026-06-16T09:01:03Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "tool_call", name: "tool.receive_inbound_email", severity: "info", fromState: null, toState: null, toolName: "receive_inbound_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 140, payload: { reply_token_valid: true, attachments: 1, filename: "Hernandez_Plumbing_COI_2026.pdf", file_type: "application/pdf", byte_size: 214_302 }, createdAt: "2026-07-15T18:22:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "guardrail_trip", name: "guardrail.pre_llm_file_check", severity: "info", fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 4, payload: { check: "file_type_and_size", result: "pass", allowed_types: ["pdf", "png", "jpg", "tiff"], max_bytes: 10_485_760 }, createdAt: "2026-07-15T18:22:01Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "awaiting_vendor_response", toState: "document_received", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "valid attachment on reply_token" }, createdAt: "2026-07-15T18:22:02Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "tool_call", name: "tool.classify_document", severity: "info", fromState: null, toState: null, toolName: "classify_document", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 96, payload: { classification: "certificate_of_insurance", confidence: 0.99, coi_document_id: "doc_hernandez_v3" }, createdAt: "2026-07-15T18:22:05Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "document_received", toState: "parsing", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "stored + classified as COI" }, createdAt: "2026-07-15T18:22:06Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "guardrail_trip", name: "guardrail.pre_llm_neutralize", severity: "info", fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 2, payload: { check: "instruction_neutralization", result: "pass", note: "document wrapped in data delimiters; system framing instructs the model to ignore any instructions inside the document" }, createdAt: "2026-07-15T18:22:07Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "llm_call", name: "tool.parse_document", severity: "info", fromState: null, toState: null, toolName: "parse_document", llmModel: "claude-sonnet-4-5", promptHash: "sha256:8f1c…d2a0", inputTokens: 3120, outputTokens: 410, costCents: 4, latencyMs: 5230, payload: { extraction_id: "ext_hernandez_v3", overall_confidence: 0.96, attempt_no: 1 }, createdAt: "2026-07-15T18:24:10Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "parsing", toState: "validating", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "schema-valid, confidence 0.96 >= 0.80" }, createdAt: "2026-07-15T18:24:12Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "tool_call", name: "tool.update_coi_record.validate", severity: "info", fromState: null, toState: null, toolName: "update_coi_record", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 61, payload: { validation_id: "val_hernandez_v3", result: "pass", faithfulness_ok: true, lines_checked: 3 }, createdAt: "2026-07-15T18:25:30Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "validating", toState: "filed", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "result=pass, faithfulness_ok=true, no high-severity flag" }, createdAt: "2026-07-15T18:25:32Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "tool_call", name: "tool.file_document", severity: "info", fromState: null, toState: null, toolName: "file_document", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 120, payload: { coi_document_id: "doc_hernandez_v3", is_current: true, superseded_document_id: "doc_hernandez_v2", valid_from: "2026-03-15", valid_to: "2027-03-15" }, createdAt: "2026-07-15T18:25:50Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "tool_call", name: "tool.mark_task_complete", severity: "info", fromState: null, toState: null, toolName: "mark_task_complete", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 34, payload: { completion_basis: "validation_passed", coi_validation_id: "val_hernandez_v3", next_due_date: "2027-02-13" }, createdAt: "2026-07-15T18:25:55Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "tool_call", name: "tool.send_email", severity: "info", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 340, payload: { template_id: "handled_notice", to: "dana@meridianpg.example", note: "PM-directed notice, does not count against vendor outreach cap" }, createdAt: "2026-07-15T18:26:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_hernandez_2026a", vendorId: "ven_hernandez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "filed", toState: "monitoring", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "filed + cycle reset", next_due_date: "2027-02-13" }, createdAt: "2026-07-15T18:26:05Z" }),

  // ---- Bay Area HVAC: renewal_due_soon, about to send first outreach ----
  evt({ organizationId: ORG_ID, runId: "run_bayarea_2026a", vendorId: "ven_bayarea_hvac", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "monitoring", toState: "renewal_due_soon", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "now >= due_date - RENEWAL_LEAD_DAYS", trigger: "scheduler" }, createdAt: "2026-07-11T15:00:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_bayarea_2026a", vendorId: "ven_bayarea_hvac", eventType: "note", name: "scheduler.next_tick", severity: "info", fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { note: "Outreach queued for next scheduler tick.", next_action_at: "2026-07-18T15:00:00Z" }, createdAt: "2026-07-18T09:00:00Z" }),

  // ---- Martinez Landscaping: awaiting response, one follow-up sent ----
  evt({ organizationId: ORG_ID, runId: "run_martinez_2026a", vendorId: "ven_martinez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "monitoring", toState: "renewal_due_soon", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "now >= due_date - RENEWAL_LEAD_DAYS" }, createdAt: "2026-06-20T09:00:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_martinez_2026a", vendorId: "ven_martinez", eventType: "tool_call", name: "tool.send_email", severity: "info", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 640, payload: { template_id: "first_outreach", to: "j.martinez@martinezland.example", provider_message_id: "resend_1a4d" }, createdAt: "2026-06-20T09:01:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_martinez_2026a", vendorId: "ven_martinez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "first_outreach_sent", toState: "awaiting_vendor_response", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "send accepted", next_action_at: "2026-06-24T09:01:00Z" }, createdAt: "2026-06-20T09:01:05Z" }),
  evt({ organizationId: ORG_ID, runId: "run_martinez_2026a", vendorId: "ven_martinez", eventType: "tool_call", name: "tool.send_email", severity: "info", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 588, payload: { template_id: "follow_up", sequence_no: 1, to: "j.martinez@martinezland.example", provider_message_id: "resend_2b91" }, createdAt: "2026-07-16T09:00:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_martinez_2026a", vendorId: "ven_martinez", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "awaiting_vendor_response", toState: "awaiting_vendor_response", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "follow-up within budget (2/3)", next_action_at: "2026-07-20T09:00:00Z" }, createdAt: "2026-07-16T09:00:05Z" }),

  // ---- Coastal Cleaning Crew: mid-pipeline, currently parsing ----
  evt({ organizationId: ORG_ID, runId: "run_coastal_2026a", vendorId: "ven_coastal", eventType: "tool_call", name: "tool.receive_inbound_email", severity: "info", fromState: null, toState: null, toolName: "receive_inbound_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 152, payload: { reply_token_valid: true, attachments: 1, filename: "Coastal_Cleaning_COI_2026.pdf" }, createdAt: "2026-07-18T08:41:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_coastal_2026a", vendorId: "ven_coastal", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "awaiting_vendor_response", toState: "document_received", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "valid attachment on reply_token" }, createdAt: "2026-07-18T08:41:05Z" }),
  evt({ organizationId: ORG_ID, runId: "run_coastal_2026a", vendorId: "ven_coastal", eventType: "tool_call", name: "tool.classify_document", severity: "info", fromState: null, toState: null, toolName: "classify_document", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 88, payload: { classification: "certificate_of_insurance", confidence: 0.98, coi_document_id: "doc_coastal_v2" }, createdAt: "2026-07-18T08:41:40Z" }),
  evt({ organizationId: ORG_ID, runId: "run_coastal_2026a", vendorId: "ven_coastal", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "document_received", toState: "parsing", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "stored + classified as COI" }, createdAt: "2026-07-18T08:42:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_coastal_2026a", vendorId: "ven_coastal", eventType: "note", name: "tool.parse_document.in_progress", severity: "info", fromState: null, toState: null, toolName: "parse_document", llmModel: "claude-sonnet-4-5", promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { note: "Extraction in progress (attempt 1 of 5)." }, createdAt: "2026-07-18T08:42:15Z" }),

  // ---- Apex Roofing: validation failed, needs human review ----
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "tool_call", name: "tool.send_email", severity: "info", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 701, payload: { template_id: "first_outreach", to: "certs@apexroofing.example", provider_message_id: "resend_5c88" }, createdAt: "2026-07-02T09:01:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "tool_call", name: "tool.receive_inbound_email", severity: "info", fromState: null, toState: null, toolName: "receive_inbound_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 133, payload: { reply_token_valid: true, attachments: 1, filename: "Apex_Roofing_COI_2026.pdf" }, createdAt: "2026-07-16T13:05:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "tool_call", name: "tool.classify_document", severity: "info", fromState: null, toState: null, toolName: "classify_document", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 91, payload: { classification: "certificate_of_insurance", confidence: 0.99, coi_document_id: "doc_apex_v2" }, createdAt: "2026-07-16T13:05:20Z" }),
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "document_received", toState: "parsing", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "stored + classified as COI" }, createdAt: "2026-07-16T13:05:22Z" }),
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "llm_call", name: "tool.parse_document", severity: "info", fromState: null, toState: null, toolName: "parse_document", llmModel: "claude-sonnet-4-5", promptHash: "sha256:2b77…f119", inputTokens: 3340, outputTokens: 455, costCents: 4, latencyMs: 5510, payload: { extraction_id: "ext_apex_v2", overall_confidence: 0.93, attempt_no: 1 }, createdAt: "2026-07-16T13:07:44Z" }),
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "parsing", toState: "validating", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "schema-valid, confidence 0.93 >= 0.80" }, createdAt: "2026-07-16T13:07:46Z" }),
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "tool_call", name: "tool.update_coi_record.validate", severity: "warn", fromState: null, toState: null, toolName: "update_coi_record", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 58, payload: { validation_id: "val_apex_v2", result: "fail", faithfulness_ok: true, failing_lines: ["general_liability"] }, createdAt: "2026-07-16T13:08:20Z" }),
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "llm_call", name: "tool.draft_gap_explanation", severity: "info", fromState: null, toState: null, toolName: "draft_gap_explanation", llmModel: "claude-sonnet-4-5", promptHash: "sha256:c410…77ab", inputTokens: 890, outputTokens: 140, costCents: 1, latencyMs: 2100, payload: { note: "Prose only -- attached to escalation, does not change routing." }, createdAt: "2026-07-16T13:08:22Z" }),
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "state_transition", name: "state.transition", severity: "warn", fromState: "validating", toState: "needs_human_review", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "result=fail", reason: "validation_failed" }, createdAt: "2026-07-16T13:08:23Z" }),
  evt({ organizationId: ORG_ID, runId: "run_apex_2026a", vendorId: "ven_apex_roofing", eventType: "tool_call", name: "tool.escalate_to_pm", severity: "warn", fromState: null, toState: null, toolName: "escalate_to_pm", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 45, payload: { escalation_id: "esc_apex", kind: "needs_human_review", reason_code: "validation_failed" }, createdAt: "2026-07-16T13:08:25Z" }),

  // ---- CleanPro: low-confidence extraction, needs human review ----
  evt({ organizationId: ORG_ID, runId: "run_cleanpro_2026a", vendorId: "ven_cleanpro", eventType: "tool_call", name: "tool.receive_inbound_email", severity: "info", fromState: null, toState: null, toolName: "receive_inbound_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 121, payload: { reply_token_valid: true, attachments: 1, filename: "CleanPro_COI_scan.pdf" }, createdAt: "2026-07-14T16:30:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_cleanpro_2026a", vendorId: "ven_cleanpro", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "awaiting_vendor_response", toState: "document_received", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "valid attachment on reply_token" }, createdAt: "2026-07-14T16:30:05Z" }),
  evt({ organizationId: ORG_ID, runId: "run_cleanpro_2026a", vendorId: "ven_cleanpro", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "document_received", toState: "parsing", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "stored + classified as COI" }, createdAt: "2026-07-14T16:30:10Z" }),
  evt({ organizationId: ORG_ID, runId: "run_cleanpro_2026a", vendorId: "ven_cleanpro", eventType: "llm_call", name: "tool.parse_document", severity: "warn", fromState: null, toState: null, toolName: "parse_document", llmModel: "claude-sonnet-4-5", promptHash: "sha256:9a04…3cde", inputTokens: 2890, outputTokens: 380, costCents: 4, latencyMs: 4870, payload: { extraction_id: "ext_cleanpro_v2", overall_confidence: 0.64, attempt_no: 1, note: "Scan quality degraded workers_comp field confidence." }, createdAt: "2026-07-14T16:33:02Z" }),
  evt({ organizationId: ORG_ID, runId: "run_cleanpro_2026a", vendorId: "ven_cleanpro", eventType: "guardrail_trip", name: "guardrail.post_llm_confidence", severity: "warn", fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 3, payload: { check: "overall_confidence >= CONFIDENCE_THRESHOLD", result: "fail", overall_confidence: 0.64, threshold: 0.8 }, createdAt: "2026-07-14T16:33:05Z" }),
  evt({ organizationId: ORG_ID, runId: "run_cleanpro_2026a", vendorId: "ven_cleanpro", eventType: "state_transition", name: "state.transition", severity: "warn", fromState: "parsing", toState: "needs_human_review", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "sub-threshold confidence", reason: "low_confidence_extraction" }, createdAt: "2026-07-14T16:33:06Z" }),
  evt({ organizationId: ORG_ID, runId: "run_cleanpro_2026a", vendorId: "ven_cleanpro", eventType: "tool_call", name: "tool.escalate_to_pm", severity: "warn", fromState: null, toState: null, toolName: "escalate_to_pm", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 39, payload: { escalation_id: "esc_cleanpro", kind: "needs_human_review", reason_code: "low_confidence_extraction" }, createdAt: "2026-07-14T16:34:15Z" }),

  // ---- Guardian Pest Control: max outreach exhausted, no response ----
  evt({ organizationId: ORG_ID, runId: "run_guardian_2026a", vendorId: "ven_guardian_pest", eventType: "tool_call", name: "tool.send_email", severity: "info", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 690, payload: { template_id: "first_outreach", sequence_no: 0, to: "renewals@guardianpest.example", provider_message_id: "resend_7d21" }, createdAt: "2026-06-10T09:01:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_guardian_2026a", vendorId: "ven_guardian_pest", eventType: "tool_call", name: "tool.send_email", severity: "info", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 655, payload: { template_id: "follow_up", sequence_no: 1, to: "renewals@guardianpest.example", provider_message_id: "resend_7d9a" }, createdAt: "2026-06-24T09:01:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_guardian_2026a", vendorId: "ven_guardian_pest", eventType: "tool_call", name: "tool.send_email", severity: "warn", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 712, payload: { template_id: "follow_up", sequence_no: 2, to: "renewals@guardianpest.example", provider_message_id: "resend_7ef3", note: "Final follow-up within budget (3/3)." }, createdAt: "2026-07-13T09:01:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_guardian_2026a", vendorId: "ven_guardian_pest", eventType: "guardrail_trip", name: "guardrail.budget_exhausted", severity: "warn", fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 2, payload: { check: "outreach_email_count < MAX_OUTREACH", result: "fail", outreach_email_count: 3, max_outreach: 3 }, createdAt: "2026-07-17T09:00:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_guardian_2026a", vendorId: "ven_guardian_pest", eventType: "state_transition", name: "state.transition", severity: "warn", fromState: "awaiting_vendor_response", toState: "escalated_to_pm", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "outreach_email_count >= MAX_OUTREACH", reason: "no_response" }, createdAt: "2026-07-17T09:00:02Z" }),
  evt({ organizationId: ORG_ID, runId: "run_guardian_2026a", vendorId: "ven_guardian_pest", eventType: "tool_call", name: "tool.escalate_to_pm", severity: "warn", fromState: null, toState: null, toolName: "escalate_to_pm", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 41, payload: { escalation_id: "esc_guardian", kind: "escalated_to_pm", reason_code: "no_response" }, createdAt: "2026-07-17T09:00:05Z" }),

  // ---- Titan General Contracting: retrieval fallback, no requirements on file ----
  evt({ organizationId: ORG_ID, runId: "run_titan_2026a", vendorId: "ven_titan_gc", eventType: "tool_call", name: "tool.send_email", severity: "info", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 590, payload: { template_id: "first_outreach", to: "insurance@titangc.example", provider_message_id: "resend_af02" }, createdAt: "2026-07-08T09:01:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_titan_2026a", vendorId: "ven_titan_gc", eventType: "tool_call", name: "tool.receive_inbound_email", severity: "info", fromState: null, toState: null, toolName: "receive_inbound_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 118, payload: { reply_token_valid: true, attachments: 1, filename: "Titan_GC_COI_2026.pdf" }, createdAt: "2026-07-14T12:00:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_titan_2026a", vendorId: "ven_titan_gc", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "document_received", toState: "parsing", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "stored + classified as COI" }, createdAt: "2026-07-14T12:00:10Z" }),
  evt({ organizationId: ORG_ID, runId: "run_titan_2026a", vendorId: "ven_titan_gc", eventType: "llm_call", name: "tool.parse_document", severity: "info", fromState: null, toState: null, toolName: "parse_document", llmModel: "claude-sonnet-4-5", promptHash: "sha256:7710…1c9e", inputTokens: 3010, outputTokens: 402, costCents: 4, latencyMs: 4920, payload: { extraction_id: "ext_titan_v1", overall_confidence: 0.95, attempt_no: 1 }, createdAt: "2026-07-15T10:10:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_titan_2026a", vendorId: "ven_titan_gc", eventType: "state_transition", name: "state.transition", severity: "info", fromState: "parsing", toState: "validating", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "schema-valid, confidence 0.95 >= 0.80" }, createdAt: "2026-07-15T10:10:02Z" }),
  evt({ organizationId: ORG_ID, runId: "run_titan_2026a", vendorId: "ven_titan_gc", eventType: "guardrail_trip", name: "guardrail.requirements_retrieval_fallback", severity: "error", fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 22, payload: { check: "requirements_retrieval", result: "fail", query: { jurisdiction_state: "CA", jurisdiction_city: "Oakland", jurisdiction_hoa: "Oakview Commons HOA", vendor_role: "general_contractor", coverage_type: "umbrella_excess" }, note: "No active compliance_requirements row matched -- vendor_coverage_requirements line has null source_compliance_requirement_id." }, createdAt: "2026-07-15T10:11:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_titan_2026a", vendorId: "ven_titan_gc", eventType: "state_transition", name: "state.transition", severity: "error", fromState: "validating", toState: "escalated_to_pm", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "no_requirements_on_file", reason: "no_requirements_on_file" }, createdAt: "2026-07-15T10:11:02Z" }),
  evt({ organizationId: ORG_ID, runId: "run_titan_2026a", vendorId: "ven_titan_gc", eventType: "tool_call", name: "tool.escalate_to_pm", severity: "error", fromState: null, toState: null, toolName: "escalate_to_pm", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 48, payload: { escalation_id: "esc_titan", kind: "escalated_to_pm", reason_code: "no_requirements_on_file" }, createdAt: "2026-07-15T10:12:05Z" }),

  // ---- Ridgeline HVAC: hard failure -> errored ----
  evt({ organizationId: ORG_ID, runId: "run_ridgeline_2026a", vendorId: "ven_ridgeline_hvac", eventType: "tool_call", name: "tool.send_email", severity: "info", fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 703, payload: { template_id: "first_outreach", to: "ops@ridgelinehvac.example", provider_message_id: "resend_c331" }, createdAt: "2026-07-05T09:01:00Z" }),
  evt({ organizationId: ORG_ID, runId: "run_ridgeline_2026a", vendorId: "ven_ridgeline_hvac", eventType: "error", name: "webhook.reply_token_conflict", severity: "error", fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { detail: "Inbound webhook resolved a reply_token already mapped to a completed run; treated as a hard fault rather than silently misfiling the attachment.", reply_token: "rt_9d21ff" }, createdAt: "2026-07-17T11:01:40Z" }),
  evt({ organizationId: ORG_ID, runId: "run_ridgeline_2026a", vendorId: "ven_ridgeline_hvac", eventType: "guardrail_trip", name: "guardrail.out_of_allowlist_action", severity: "error", fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: 5, payload: { check: "action_allowlist", result: "fail", attempted_action: "file_document", current_state: "awaiting_vendor_response", note: "file_document is not allowlisted outside document_received/validating/filed -- routed to errored rather than silently acting." }, createdAt: "2026-07-17T11:01:55Z" }),
  evt({ organizationId: ORG_ID, runId: "run_ridgeline_2026a", vendorId: "ven_ridgeline_hvac", eventType: "state_transition", name: "state.transition", severity: "error", fromState: "awaiting_vendor_response", toState: "errored", toolName: null, llmModel: null, promptHash: null, inputTokens: null, outputTokens: null, costCents: null, latencyMs: null, payload: { guard: "out-of-allowlist action", reason: "webhook_reply_token_conflict" }, createdAt: "2026-07-17T11:02:00Z" }),
];
