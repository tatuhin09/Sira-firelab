const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const recordsBody = $("#records-body");
const qualityBody = $("#quality-body");
let records = [];
let quality = null;
let manifest = null;
let conversations = [];
let activeConversationId = null;
let chatStorageAvailable = true;
let assistantSessionToken = null;
let assistantRequestInFlight = false;
let researchSynthesisRequestInFlight = false;
let researchSynthesisResult = null;
let researchSynthesisResultContext = null;

const APPROVED_INVESTIGATION_IDS = Object.freeze(["auto", "psi69-flex-v5", "psi25-bass-ii-v4"]);
const REGISTERED_INVESTIGATION_IDS = Object.freeze(["psi69-flex-v5", "psi25-bass-ii-v4"]);
const PSI25_METRIC_ORDER = Object.freeze(["o2", "co2", "co"]);

const SCIENTIFIC_PLAN_DATA_SCOPES = Object.freeze([
  "all-records", "exact-burning-rate", "selected-records", "quality-summary",
  "cohort-evidence", "research-questions", "none",
]);
const SCIENTIFIC_PLAN_EVIDENCE_IDS = Object.freeze([
  "psi69.source_manifest", "psi69.records", "psi69.quality_report",
  "psi25.canonical_records", "psi25.paired_analysis", "psi25.findings",
  "psi25.evidence_synthesis",
]);
const SCIENTIFIC_PLAN_OPERATION_MAP = Object.freeze({
  "flex.dataset.snapshot": Object.freeze({ investigationId: "psi69-flex-v5", metric: "", dataScope: "all-records" }),
  "flex.outcomes.by_fuel": Object.freeze({ investigationId: "psi69-flex-v5", metric: "", dataScope: "all-records" }),
  "flex.burning_rate.exact_by_fuel": Object.freeze({ investigationId: "psi69-flex-v5", metric: "", dataScope: "exact-burning-rate" }),
  "flex.measurement_quality": Object.freeze({ investigationId: "psi69-flex-v5", metric: "", dataScope: "quality-summary" }),
  "flex.oxygen_cohort_sensitivity": Object.freeze({ investigationId: "psi69-flex-v5", metric: "", dataScope: "selected-records" }),
  "psi25.bass_ii.v4.snapshot": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "", dataScope: "all-records" }),
  "psi25.bass_ii.v4.research_questions": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "", dataScope: "research-questions" }),
  "psi25.bass_ii.v4.o2.insights": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "o2", dataScope: "cohort-evidence" }),
  "psi25.bass_ii.v4.o2.ranking": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "o2", dataScope: "cohort-evidence" }),
  "psi25.bass_ii.v4.o2.research_questions": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "o2", dataScope: "research-questions" }),
  "psi25.bass_ii.v4.co2.insights": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "co2", dataScope: "cohort-evidence" }),
  "psi25.bass_ii.v4.co2.ranking": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "co2", dataScope: "cohort-evidence" }),
  "psi25.bass_ii.v4.co2.research_questions": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "co2", dataScope: "research-questions" }),
  "psi25.bass_ii.v4.co.insights": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "co", dataScope: "cohort-evidence" }),
  "psi25.bass_ii.v4.co.ranking": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "co", dataScope: "cohort-evidence" }),
  "psi25.bass_ii.v4.co.research_questions": Object.freeze({ investigationId: "psi25-bass-ii-v4", metric: "co", dataScope: "research-questions" }),
});

function normalizeInvestigationId(value, fallback = "psi69-flex-v5") {
  return APPROVED_INVESTIGATION_IDS.includes(value) ? value : fallback;
}

function investigationDisplayName(value) {
  if (value === "psi25-bass-ii-v4") return "PSI-25 BASS-II";
  if (value === "psi69-flex-v5") return "PSI-69 FLEX";
  return "Auto";
}

function safeNonnegativeInteger(value) {
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 0 ? number : 0;
}

function normalizeMetricSummary(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result = {};
  for (const metric of PSI25_METRIC_ORDER) {
    const row = value[metric];
    if (!row || typeof row !== "object" || Array.isArray(row)) continue;
    result[metric] = {
      eligiblePairs: safeNonnegativeInteger(row.eligible_pairs),
      excludedPairs: safeNonnegativeInteger(row.excluded_pairs),
      rankableCohorts: safeNonnegativeInteger(row.rankable_cohorts),
      notRankableCohorts: safeNonnegativeInteger(row.not_rankable_cohorts),
      insightCards: safeNonnegativeInteger(row.insight_cards),
    };
  }
  return result;
}


function normalizeScientificPlan(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  if (value.schema !== "sira.firelab.scientific_plan.v1" || value.plannerVersion !== 1) return null;
  const decision = value.decision;
  if (decision !== "execute" && decision !== "abstain") return null;
  if (typeof value.executionAllowed !== "boolean") return null;
  const requestedInvestigation = value.requestedInvestigation;
  const resolvedInvestigation = value.resolvedInvestigation;
  if (!APPROVED_INVESTIGATION_IDS.includes(requestedInvestigation)) return null;
  if (resolvedInvestigation !== "" && !REGISTERED_INVESTIGATION_IDS.includes(resolvedInvestigation)) return null;
  const intent = typeof value.intent === "string" && /^[a-z][a-z0-9_]{0,79}$/.test(value.intent)
    ? value.intent : "";
  if (!intent) return null;
  const metric = value.metric === "" || PSI25_METRIC_ORDER.includes(value.metric) ? value.metric : null;
  if (metric === null) return null;
  const operationId = typeof value.operationId === "string" ? value.operationId : "";
  const dataScope = typeof value.dataScope === "string" ? value.dataScope : "";
  if (!SCIENTIFIC_PLAN_DATA_SCOPES.includes(dataScope)) return null;
  if (decision === "execute") {
    const expected = SCIENTIFIC_PLAN_OPERATION_MAP[operationId];
    if (!value.executionAllowed || !expected) return null;
    if (expected.investigationId !== resolvedInvestigation || expected.metric !== metric || expected.dataScope !== dataScope) return null;
  } else if (value.executionAllowed || operationId !== "" || dataScope !== "none") {
    return null;
  }
  const normalizeTokenList = (items, limit = 12) => {
    if (!Array.isArray(items)) return [];
    return items.slice(0, limit).flatMap((item) =>
      typeof item === "string" && item.length <= 100 && /^[a-z0-9][a-z0-9._-]*$/i.test(item) ? [item] : []);
  };
  const evidenceRequirements = normalizeTokenList(value.evidenceRequirements, 10);
  if (evidenceRequirements.some((item) => !SCIENTIFIC_PLAN_EVIDENCE_IDS.includes(item))) return null;
  const normalizeTextList = (items, limit, maxLength) => Array.isArray(items)
    ? items.slice(0, limit).flatMap((item) => typeof item === "string" && item.length <= maxLength ? [item] : [])
    : [];
  const reasonCodes = normalizeTokenList(value.reasonCodes, 8);
  const constraintCodes = normalizeTokenList(value.constraintCodes, 16);
  const selectionRules = normalizeTextList(value.selectionRules, 8, 500);
  const explanation = typeof value.explanation === "string" ? value.explanation.slice(0, 700) : "";
  return {
    schema: "sira.firelab.scientific_plan.v1",
    plannerVersion: 1,
    decision,
    executionAllowed: value.executionAllowed,
    requestedInvestigation,
    resolvedInvestigation,
    intent,
    metric,
    operationId,
    dataScope,
    evidenceRequirements,
    constraintCodes,
    reasonCodes,
    selectionRules,
    explanation,
  };
}

const CLAIM_LEDGER_SCHEMA = "sira.firelab.claim_ledger.v1";
const CLAIM_LEDGER_CLAIM_TYPES = new Set([
  "source_table_count",
  "descriptive_summary",
  "measurement_quality_observation",
  "descriptive_cohort_finding",
  "observed_cohort_comparison",
]);
const CLAIM_LEDGER_INTERPRETATION_STATUSES = new Set([
  "source_reported",
  "descriptive_only",
  "descriptive_with_limitations",
  "quality_observation",
]);
const CLAIM_LEDGER_EVIDENCE_REFERENCE_IDS = new Set([
  "psi69.source_manifest",
  "psi69.records",
  "psi69.quality_report",
  "psi25-source-csv",
  "psi25-canonical-records",
  "psi25-paired-analysis",
  "psi25-findings",
  "psi25-synthesis",
]);

function sanitizeClaimLedgerValue(value, depth = 0, state = { nodes: 0 }) {
  state.nodes += 1;
  if (state.nodes > 2048 || depth > 6) return undefined;
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value === "string") {
    return value.slice(0, 500).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "");
  }
  if (Array.isArray(value)) {
    return value.slice(0, 300).map((item) => sanitizeClaimLedgerValue(item, depth + 1, state))
      .filter((item) => item !== undefined);
  }
  if (!value || typeof value !== "object") return undefined;
  const clean = {};
  for (const [key, item] of Object.entries(value).slice(0, 40)) {
    if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(key)) continue;
    if (/(?:confidence|score|grade)/i.test(key)) continue;
    const safe = sanitizeClaimLedgerValue(item, depth + 1, state);
    if (safe !== undefined) clean[key] = safe;
  }
  return clean;
}

function normalizeClaimLedger(answer) {
  const raw = answer && typeof answer === "object" ? answer.claimLedger : null;
  if (!raw || typeof raw !== "object" || Array.isArray(raw) || answer.status === "abstained") return null;
  if (raw.schema !== CLAIM_LEDGER_SCHEMA || raw.ledgerVersion !== 1 || raw.ledgerStatus !== "verified_provenance") return null;

  const responseInvestigation = normalizeInvestigationId(answer.investigationId, "");
  const investigationId = normalizeInvestigationId(raw.investigationId, "");
  if (!responseInvestigation || !investigationId || investigationId !== responseInvestigation) return null;

  const sourceRelease = typeof raw.sourceRelease === "string" ? raw.sourceRelease.slice(0, 160) : "";
  const operationId = typeof raw.operationId === "string" ? raw.operationId.slice(0, 80) : "";
  const metric = typeof raw.metric === "string" ? raw.metric.slice(0, 80) : "";
  const dataScope = typeof raw.dataScope === "string" ? raw.dataScope.slice(0, 80) : "";
  if (!sourceRelease || !/^[A-Za-z0-9._:-]{1,80}$/.test(operationId) || !dataScope) return null;

  const plan = normalizeScientificPlan(answer.scientificPlan);
  if (plan && (plan.operationId !== operationId || plan.dataScope !== dataScope)) return null;

  if (!Array.isArray(raw.claims) || raw.claims.length > 30) return null;
  const seenClaimIds = new Set();
  const claims = [];
  for (const row of raw.claims) {
    if (!row || typeof row !== "object" || Array.isArray(row)) return null;
    const claimId = typeof row.claimId === "string" ? row.claimId.slice(0, 80) : "";
    const claimType = typeof row.claimType === "string" ? row.claimType : "";
    const statement = typeof row.statement === "string" ? row.statement.slice(0, 1200) : "";
    const interpretationStatus = typeof row.interpretationStatus === "string" ? row.interpretationStatus : "";
    if (!claimId || seenClaimIds.has(claimId) || !CLAIM_LEDGER_CLAIM_TYPES.has(claimType) || !statement || !CLAIM_LEDGER_INTERPRETATION_STATUSES.has(interpretationStatus)) return null;
    seenClaimIds.add(claimId);

    if (!Array.isArray(row.evidenceReferences) || row.evidenceReferences.length < 1 || row.evidenceReferences.length > 10) return null;
    const evidenceReferences = [];
    for (const ref of row.evidenceReferences) {
      if (!ref || typeof ref !== "object" || Array.isArray(ref)) return null;
      const referenceId = typeof ref.referenceId === "string" ? ref.referenceId : "";
      const sha256 = typeof ref.sha256 === "string" ? ref.sha256.toLowerCase() : "";
      if (!CLAIM_LEDGER_EVIDENCE_REFERENCE_IDS.has(referenceId) || !/^[a-f0-9]{64}$/.test(sha256)) return null;
      evidenceReferences.push({ referenceId, sha256 });
    }

    const result = sanitizeClaimLedgerValue(row.result);
    const recordLineage = sanitizeClaimLedgerValue(row.recordLineage);
    const qualityDimensions = sanitizeClaimLedgerValue(row.qualityDimensions);
    const cohort = row.cohort === null ? null : sanitizeClaimLedgerValue(row.cohort);
    if (result === undefined || !recordLineage || typeof recordLineage !== "object" || Array.isArray(recordLineage)) return null;
    if (!qualityDimensions || typeof qualityDimensions !== "object" || Array.isArray(qualityDimensions)) return null;
    if (row.cohort !== null && (!cohort || typeof cohort !== "object" || Array.isArray(cohort))) return null;
    if (!Array.isArray(row.limitations) || row.limitations.length > 24 || row.limitations.some((item) => typeof item !== "string")) return null;

    claims.push({
      claimId,
      claimType,
      statement,
      result,
      metric: typeof row.metric === "string" ? row.metric.slice(0, 80) : "",
      unit: typeof row.unit === "string" ? row.unit.slice(0, 80) : "",
      cohort,
      evidenceReferences,
      recordLineage,
      qualityDimensions,
      limitations: row.limitations.slice(0, 24).map((item) => item.slice(0, 500)),
      interpretationStatus,
    });
  }

  return {
    schema: CLAIM_LEDGER_SCHEMA,
    ledgerVersion: 1,
    investigationId,
    sourceRelease,
    operationId,
    metric,
    dataScope,
    ledgerStatus: "verified_provenance",
    claims,
  };
}

function normalizeStructuredAnswerFields(answer) {
  const recordRefs = Array.isArray(answer.recordRefs)
    ? [...new Set(answer.recordRefs.filter((value) => typeof value === "string" && value.length <= 200 && !/[\u0000-\u001f\u007f]/.test(value)).slice(0, 60))]
    : [];
  const citations = Array.isArray(answer.citations) ? answer.citations.slice(0, 10).flatMap((row) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return [];
    return [{
      referenceId: typeof row.reference_id === "string" ? row.reference_id.slice(0, 100) : "",
      title: typeof row.title === "string" ? row.title.slice(0, 240) : "Evidence reference",
      kind: typeof row.kind === "string" ? row.kind.slice(0, 80) : "",
      sha256: typeof row.sha256 === "string" && /^[a-f0-9]{64}$/i.test(row.sha256) ? row.sha256.toLowerCase() : "",
      url: typeof row.url === "string" ? row.url.slice(0, 500) : "",
    }];
  }) : [];
  const claimReferences = Array.isArray(answer.claimReferences) ? answer.claimReferences.slice(0, 10).flatMap((row) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return [];
    const cohort = row.cohort && typeof row.cohort === "object" && !Array.isArray(row.cohort) ? row.cohort : {};
    const rawStats = row.statistics && typeof row.statistics === "object" && !Array.isArray(row.statistics) ? row.statistics : {};
    const statistics = {};
    for (const [key, value] of Object.entries(rawStats).slice(0, 12)) {
      if (!/^[A-Za-z0-9_-]{1,60}$/.test(key)) continue;
      if (typeof value === "number" && Number.isFinite(value)) statistics[key] = value;
      else if (typeof value === "string" && value.length <= 80) statistics[key] = value;
    }
    return [{
      claimId: typeof row.claim_id === "string" ? row.claim_id.slice(0, 120) : "",
      rank: Number.isInteger(row.rank) && row.rank > 0 ? row.rank : 0,
      metric: PSI25_METRIC_ORDER.includes(row.metric) ? row.metric : "",
      cohort: {
        pi: typeof cohort.pi === "string" ? cohort.pi.slice(0, 160) : "",
        materialClass: typeof cohort.material_class === "string" ? cohort.material_class.slice(0, 160) : "",
        flowRestrictorCode: typeof cohort.flow_restrictor_code === "string" ? cohort.flow_restrictor_code.slice(0, 80) : "",
      },
      statistics,
      interpretation: typeof row.interpretation === "string" ? row.interpretation.slice(0, 1200) : "",
      distribution: typeof row.distribution === "string" ? row.distribution.slice(0, 800) : "",
      flags: cleanStringList(row.flags, 12),
      supportingRecordKeys: Array.isArray(row.supporting_record_keys) ? row.supporting_record_keys.filter((value) => typeof value === "string" && value.length <= 200).slice(0, 60) : [],
      excludedRecordKeys: Array.isArray(row.excluded_record_keys) ? row.excluded_record_keys.filter((value) => typeof value === "string" && value.length <= 200).slice(0, 60) : [],
      sourceReferenceIds: cleanStringList(row.source_reference_ids, 10),
      interpretationStatus: typeof row.interpretation_status === "string" ? row.interpretation_status.slice(0, 80) : "",
    }];
  }) : [];
  const researchQuestions = Array.isArray(answer.researchQuestions) ? answer.researchQuestions.slice(0, 12).flatMap((row) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return [];
    return [{
      questionId: typeof row.question_id === "string" ? row.question_id.slice(0, 100) : "",
      question: typeof row.question === "string" ? row.question.slice(0, 1200) : "",
      trigger: typeof row.trigger === "string" ? row.trigger.slice(0, 800) : "",
    }];
  }) : [];
  const artifactHashes = {};
  if (answer.artifactHashes && typeof answer.artifactHashes === "object" && !Array.isArray(answer.artifactHashes)) {
    for (const [key, value] of Object.entries(answer.artifactHashes).slice(0, 12)) {
      if (/^[A-Za-z0-9._-]{1,80}$/.test(key) && typeof value === "string" && /^[a-f0-9]{64}$/i.test(value)) artifactHashes[key] = value.toLowerCase();
    }
  }
  return {
    recordRefs,
    citations,
    claimReferences,
    researchQuestions,
    artifactHashes,
    metricSummary: normalizeMetricSummary(answer.metricSummary),
    investigationId: normalizeInvestigationId(answer.investigationId, ""),
    metric: PSI25_METRIC_ORDER.includes(answer.metric) ? answer.metric : "",
    rankableCohortCount: safeNonnegativeInteger(answer.rankableCohortCount),
    notRankableCohortCount: safeNonnegativeInteger(answer.notRankableCohortCount),
    eligiblePairCount: safeNonnegativeInteger(answer.eligiblePairCount),
    excludedPairCount: safeNonnegativeInteger(answer.excludedPairCount),
    scientificPlan: normalizeScientificPlan(answer.scientificPlan),
    claimLedger: normalizeClaimLedger(answer),
  };
}

function makeAnswerDisclosure(title, className) {
  const details = document.createElement("details");
  details.className = className;
  const summary = document.createElement("summary");
  summary.textContent = title;
  details.append(summary);
  return { details, body: details };
}


function makeScientificPlanDisclosure(plan) {
  const details = document.createElement("details");
  details.className = "answer-scientific-plan";
  details.dataset.decision = plan.decision;
  const summary = document.createElement("summary");
  const title = document.createElement("span");
  title.textContent = "Scientific intent plan";
  const state = document.createElement("small");
  state.textContent = plan.decision === "execute"
    ? "Registered operation approved"
    : "Abstained · no operation executed";
  summary.append(title, state);
  details.append(summary);

  const body = document.createElement("div");
  body.className = "answer-scientific-plan-body";
  const facts = document.createElement("dl");
  facts.className = "answer-scientific-plan-facts";
  const factRows = [
    ["Decision", plan.decision === "execute" ? "Execution approved" : "Abstained · no analysis run"],
    ["Requested investigation", investigationDisplayName(plan.requestedInvestigation)],
    ["Resolved investigation", plan.resolvedInvestigation ? investigationDisplayName(plan.resolvedInvestigation) : "Not resolved"],
    ["Scientific intent", plan.intent.replaceAll("_", " ")],
    ["Metric", plan.metric ? plan.metric.toUpperCase() : "Not applicable"],
    ["Registered operation", plan.operationId || "No operation selected"],
    ["Evidence scope", plan.dataScope.replaceAll("-", " ")],
    ["Execution permission", plan.executionAllowed ? "Allowed by validated plan" : "Not allowed"],
  ];
  for (const [term, value] of factRows) {
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    row.append(dt, dd);
    facts.append(row);
  }
  body.append(facts);

  const appendList = (headingText, className, values, formatter = (value) => value) => {
    if (!values?.length) return;
    const section = document.createElement("section");
    section.className = `answer-scientific-plan-list ${className}`;
    const heading = document.createElement("h4");
    heading.textContent = headingText;
    const list = document.createElement("ul");
    for (const value of values) {
      const item = document.createElement("li");
      item.textContent = formatter(value);
      list.append(item);
    }
    section.append(heading, list);
    body.append(section);
  };
  appendList("Required verified evidence", "is-evidence", plan.evidenceRequirements);
  appendList("Scientific constraints", "is-constraints", plan.constraintCodes, (value) => value.replaceAll("_", " "));
  appendList("Decision reasons", "is-reasons", plan.reasonCodes, (value) => value.replaceAll("_", " "));
  appendList("Selection rules", "is-rules", plan.selectionRules);
  if (plan.explanation) {
    const explanation = document.createElement("p");
    explanation.className = "answer-scientific-plan-explanation";
    explanation.textContent = plan.explanation;
    body.append(explanation);
  }
  details.append(body);
  return details;
}

function makeClaimLedgerJsonPanel(title, value, className) {
  const disclosure = makeAnswerDisclosure(title, className);
  const pre = document.createElement("pre");
  pre.className = "answer-claim-ledger-json";
  pre.textContent = JSON.stringify(value, null, 2);
  disclosure.body.append(pre);
  return disclosure.details;
}

function makeClaimLedgerDisclosure(ledger) {
  const disclosure = makeAnswerDisclosure(`Evidence Claim Ledger (${ledger.claims.length})`, "answer-claim-ledger");
  const body = disclosure.body;

  const status = document.createElement("p");
  status.className = "answer-claim-ledger-status";
  status.textContent = "VERIFIED PROVENANCE · NOT SCIENTIFIC TRUTH";
  body.append(status);

  const metadata = document.createElement("dl");
  metadata.className = "answer-claim-ledger-metadata";
  const metadataRows = [
    ["Investigation", ledger.investigationId],
    ["Source release", ledger.sourceRelease],
    ["Operation", ledger.operationId],
    ["Metric", ledger.metric || "Not specified"],
    ["Data scope", ledger.dataScope],
  ];
  for (const [label, value] of metadataRows) {
    const term = document.createElement("dt"); term.textContent = label;
    const description = document.createElement("dd"); description.textContent = value;
    metadata.append(term, description);
  }
  body.append(metadata);

  const warning = document.createElement("p");
  warning.className = "answer-claim-ledger-warning";
  warning.textContent = "This status means that provenance, source hashes and structural record-lineage checks passed. It does not establish scientific truth, causality, independent replication, safety, or mission transferability.";
  body.append(warning);

  if (!ledger.claims.length) {
    const empty = document.createElement("p");
    empty.className = "answer-claim-ledger-empty";
    empty.textContent = "This operation emitted no claims. No claim-level conclusion is available.";
    body.append(empty);
  }

  for (const claim of ledger.claims) {
    const card = document.createElement("article");
    card.className = "answer-claim-ledger-card";
    const heading = document.createElement("h4");
    heading.textContent = `${claim.claimId} · ${claim.claimType.replaceAll("_", " ")}`;
    card.append(heading);

    const interpretation = document.createElement("p");
    interpretation.className = "answer-claim-ledger-interpretation";
    interpretation.textContent = `Interpretation status: ${claim.interpretationStatus.replaceAll("_", " ")}`;
    card.append(interpretation);

    const claimScope = document.createElement("p");
    claimScope.className = "answer-claim-ledger-claim-scope";
    claimScope.textContent = `Metric: ${claim.metric || ledger.metric || "Not specified"} · Unit: ${claim.unit || "Not specified"}`;
    card.append(claimScope);

    const statement = document.createElement("p");
    statement.className = "answer-claim-ledger-statement";
    statement.textContent = claim.statement;
    card.append(statement);

    card.append(makeClaimLedgerJsonPanel("Structured result", claim.result, "answer-claim-ledger-result"));

    const refs = document.createElement("section");
    refs.className = "answer-claim-ledger-references";
    const refsHeading = document.createElement("h5"); refsHeading.textContent = `Evidence references (${claim.evidenceReferences.length})`;
    const refsList = document.createElement("ul");
    for (const ref of claim.evidenceReferences) {
      const item = document.createElement("li");
      const refName = document.createElement("strong"); refName.textContent = ref.referenceId;
      const hash = document.createElement("code"); hash.textContent = `SHA-256 ${ref.sha256}`;
      item.append(refName, hash); refsList.append(item);
    }
    refs.append(refsHeading, refsList); card.append(refs);

    card.append(makeClaimLedgerJsonPanel("Record lineage and selection scope", claim.recordLineage, "answer-claim-ledger-lineage"));
    card.append(makeClaimLedgerJsonPanel("Quality dimensions", claim.qualityDimensions, "answer-claim-ledger-quality"));
    if (claim.cohort !== null) card.append(makeClaimLedgerJsonPanel("Cohort definition", claim.cohort, "answer-claim-ledger-cohort"));

    const limitations = document.createElement("section");
    limitations.className = "answer-claim-ledger-limitations";
    const limitationsHeading = document.createElement("h5"); limitationsHeading.textContent = `Limitations (${claim.limitations.length})`;
    const limitationsList = document.createElement("ul");
    for (const text of claim.limitations) {
      const item = document.createElement("li"); item.textContent = text; limitationsList.append(item);
    }
    limitations.append(limitationsHeading, limitationsList); card.append(limitations);
    body.append(card);
  }
  return disclosure.details;
}

function makeStructuredAnswerDetails(answer) {
  const root = document.createElement("section");
  root.className = "answer-structured";
  const investigation = answer.investigationId || "";
  if (investigation || answer.metric) {
    const badges = document.createElement("div");
    badges.className = "answer-scope-badges";
    if (investigation) {
      const badge = document.createElement("span");
      badge.textContent = investigationDisplayName(investigation);
      badges.append(badge);
    }
    if (answer.metric) {
      const badge = document.createElement("span");
      badge.textContent = `Metric · ${answer.metric.toUpperCase()}`;
      badges.append(badge);
    }
    root.append(badges);
  }

  if (answer.scientificPlan) root.append(makeScientificPlanDisclosure(answer.scientificPlan));

  if (answer.claimLedger) root.append(makeClaimLedgerDisclosure(answer.claimLedger));
  if (Object.keys(answer.metricSummary || {}).length) {
    const section = document.createElement("section");
    section.className = "answer-metric-summary";
    const heading = document.createElement("h3");
    heading.textContent = "BASS-II metric-separated summary";
    const note = document.createElement("p");
    note.textContent = "O₂, CO₂ and CO remain separate measurement scopes; these values are not pooled or ranked against one another.";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const header = document.createElement("tr");
    for (const label of ["Metric", "Eligible pairs", "Excluded", "Rankable cohorts", "Not rankable", "Insight cards"]) {
      const th = document.createElement("th"); th.scope = "col"; th.textContent = label; header.append(th);
    }
    thead.append(header); table.append(thead);
    const tbody = document.createElement("tbody");
    for (const metric of PSI25_METRIC_ORDER) {
      const rowData = answer.metricSummary[metric];
      if (!rowData) continue;
      const tr = document.createElement("tr");
      const values = [metric.toUpperCase(), rowData.eligiblePairs, rowData.excludedPairs, rowData.rankableCohorts, rowData.notRankableCohorts, rowData.insightCards];
      for (const value of values) { const td = document.createElement("td"); td.textContent = String(value); tr.append(td); }
      tbody.append(tr);
    }
    table.append(tbody); section.append(heading, note, table); root.append(section);
  }

  if (answer.claimReferences?.length) {
    const disclosure = makeAnswerDisclosure(`Claim-level cohort evidence (${answer.claimReferences.length})`, "answer-claims");
    for (const claim of answer.claimReferences) {
      const card = document.createElement("article"); card.className = "answer-claim-card";
      const heading = document.createElement("h4");
      const cohort = [claim.cohort.pi, claim.cohort.materialClass, claim.cohort.flowRestrictorCode].filter(Boolean).join(" · ");
      heading.textContent = `${claim.rank ? `Rank ${claim.rank} · ` : ""}${claim.metric ? claim.metric.toUpperCase() : "Metric"}${cohort ? ` · ${cohort}` : ""}`;
      card.append(heading);
      const stats = Object.entries(claim.statistics || {});
      if (stats.length) {
        const p = document.createElement("p");
        p.textContent = stats.map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · ");
        card.append(p);
      }
      if (claim.interpretation) { const p = document.createElement("p"); p.textContent = claim.interpretation; card.append(p); }
      if (claim.distribution) { const p = document.createElement("p"); p.textContent = claim.distribution; card.append(p); }
      if (claim.flags?.length) { const p = document.createElement("p"); p.className = "answer-claim-flags"; p.textContent = `Flags: ${claim.flags.join(" · ")}`; card.append(p); }
      const counts = document.createElement("p");
      counts.textContent = `Supporting canonical records: ${claim.supportingRecordKeys.length} · Excluded record references: ${claim.excludedRecordKeys.length}`;
      card.append(counts); disclosure.body.append(card);
    }
    root.append(disclosure.details);
  }

  if (answer.researchQuestions?.length) {
    const disclosure = makeAnswerDisclosure(`Research questions (${answer.researchQuestions.length})`, "answer-research-questions");
    const list = document.createElement("ol");
    for (const question of answer.researchQuestions) {
      const item = document.createElement("li");
      const strong = document.createElement("strong"); strong.textContent = question.questionId;
      const text = document.createElement("p"); text.textContent = question.question;
      item.append(strong, text);
      if (question.trigger) { const trigger = document.createElement("small"); trigger.textContent = `Evidence-gap trigger: ${question.trigger}`; item.append(trigger); }
      list.append(item);
    }
    disclosure.body.append(list); root.append(disclosure.details);
  }

  if (answer.recordRefs?.length) {
    const disclosure = makeAnswerDisclosure(`Verified canonical record keys (${answer.recordRefs.length})`, "answer-record-refs");
    const list = document.createElement("ul");
    for (const key of answer.recordRefs) { const item = document.createElement("li"); item.textContent = key; list.append(item); }
    disclosure.body.append(list); root.append(disclosure.details);
  }

  if (answer.citations?.length) {
    const disclosure = makeAnswerDisclosure(`Evidence citations (${answer.citations.length})`, "answer-citations");
    const list = document.createElement("ul");
    for (const citation of answer.citations) {
      const item = document.createElement("li");
      const title = document.createElement("strong"); title.textContent = citation.title || citation.referenceId || "Evidence reference"; item.append(title);
      if (citation.kind) { const kind = document.createElement("small"); kind.textContent = citation.kind.replaceAll("_", " "); item.append(kind); }
      if (citation.sha256) { const hash = document.createElement("code"); hash.textContent = `SHA-256 ${citation.sha256}`; item.append(hash); }
      try {
        const url = new URL(citation.url);
        if (url.protocol === "https:" && url.hostname === "psi.nasa.gov") {
          const link = document.createElement("a"); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "Open NASA source"; item.append(link);
        }
      } catch { /* Local evidence references intentionally have no external URL. */ }
      list.append(item);
    }
    disclosure.body.append(list); root.append(disclosure.details);
  }

  if (Object.keys(answer.artifactHashes || {}).length) {
    const disclosure = makeAnswerDisclosure(`Verified artifact hashes (${Object.keys(answer.artifactHashes).length})`, "answer-artifact-hashes");
    const list = document.createElement("ul");
    for (const [key, hash] of Object.entries(answer.artifactHashes)) {
      const item = document.createElement("li"); const label = document.createElement("strong"); label.textContent = key;
      const value = document.createElement("code"); value.textContent = hash; item.append(label, value); list.append(item);
    }
    disclosure.body.append(list); root.append(disclosure.details);
  }
  return root;
}

function updateAskEvidenceContext(value) {
  const selected = normalizeInvestigationId(value, "auto");
  const isPsi25 = selected === "psi25-bass-ii-v4";
  const isPsi69 = selected === "psi69-flex-v5";
  const title = isPsi25 ? "NASA BASS-II" : isPsi69 ? "NASA FLEX" : "Automatic routing";
  const description = isPsi25 ? "BASS-II · microgravity combustion" : isPsi69 ? "FLEX · droplet combustion" : "PSI-69 FLEX v5 · PSI-25 BASS-II v4";
  const countLabel = isPsi25 ? "Canonical records" : isPsi69 ? "Source records" : "Registered investigations";
  const count = isPsi25 ? "129" : isPsi69 ? (records.length ? String(records.length) : "Unavailable") : "2 approved";
  const release = isPsi25 ? "PSI-25 · Study Version 4" : isPsi69 ? "PSI-69 · Version 5" : "Auto · registered sources";
  const sourceHref = isPsi25
    ? "https://psi.nasa.gov/physci/repo/data/investigations/PSI-25"
    : isPsi69
      ? "https://psi.nasa.gov/physci/repo/data/investigations/PSI-69"
      : "#methods";
  const sourceLabel = isPsi25 || isPsi69 ? "Open NASA source" : "Review registered sources";
  const titleNode = $("#assistant-evidence-title");
  const descriptionNode = $("#assistant-evidence-description");
  const countLabelNode = $("#assistant-record-label");
  const countNode = $("#assistant-record-count");
  const releaseNode = $("#assistant-source-version");
  const sourceLink = $("#assistant-source-link");
  const sourceLinkLabel = $("#assistant-source-link-label");
  if (titleNode) titleNode.textContent = title;
  if (descriptionNode) descriptionNode.textContent = description;
  if (countLabelNode) countLabelNode.textContent = countLabel;
  if (countNode) countNode.textContent = count;
  if (releaseNode) releaseNode.textContent = release;
  if (sourceLink) {
    sourceLink.href = sourceHref;
    sourceLink.target = isPsi25 || isPsi69 ? "_blank" : "_self";
    sourceLink.rel = "noopener noreferrer";
  }
  if (sourceLinkLabel) sourceLinkLabel.textContent = sourceLabel;

  const promptSets = {
    auto: ["Summarize the FLEX dataset", "Summarize BASS-II dataset", "Show outcome counts by fuel", "Show O₂ ranking in BASS-II"],
    "psi69-flex-v5": ["Summarize the FLEX dataset", "Show outcome counts by fuel", "What should I know about data quality?", "Compare oxygen conditions"],
    "psi25-bass-ii-v4": ["Summarize BASS-II dataset", "Show O₂ ranking in BASS-II", "List BASS-II research questions", "Show CO₂ findings in BASS-II"],
  };
  for (const host of [welcomeMessageTemplate, $("#conversation")]) {
    if (!host) continue;
    const buttons = [...host.querySelectorAll(".suggestion")];
    buttons.forEach((button, index) => {
      const prompt = promptSets[selected][index];
      if (!prompt) return;
      button.dataset.prompt = prompt;
      const label = button.querySelector("span:nth-child(2)");
      if (label) label.textContent = prompt;
    });
  }
  const input = $("#question-input");
  if (input) input.placeholder = isPsi25
    ? "Ask about BASS-II O₂, CO₂, CO findings, or research questions…"
    : isPsi69
      ? "Ask about FLEX records, outcomes, or data quality…"
      : "Ask about FLEX or BASS-II evidence…";
}

function handleInvestigationSelectionChange() {
  const selector = $("#investigation-select");
  if (!selector) return;
  const selected = normalizeInvestigationId(selector.value, "auto");
  selector.value = selected;
  const active = conversations.find((item) => item.id === activeConversationId);
  if (active?.messages?.length) {
    // A conversation is investigation-scoped. Changing sources starts a new draft and preserves the old thread.
    activeConversationId = null;
  } else if (active) {
    active.investigationId = selected;
  }
  saveChatState();
  renderActiveConversation();
}

const CHAT_STORAGE_KEY = "sira-firelab-chat-history-v1";
const MAX_SAVED_CONVERSATIONS = 40;
const welcomeMessageTemplate = $("#welcome-message")?.cloneNode(true);

const OUTCOME_ORDER = ["Extinction", "Disruption", "Completion"];
const OUTCOME_CLASS = { Extinction: "extinction", Disruption: "disruption", Completion: "completion" };
const PAGE_LABELS = { ask: "Ask SIRA", overview: "Overview", data: "Data Explorer", psi25: "BASS-II Explorer", research: "Research Lab", methods: "Methods & Sources" };
const CONDITION_BASELINE = {
  pressureMin: 750,
  pressureMax: 770,
  oxygenMoleFraction: 0.21,
  coSourceMoleFraction: 0,
  heliumMoleFraction: 0,
};

function addCell(row, value, className = "") {
  const cell = document.createElement("td");
  cell.textContent = value;
  if (className) cell.className = className;
  row.append(cell);
  return cell;
}

function sourceValue(record, key, value) {
  const status = record.quality?.[key];
  if (status === "missing" || status === "invalid" || value === null || value === undefined) {
    return { text: "—", className: "missing", title: status === "invalid" ? "Source value could not be parsed" : "No exact value reported" };
  }
  const raw = record.sourceValues || {};
  const sourceKey = {
    ambientPressureMmHg: "Ambient pressure; mmHg",
    oxygenMoleFraction: "O initial ambient composition; mole fraction",
    visibleFlameExtinctionDiameterMm: "Visible flame extinction diameter; mm",
    burningRateMm2PerSec: "Burning rate; mm",
  }[key];
  const text = sourceKey && raw[sourceKey] ? raw[sourceKey] : String(value);
  return { text, className: status === "approximate" ? "approximate" : "", title: status === "approximate" ? "Approximate value as marked in the source" : "Source-reported value" };
}

function renderRecords() {
  if (!recordsBody || !records.length) return;
  const fuel = $("#fuel-filter").value;
  const outcome = $("#outcome-filter").value;
  const filtered = records.filter((record) => (!fuel || record.fuel === fuel) && (!outcome || record.testEnd === outcome));
  recordsBody.replaceChildren();
  for (const record of filtered) {
    const row = document.createElement("tr");
    addCell(row, String(record.testNumber));
    addCell(row, record.fuel || "—");
    for (const [key, value] of [
      ["ambientPressureMmHg", record.ambientPressureMmHg],
      ["oxygenMoleFraction", record.oxygenMoleFraction],
      ["visibleFlameExtinctionDiameterMm", record.visibleFlameExtinctionDiameterMm],
      ["burningRateMm2PerSec", record.burningRateMm2PerSec],
    ]) {
      const formatted = sourceValue(record, key, value);
      const cell = addCell(row, formatted.text, formatted.className);
      cell.title = formatted.title;
      if (key === "ambientPressureMmHg" && record.flags?.includes("zero_pressure_source_value")) {
        cell.classList.add("flagged");
        cell.title = "NASA source reports 0 mmHg; preserved and flagged for interpretation";
      }
    }
    addCell(row, record.testEnd || "—");
    recordsBody.append(row);
  }
  $("#record-match").textContent = `Showing ${filtered.length} of ${records.length} tests`;
}

function addFilterOptions(selector, values, allLabel) {
  const select = $(selector);
  const first = document.createElement("option");
  first.value = "";
  first.textContent = allLabel;
  select.replaceChildren(first);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
}

function renderQuality() {
  qualityBody.replaceChildren();
  const order = [
    "ambientPressureMmHg", "oxygenMoleFraction", "nitrogenMoleFraction", "coSourceMoleFraction",
    "heliumMoleFraction", "initialDropletDiameterMm", "visibleFlameExtinctionDiameterMm",
    "burningRateMm2PerSec", "burnTimeSeconds",
  ];
  for (const key of order) {
    const metric = quality.measurementQuality?.[key];
    if (!metric) continue;
    const row = document.createElement("tr");
    addCell(row, `${metric.label} (${metric.unit})`);
    addCell(row, String(metric.exact));
    addCell(row, String(metric.approximate));
    addCell(row, String(metric.missing));
    addCell(row, String(metric.invalid));
    qualityBody.append(row);
  }
  const notes = $("#source-notes");
  notes.replaceChildren();
  const list = document.createElement("ul");
  for (const note of quality.sourceNotes || []) {
    const item = document.createElement("li");
    item.textContent = note;
    list.append(item);
  }
  notes.append(list);
  const duplicateCount = quality.identifierChecks?.["FLEX Identifier"]?.duplicateRows ?? 0;
  const pressureCount = quality.zeroPressureTestNumbers?.length ?? 0;
  const compositionCount = quality.compositionCheck?.outsideOnePercent ?? 0;
  const flags = [
    [duplicateCount, "reused secondary identifier"],
    [pressureCount, "source-reported zero pressure"],
    [compositionCount, "mixtures outside ±0.01 of 1"],
  ];
  const flagHost = $("#quality-flags");
  flagHost.replaceChildren();
  for (const [count, label] of flags) {
    const card = document.createElement("div");
    card.className = "quality-flag";
    const value = document.createElement("strong");
    value.textContent = String(count);
    const caption = document.createElement("span");
    caption.textContent = label;
    card.append(value, caption);
    flagHost.append(card);
  }
}

function countsBy(recordsToCount, field) {
  const counts = {};
  for (const row of recordsToCount) {
    const value = row[field];
    if (value) counts[value] = (counts[value] || 0) + 1;
  }
  return counts;
}

function fuels() {
  return Object.keys(quality?.fuelCounts || countsBy(records, "fuel")).sort();
}

function outcomes() {
  const counts = quality?.testEndCounts || countsBy(records, "testEnd");
  const known = OUTCOME_ORDER.filter((name) => counts[name] !== undefined);
  const other = Object.keys(counts).filter((name) => !OUTCOME_ORDER.includes(name)).sort();
  return [...known, ...other];
}

function formatNumber(value, digits = 2) {
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
}

function exactMeasurementSummary(rows, key) {
  const exact = rows.filter((row) => row.quality?.[key] === "exact" && Number.isFinite(row[key])).map((row) => row[key]);
  const approximate = rows.filter((row) => row.quality?.[key] === "approximate").length;
  const missing = rows.filter((row) => row.quality?.[key] === "missing" || row[key] === null || row[key] === undefined).length;
  const invalid = rows.filter((row) => row.quality?.[key] === "invalid").length;
  const mean = exact.length ? exact.reduce((sum, value) => sum + value, 0) / exact.length : null;
  const variance = exact.length > 1 ? exact.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (exact.length - 1) : null;
  return { n: exact.length, mean, sd: variance === null ? null : Math.sqrt(variance), approximate, missing, invalid };
}

function renderOutcomeChart() {
  const host = $("#outcome-chart");
  const counts = quality.testEndCounts || countsBy(records, "testEnd");
  const names = outcomes();
  const total = records.length;
  const maximum = Math.max(1, ...names.map((name) => counts[name] || 0));
  $("#outcome-total").textContent = String(total);
  host.replaceChildren();
  host.setAttribute("aria-label", names.map((name) => `${name}: ${counts[name] || 0}`).join("; "));
  for (const name of names) {
    const count = counts[name] || 0;
    const row = document.createElement("div");
    row.className = "outcome-row";
    const label = document.createElement("span");
    label.className = "outcome-label";
    label.textContent = name;
    const track = document.createElement("div");
    track.className = "bar-track";
    track.setAttribute("aria-hidden", "true");
    const fill = document.createElement("div");
    fill.className = `bar-fill ${OUTCOME_CLASS[name] || ""}`;
    fill.style.width = `${(count / maximum) * 100}%`;
    track.append(fill);
    const value = document.createElement("strong");
    value.className = "outcome-count";
    value.textContent = String(count);
    row.append(label, track, value);
    host.append(row);
  }
  const legend = $("#mix-legend");
  legend.replaceChildren();
  for (const name of names) {
    const item = document.createElement("span");
    const dot = document.createElement("i");
    dot.className = `${OUTCOME_CLASS[name] || ""}-color`;
    const text = document.createElement("span");
    text.textContent = name;
    item.append(dot, text);
    legend.append(item);
  }
}

function renderFuelMix() {
  const host = $("#fuel-outcome-mix");
  host.replaceChildren();
  const outcomeNames = outcomes();
  for (const fuel of fuels()) {
    const rows = records.filter((row) => row.fuel === fuel);
    const row = document.createElement("div");
    row.className = "fuel-mix-row";
    const heading = document.createElement("div");
    heading.className = "fuel-mix-heading";
    const name = document.createElement("span");
    name.textContent = fuel;
    const n = document.createElement("small");
    n.textContent = `n = ${rows.length}`;
    heading.append(name, n);
    const track = document.createElement("div");
    track.className = "stack-track";
    track.setAttribute("role", "img");
    const countLine = document.createElement("div");
    countLine.className = "stack-counts";
    const pieces = [];
    for (const outcome of outcomeNames) {
      const count = rows.filter((item) => item.testEnd === outcome).length;
      const segment = document.createElement("span");
      segment.className = `stack-segment ${OUTCOME_CLASS[outcome] || ""}`;
      segment.style.width = `${rows.length ? (count / rows.length) * 100 : 0}%`;
      segment.title = `${outcome}: ${count} of ${rows.length}`;
      track.append(segment);
      pieces.push(`${outcome} ${count}`);
    }
    track.setAttribute("aria-label", `${fuel}: ${pieces.join(", ")}`);
    countLine.textContent = "";
    outcomeNames.forEach((outcome, index) => {
      if (index) countLine.append(document.createTextNode(" · "));
      const part = document.createElement("span");
      const label = document.createTextNode(`${outcome} `);
      const value = document.createElement("b");
      value.textContent = String(rows.filter((item) => item.testEnd === outcome).length);
      part.append(label, value);
      countLine.append(part);
    });
    row.append(heading, track, countLine);
    host.append(row);
  }
}

function renderBurnRateSummary() {
  const host = $("#burn-rate-summary");
  host.replaceChildren();
  for (const fuel of fuels()) {
    const rows = records.filter((row) => row.fuel === fuel);
    const summary = exactMeasurementSummary(rows, "burningRateMm2PerSec");
    const card = document.createElement("div");
    card.className = "rate-group";
    const title = document.createElement("span");
    title.textContent = fuel;
    const value = document.createElement("strong");
    value.className = "rate-value";
    value.textContent = `${formatNumber(summary.mean, 3)} ± ${formatNumber(summary.sd, 3)}`;
    const note = document.createElement("small");
    note.textContent = `n = ${summary.n} exact · ${summary.missing} missing`;
    card.append(title, value, note);
    host.append(card);
  }
}

function populateConditionChoices(selector, field, defaultValue) {
  const select = $(selector);
  if (!select) return;
  const values = [...new Set(records
    .filter((record) => record.quality?.[field] === "exact" && Number.isFinite(record[field]))
    .map((record) => record[field]))].sort((left, right) => left - right);
  const options = [new Option("Any exact value", "")];
  for (const value of values) options.push(new Option(String(value), String(value)));
  select.replaceChildren(...options);
  const requested = String(defaultValue);
  select.value = values.some((value) => String(value) === requested) ? requested : "";
}

function readConditionFilters() {
  const optionalValue = (selector) => {
    const value = $(selector)?.value ?? "";
    return value === "" ? null : Number(value);
  };
  return {
    pressureMin: Number($("#condition-pressure-min")?.value),
    pressureMax: Number($("#condition-pressure-max")?.value),
    oxygenMoleFraction: optionalValue("#condition-oxygen"),
    coSourceMoleFraction: optionalValue("#condition-co"),
    heliumMoleFraction: optionalValue("#condition-helium"),
  };
}

function renderConditionEvidence() {
  const host = $("#condition-results");
  const cohort = $("#condition-cohort");
  const errorHost = $("#condition-error");
  const rankingHost = $("#condition-ranking-list");
  const rankingEmpty = $("#condition-ranking-empty");
  if (!host || !cohort || !errorHost || !rankingHost || !rankingEmpty) return;
  host.replaceChildren();
  rankingHost.replaceChildren();
  rankingEmpty.hidden = true;
  if (!records.length || !window.FireLabConditionAnalysis) {
    cohort.textContent = "Condition evidence is unavailable until the local source bundle loads.";
    renderOutcomeGapRanking([], "Load the local source bundle to rank observed outcome gaps.");
    renderOxygenSensitivity(null);
    return;
  }

  const filters = readConditionFilters();
  renderOxygenSensitivity(filters);
  const result = window.FireLabConditionAnalysis.filterRecords(records, filters);
  errorHost.hidden = !result.error;
  errorHost.textContent = result.error || "";
  if (result.error) {
    cohort.textContent = "No comparison was run. Correct the highlighted pressure bounds.";
    renderOutcomeGapRanking([], "Correct the condition filters to rank observed outcome gaps.");
    return;
  }
  const sourceGas = filters.coSourceMoleFraction === null ? "any exact value" : formatNumber(filters.coSourceMoleFraction, 3);
  const helium = filters.heliumMoleFraction === null ? "any exact value" : formatNumber(filters.heliumMoleFraction, 3);
  const oxygen = filters.oxygenMoleFraction === null ? "any exact value" : formatNumber(filters.oxygenMoleFraction, 3);
  cohort.textContent = `${result.rows.length} matched records · ${formatNumber(filters.pressureMin, 1)}–${formatNumber(filters.pressureMax, 1)} mmHg · O₂ ${oxygen} · source CO ${sourceGas} · He ${helium}`;

  if (!result.rows.length) {
    const empty = document.createElement("p");
    empty.className = "condition-empty";
    empty.textContent = "No source records match these exact conditions. Widen the pressure range or choose another composition value.";
    host.append(empty);
    renderOutcomeGapRanking([], "No records matched this cohort. Adjust the filters to see outcome gaps.");
    return;
  }

  const groups = window.FireLabConditionAnalysis.summarizeByFuel(result.rows);
  renderOutcomeGapRanking(groups);
  for (const group of groups) {
    const card = document.createElement("article");
    card.className = "condition-result-card";
    const header = document.createElement("div");
    header.className = "condition-result-heading";
    const title = document.createElement("h3");
    title.textContent = group.fuel;
    const sample = document.createElement("span");
    sample.textContent = `n = ${group.n} matched tests`;
    header.append(title, sample);
    card.append(header);

    const outcomesHost = document.createElement("div");
    outcomesHost.className = "condition-outcomes";
    for (const item of group.outcomeSummaries) {
      const row = document.createElement("div");
      row.className = "condition-outcome-row";
      const label = document.createElement("span");
      label.className = "condition-outcome-label";
      label.textContent = item.outcome;
      const track = document.createElement("div");
      track.className = "condition-bar-track";
      track.setAttribute("aria-hidden", "true");
      const fill = document.createElement("div");
      fill.className = `condition-bar-fill ${OUTCOME_CLASS[item.outcome] || ""}`;
      fill.style.width = `${item.share * 100}%`;
      track.append(fill);
      const value = document.createElement("span");
      value.className = "condition-outcome-value";
      value.textContent = `${item.count}/${group.n} · ${formatNumber(item.share * 100, 1)}%`;
      const interval = document.createElement("small");
      interval.className = "condition-interval";
      interval.textContent = `95% Wilson CI ${formatNumber(item.ciLow * 100, 1)}–${formatNumber(item.ciHigh * 100, 1)}%`;
      row.append(label, track, value, interval);
      row.setAttribute("aria-label", `${item.outcome}: ${item.count} of ${group.n}, ${formatNumber(item.share * 100, 1)} percent; 95 percent Wilson interval ${formatNumber(item.ciLow * 100, 1)} to ${formatNumber(item.ciHigh * 100, 1)} percent`);
      outcomesHost.append(row);
    }
    card.append(outcomesHost);

    const diameter = group.extinctionDiameter;
    const diameterNote = document.createElement("p");
    diameterNote.className = "condition-diameter-note";
    const diameterSummary = diameter.exact
      ? `Median ${formatNumber(diameter.median, 2)} mm (range ${formatNumber(diameter.min, 2)}–${formatNumber(diameter.max, 2)} mm)`
      : "No exact diameter values in this slice";
    diameterNote.textContent = `Visible-flame extinction diameter among Extinction tests: ${diameterSummary}. Exact n=${diameter.exact}; approximate ${diameter.approximate}; missing ${diameter.missing}; invalid ${diameter.invalid}.`;
    card.append(diameterNote);
    host.append(card);
  }
}

function renderOutcomeGapRanking(groups, emptyMessage = "At least two fuel groups with matched records are needed to rank outcome-share gaps.") {
  const host = $("#condition-ranking-list");
  const empty = $("#condition-ranking-empty");
  if (!host || !empty) return;
  host.replaceChildren();
  const ranked = window.FireLabConditionAnalysis?.rankOutcomeShareGaps(groups) || [];
  if (!ranked.length) {
    empty.hidden = false;
    empty.textContent = emptyMessage;
    return;
  }
  empty.hidden = true;
  for (const [index, item] of ranked.entries()) {
    const row = document.createElement("li");
    row.className = "condition-rank-item";
    const position = document.createElement("span");
    position.className = "condition-rank-position";
    position.textContent = String(index + 1).padStart(2, "0");
    const description = document.createElement("div");
    description.className = "condition-rank-description";
    const heading = document.createElement("div");
    heading.className = "condition-rank-title";
    const outcome = document.createElement("b");
    outcome.textContent = item.outcome;
    const direction = document.createElement("span");
    direction.textContent = item.higherShareFuel ? `Larger observed share: ${item.higherShareFuel}` : "Equal observed shares";
    heading.append(outcome, direction);
    const pair = document.createElement("p");
    pair.textContent = `${item.left.fuel} ${item.left.count}/${item.left.n} (${formatNumber(item.left.share * 100, 1)}%) · ${item.right.fuel} ${item.right.count}/${item.right.n} (${formatNumber(item.right.share * 100, 1)}%)`;
    description.append(heading, pair);
    const gap = document.createElement("strong");
    gap.className = "condition-rank-gap";
    gap.textContent = `${formatNumber(item.gapPercentagePoints, 1)} pp`;
    row.setAttribute("aria-label", `Rank ${index + 1}, ${item.outcome}, absolute observed share gap ${formatNumber(item.gapPercentagePoints, 1)} percentage points. ${pair.textContent}.`);
    row.append(position, description, gap);
    host.append(row);
  }
}

function renderOxygenSensitivity(filters) {
  const host = $("#condition-sensitivity");
  if (!host) return;
  host.replaceChildren();

  const status = (message) => {
    const paragraph = document.createElement("p");
    paragraph.className = "condition-sensitivity-empty";
    paragraph.textContent = message;
    host.append(paragraph);
  };
  if (!records.length || !window.FireLabConditionAnalysis) {
    status("Sensitivity comparison is unavailable until the local NASA source bundle loads.");
    return;
  }
  if (!filters) {
    status("Sensitivity comparison is unavailable until the condition filters are ready.");
    return;
  }

  const fixedFilters = {
    pressureMin: filters.pressureMin,
    pressureMax: filters.pressureMax,
    coSourceMoleFraction: filters.coSourceMoleFraction,
    heliumMoleFraction: filters.heliumMoleFraction,
  };
  const definitions = [
    { label: "Fixed oxygen · 0.21", oxygenMoleFraction: 0.21 },
    { label: "All exact oxygen values", oxygenMoleFraction: null },
  ];
  const slices = definitions.map((definition) => {
    const result = window.FireLabConditionAnalysis.filterRecords(records, {
      ...fixedFilters,
      oxygenMoleFraction: definition.oxygenMoleFraction,
    });
    return {
      ...definition,
      rows: result.rows,
      error: result.error,
      groups: window.FireLabConditionAnalysis.summarizeByFuel(result.rows),
    };
  });

  const invalidSlice = slices.find((slice) => slice.error);
  if (invalidSlice) {
    status(`Sensitivity comparison unavailable: ${invalidSlice.error}`);
    return;
  }
  const insufficientSlice = slices.find((slice) => window.FireLabConditionAnalysis.rankOutcomeShareGaps(slice.groups).length === 0);
  if (insufficientSlice) {
    status(`At least two fuel groups with matched records are needed in both slices. ${insufficientSlice.label} has ${insufficientSlice.groups.length} fuel group${insufficientSlice.groups.length === 1 ? "" : "s"}.`);
    return;
  }

  const rankedSlices = slices.map((slice) => ({
    ...slice,
    ranked: window.FireLabConditionAnalysis.rankOutcomeShareGaps(slice.groups),
  }));
  const rankOrder = (slice) => slice.ranked.map((item) => item.outcome);
  const fixedOrder = rankOrder(rankedSlices[0]);
  const broadOrder = rankOrder(rankedSlices[1]);
  const orderChanged = fixedOrder.join("|") !== broadOrder.join("|");
  const orderNote = document.createElement("p");
  orderNote.className = `condition-sensitivity-order${orderChanged ? " is-changed" : ""}`;
  const orderLabel = document.createElement("b");
  orderLabel.textContent = orderChanged ? "Observed rank order changes" : "Observed rank order is unchanged";
  const orderText = document.createElement("span");
  orderText.textContent = `O₂ 0.21: ${fixedOrder.join(" → ")} · All exact O₂: ${broadOrder.join(" → ")}`;
  orderNote.append(orderLabel, orderText);
  host.append(orderNote);

  const comparison = document.createElement("div");
  comparison.className = "condition-sensitivity-grid";
  for (const slice of rankedSlices) {
    const card = document.createElement("article");
    card.className = "condition-sensitivity-card";
    const heading = document.createElement("div");
    heading.className = "condition-sensitivity-card-heading";
    const title = document.createElement("h4");
    title.textContent = slice.label;
    const total = document.createElement("span");
    total.textContent = `n = ${slice.rows.length}`;
    heading.append(title, total);
    const groups = document.createElement("p");
    groups.className = "condition-sensitivity-groups";
    groups.textContent = slice.groups.map((group) => `${group.fuel} n=${group.n}`).join(" · ");
    const list = document.createElement("ol");
    list.className = "condition-sensitivity-list";
    for (const [index, item] of slice.ranked.entries()) {
      const row = document.createElement("li");
      row.className = "condition-sensitivity-row";
      const position = document.createElement("span");
      position.className = "condition-sensitivity-position";
      position.textContent = String(index + 1).padStart(2, "0");
      const detail = document.createElement("div");
      detail.className = "condition-sensitivity-detail";
      const outcome = document.createElement("b");
      outcome.textContent = item.outcome;
      const direction = document.createElement("small");
      direction.textContent = item.higherShareFuel ? `Higher observed share: ${item.higherShareFuel}` : "Equal observed shares";
      const counts = document.createElement("p");
      counts.textContent = `${item.left.fuel} ${item.left.count}/${item.left.n} (${formatNumber(item.left.share * 100, 1)}%) · ${item.right.fuel} ${item.right.count}/${item.right.n} (${formatNumber(item.right.share * 100, 1)}%)`;
      detail.append(outcome, direction, counts);
      const gap = document.createElement("strong");
      gap.className = "condition-sensitivity-gap";
      gap.textContent = `${formatNumber(item.gapPercentagePoints, 1)} pp`;
      row.setAttribute("aria-label", `${item.outcome}: ${formatNumber(item.gapPercentagePoints, 1)} percentage-point absolute observed share gap. ${counts.textContent}.`);
      row.append(position, detail, gap);
      list.append(row);
    }
    card.append(heading, groups, list);
    comparison.append(card);
  }
  host.append(comparison);
}

function renderOverview() {
  $("#overview-record-count").textContent = String(records.length);
  $("#overview-fuel-count").textContent = String(fuels().length);
  $("#overview-outcome-count").textContent = String(outcomes().length);
  $("#overview-evidence-status").textContent = "Source-backed";
  $("#assistant-record-count").textContent = String(records.length);
  $("#assistant-source-version").textContent = manifest.sourceVersion || "NASA PSI-69";
}

function renderProvenance() {
  const setText = (selector, value, fallback = "Not available") => { $(selector).textContent = value || fallback; };
  setText("#source-investigation", manifest.title, "Flame Extinguishment Experiment (FLEX)");
  setText("#source-doi", manifest.doi);
  setText("#source-license", manifest.license);
  setText("#source-file", manifest.sourceFile);
  setText("#source-hash", manifest.sourceSha256);
  setText("#source-retrieved", manifest.retrievedAt);
  setText("#source-version-tag", manifest.sourceVersion);
  setText("#analysis-hash", `SHA-256 ${manifest.sourceSha256 || "unavailable"}`);
  const releaseLabel = window.FireLabSourceLabel?.formatNasaReleaseLabel(manifest.sourceVersion) || "NASA PSI-69";
  setText("#condition-source-note", `Source: ${releaseLabel} · SHA-256 ${manifest.sourceSha256 || "unavailable"} · source values preserved · no imputation`);
  setText("#license-badge", manifest.license || "NASA DATA");
  setText("#data-record-foot", `${manifest.recordCount ?? records.length} records · ${manifest.sourceVersion || "NASA PSI-69"}`);
  if (manifest.sourceUrl) {
    for (const selector of ["#source-link", "#assistant-source-link", "#data-source-link"]) $(selector).href = manifest.sourceUrl;
  }
  if (manifest.reportUrl) $("#report-link").href = manifest.reportUrl;
}

function renderDataset() {
  const count = records.length;
  const bundleStatus = count ? `${count} source records loaded` : "Dataset unavailable";
  $("#sidebar-bundle-state").textContent = count ? "Source bundle loaded" : "Source bundle unavailable";
  $("#sidebar-bundle-count").textContent = count ? `NASA PSI-69 · ${count} FLEX tests` : "Check the local data bundle";
  $("#sidebar-indicator").classList.toggle("is-loaded", count > 0);
  $("#header-data-state").textContent = bundleStatus;
  updateInvestigationContext(location.hash.slice(1) || "ask");
  $("#assistant-record-count").textContent = count ? String(count) : "—";
  if (!count) {
    $("#overview-evidence-status").textContent = "Bundle unavailable";
    $("#record-match").textContent = "No source records loaded";
    recordsBody.replaceChildren();
    const row = recordsBody.insertRow();
    const cell = addCell(row, "No source records loaded. Restore the documented NASA FLEX data bundle.");
    cell.colSpan = 7;
    qualityBody.replaceChildren();
    const qualityRow = qualityBody.insertRow();
    const qualityCell = addCell(qualityRow, "No quality report loaded.");
    qualityCell.colSpan = 5;
    return;
  }
  addFilterOptions("#fuel-filter", fuels(), "All fuels");
  addFilterOptions("#outcome-filter", outcomes(), "All outcomes");
  renderRecords();
  renderQuality();
  renderOutcomeChart();
  renderFuelMix();
  renderBurnRateSummary();
  populateConditionChoices("#condition-oxygen", "oxygenMoleFraction", CONDITION_BASELINE.oxygenMoleFraction);
  populateConditionChoices("#condition-co", "coSourceMoleFraction", CONDITION_BASELINE.coSourceMoleFraction);
  populateConditionChoices("#condition-helium", "heliumMoleFraction", CONDITION_BASELINE.heliumMoleFraction);
  renderConditionEvidence();
  renderOverview();
  renderProvenance();
}

const TRACE_FIELD_META = {
  testNumber: { label: "FLEX Test #", sourceKey: "FLEX Test #" },
  identifier: { label: "FLEX Identifier", sourceKey: "FLEX Identifier" },
  fuel: { label: "Fuel", sourceKey: "Fuel" },
  ambientPressureMmHg: { label: "Pressure (mmHg)", sourceKey: "Ambient pressure; mmHg" },
  oxygenMoleFraction: { label: "O₂ mole fraction", sourceKey: "O initial ambient composition; mole fraction" },
  coSourceMoleFraction: { label: "Source CO field", sourceKey: "CO initial ambient composition; mole fraction" },
  heliumMoleFraction: { label: "He mole fraction", sourceKey: "He initial ambient composition; mole fraction" },
  testEnd: { label: "Test end", sourceKey: "Test end" },
  burningRateMm2PerSec: { label: "Burning rate (mm²/s)", sourceKey: "Burning rate; mm" },
  measurementQuality: { label: "Field-level quality report" },
};

function cleanStringList(value, limit = 30) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string").slice(0, limit).map((item) => item.slice(0, 2000)) : [];
}

function normalizeStoredAnswer(answer) {
  if (!answer || typeof answer !== "object") return null;
  const qualityRows = Array.isArray(answer.qualityRows) ? answer.qualityRows.slice(0, 30).map((row) => ({
    label: typeof row?.label === "string" ? row.label.slice(0, 120) : "Measurement",
    exact: Number(row?.exact) || 0,
    approximate: Number(row?.approximate) || 0,
    missing: Number(row?.missing) || 0,
    invalid: Number(row?.invalid) || 0,
  })) : [];
  const validScopes = ["all-records", "exact-burning-rate", "selected-records", "quality-summary", "cohort-evidence", "research-questions", "none"];
  const recordIds = Array.isArray(answer.recordIds)
    ? answer.recordIds.filter((value) => Number.isInteger(value) && value > 0).slice(0, 300)
    : [];
  const events = Array.isArray(answer.events) ? answer.events.slice(0, 12).map((event, index) => ({
    sequence: Number.isInteger(event?.sequence) ? event.sequence : index + 1,
    type: typeof event?.type === "string" ? event.type.slice(0, 80) : "event",
    status: typeof event?.status === "string" ? event.status.slice(0, 40) : "complete",
    summary: typeof event?.summary === "string" ? event.summary.slice(0, 300) : "",
    timestamp: typeof event?.timestamp === "string" ? event.timestamp.slice(0, 40) : "",
  })) : [];
  return {
    title: typeof answer.title === "string" ? answer.title.slice(0, 240) : "SIRA answer",
    text: typeof answer.text === "string" ? answer.text.slice(0, 5000) : "",
    bullets: cleanStringList(answer.bullets, 30),
    evidence: cleanStringList(answer.evidence, 30),
    trace: cleanStringList(answer.trace, 20),
    fields: cleanStringList(answer.fields, 20),
    sampleSize: Number.isFinite(Number(answer.sampleSize)) ? Math.max(0, Number(answer.sampleSize)) : 0,
    dataScope: validScopes.includes(answer.dataScope) ? answer.dataScope : "none",
    recordIds,
    status: answer.status === "abstained" ? "abstained" : "completed",
    intent: typeof answer.intent === "string" ? answer.intent.slice(0, 80) : "",
    events,
    source: typeof answer.source === "string" ? answer.source.slice(0, 240) : (answer.status === "abstained" ? "" : "NASA PSI-69"),
    sourceFile: typeof answer.sourceFile === "string" ? answer.sourceFile.slice(0, 240) : "",
    sourceVersion: typeof answer.sourceVersion === "string" ? answer.sourceVersion.slice(0, 120) : "",
    sourceHash: typeof answer.sourceHash === "string" ? answer.sourceHash.slice(0, 128) : "",
    recordsHash: typeof answer.recordsHash === "string" ? answer.recordsHash.slice(0, 128) : "",
    qualityHash: typeof answer.qualityHash === "string" ? answer.qualityHash.slice(0, 128) : "",
    sourceUrl: typeof answer.sourceUrl === "string" ? answer.sourceUrl.slice(0, 500) : "",
    reportUrl: typeof answer.reportUrl === "string" ? answer.reportUrl.slice(0, 500) : "",
    doi: typeof answer.doi === "string" ? answer.doi.slice(0, 200) : "",
    license: typeof answer.license === "string" ? answer.license.slice(0, 80) : "",
    analysisId: typeof answer.analysisId === "string" ? answer.analysisId.slice(0, 120) : "",
    analysisVersion: Number.isInteger(answer.analysisVersion) ? answer.analysisVersion : 1,
    qualityRows,
    ...normalizeStructuredAnswerFields(answer),
  };
}
function readChatState() {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) return { conversations: [], activeConversationId: null };
    const parsed = JSON.parse(raw);
    const stored = Array.isArray(parsed?.conversations) ? parsed.conversations : [];
    const normalized = stored.slice(0, MAX_SAVED_CONVERSATIONS).map((item, index) => {
      const messages = Array.isArray(item?.messages) ? item.messages.slice(-120).flatMap((message) => {
        if (!message || !["user", "assistant"].includes(message.role)) return [];
        const text = typeof message.text === "string" ? message.text.slice(0, 5000) : "";
        if (message.role === "user") return text ? [{ role: "user", text }] : [];
        const answer = normalizeStoredAnswer(message.answer);
        return answer ? [{ role: "assistant", text: text || answer.title, answer }] : [];
      }) : [];
      return {
        id: typeof item?.id === "string" ? item.id.slice(0, 100) : `restored-${index}`,
        title: typeof item?.title === "string" ? item.title.slice(0, 400) : "Saved investigation",
        createdAt: typeof item?.createdAt === "string" ? item.createdAt : new Date().toISOString(),
        updatedAt: typeof item?.updatedAt === "string" ? item.updatedAt : new Date().toISOString(),
        investigationId: normalizeInvestigationId(item?.investigationId, "psi69-flex-v5"),
        messages,
      };
    }).filter((item) => item.messages.length);
    const activeId = typeof parsed?.activeConversationId === "string" && normalized.some((item) => item.id === parsed.activeConversationId)
      ? parsed.activeConversationId : normalized[0]?.id || null;
    return { conversations: normalized, activeConversationId: activeId };
  } catch {
    chatStorageAvailable = false;
    return { conversations: [], activeConversationId: null };
  }
}

function updateChatStorageStatus() {
  const status = $("#history-storage-status");
  const hint = $("#assistant-hint");
  if (status) status.textContent = chatStorageAvailable ? "Saved only in this browser" : "Browser storage unavailable · this session only";
  if (hint) hint.textContent = chatStorageAvailable ? "SIRA evidence service · Browser-only history" : "SIRA evidence service · History stays in this tab";
}

function saveChatState() {
  try {
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify({ version: 1, activeConversationId, conversations: conversations.slice(0, MAX_SAVED_CONVERSATIONS) }));
    chatStorageAvailable = true;
  } catch {
    chatStorageAvailable = false;
  }
  updateChatStorageStatus();
}

function conversationDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Saved";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function renderConversationList() {
  const list = $("#conversation-list");
  list.replaceChildren();
  const ordered = [...conversations].sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
  if (!ordered.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "Your investigations will appear here.";
    list.append(empty);
    return;
  }
  for (const item of ordered) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    button.dataset.conversationId = item.id;
    button.setAttribute("aria-current", String(item.id === activeConversationId));
    const title = document.createElement("span");
    title.className = "history-item-title";
    title.textContent = item.title || "Saved investigation";
    const meta = document.createElement("small");
    meta.textContent = `${item.messages.filter((message) => message.role === "user").length} questions · ${conversationDate(item.updatedAt)} · ${investigationDisplayName(item.investigationId)}`;
    button.append(title, meta);
    list.append(button);
  }
}

function appendUserMessage(question, target = $("#conversation")) {
  const wrapper = document.createElement("div");
  wrapper.className = "user-message";
  const message = document.createElement("span");
  message.textContent = question;
  wrapper.append(message);
  target.append(wrapper);
}

function makeTraceDataTable(answer) {
  const wrapper = document.createElement("div");
  wrapper.className = "trace-table-wrap";
  const table = document.createElement("table");
  table.className = "trace-data-table";
  const caption = document.createElement("caption");
  caption.textContent = answer.dataScope === "quality-summary" ? "Quality report values used" : `Source records used (${answer.sampleSize})`;
  table.append(caption);
  const thead = document.createElement("thead");
  const header = document.createElement("tr");
  const fields = answer.dataScope === "quality-summary" ? ["label", "exact", "approximate", "missing", "invalid"] : answer.fields;
  for (const field of fields) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = answer.dataScope === "quality-summary"
      ? ({ label: "Measurement", exact: "Exact", approximate: "Approx.", missing: "Missing", invalid: "Invalid" }[field] || field)
      : (TRACE_FIELD_META[field]?.label || field);
    header.append(cell);
  }
  thead.append(header);
  table.append(thead);
  const body = document.createElement("tbody");
  if (answer.dataScope === "quality-summary") {
    for (const rowData of answer.qualityRows || []) {
      const row = document.createElement("tr");
      for (const field of fields) {
        const cell = document.createElement("td");
        cell.textContent = String(rowData[field] ?? "—");
        row.append(cell);
      }
      body.append(row);
    }
  } else {
    if (!manifest || !records.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = Math.max(fields.length, 1);
      cell.textContent = "The NASA source bundle has not loaded in this tab yet; reload the page after it finishes loading to inspect these records.";
      row.append(cell);
      body.append(row);
      table.append(body);
      wrapper.append(table);
      return wrapper;
    }
    const sourceMatches = !answer.sourceHash || answer.sourceHash === manifest?.sourceSha256;
    const sourceRecords = answer.dataScope === "exact-burning-rate"
      ? records.filter((record) => record.quality?.burningRateMm2PerSec === "exact" && Number.isFinite(record.burningRateMm2PerSec))
      : answer.dataScope === "selected-records"
        ? records.filter((record) => answer.recordIds.includes(record.testNumber))
        : answer.dataScope === "all-records" ? records : [];
    if (!sourceMatches) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = Math.max(fields.length, 1);
      cell.textContent = "The loaded source bundle differs from the one used for this answer; record values are not rebound.";
      row.append(cell);
      body.append(row);
    } else {
      for (const record of sourceRecords) {
        const row = document.createElement("tr");
        for (const field of fields) {
          const cell = document.createElement("td");
          const meta = TRACE_FIELD_META[field];
          const rawValue = meta?.sourceKey ? record.sourceValues?.[meta.sourceKey] : record[field];
          cell.textContent = rawValue === undefined || rawValue === null || rawValue === "" ? "—" : String(rawValue);
          row.append(cell);
        }
        body.append(row);
      }
    }
  }
  table.append(body);
  wrapper.append(table);
  return wrapper;
}

function makeResearchTrace(answer) {
  const details = document.createElement("details");
  details.className = "research-trace";
  const summary = document.createElement("summary");
  const label = document.createElement("span");
  label.textContent = "SIRA activity and evidence trace";
  const count = document.createElement("small");
  count.textContent = answer.dataScope === "none" ? "No analysis run" : `${answer.sampleSize} records · SIRA evidence service`;
  summary.append(label, count);
  details.append(summary);
  const content = document.createElement("div");
  content.className = "trace-content";
  const steps = document.createElement("ol");
  steps.className = "trace-steps";
  for (const text of answer.trace || []) {
    const item = document.createElement("li");
    item.textContent = text;
    steps.append(item);
  }
  content.append(steps);
  if (answer.events?.length) {
    const eventHeading = document.createElement("h3");
    eventHeading.className = "trace-event-heading";
    eventHeading.textContent = "Backend activity";
    const eventList = document.createElement("ol");
    eventList.className = "trace-steps trace-events";
    for (const event of answer.events) {
      const item = document.createElement("li");
      const type = event.type.replaceAll(".", " · ");
      item.textContent = `${type} — ${event.summary}${event.status ? ` [${event.status}]` : ""}`;
      eventList.append(item);
    }
    content.append(eventHeading, eventList);
  }
  const facts = document.createElement("dl");
  facts.className = "trace-facts";
  // An abstention may carry an investigation context without having opened
  // that investigation source bundle. Do not infer PSI-69 from empty fields.
  // Older stored abstentions may already contain the old PSI-69 label; source
  // provenance fields (file/hash/release/citation) decide whether it was real.
  const sourceMetadataPresent = Boolean(
    answer.sourceFile || answer.sourceVersion || answer.sourceHash ||
    answer.recordsHash || answer.qualityHash || answer.sourceUrl ||
    answer.reportUrl || answer.doi || answer.license ||
    (Array.isArray(answer.citations) && answer.citations.length) ||
    (answer.artifactHashes && Object.keys(answer.artifactHashes).length)
  );
  const noSourceAccess = answer.status === "abstained" && !sourceMetadataPresent;
  const factRows = [
    ["Source", noSourceAccess ? "Not accessed" : (answer.source || (sourceMetadataPresent ? "Source identity unavailable" : "NASA PSI-69"))],
    ["Source file", answer.sourceFile || (noSourceAccess ? "Not accessed" : "Unavailable")],
    ["Release", answer.sourceVersion || (noSourceAccess ? "Not accessed" : "—")],
    ["Fields read", (answer.fields || []).map((field) => TRACE_FIELD_META[field]?.label || field).join(" · ") || "No data fields"],
    ["Source CSV SHA-256", answer.sourceHash || (noSourceAccess ? "Not accessed" : "Unavailable")],
    ["Records bundle SHA-256", answer.recordsHash || (noSourceAccess ? "Not accessed" : "Unavailable")],
    ["Quality bundle SHA-256", answer.qualityHash || (noSourceAccess ? "Not accessed" : "Unavailable")],
    ["Analysis", answer.analysisId ? `${answer.analysisId} v${answer.analysisVersion}` : "No registered calculation"],
    ["License", answer.license || (noSourceAccess ? "Not accessed" : "Not stated in manifest")],
  ];
  for (const [term, value] of factRows) {
    const wrapper = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    wrapper.append(dt, dd);
    facts.append(wrapper);
  }
  content.append(facts);
  const references = document.createElement("div");
  references.className = "trace-reference-links";
  const addReference = (label, rawUrl, allowedHost) => {
    try {
      const url = new URL(rawUrl);
      if (url.protocol !== "https:" || url.hostname !== allowedHost) return;
      const link = document.createElement("a");
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = label;
      references.append(link);
    } catch {
      return;
    }
  };
  addReference("NASA PSI-69 dataset", answer.sourceUrl, "psi.nasa.gov");
  addReference("NASA technical report", answer.reportUrl, "ntrs.nasa.gov");
  if (/^10\.\d{4,9}\/\S+$/i.test(answer.doi || "")) {
    const doiLink = document.createElement("a");
    doiLink.href = `https://doi.org/${encodeURIComponent(answer.doi).replaceAll("%2F", "/")}`;
    doiLink.target = "_blank";
    doiLink.rel = "noopener noreferrer";
    doiLink.textContent = `Dataset DOI: ${answer.doi}`;
    references.append(doiLink);
  }
  if (references.childElementCount) content.append(references);
  if (answer.dataScope === "none") {
    const note = document.createElement("p");
    note.className = "trace-no-analysis";
    note.textContent = "This request was abstained from by the SIRA evidence service. No source rows were filtered and no calculation was performed.";
    content.append(note);
  } else if (answer.investigationId === "psi25-bass-ii-v4" || !["all-records", "exact-burning-rate", "selected-records", "quality-summary"].includes(answer.dataScope)) {
    const note = document.createElement("p");
    note.className = "trace-no-analysis";
    note.textContent = answer.investigationId === "psi25-bass-ii-v4"
      ? "BASS-II values are not rebound to the PSI-69 FLEX table. Use the verified canonical record keys and claim-level references above, or open the BASS-II Explorer."
      : "This evidence scope does not expose a PSI-69 source-row table. Consult the structured references above.";
    content.append(note);
  } else {
    const dataHost = document.createElement("div");
    dataHost.className = "trace-data-host";
    dataHost.dataset.loaded = "false";
    dataHost.textContent = "Open this section to load the exact data used.";
    content.append(dataHost);
    details.addEventListener("toggle", () => {
      if (!details.open || dataHost.dataset.loaded === "true") return;
      dataHost.replaceChildren(makeTraceDataTable(answer));
      dataHost.dataset.loaded = "true";
    });
  }
  details.append(content);
  return details;
}

function appendAssistantAnswer(answer, target = $("#conversation")) {
  const article = document.createElement("article");
  article.className = "assistant-message answer-message";
  const avatar = document.createElement("div");
  avatar.className = "assistant-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = "S";
  const content = document.createElement("div");
  content.className = "message-content";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  const name = document.createElement("strong");
  name.textContent = "SIRA";
  const mode = document.createElement("span");
  mode.textContent = answer.status === "abstained" ? "EVIDENCE ABSTENTION" : "SIRA SERVER · EVIDENCE MODE";
  meta.append(name, mode);
  const heading = document.createElement("h2");
  heading.className = "answer-heading";
  heading.textContent = answer.title;
  const paragraph = document.createElement("p");
  paragraph.textContent = answer.text;
  content.append(meta, heading, paragraph, makeStructuredAnswerDetails(answer));
  if (answer.bullets?.length) {
    const list = document.createElement("ul");
    list.className = "answer-list";
    for (const text of answer.bullets) {
      const item = document.createElement("li");
      item.textContent = text;
      list.append(item);
    }
    content.append(list);
  }
  if (answer.evidence?.length) {
    const tags = document.createElement("div");
    tags.className = "answer-evidence";
    for (const text of answer.evidence) {
      const tag = document.createElement("span");
      tag.textContent = text;
      tags.append(tag);
    }
    content.append(tags);
  }
  content.append(makeResearchTrace(answer));
  article.append(avatar, content);
  target.append(article);
  article.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function makeConversationId() {
  return globalThis.crypto?.randomUUID?.() || `chat-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function titleFromQuestion(question) {
  const normalized = question.replace(/\s+/g, " ").trim();
  return normalized.length > 54 ? `${normalized.slice(0, 51).trimEnd()}…` : normalized;
}

function renderActiveConversation() {
  const host = $("#conversation");
  host.replaceChildren();
  const active = conversations.find((item) => item.id === activeConversationId);
  const investigationSelector = $("#investigation-select");
  if (investigationSelector && active) investigationSelector.value = normalizeInvestigationId(active.investigationId, "psi69-flex-v5");
  syncInvestigationContext(currentWorkspacePage());
  $("#active-conversation-title").textContent = active?.title || "New investigation";
  if (!active) {
    if (welcomeMessageTemplate) {
      const welcome = welcomeMessageTemplate.cloneNode(true);
      welcome.removeAttribute("id");
      host.append(welcome);
    }
  } else {
    for (const message of active.messages) {
      if (message.role === "user") appendUserMessage(message.text, host);
      else appendAssistantAnswer(message.answer, host);
    }
  }
    renderConversationList();
    updateResearchSynthesisAvailability();
  }

  function startNewConversation() {
  const selector = $("#investigation-select");
  if (selector) selector.value = "auto";
  activeConversationId = null;
  saveChatState();
  renderActiveConversation();
  $("#question-input").focus();
}

function initializeChatHistory() {
  const stored = readChatState();
  conversations = stored.conversations;
  activeConversationId = stored.activeConversationId;
  updateChatStorageStatus();
  renderActiveConversation();
}

async function assistantToken() {
  if (assistantSessionToken) return assistantSessionToken;
  const response = await fetch("/api/session", { credentials: "same-origin", cache: "no-store" });
  if (!response.ok) throw new Error("session_unavailable");
  const payload = await response.json();
  if (typeof payload?.token !== "string" || payload.token.length < 20) throw new Error("invalid_session");
  assistantSessionToken = payload.token;
  return assistantSessionToken;
}

async function requestAssistantAnswer(question, conversationId, investigationId = "psi69-flex-v5") {
  const token = await assistantToken();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch("/api/assistant/ask", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-FireLab-Session": token,
      },
      body: JSON.stringify({ question, conversation_id: conversationId, investigation_id: normalizeInvestigationId(investigationId, "psi69-flex-v5") }),
    });
    if (!response.ok) throw new Error(`assistant_http_${response.status}`);
    const payload = await response.json();
    const answer = normalizeStoredAnswer(payload);
    if (!answer || !answer.title || !answer.text || !Array.isArray(answer.events) || !answer.events.length) {
      throw new Error("invalid_assistant_response");
    }
    return answer;
  } finally {
    clearTimeout(timeout);
  }
}

function assistantUnavailableAnswer() {
  return normalizeStoredAnswer({
    title: "The SIRA evidence service is unavailable.",
    text: "No verified answer was returned by the local FireLab evidence endpoint. Check the SIRA FireLab server and retry. This message is not a dataset finding.",
    bullets: ["No source rows were selected.", "No scientific calculation was run."],
    evidence: ["Service unavailable", "No analysis run"],
    trace: ["The browser could not obtain a verified response from /api/assistant/ask."],
    fields: [], sampleSize: 0, dataScope: "none", status: "abstained", events: [],
    // No verified response was returned, so this request did not access a dataset.
    // Do not attach the current page's FLEX manifest to a service error.
    source: "",
    sourceFile: "",
    sourceVersion: "",
    sourceHash: "",
  });
}

async function ask(question) {
  const cleaned = question.trim();
  if (!cleaned || assistantRequestInFlight) return;
  let active = conversations.find((item) => item.id === activeConversationId);
  if (!active) {
    const timestamp = new Date().toISOString();
    active = { id: makeConversationId(), title: titleFromQuestion(cleaned), createdAt: timestamp, updatedAt: timestamp,
      investigationId: normalizeInvestigationId($("#investigation-select")?.value, "auto"), messages: [] };
    conversations.unshift(active);
    activeConversationId = active.id;
  }
  const targetConversationId = active.id;
  active.messages.push({ role: "user", text: cleaned });
  clearResearchSynthesisResult();
  active.updatedAt = new Date().toISOString();
  active.messages = active.messages.slice(-120);
  assistantRequestInFlight = true;
  const submit = $("#ask-form button[type='submit']");
  const input = $("#question-input");
  if (submit) submit.disabled = true;
  const investigationSelector = $("#investigation-select");
  if (investigationSelector) investigationSelector.disabled = true;
  if (input) input.disabled = true;
  if (input) input.value = "";
  saveChatState();
  renderActiveConversation();

  let answer;
  try {
    answer = await requestAssistantAnswer(cleaned, targetConversationId, normalizeInvestigationId(active.investigationId, "psi69-flex-v5"));
  } catch {
    answer = assistantUnavailableAnswer();
  }
  const target = conversations.find((item) => item.id === targetConversationId);
  if (target) {
    const resolvedInvestigationId = normalizeInvestigationId(answer.investigationId, "");
    if (REGISTERED_INVESTIGATION_IDS.includes(resolvedInvestigationId)) target.investigationId = resolvedInvestigationId;
    target.messages.push({ role: "assistant", text: answer.title, answer });
    target.messages = target.messages.slice(-120);
    target.updatedAt = new Date().toISOString();
  }
  conversations = conversations
    .sort((left, right) => new Date(right.updatedAt) - new Date(left.updatedAt))
    .slice(0, MAX_SAVED_CONVERSATIONS);
  assistantRequestInFlight = false;
  if (submit) submit.disabled = false;
  const finalInvestigationSelector = $("#investigation-select");
  if (finalInvestigationSelector) {
    finalInvestigationSelector.disabled = false;
    const activeTarget = conversations.find((item) => item.id === targetConversationId);
    if (activeTarget && activeConversationId === targetConversationId) finalInvestigationSelector.value = normalizeInvestigationId(activeTarget.investigationId, "auto");
  }
  if (input) {
    input.disabled = false;
    input.focus();
  }
  saveChatState();
  if (activeConversationId === targetConversationId) renderActiveConversation();
  else renderConversationList();
}

/* FireLab Step 6B SI research-synthesis integration v1 */
function latestResearchSynthesisContext() {
  if (assistantRequestInFlight) return null;
  const active = conversations.find((item) => item.id === activeConversationId);
  if (!active || !Array.isArray(active.messages) || active.messages.length < 2) return null;

  // The latest message must be a completed assistant response immediately
  // preceded by its own user question. A pending question cannot reuse an
  // older answer from the same conversation.
  const lastIndex = active.messages.length - 1;
  const assistantMessage = active.messages[lastIndex];
  const userMessage = active.messages[lastIndex - 1];
  if (assistantMessage?.role !== "assistant" || userMessage?.role !== "user") return null;

  const answer = assistantMessage.answer;
  if (!answer || answer.status !== "completed") return null;
  const investigationId = normalizeInvestigationId(answer.investigationId, "");
  if (!REGISTERED_INVESTIGATION_IDS.includes(investigationId)) return null;

  const analysisId = typeof answer.analysisId === "string" ? answer.analysisId : "";
  const operation = SCIENTIFIC_PLAN_OPERATION_MAP[analysisId];
  // Research-question operations identify gaps; they are not measurement analyses.
  if (!operation || operation.investigationId !== investigationId ||
      analysisId.endsWith("research_questions")) return null;

  const ledger = answer.claimLedger;
  if (!ledger || ledger.ledgerStatus !== "verified_provenance" ||
      ledger.investigationId !== investigationId || ledger.operationId !== analysisId) return null;

  const question = typeof userMessage.text === "string" ? userMessage.text.trim() : "";
  const conversationId = typeof active.id === "string" ? active.id : "";
  if (question.length < 3 || question.length > 400 ||
      !/^[A-Za-z0-9._-]{1,100}$/.test(conversationId)) return null;

  return { conversationId, question, investigationId, analysisId };
}

function sameResearchSynthesisContext(left, right) {
  return Boolean(left && right &&
    left.conversationId === right.conversationId &&
    left.question === right.question &&
    left.investigationId === right.investigationId &&
    left.analysisId === right.analysisId);
}

function setResearchSynthesisStatus(message, state = "") {
  const node = $("#research-synthesis-status");
  if (!node) return;
  node.textContent = message;
  node.dataset.state = state;
}

function clearResearchSynthesisResult() {
  researchSynthesisResult = null;
  researchSynthesisResultContext = null;
  const host = $("#research-synthesis-results");
  if (host) host.replaceChildren();
}

function updateResearchSynthesisAvailability() {
  const button = $("#research-synthesis-submit");
  const contextNode = $("#research-synthesis-context");
  if (!button || !contextNode) return null;

  const context = latestResearchSynthesisContext();
  if (researchSynthesisResultContext &&
      !sameResearchSynthesisContext(researchSynthesisResultContext, context)) {
    clearResearchSynthesisResult();
  }

  if (researchSynthesisRequestInFlight) {
    button.disabled = true;
    contextNode.textContent = context
      ? `Selected source: ${investigationDisplayName(context.investigationId)} · ${context.analysisId}`
      : "Synthesis request is running for the previously selected conversation.";
    setResearchSynthesisStatus("Research synthesis request in progress…", "loading");
    return context;
  }

  if (!context) {
    button.disabled = true;
    const active = conversations.find((item) => item.id === activeConversationId);
    const last = active?.messages?.[active.messages.length - 1];
    contextNode.textContent = "No eligible completed answer is selected.";
    if (assistantRequestInFlight || last?.role === "user") {
      setResearchSynthesisStatus("Waiting for the latest Ask SIRA answer to complete.", "loading");
    } else {
      setResearchSynthesisStatus(
        "Ask SIRA first. Synthesis requires a completed answer with a verified Claim Ledger and an explicit registered investigation.",
        ""
      );
    }
    return null;
  }

  contextNode.textContent = `Latest verified answer: ${investigationDisplayName(context.investigationId)} · ${context.analysisId}`;
  button.disabled = false;
  if (sameResearchSynthesisContext(researchSynthesisResultContext, context)) {
    const verification = researchSynthesisResult?.scientific_verification;
    const literature = researchSynthesisResult?.literature;
    const count = Number.isSafeInteger(literature?.source_count) ? literature.source_count : 0;
    setResearchSynthesisStatus(
      `Synthesis packet received · verification: ${verification?.status || "reported"} · literature records: ${count}.`,
      "success"
    );
  } else {
    setResearchSynthesisStatus("Ready. The latest verified Ask SIRA result will be recomputed by the server.", "ready");
  }
  return context;
}

function renderResearchSynthesisReceipt(packet, context) {
  const host = $("#research-synthesis-results");
  if (!host) return;
  host.replaceChildren();

  const safeText = (value, maximum = 1600) => {
    if (typeof value === "string") return value.slice(0, maximum);
    if (value === null || value === undefined) return "Not reported";
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    try {
      return JSON.stringify(value).slice(0, maximum);
    } catch {
      return "Not available";
    }
  };
  const appendText = (parent, tag, className, value, maximum = 1600) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = safeText(value, maximum);
    parent.append(node);
    return node;
  };
  const appendSection = (title, className) => {
    const section = document.createElement("section");
    section.className = `research-synthesis-section ${className}`;
    appendText(section, "h3", "research-synthesis-section-title", title, 180);
    host.append(section);
    return section;
  };
  const appendDefinitionList = (parent, rows) => {
    const list = document.createElement("dl");
    list.className = "research-synthesis-facts";
    for (const [label, value] of rows) {
      const item = document.createElement("div");
      appendText(item, "dt", "", label, 100);
      appendText(item, "dd", "", value, 1800);
      list.append(item);
    }
    parent.append(list);
    return list;
  };
  const appendStringList = (parent, values, className, maximumItems = 24) => {
    if (!Array.isArray(values) || !values.length) {
      appendText(parent, "p", "research-synthesis-muted", "None reported.", 120);
      return;
    }
    const list = document.createElement("ul");
    list.className = className;
    for (const value of values.slice(0, maximumItems)) {
      if (typeof value !== "string" || !value.trim()) continue;
      appendText(list, "li", "", value, 1200);
    }
    parent.append(list);
  };
  const safeHttpsUrl = (value) => {
    if (typeof value !== "string" || value.length > 2048) return null;
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== "https:" || !parsed.hostname || parsed.username || parsed.password) return null;
      return parsed.href;
    } catch {
      return null;
    }
  };
  const appendExternalLink = (parent, label, value) => {
    const href = safeHttpsUrl(value);
    if (!href) return false;
    const link = document.createElement("a");
    link.className = "research-synthesis-link";
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = label;
    parent.append(link);
    return true;
  };

  const dataset = packet?.dataset_context || {};
  const verification = packet?.scientific_verification || {};
  const literature = packet?.literature || {};
  const synthesis = packet?.synthesis || {};
  const mission = packet?.mission_interpretation || {};
  const boundary = packet?.verification_boundary || {};
  const packetStatus = safeText(packet?.status, 80);

  const overview = appendSection("Synthesis packet", "research-synthesis-overview");
  appendDefinitionList(overview, [
    ["Investigation", investigationDisplayName(context.investigationId)],
    ["Source release", dataset.source_release || "Not reported"],
    ["Registered operation", dataset.operation_id || context.analysisId],
    ["Metric", dataset.metric || "Not metric-specific"],
    ["Data scope", dataset.data_scope || "Not reported"],
    ["Sample size", dataset.sample_size],
    ["Claim Ledger", dataset.claim_ledger_status],
    ["Packet status", packetStatus],
  ]);

  const verificationSection = appendSection("Independent scientific verification", "research-synthesis-verification");
  verificationSection.dataset.state = safeText(verification.status, 40);
  appendDefinitionList(verificationSection, [
    ["Status", verification.status],
    ["Checks", verification.check_count],
    ["Passed checks", verification.passed_check_count],
    ["Failed checks", verification.failed_check_count],
    ["Unverifiable checks", verification.unverifiable_check_count],
    ["Claim results checked", verification.claim_result_count],
  ]);

  const claimsSection = appendSection("Verified dataset claims", "research-synthesis-claims");
  const claims = Array.isArray(packet?.dataset_claims) ? packet.dataset_claims.slice(0, 30) : [];
  appendText(claimsSection, "p", "research-synthesis-muted", `${claims.length} claim(s) in this packet.`, 120);
  if (!claims.length) {
    appendText(claimsSection, "p", "research-synthesis-muted", "No dataset claims were supplied.", 160);
  }
  for (const claim of claims) {
    if (!claim || typeof claim !== "object" || Array.isArray(claim)) continue;
    const card = document.createElement("article");
    card.className = "research-synthesis-claim";
    appendText(card, "h4", "research-synthesis-claim-title", claim.claim_id || "Dataset claim", 180);
    appendText(card, "p", "research-synthesis-claim-statement", claim.statement || "No claim statement supplied.", 1200);
    appendDefinitionList(card, [
      ["Claim type", claim.claim_type],
      ["Metric", claim.metric || "Not metric-specific"],
      ["Unit", claim.unit],
      ["Result", claim.result],
      ["Cohort", claim.cohort],
      ["Interpretation status", claim.interpretation_status],
      ["Record lineage", claim.record_lineage],
      ["Quality dimensions", claim.quality_dimensions],
      ["Evidence references", claim.evidence_references],
    ]);
    const limitations = document.createElement("div");
    limitations.className = "research-synthesis-claim-limitations";
    appendText(limitations, "h5", "", "Claim limitations", 100);
    appendStringList(limitations, claim.limitations, "research-synthesis-list", 24);
    card.append(limitations);
    claimsSection.append(card);
  }

  const literatureSection = appendSection("Scholarly literature discovery", "research-synthesis-literature");
  appendDefinitionList(literatureSection, [
    ["Query", literature.query],
    ["Retrieval state", literature.state],
    ["Retrieved at", literature.retrieved_at],
    ["Provider(s)", literature.providers],
    ["Partial result", literature.partial],
    ["Source count", literature.source_count],
    ["Evidence level", literature.evidence_level],
  ]);
  const sources = Array.isArray(literature.sources) ? literature.sources.slice(0, 3) : [];
  if (!sources.length) {
    appendText(literatureSection, "p", "research-synthesis-muted", "No scholarly records were retrieved. This is not evidence that no relevant literature exists.", 300);
  }
  for (const source of sources) {
    if (!source || typeof source !== "object" || Array.isArray(source)) continue;
    const card = document.createElement("article");
    card.className = "research-synthesis-paper";
    appendText(card, "h4", "research-synthesis-paper-title", source.title || "Untitled scholarly record", 500);
    appendDefinitionList(card, [
      ["Authors", source.authors],
      ["Year", source.year],
      ["DOI", source.doi],
      ["Provider", source.provider],
      ["Provider attribution", source.providers],
      ["Published", source.published_date],
      ["Retrieved", source.retrieved_at],
      ["Matched terms", source.matched_terms],
      ["Interpretation status", source.interpretation_status],
      ["Claim support", source.claim_support_status || "not_assessed"],
    ]);
    const doi = typeof source.doi === "string" ? source.doi.trim() : "";
    if (/^10\.\d{4,9}\/\S+$/i.test(doi)) {
      const doiUrl = `https://doi.org/${encodeURIComponent(doi).replace(/%2F/gi, "/")}`;
      appendExternalLink(card, `Open DOI: ${doi}`, doiUrl);
    } else if (!appendExternalLink(card, "Open scholarly record", source.url)) {
      appendText(card, "p", "research-synthesis-muted", "No validated HTTPS record link.", 120);
    }
    appendExternalLink(card, "Open-access PDF", source.open_access_pdf_url);
    if (typeof source.abstract === "string" && source.abstract) {
      appendText(card, "p", "research-synthesis-paper-abstract", source.abstract, 4000);
      if (source.abstract_truncated === true) {
        appendText(card, "p", "research-synthesis-muted", "Abstract truncated by the source adapter.", 120);
      }
    } else {
      appendText(card, "p", "research-synthesis-muted", "No abstract was supplied.", 100);
    }
    literatureSection.append(card);
  }
  appendText(literatureSection, "p", "research-synthesis-boundary-inline",
    "Scholarly metadata and optional abstracts are discovery references only. Their support for individual NASA claims has not been assessed.", 500);

  const assemblySection = appendSection("Deterministic synthesis and evidence separation", "research-synthesis-assembly");
  appendDefinitionList(assemblySection, [
    ["Method", synthesis.method],
    ["Generated with model", synthesis.generated_with_model],
    ["Model synthesis status", synthesis.model_synthesis_status],
    ["Cross-source support", synthesis.cross_source_support_status],
    ["Claim-to-literature links", synthesis.claim_to_literature_links],
    ["Literature verifies NASA measurements", synthesis.literature_verifies_nasa_measurements],
    ["Cross-investigation pooling", synthesis.cross_investigation_pooling_performed],
    ["Causal inference", synthesis.causal_inference_performed],
  ]);

  const missionSection = appendSection("Mission research interpretation", "research-synthesis-mission");
  appendDefinitionList(missionSection, [
    ["Status", mission.status],
    ["Method", mission.method],
    ["Generated with model", mission.generated_with_model],
    ["Mission transferability", mission.mission_transferability],
    ["Operational safety conclusion", mission.operational_safety_conclusion],
    ["Basis claim IDs", mission.basis_claim_ids],
  ]);
  appendText(missionSection, "p", "research-synthesis-mission-statement", mission.statement || "No mission interpretation was supplied.", 1800);
  appendText(missionSection, "h4", "research-synthesis-subtitle", "Interpretation limitations", 100);
  appendStringList(missionSection, mission.limitations, "research-synthesis-list", 24);

  const boundarySection = appendSection("Verification boundaries", "research-synthesis-boundaries");
  appendDefinitionList(boundarySection, Object.entries(boundary).slice(0, 16));

  const limitationsSection = appendSection("Packet limitations", "research-synthesis-limitations");
  appendStringList(limitationsSection, packet.limitations, "research-synthesis-list", 30);

  appendText(host, "p", "research-synthesis-final-note",
    "This packet is a bounded research aid. It does not establish scientific truth, causal effects, mission transferability, or operational fire-safety guidance.", 500);
}
async function submitResearchSynthesis(event) {
  event.preventDefault();
  if (researchSynthesisRequestInFlight) return;
  const context = latestResearchSynthesisContext();
  if (!context) {
    updateResearchSynthesisAvailability();
    return;
  }

  const queryInput = $("#research-synthesis-query");
  const literatureQuery = typeof queryInput?.value === "string" ? queryInput.value.trim() : "";
  if (literatureQuery.length < 3 || literatureQuery.length > 200) {
    setResearchSynthesisStatus("Enter a literature query containing 3 to 200 characters.", "error");
    queryInput?.focus();
    return;
  }

  researchSynthesisRequestInFlight = true;
  updateResearchSynthesisAvailability();
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 45000);
  try {
    const token = await assistantToken();
    const response = await fetch("/api/research/synthesis", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-FireLab-Session": token,
      },
      // Never send a browser-supplied answer or Claim Ledger. The server
      // recomputes the registered analysis from this question and scope.
      body: JSON.stringify({
        question: context.question,
        conversation_id: context.conversationId,
        investigation_id: context.investigationId,
        literature_query: literatureQuery,
      }),
    });
    if (!response.ok) throw new Error(`research_synthesis_http_${response.status}`);
    const payload = await response.json();
    if (!payload || payload.schema !== "sira.firelab.research_synthesis_response.v1") {
      throw new Error("invalid_research_synthesis_envelope");
    }

    const serverAnswer = normalizeStoredAnswer(payload.answer);
    const packet = payload.research_synthesis;
    const ledger = serverAnswer?.claimLedger;
    const datasetContext = packet?.dataset_context;
    if (!serverAnswer || serverAnswer.status !== "completed" ||
        serverAnswer.investigationId !== context.investigationId ||
        serverAnswer.analysisId !== context.analysisId ||
        !ledger || ledger.ledgerStatus !== "verified_provenance" ||
        ledger.investigationId !== context.investigationId || ledger.operationId !== context.analysisId ||
        !packet || packet.schema !== "sira.firelab.research_synthesis.v1" ||
        !datasetContext || datasetContext.investigation_id !== context.investigationId ||
        datasetContext.operation_id !== context.analysisId ||
        !packet.scientific_verification || !packet.literature || !packet.synthesis ||
        packet.synthesis.generated_with_model !== false ||
        packet.synthesis.literature_verifies_nasa_measurements !== false ||
        packet.synthesis.cross_investigation_pooling_performed !== false ||
        packet.synthesis.causal_inference_performed !== false) {
      throw new Error("research_synthesis_response_contract_mismatch");
    }

    const currentContext = latestResearchSynthesisContext();
    if (sameResearchSynthesisContext(context, currentContext)) {
      researchSynthesisResult = packet;
      researchSynthesisResultContext = context;
      renderResearchSynthesisReceipt(packet, context);
    }
  } catch {
    const currentContext = latestResearchSynthesisContext();
    if (sameResearchSynthesisContext(context, currentContext)) {
      setResearchSynthesisStatus(
        "Research synthesis could not be completed or its response failed validation. Check the local FireLab service and retry.",
        "error"
      );
    }
  } finally {
    window.clearTimeout(timeout);
    researchSynthesisRequestInFlight = false;
    updateResearchSynthesisAvailability();
  }
}

const INVESTIGATION_CONTEXTS = {
  auto: {
    name: "Automatic routing",
    description: "PSI-69 FLEX · PSI-25 BASS-II",
    missionHref: "#ask",
    bundleState: () => "Automatic investigation routing",
    bundleCount: () => "2 approved NASA investigations",
    sourceHref: "#methods",
    sourceLabel: "Registered NASA sources",
    header: () => "2 approved investigations",
    footerLabel: "NASA PSI data",
  },
  psi69: {
    name: "NASA PSI-69",
    description: "FLEX · droplet combustion",
    missionHref: "#overview",
    bundleState: () => records.length ? "Source bundle loaded" : "Source bundle unavailable",
    bundleCount: () => records.length ? `NASA PSI-69 · ${records.length} FLEX tests` : "Check the local data bundle",
    sourceHref: "https://psi.nasa.gov/physci/repo/data/investigations/PSI-69",
    sourceLabel: "NASA PSI-69 source",
    header: () => records.length ? `${records.length} source records loaded` : "Dataset unavailable",
    footerLabel: "NASA PSI-69",
  },
  psi25: {
    name: "NASA PSI-25",
    description: "BASS-II · microgravity combustion",
    missionHref: "#psi25",
    bundleState: () => "BASS-II dataset selected",
    bundleCount: () => "NASA PSI-25 · Study version 4",
    sourceHref: "https://psi.nasa.gov/physci/repo/data/investigations/PSI-25",
    sourceLabel: "NASA PSI-25 source",
    header: () => "NASA PSI-25 · BASS-II",
    footerLabel: "NASA PSI-25",
  },
};

function currentWorkspacePage() {
  const page = location.hash.slice(1);
  return PAGE_LABELS[page] ? page : "ask";
}

function currentAskInvestigationId() {
  const active = conversations.find((item) => item.id === activeConversationId);
  if (active) return normalizeInvestigationId(active.investigationId, "psi69-flex-v5");
  return normalizeInvestigationId($("#investigation-select")?.value, "auto");
}

function workspaceInvestigationId(page) {
  // Dedicated data explorers always identify their own source independently
  // from the currently selected Ask SIRA conversation.
  if (page === "psi25") return "psi25-bass-ii-v4";
  if (page === "data") return "psi69-flex-v5";
  return currentAskInvestigationId();
}

function syncInvestigationContext(page = currentWorkspacePage()) {
  // Keep one source of truth: updateInvestigationContext refreshes both the
  // Ask evidence rail and the page-specific workspace context.
  updateInvestigationContext(page);
}

function updateInvestigationContext(page) {
  // Synchronize Ask SIRA evidence context and the page-specific workspace
  // context together, including callers from the legacy page router.
  updateAskEvidenceContext(currentAskInvestigationId());
  const investigationId = workspaceInvestigationId(page);
  const context = investigationId === "psi25-bass-ii-v4"
    ? INVESTIGATION_CONTEXTS.psi25
    : investigationId === "psi69-flex-v5"
      ? INVESTIGATION_CONTEXTS.psi69
      : INVESTIGATION_CONTEXTS.auto;
  const missionLink = $("#active-investigation-link");
  const missionName = $("#active-investigation-name");
  const missionDescription = $("#active-investigation-description");
  const sourceLink = $("#sidebar-source-link");
  const sourceLabel = $("#sidebar-source-label");
  const bundleState = $("#sidebar-bundle-state");
  const bundleCount = $("#sidebar-bundle-count");
  const headerState = $("#header-data-state");
  const footerLabel = $("#footer-investigation-label");
  if (missionLink) missionLink.href = context.missionHref;
  if (missionName) missionName.textContent = context.name;
  if (missionDescription) missionDescription.textContent = context.description;
  if (sourceLink) {
    sourceLink.href = context.sourceHref;
    sourceLink.target = investigationId === "psi25-bass-ii-v4" || investigationId === "psi69-flex-v5" ? "_blank" : "_self";
    sourceLink.rel = "noopener noreferrer";
  }
  if (sourceLabel) sourceLabel.textContent = context.sourceLabel;
  if (bundleState) bundleState.textContent = context.bundleState();
  if (bundleCount) bundleCount.textContent = context.bundleCount();
  if (headerState) headerState.textContent = context.header();
  if (footerLabel) footerLabel.textContent = context.footerLabel;
}

function setPage(page) {
  const target = PAGE_LABELS[page] ? page : "ask";
  for (const view of $$("[data-view]")) view.hidden = view.dataset.view !== target;
  for (const link of $$(".nav-link")) {
    if (link.dataset.page === target) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  $("#current-page-label").textContent = PAGE_LABELS[target];
  updateInvestigationContext(target);
  document.title = `${PAGE_LABELS[target]} · SIRA FireLab`;
  closeSidebar();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function closeSidebar() {
  $("#sidebar").classList.remove("is-open");
  $("#sidebar-backdrop").hidden = true;
  $("#menu-toggle").setAttribute("aria-expanded", "false");
  $("#menu-toggle").setAttribute("aria-label", "Open navigation");
}

async function loadDataset() {
  try {
    const [manifestResponse, recordsResponse, qualityResponse] = await Promise.all([
      fetch("data/manifest.json", { cache: "no-store" }),
      fetch("data/records.json", { cache: "no-store" }),
      fetch("data/quality.json", { cache: "no-store" }),
    ]);
    if (![manifestResponse, recordsResponse, qualityResponse].every((response) => response.ok)) throw new Error("dataset files unavailable");
    const [loadedManifest, recordData, qualityData] = await Promise.all([
      manifestResponse.json(), recordsResponse.json(), qualityResponse.json(),
    ]);
    if (!Array.isArray(recordData) || !recordData.length || !qualityData.measurementQuality) throw new Error("dataset schema unavailable");
    manifest = loadedManifest;
    records = recordData;
    quality = qualityData;
    renderDataset();
    renderActiveConversation();
  } catch {
    $("#sidebar-bundle-state").textContent = "Source bundle unavailable";
    $("#sidebar-bundle-count").textContent = "Check the local data bundle";
    $("#header-data-state").textContent = "Dataset unavailable";
    $("#record-match").textContent = "No source records loaded";
    recordsBody.replaceChildren();
    const row = recordsBody.insertRow();
    const cell = addCell(row, "No source records loaded. Restore the documented NASA FLEX data bundle.");
    cell.colSpan = 7;
    qualityBody.replaceChildren();
    const qualityRow = qualityBody.insertRow();
    const qualityCell = addCell(qualityRow, "No quality report loaded.");
    qualityCell.colSpan = 5;
    $("#overview-evidence-status").textContent = "Bundle unavailable";
  }
}

$("#fuel-filter").addEventListener("change", renderRecords);
$("#outcome-filter").addEventListener("change", renderRecords);
$("#condition-filter-form").addEventListener("submit", (event) => {
  event.preventDefault();
  renderConditionEvidence();
});
$("#condition-reset").addEventListener("click", () => {
  $("#condition-pressure-min").value = String(CONDITION_BASELINE.pressureMin);
  $("#condition-pressure-max").value = String(CONDITION_BASELINE.pressureMax);
  $("#condition-oxygen").value = String(CONDITION_BASELINE.oxygenMoleFraction);
  $("#condition-co").value = String(CONDITION_BASELINE.coSourceMoleFraction);
  $("#condition-helium").value = String(CONDITION_BASELINE.heliumMoleFraction);
  renderConditionEvidence();
});
$("#ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  ask($("#question-input").value);
});
$("#research-synthesis-form").addEventListener("submit", submitResearchSynthesis);
$("#new-chat-button").addEventListener("click", startNewConversation);
$("#conversation-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-conversation-id]");
  if (!button) return;
  activeConversationId = button.dataset.conversationId;
  saveChatState();
  renderActiveConversation();
});
$("#conversation").addEventListener("click", (event) => {
  const button = event.target.closest("[data-prompt]");
  if (button) ask(button.dataset.prompt);
});
for (const link of $$(".nav-link, .workspace-card, .mission-card, .inline-route, .primary-link, .below-panel-note a")) {
  link.addEventListener("click", () => {
    const page = link.getAttribute("href")?.slice(1);
    if (PAGE_LABELS[page]) setPage(page);
  });
}
window.addEventListener("hashchange", () => setPage(location.hash.slice(1)));
$("#menu-toggle").addEventListener("click", () => {
  const open = !$("#sidebar").classList.contains("is-open");
  $("#sidebar").classList.toggle("is-open", open);
  $("#sidebar-backdrop").hidden = !open;
  $("#menu-toggle").setAttribute("aria-expanded", String(open));
  $("#menu-toggle").setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
});
$("#sidebar-backdrop").addEventListener("click", closeSidebar);

const initialPage = PAGE_LABELS[location.hash.slice(1)] ? location.hash.slice(1) : "ask";
if (!location.hash || !PAGE_LABELS[location.hash.slice(1)]) history.replaceState(null, "", "#ask");
setPage(initialPage);
initializeChatHistory();
loadDataset();

// M4.2: investigation selection is conversation-scoped.
const fireLabInvestigationSelector = $("#investigation-select");
if (fireLabInvestigationSelector) fireLabInvestigationSelector.addEventListener("change", handleInvestigationSelectionChange);
updateAskEvidenceContext(fireLabInvestigationSelector?.value || "auto");
