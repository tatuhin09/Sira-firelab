(() => {
  "use strict";

  const DATA_ROOT = "data/derived/psi25_bass_ii_v4";
  const FILES = {
    records: `${DATA_ROOT}/canonical_records.json`,
    quality: `${DATA_ROOT}/quality_report.json`,
    manifest: `${DATA_ROOT}/canonical_manifest.json`,
  };
  const ANALYSIS_FILES = {
    payload: `${DATA_ROOT}/paired_analysis_v1/paired_measurement_analysis.json`,
    manifest: `${DATA_ROOT}/paired_analysis_v1/analysis_manifest.json`,
  };
  const SYNTHESIS_FILES = {
    payload: `${DATA_ROOT}/evidence_synthesis_v1/evidence_synthesis.json`,
    manifest: `${DATA_ROOT}/evidence_synthesis_v1/synthesis_manifest.json`,
  };
  const FINDINGS_FILES = {
    payload: `${DATA_ROOT}/findings_ranking_v1/findings_ranking.json`,
    manifest: `${DATA_ROOT}/findings_ranking_v1/findings_manifest.json`,
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const FIELD_LABELS = {
    air_display: "Air display",
    fan_display: "Fan display",
    initial_o2: "Initial O₂",
    final_o2: "Final O₂",
    initial_co2: "Initial CO₂",
    final_co2: "Final CO₂",
    initial_co: "Initial CO",
    final_co: "Final CO",
    radiometer_gain: "Radiometer gain",
    total_frames_shot: "Total frames shot",
  };
  const STATUS_LABELS = {
    numeric_exact: "Numeric exact",
    right_censored: "Right-censored",
    over_range_threshold_unspecified: "Over-range · threshold unspecified",
    negative_numeric_requires_review: "Negative numeric · review",
    numeric_scalar_steady_state_unverified: "Scalar · steady state unverified",
    single_numeric_token_uninterpreted: "Single token · uninterpreted",
    single_gain_setting: "Single gain setting",
    sequence_or_note: "Sequence / note",
    integer_frame_count: "Integer frame count",
    source_descriptor: "Source descriptor",
    source_none: "Source says none",
    blank: "Blank source cell",
  };
  const RESTRICTOR_LABELS = {
    0: "highest flow · lowest restriction",
    1: "intermediate code",
    2: "lowest flow · highest restriction",
  };

  let records = [];
  let quality = null;
  let manifest = null;
  const byRecordKey = new Map();

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function labelStatus(status) {
    return STATUS_LABELS[status] || String(status || "Unclassified").replaceAll("_", " ");
  }

  function statusClass(status) {
    if (status === "numeric_exact" || status === "integer_frame_count") return "is-exact";
    if (["right_censored", "over_range_threshold_unspecified", "negative_numeric_requires_review", "numeric_scalar_steady_state_unverified", "single_numeric_token_uninterpreted", "single_gain_setting", "sequence_or_note", "source_descriptor"].includes(status)) return "is-caution";
    return "is-missing";
  }

  function rawValue(measurement) {
    if (!measurement || typeof measurement !== "object") return "—";
    if (measurement.raw === "") return "(blank)";
    return measurement.raw === null || measurement.raw === undefined ? "—" : String(measurement.raw);
  }

  function restrictorLabel(value) {
    if (!value || typeof value !== "object") return "—";
    const code = value.code;
    if (code === 0 || code === 1 || code === 2) return `${code} · ${RESTRICTOR_LABELS[code]}`;
    return value.raw || "Unspecified";
  }

  function addTextCell(row, text, className = "") {
    const cell = node("td", className, text);
    row.append(cell);
    return cell;
  }

  function addFilterOptions(selector, values, firstLabel) {
    const select = $(selector);
    const first = node("option", "", firstLabel);
    first.value = "";
    select.replaceChildren(first);
    for (const value of values) {
      const option = node("option", "", value);
      option.value = value;
      select.append(option);
    }
  }

  function measurementCell(row, measurement) {
    const cell = node("td");
    const wrapper = node("span", `psi25-measurement-cell ${statusClass(measurement?.status)}`);
    wrapper.append(node("strong", "", rawValue(measurement)));
    wrapper.append(node("small", "", labelStatus(measurement?.status)));
    cell.title = [measurement?.status, measurement?.unit].filter(Boolean).join(" · ");
    cell.append(wrapper);
    row.append(cell);
    return cell;
  }

  function renderRecordTable() {
    const body = $("#psi25-records-body");
    if (!body) return;
    const pi = $("#psi25-filter-pi").value;
    const material = $("#psi25-filter-material").value;
    const restrictor = $("#psi25-filter-restrictor").value;
    const query = $("#psi25-filter-search").value.trim().toLocaleLowerCase();

    const filtered = records.filter((record) => {
      const identity = record.identity || {};
      const sample = record.sample || {};
      const recordMaterial = record.material || {};
      const flow = record.flow_restrictor || {};
      const searchText = [identity.pi, identity.test_id, identity.record_key, sample.id_raw, recordMaterial.raw].join(" ").toLocaleLowerCase();
      return (!pi || identity.pi === pi)
        && (!material || (recordMaterial.canonical_class || "Unclassified") === material)
        && (!restrictor || String(flow.code ?? "") === restrictor)
        && (!query || searchText.includes(query));
    });

    body.replaceChildren();
    if (!filtered.length) {
      const row = node("tr");
      const cell = addTextCell(row, "No BASS-II records match these filters.", "psi25-empty");
      cell.colSpan = 11;
      body.append(row);
    } else {
      for (const record of filtered) {
        const row = node("tr");
        const identity = record.identity || {};
        const sample = record.sample || {};
        const materialInfo = record.material || {};
        const measurements = record.measurements || {};
        addTextCell(row, identity.pi || "—");
        addTextCell(row, identity.test_id_raw || identity.test_id || "—");
        addTextCell(row, record.date?.iso || record.date?.raw || "—");
        const sampleCell = addTextCell(row, sample.id_raw || "—");
        if (sample.is_reused_exact_raw_id) {
          sampleCell.classList.add("flagged");
          sampleCell.title = `Exact, case-sensitive sample ID reused across ${sample.reuse_count_exact_raw_id} experiment records; records remain distinct.`;
        }
        const materialCell = addTextCell(row, materialInfo.raw || "—");
        materialCell.title = `Canonical class: ${materialInfo.canonical_class || "unclassified"}; mapping: ${materialInfo.mapping_status || "not stated"}`;
        addTextCell(row, restrictorLabel(record.flow_restrictor));
        measurementCell(row, measurements.initial_o2);
        measurementCell(row, measurements.final_o2);
        measurementCell(row, measurements.initial_co);
        measurementCell(row, measurements.final_co);
        const actionCell = node("td");
        const button = node("button", "", "Details");
        button.type = "button";
        button.dataset.recordKey = identity.record_key || "";
        button.setAttribute("aria-label", `Inspect source details for ${identity.test_id || "this record"}`);
        actionCell.append(button);
        row.append(actionCell);
        body.append(row);
      }
    }
    $("#psi25-record-match").textContent = `Showing ${filtered.length} of ${records.length} experiment records`;
  }

  function appendMetaItem(host, label, value) {
    const item = node("dl", "psi25-meta-item");
    item.append(node("dt", "", label), node("dd", "", value));
    host.append(item);
  }

  function appendMeasurementCard(host, key, measurement) {
    const card = node("article", "psi25-measurement-card");
    card.append(node("h3", "", FIELD_LABELS[key] || key.replaceAll("_", " ")));
    const dl = node("dl");
    const entries = [
      ["Raw source token", measurement.raw === "" ? '"" (empty string)' : rawValue(measurement), "psi25-raw"],
      ["Status", labelStatus(measurement.status), ""],
      ["Unit", measurement.unit || "Not specified", ""],
      ["Aggregation eligible", measurement.aggregation_eligible ? "Yes" : "No", ""],
    ];
    if (measurement.parsed_decimal !== null && measurement.parsed_decimal !== undefined) {
      entries.push(["Parser output", String(measurement.parsed_decimal) + (measurement.aggregation_eligible ? "" : " · not eligible for aggregation"), ""]);
    }
    if (measurement.parsed_integer !== null && measurement.parsed_integer !== undefined) {
      entries.push(["Parsed integer", String(measurement.parsed_integer) + (measurement.aggregation_eligible ? "" : " · not eligible for aggregation"), ""]);
    }
    if (measurement.candidate_decimal !== null && measurement.candidate_decimal !== undefined) {
      entries.push(["Uninterpreted candidate", String(measurement.candidate_decimal), ""]);
    }
    if (measurement.censoring) {
      const c = measurement.censoring;
      entries.push(["Censoring", `${c.operator || ""}${c.lower_bound ?? ""} ${measurement.unit || ""}`.trim(), ""]);
      if (c.bound_basis) entries.push(["Censoring basis", c.bound_basis, ""]);
    }
    if (measurement.interpretation_note) entries.push(["Interpretation note", measurement.interpretation_note, ""]);
    if (measurement.steady_state_evidence) entries.push(["Steady-state evidence", measurement.steady_state_evidence, ""]);
    for (const [label, value, className] of entries) {
      dl.append(node("dt", "", label));
      dl.append(node("dd", className, value));
    }
    card.append(dl);
    host.append(card);
  }

  function renderRecordDetails(record) {
    const panel = $("#psi25-record-detail");
    const host = $("#psi25-detail-content");
    const identity = record.identity || {};
    const sample = record.sample || {};
    const material = record.material || {};
    const meta = node("div", "psi25-detail-meta");
    appendMetaItem(meta, "Test ID", identity.test_id_raw || identity.test_id || "—");
    appendMetaItem(meta, "Principal Investigator", identity.pi_raw || identity.pi || "—");
    appendMetaItem(meta, "Experiment date", record.date?.raw || record.date?.iso || "—");
    appendMetaItem(meta, "GMT day-of-year", record.gmt_day_of_year?.raw || "—");
    appendMetaItem(meta, "Sample ID · case-sensitive", sample.id_raw || "—");
    appendMetaItem(meta, "Sample reuse", sample.is_reused_exact_raw_id ? `Reused · ${sample.reuse_count_exact_raw_id} records` : "Not repeated by exact raw ID");
    appendMetaItem(meta, "Material · source wording", material.raw || "—");
    appendMetaItem(meta, "Material class", `${material.canonical_class || "Unclassified"} · ${material.mapping_status || "mapping not stated"}`);
    appendMetaItem(meta, "Flow restrictor", restrictorLabel(record.flow_restrictor));
    const measurements = node("div", "psi25-measurement-grid");
    for (const [key, value] of Object.entries(record.measurements || {})) appendMeasurementCard(measurements, key, value || {});
    const provenance = node("details", "psi25-provenance-detail");
    provenance.append(node("summary", "", "View exact source row and matrix lineage"));
    provenance.append(node("pre", "", JSON.stringify(record.source_provenance || {}, null, 2)));
    host.replaceChildren(meta, node("p", "panel-description", "Raw values and parser status are shown separately. A parsed token is not automatically a scientifically eligible measurement."), measurements, provenance);
    $("#psi25-detail-title").textContent = `Experiment ${identity.test_id || "record"} · ${identity.pi || "Unknown PI"}`;
    panel.hidden = false;
  }

  function renderQuality() {
    const host = $("#psi25-quality-grid");
    host.replaceChildren();
    const statusMap = quality.measurement_status_counts || {};
    for (const [field, counts] of Object.entries(statusMap)) {
      const card = node("article", "psi25-quality-card");
      card.append(node("h3", "", FIELD_LABELS[field] || field.replaceAll("_", " ")));
      const total = Object.values(counts).reduce((sum, count) => sum + (Number.isFinite(count) ? count : 0), 0);
      card.append(node("p", "psi25-quality-count", `${total} source entries`));
      const chips = node("div", "psi25-status-chips");
      for (const [status, count] of Object.entries(counts)) {
        const chip = node("span", `psi25-status-chip ${statusClass(status)}`, `${labelStatus(status)} · ${count}`);
        chips.append(chip);
      }
      card.append(chips);
      host.append(card);
    }
    const censoring = quality.censoring_documentation || {};
    if (censoring.co_or_threshold_verified && censoring.or_threshold_used_ppm) {
      $("#psi25-censoring-note").textContent = `CO over-range notation: the BASS-II ReadMe verifies OR as >${censoring.or_threshold_used_ppm} ppm (paragraph ${((censoring.co_or_threshold_readme_paragraphs || []).join(", ")) || "not recorded"}). OR remains right-censored; it is never replaced with the threshold value. The raw word “over” has no inferred threshold.`;
    } else {
      $("#psi25-censoring-note").textContent = "Censoring thresholds are only displayed when supported by the retained source documentation.";
    }
  }

  function renderProvenance() {
    $("#psi25-study-version").textContent = String(manifest.study_version ?? quality.investigation_version ?? "Not stated");
    const derived = manifest.derived_files || {};
    const canonicalHash = derived.canonical_records?.sha256 || derived.canonical_records_sha256 || manifest.canonical_records_sha256 || "See complete manifest";
    const qualityHash = derived.quality_report?.sha256 || derived.quality_report_sha256 || manifest.quality_report_sha256 || "See complete manifest";
    $("#psi25-records-hash").textContent = String(canonicalHash);
    $("#psi25-quality-hash").textContent = String(qualityHash);
    const safeManifest = {
      dataset: manifest.dataset,
      study_version: manifest.study_version,
      record_count: manifest.record_count,
      source_manifest_sha256: manifest.source_manifest_sha256,
      source_files: manifest.source_files,
      derived_files: manifest.derived_files,
      builder: manifest.builder,
      deterministic_build: manifest.deterministic_build,
      original_sources_modified: manifest.original_sources_modified,
    };
    $("#psi25-manifest-json").textContent = JSON.stringify(safeManifest, null, 2);
  }

  function renderConstraints() {
    const host = $("#psi25-constraints");
    host.replaceChildren();
    for (const constraint of quality.scientific_use_constraints || []) host.append(node("li", "", constraint));
  }

  function renderSummary() {
    const piCount = new Set(records.map((record) => record.identity?.pi).filter(Boolean)).size;
    const sampleIds = new Set(records.map((record) => record.sample?.id_raw).filter((value) => value !== undefined && value !== null && value !== ""));
    const reuse = quality.sample_reuse || {};
    $("#psi25-record-count").textContent = String(records.length);
    $("#psi25-pi-count").textContent = String(piCount);
    $("#psi25-sample-count").textContent = String(reuse.distinct_exact_raw_ids ?? sampleIds.size);
    $("#psi25-reuse-count").textContent = String(reuse.reused_exact_raw_id_groups ?? "—");
    $("#psi25-schema-label").textContent = `${manifest.dataset || "NASA PSI-25 BASS-II"} · schema ${records[0]?.schema || "canonical"}`;
    $("#psi25-load-state").textContent = "Local canonical bundle loaded · read-only";
  }

  function initializeFilters() {
    addFilterOptions("#psi25-filter-pi", [...new Set(records.map((record) => record.identity?.pi).filter(Boolean))].sort(), "All investigators");
    addFilterOptions("#psi25-filter-material", [...new Set(records.map((record) => record.material?.canonical_class || "Unclassified"))].sort(), "All material classes");
    addFilterOptions("#psi25-filter-restrictor", [...new Set(records.map((record) => record.flow_restrictor?.code).filter((value) => value === 0 || value === 1 || value === 2))].sort((a, b) => a - b).map(String), "All restrictor codes");
  }

  function showLoadError() {
    $("#psi25-load-state").textContent = "BASS-II bundle unavailable";
    $("#psi25-record-match").textContent = "No canonical BASS-II records loaded";
    const body = $("#psi25-records-body");
    const row = node("tr");
    const cell = node("td", "psi25-empty", "The local PSI-25 canonical bundle could not be loaded or its record counts did not agree. Restore the derived build and reload this page.");
    cell.colSpan = 11;
    row.append(cell);
    body.replaceChildren(row);
    const error = node("p", "psi25-load-error", "BASS-II data unavailable. The PSI-69 workspace remains separate and is not affected by this bundle status.");
    $(".psi25-data-panel").append(error);
  }

  const ANALYSIS_METRIC_LABELS = {
    o2: "Oxygen concentration change",
    co2: "Carbon dioxide concentration change",
    co: "Carbon monoxide concentration change",
  };
  let pairedAnalysis = null;
  let pairedAnalysisHash = null;

  function analysisCell(row, value, className = "") {
    const cell = node("td", className, analysisFormat(value));
    row.append(cell);
    return cell;
  }

  function analysisCohortLabel(cohort) {
    const restrictor = cohort.flow_restrictor_code === null || cohort.flow_restrictor_code === undefined
      ? "Unspecified restrictor"
      : `Restrictor ${cohort.flow_restrictor_code}`;
    return `${cohort.pi || "Unknown PI"} · ${cohort.material_class || "Unclassified material"} · ${restrictor}`;
  }

  function analysisFormat(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "object") {
      if (value.raw !== undefined && value.raw !== null) return value.raw === "" ? "(blank)" : String(value.raw);
      if (value.parsed_decimal !== undefined && value.parsed_decimal !== null) return String(value.parsed_decimal);
      if (value.value !== undefined && value.value !== null) return String(value.value);
      return value.status ? labelStatus(value.status) : "—";
    }
    return String(value);
  }

  function analysisRestrictorLabel(value) {
    if (value === null || value === undefined || value === "") return "Unspecified";
    const labels = { "0": "0 · highest flow / lowest restriction", "1": "1 · intermediate code", "2": "2 · lowest flow / highest restriction" };
    return labels[String(value)] || String(value);
  }

  function setAnalysisOptions(selector, values, firstLabel) {
    const select = $(selector);
    const selected = select.value;
    const first = node("option", "", firstLabel);
    first.value = "";
    select.replaceChildren(first);
    for (const value of values) {
      const option = node("option", "", value);
      option.value = value;
      select.append(option);
    }
    if (values.includes(selected)) select.value = selected;
  }

  function selectedAnalysisCohorts(metric) {
    const pi = $("#psi25-analysis-pi").value;
    const material = $("#psi25-analysis-material").value;
    const restrictor = $("#psi25-analysis-restrictor").value;
    return metric.cohort_summaries.filter((item) => {
      const cohort = item.cohort || {};
      return (!pi || cohort.pi === pi)
        && (!material || cohort.material_class === material)
        && (!restrictor || String(cohort.flow_restrictor_code ?? "") === restrictor);
    });
  }

  function renderAnalysisSummary(metric, cohorts) {
    const eligiblePairs = cohorts.reduce((sum, item) => sum + Number(item.eligible_pairs || 0), 0);
    const excludedPairs = cohorts.reduce((sum, item) => sum + Number(item.excluded_pairs || 0), 0);
    const smallN = cohorts.filter((item) => item.summary_status === "small_n_descriptive_only").length;
    const values = [
      ["ELIGIBLE PAIRS", eligiblePairs, "Exact eligible pairs in filtered cohorts"],
      ["EXCLUDED PAIRS", excludedPairs, "Ineligible/unavailable pairs in filtered cohorts"],
      ["COHORTS SHOWN", cohorts.length, "After current cohort filters"],
      ["SMALL-N COHORTS", smallN, "Descriptive only; inspect sample reuse"],
    ];
    const host = $("#psi25-analysis-summary");
    host.replaceChildren();
    for (const [label, value, note] of values) {
      const card = node("article", "");
      card.append(node("span", "", label), node("strong", "", value), node("small", "", note));
      host.append(card);
    }
  }

  function renderAnalysisChart(metric, cohorts) {
    const host = $("#psi25-analysis-chart");
    host.replaceChildren();
    $("#psi25-analysis-chart-unit").textContent = metric.unit || "Unit not stated";
    if (!cohorts.length) {
      host.append(node("p", "psi25-analysis-empty", "No cohorts match the selected filters."));
      return;
    }
    const meanMagnitudes = cohorts.map((item) => Number(item.statistics?.mean)).filter(Number.isFinite).map(Math.abs);
    const maxMagnitude = Math.max(0, ...meanMagnitudes);
    for (const item of cohorts) {
      const stats = item.statistics || {};
      const meanNumber = Number(stats.mean);
      const magnitude = Number.isFinite(meanNumber) ? Math.abs(meanNumber) : 0;
      const percent = maxMagnitude > 0 ? Math.max(0, Math.min(100, magnitude / maxMagnitude * 100)) : 0;
      const row = node("div", "psi25-analysis-chart-row");
      const heading = node("div", "psi25-analysis-chart-heading");
      heading.append(node("span", "psi25-analysis-chart-label", analysisCohortLabel(item.cohort || {})));
      heading.append(node("strong", "psi25-analysis-chart-value", `${analysisFormat(stats.mean)} ${metric.unit || ""}`));
      const track = node("div", "psi25-analysis-bar-track");
      const barClass = !Number.isFinite(meanNumber) || meanNumber === 0 ? "is-zero" : meanNumber < 0 ? "is-negative" : "is-positive";
      const bar = node("span", `psi25-analysis-bar ${barClass}`);
      bar.style.width = `${percent}%`;
      bar.setAttribute("aria-hidden", "true");
      track.append(bar);
      row.append(heading, track);
      host.append(row);
    }
  }

  function renderAnalysisCohortTable(metric, cohorts) {
    const body = $("#psi25-analysis-cohorts");
    body.replaceChildren();
    if (!cohorts.length) {
      const row = node("tr");
      const cell = analysisCell(row, "No cohorts match the selected filters.", "psi25-analysis-empty");
      cell.colSpan = 8;
      body.append(row);
      return;
    }
    for (const item of cohorts) {
      const cohort = item.cohort || {};
      const stats = item.statistics || {};
      const row = node("tr");
      analysisCell(row, cohort.pi);
      analysisCell(row, cohort.material_class);
      analysisCell(row, analysisRestrictorLabel(cohort.flow_restrictor_code));
      analysisCell(row, `${item.eligible_pairs} / ${item.records_in_cohort}`);
      analysisCell(row, stats.mean, "psi25-analysis-number");
      analysisCell(row, stats.median, "psi25-analysis-number");
      analysisCell(row, `${analysisFormat(stats.minimum)} – ${analysisFormat(stats.maximum)}`, "psi25-analysis-number");
      const status = item.summary_status === "small_n_descriptive_only" ? "Small n · descriptive only" : "Descriptive · no inference";
      const statusCell = analysisCell(row, status, item.summary_status === "small_n_descriptive_only" ? "is-caution" : "");
      statusCell.title = item.sample_reuse_caveat || item.statistics_n_definition || "Eligible experiment records; not necessarily independent physical samples.";
      if (item.records_marked_with_reused_sample_id > 0) {
        statusCell.append(node("small", "psi25-analysis-reuse-flag", ` · ${item.records_marked_with_reused_sample_id} record(s) flagged with reused Sample ID`));
      }
      body.append(row);
    }
  }

  function currentAnalysisAuditRows(metric) {
    const pi = $("#psi25-analysis-pi").value;
    const material = $("#psi25-analysis-material").value;
    const restrictor = $("#psi25-analysis-restrictor").value;
    const query = $("#psi25-analysis-audit-search").value.trim().toLocaleLowerCase();
    return metric.record_level_audit.filter((item) => {
      if (pi && item.pi !== pi) return false;
      if (material && item.material_class !== material) return false;
      if (restrictor && String(item.flow_restrictor_code ?? "") !== restrictor) return false;
      if (query) {
        const haystack = `${item.test_id_raw || item.test_id || ""} ${item.sample_id_raw || ""}`.toLocaleLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
  }

  function renderAnalysisAudit(metric) {
    const body = $("#psi25-analysis-audit");
    body.replaceChildren();
    const rows = currentAnalysisAuditRows(metric);
    $("#psi25-analysis-audit-count").textContent = `Showing ${rows.length} of ${metric.record_level_audit.length} experiment records for this metric and filter.`;
    if (!rows.length) {
      const row = node("tr");
      const cell = analysisCell(row, "No experiment records match the audit filters.", "psi25-analysis-empty");
      cell.colSpan = 8;
      body.append(row);
      return;
    }
    for (const item of rows) {
      const row = node("tr");
      analysisCell(row, item.test_id_raw || item.test_id);
      const sample = analysisCell(row, item.sample_id_raw);
      if (item.sample_id_reused) {
        sample.classList.add("is-caution");
        sample.title = `Exact Sample ID appears in ${item.sample_id_reuse_count_exact_raw_id} experiment records; not an independent physical-sample count.`;
      }
      analysisCell(row, item.pi);
      analysisCell(row, item.material_raw || item.material_class);
      analysisCell(row, item.initial, "psi25-analysis-number");
      analysisCell(row, item.final, "psi25-analysis-number");
      analysisCell(row, item.delta_final_minus_initial, "psi25-analysis-number");
      const reason = item.pair_eligible ? "Eligible exact pair" : (item.exclusion_reasons || []).join("; ") || "Excluded; reason not stated";
      analysisCell(row, reason, item.pair_eligible ? "is-exact" : "is-caution");
      body.append(row);
    }
  }

  function renderAnalysisCaveats(metricKey) {
    const host = $("#psi25-analysis-caveats");
    host.replaceChildren();
    const reuse = pairedAnalysis.sample_reuse_summary || {};
    const reuseNote = node("p", "", `Sample reuse: ${reuse.distinct_nonblank_exact_raw_sample_ids ?? "—"} distinct exact Sample IDs; ${reuse.reused_exact_raw_id_groups ?? "—"} reused ID groups cover ${reuse.records_in_reused_exact_raw_id_groups ?? "some"} experiment records. Repeated IDs remain separate records but may be statistically dependent; cohort n is not independent physical-sample n.`);
    host.append(reuseNote);
    if (metricKey === "o2") {
      const caveat = pairedAnalysis.measurement_provenance_caveats?.o2 || {};
      host.append(node("p", "is-caution", `O₂ calibration limitation: ${caveat.source_note || "The source ReadMe reports an O₂ sensor calibration limitation."} ${caveat.interpretation_limit || "Differences remain subject to source-stated measurement uncertainty."} ${caveat.analysis_handling || "No independent recalibration was performed."}`));
    }
    host.append(node("p", "", "All displayed statistics are descriptive summaries of eligible experiment records. No inferential statistics, causal attribution, imputation, or pooled cross-cohort estimate is produced. CO censored/over-range values and negative CO review values remain excluded from exact paired analysis."));
  }

  function renderPairedAnalysis() {
    if (!pairedAnalysis) return;
    const metricKey = $("#psi25-analysis-metric").value;
    const metric = pairedAnalysis.metrics[metricKey];
    if (!metric) return;
    $("#psi25-analysis-title").textContent = `${ANALYSIS_METRIC_LABELS[metricKey]} by cohort`;
    const cohorts = selectedAnalysisCohorts(metric);
    renderAnalysisSummary(metric, cohorts);
    renderAnalysisChart(metric, cohorts);
    renderAnalysisCohortTable(metric, cohorts);
    renderAnalysisAudit(metric);
    renderAnalysisCaveats(metricKey);
  }

  function initializeAnalysisFilters() {
    const reference = pairedAnalysis.metrics.o2.cohort_summaries;
    setAnalysisOptions("#psi25-analysis-pi", [...new Set(reference.map((item) => item.cohort?.pi).filter(Boolean))].sort(), "All investigators");
    setAnalysisOptions("#psi25-analysis-material", [...new Set(reference.map((item) => item.cohort?.material_class).filter(Boolean))].sort(), "All material classes");
    setAnalysisOptions("#psi25-analysis-restrictor", [...new Set(reference.map((item) => item.cohort?.flow_restrictor_code).filter((value) => value !== null && value !== undefined).map(String))].sort((a, b) => Number(a) - Number(b)), "All codes");
  }

  function bytesToHex(buffer) {
    return [...new Uint8Array(buffer)].map((value) => value.toString(16).padStart(2, "0")).join("");
  }

  const FINDINGS_METRIC_LABELS = {
    o2: "Oxygen concentration change",
    co2: "Carbon dioxide concentration change",
    co: "Carbon monoxide concentration change",
  };
  let findingsBundle = null;

  function findingsDisplay(value) {
    if (value === null || value === undefined || value === "") return "—";
    const raw = String(value);
    const number = Number(raw);
    if (!Number.isFinite(number)) return raw;
    return number.toLocaleString(undefined, { maximumSignificantDigits: 7 });
  }

  function findingsGroupLabel(group) {
    const flow = group?.flow_restrictor_code;
    const flowLabel = flow === null || flow === undefined || flow === "" ? "Unspecified restrictor" : `Restrictor ${flow}`;
    return `${group?.pi || "Unknown PI"} · ${group?.material_class || "Unclassified material"} · ${flowLabel}`;
  }

  function findingsStatusLabel(status) {
    const labels = {
      descriptive_only: "Descriptive · no inference",
      small_n_descriptive_only: "Small n · descriptive only",
      no_eligible_pairs: "Not rankable · no eligible pairs",
      same_sign: "Mean and median same sign",
      opposite_sign: "Mean and median opposite signs",
      one_zero: "Mean or median is zero",
      both_zero: "Mean and median are zero",
      positive_mean_change: "Positive mean change",
      negative_mean_change: "Negative mean change",
      zero_mean_change: "Zero mean change",
    };
    return labels[status] || String(status || "Not stated").replaceAll("_", " ");
  }

  function findingsAddCell(row, value, className = "") {
    const cell = node("td", className, value);
    row.append(cell);
    return cell;
  }

  function findingsSetOptions(selector, values, label) {
    const select = $(selector);
    const current = select.value;
    const first = node("option", "", label);
    first.value = "";
    select.replaceChildren(first);
    for (const value of values) {
      const option = node("option", "", value);
      option.value = value;
      select.append(option);
    }
    if (values.includes(current)) select.value = current;
  }

  function findingsMatches(item) {
    const group = item.cohort || {};
    const pi = $("#psi25-findings-pi").value;
    const material = $("#psi25-findings-material").value;
    const restrictor = $("#psi25-findings-restrictor").value;
    return (!pi || group.pi === pi)
      && (!material || group.material_class === material)
      && (!restrictor || String(group.flow_restrictor_code ?? "") === restrictor);
  }

  function findingsSummaryCard(label, value, note, caution = false) {
    const card = node("article", caution ? "is-caution" : "");
    card.append(node("span", "", label), node("strong", "", value), node("small", "", note));
    return card;
  }

  function renderFindingsSummary(metric, ranked, notRanked) {
    const all = [...ranked, ...notRanked];
    const eligible = all.reduce((sum, item) => sum + Number(item.eligible_pairs || 0), 0);
    const excluded = all.reduce((sum, item) => sum + Number(item.excluded_pairs || 0), 0);
    const host = $("#psi25-findings-summary");
    host.replaceChildren(
      findingsSummaryCard("RANKABLE COHORTS", ranked.length, "Pre-ranked within this gas metric"),
      findingsSummaryCard("NOT RANKABLE", notRanked.length, "No eligible exact pairs", notRanked.length > 0),
      findingsSummaryCard("ELIGIBLE PAIRS", eligible, "Filtered eligible experiment records"),
      findingsSummaryCard("EXCLUDED PAIRS", excluded, "Filtered records not used in means", excluded > 0),
    );
  }

  function renderFindingsExtremes(ranked, unit) {
    const host = $("#psi25-findings-extremes");
    host.replaceChildren();
    if (!ranked.length) {
      host.append(node("p", "psi25-findings-empty", "No rankable cohorts match the current filters."));
      return;
    }
    const highest = ranked[0];
    const lowest = ranked[ranked.length - 1];
    const entries = [
      ["Highest signed mean in filtered view", highest],
      ["Lowest signed mean in filtered view", lowest],
    ];
    for (const [label, item] of entries) {
      const card = node("article", "psi25-findings-extreme-card");
      const stats = item.statistics || {};
      card.append(
        node("span", "psi25-findings-extreme-label", label),
        node("strong", "psi25-findings-extreme-value", `${findingsDisplay(stats.mean)} ${unit}`),
        node("p", "", findingsGroupLabel(item.cohort)),
        node("small", "", `Rank ${item.rank} · ${item.eligible_pairs} eligible experiment records · ${findingsStatusLabel(item.summary_status)}`),
      );
      host.append(card);
    }
  }

  function findingsOpenButton(kind, index, metricKey, label = "Inspect evidence") {
    const button = node("button", "psi25-findings-evidence-button", label);
    button.type = "button";
    button.dataset.findingsKind = kind;
    button.dataset.findingsIndex = String(index);
    button.dataset.findingsMetric = metricKey;
    return button;
  }

  function renderFindingsRanked(metricKey, metric, ranked) {
    const body = $("#psi25-findings-ranked");
    body.replaceChildren();
    if (!ranked.length) {
      const row = node("tr");
      const cell = findingsAddCell(row, "No rankable cohorts match the current filters.", "psi25-findings-empty");
      cell.colSpan = 12;
      body.append(row);
      return;
    }
    const sourceItems = metric.ranked_cohorts || [];
    for (const item of ranked) {
      const sourceIndex = sourceItems.indexOf(item);
      const stats = item.statistics || {};
      const group = item.cohort || {};
      const row = node("tr");
      const rankCell = findingsAddCell(row, item.rank === item.display_order ? `#${item.rank}` : `#${item.rank} tie`, "psi25-findings-rank");
      rankCell.title = `Original display order ${item.display_order}; rank is based on signed mean within this metric only.`;
      findingsAddCell(row, group.pi || "Unknown PI");
      findingsAddCell(row, group.material_class || "Unclassified");
      findingsAddCell(row, group.flow_restrictor_code ?? "Unspecified");
      findingsAddCell(row, `${item.eligible_pairs} / ${item.records_in_cohort}`);
      findingsAddCell(row, item.distinct_exact_sample_ids_in_cohort ?? "—");
      const reused = Number(item.records_marked_with_reused_sample_id || 0);
      findingsAddCell(row, reused, reused > 0 ? "is-caution" : "");
      findingsAddCell(row, findingsDisplay(stats.mean), "psi25-findings-number").title = String(stats.mean);
      findingsAddCell(row, findingsDisplay(stats.median), "psi25-findings-number").title = String(stats.median);
      const relation = findingsAddCell(row, `${findingsStatusLabel(item.mean_median_sign_relation)} · gap ${findingsDisplay(item.absolute_mean_median_gap)}`, item.mean_median_sign_relation === "opposite_sign" ? "is-caution" : "");
      relation.title = `Absolute mean–median gap: ${item.absolute_mean_median_gap}; this is a descriptive comparison, not an outlier test.`;
      findingsAddCell(row, findingsStatusLabel(item.summary_status), item.summary_status === "small_n_descriptive_only" ? "is-caution" : "");
      const action = node("td");
      action.append(findingsOpenButton("ranked", sourceIndex, metricKey));
      row.append(action);
      body.append(row);
    }
  }

  function renderFindingsNotRankable(metricKey, metric, notRanked) {
    const body = $("#psi25-findings-not-ranked");
    body.replaceChildren();
    if (!notRanked.length) {
      const row = node("tr");
      const cell = findingsAddCell(row, "No not-rankable cohorts in the current filter.", "psi25-findings-empty");
      cell.colSpan = 9;
      body.append(row);
      return;
    }
    const sourceItems = metric.not_rankable_cohorts || [];
    for (const item of notRanked) {
      const sourceIndex = sourceItems.indexOf(item);
      const group = item.cohort || {};
      const row = node("tr");
      findingsAddCell(row, group.pi || "Unknown PI");
      findingsAddCell(row, group.material_class || "Unclassified");
      findingsAddCell(row, group.flow_restrictor_code ?? "Unspecified");
      findingsAddCell(row, item.records_in_cohort);
      findingsAddCell(row, item.excluded_pairs, "is-caution");
      findingsAddCell(row, item.distinct_exact_sample_ids_in_cohort ?? "—");
      findingsAddCell(row, item.records_marked_with_reused_sample_id ?? 0);
      findingsAddCell(row, findingsStatusLabel(item.not_rankable_reason), "is-caution");
      const action = node("td");
      action.append(findingsOpenButton("not-ranked", sourceIndex, metricKey));
      row.append(action);
      body.append(row);
    }
  }

  function findingsMeta(host, label, value, caution = false) {
    const item = node("dl", "psi25-findings-meta-item");
    item.append(node("dt", "", label), node("dd", caution ? "is-caution" : "", value));
    host.append(item);
  }

  function findingsEvidenceRow(body, evidence, eligible) {
    const row = node("tr");
    findingsAddCell(row, evidence.test_id || "—");
    const sample = findingsAddCell(row, evidence.sample_id_raw || "—", evidence.sample_id_reused ? "is-caution" : "");
    if (evidence.sample_id_reused) sample.title = "Exact, case-sensitive Sample ID reused across multiple experiment records.";
    if (eligible) {
      findingsAddCell(row, findingsDisplay(evidence.delta_final_minus_initial), "psi25-findings-number").title = String(evidence.delta_final_minus_initial);
      findingsAddCell(row, evidence.sample_id_reused ? "Reused ID · potential dependence" : "No reuse flag");
    } else {
      const reason = Array.isArray(evidence.exclusion_reasons) ? evidence.exclusion_reasons.join("; ") : "Exclusion reason not stated";
      const reasonCell = findingsAddCell(row, reason, "is-caution");
      reasonCell.title = reason;
    }
    const action = node("td");
    const button = node("button", "psi25-findings-evidence-button", "Open source record");
    button.type = "button";
    button.dataset.findingsRecordKey = evidence.record_key || "";
    action.append(button);
    row.append(action);
    body.append(row);
  }

  function renderFindingsEvidence(metricKey, kind, index) {
    const metric = findingsBundle?.payload?.metrics?.[metricKey];
    if (!metric) return;
    const list = kind === "ranked" ? metric.ranked_cohorts : metric.not_rankable_cohorts;
    const item = Array.isArray(list) ? list[index] : null;
    if (!item) return;
    const panel = $("#psi25-findings-evidence");
    const summary = $("#psi25-findings-evidence-summary");
    summary.replaceChildren();
    const group = item.cohort || {};
    const stats = item.statistics || {};
    const title = kind === "ranked"
      ? `Rank ${item.rank} · ${findingsGroupLabel(group)}`
      : `Not rankable · ${findingsGroupLabel(group)}`;
    $("#psi25-findings-evidence-title").textContent = title;
    findingsMeta(summary, "Metric", FINDINGS_METRIC_LABELS[metricKey]);
    findingsMeta(summary, "Eligible experiment pairs", item.eligible_pairs);
    findingsMeta(summary, "Excluded experiment pairs", item.excluded_pairs);
    findingsMeta(summary, "Distinct exact Sample IDs", item.distinct_exact_sample_ids_in_cohort ?? "—");
    findingsMeta(summary, "Records flagged with reused ID", item.records_marked_with_reused_sample_id ?? 0, Number(item.records_marked_with_reused_sample_id || 0) > 0);
    if (kind === "ranked") {
      findingsMeta(summary, "Mean paired change", `${findingsDisplay(stats.mean)} ${metric.unit}`);
      findingsMeta(summary, "Median paired change", `${findingsDisplay(stats.median)} ${metric.unit}`);
      findingsMeta(summary, "Observed range", `${findingsDisplay(stats.minimum)} – ${findingsDisplay(stats.maximum)} ${metric.unit}`);
      findingsMeta(summary, "Mean–median relation", findingsStatusLabel(item.mean_median_sign_relation));
      findingsMeta(summary, "Absolute mean–median gap", findingsDisplay(item.absolute_mean_median_gap));
      findingsMeta(summary, "Summary status", findingsStatusLabel(item.summary_status), item.summary_status === "small_n_descriptive_only");
    } else {
      findingsMeta(summary, "Rank status", "Not ranked: no eligible exact pairs", true);
      findingsMeta(summary, "Reason", findingsStatusLabel(item.not_rankable_reason), true);
    }
    if (item.sample_reuse_caveat) {
      summary.append(node("p", "psi25-findings-evidence-caveat", item.sample_reuse_caveat));
    }

    const eligibleBody = $("#psi25-findings-eligible-evidence");
    eligibleBody.replaceChildren();
    const eligibleRows = item.eligible_record_evidence || [];
    if (!eligibleRows.length) {
      const row = node("tr");
      const cell = findingsAddCell(row, "No eligible supporting records.", "psi25-findings-empty");
      cell.colSpan = 5;
      eligibleBody.append(row);
    } else {
      for (const evidence of eligibleRows) findingsEvidenceRow(eligibleBody, evidence, true);
    }

    const excludedBody = $("#psi25-findings-excluded-evidence");
    excludedBody.replaceChildren();
    const excludedRows = item.excluded_record_evidence || [];
    if (!excludedRows.length) {
      const row = node("tr");
      const cell = findingsAddCell(row, "No excluded records in this cohort.", "psi25-findings-empty");
      cell.colSpan = 4;
      excludedBody.append(row);
    } else {
      for (const evidence of excludedRows) findingsEvidenceRow(excludedBody, evidence, false);
    }
    panel.hidden = false;
  }

  function renderFindingsCaveats(metricKey) {
    const host = $("#psi25-findings-caveats");
    host.replaceChildren();
    const reuse = findingsBundle.payload.sample_reuse_summary || {};
    host.append(node("p", "", `Sample reuse: ${reuse.distinct_nonblank_exact_raw_sample_ids ?? "—"} distinct exact Sample IDs; ${reuse.reused_exact_raw_id_groups ?? "—"} reused ID groups include ${reuse.records_in_reused_exact_raw_id_groups ?? "—"} experiment records. Repeated exact Sample IDs remain separate experiment records and may indicate dependent observations; cohort n is not independent physical-sample n.`));
    if (metricKey === "o2") {
      const caveat = findingsBundle.payload.measurement_provenance_caveats?.o2 || {};
      host.append(node("p", "is-caution", `O₂ calibration limitation: ${caveat.source_note || "The source ReadMe reports an O₂ sensor calibration limitation."} ${caveat.interpretation_limit || "Differences remain subject to the source-stated limitation."}`));
    }
    host.append(node("p", "", "Rankings are separate by gas and unit, and order precomputed signed cohort means only. Mean–median gaps are descriptive context, not outlier tests. No causal attribution, inferential statistics, independent physical-sample inference, or cross-metric ranking is supported."));
  }

  function renderFindings() {
    if (!findingsBundle) return;
    const metricKey = $("#psi25-findings-metric").value;
    const metric = findingsBundle.payload.metrics[metricKey];
    if (!metric) return;
    const ranked = (metric.ranked_cohorts || []).filter(findingsMatches);
    const notRanked = (metric.not_rankable_cohorts || []).filter(findingsMatches);
    $("#psi25-findings-unit").textContent = metric.unit;
    renderFindingsSummary(metric, ranked, notRanked);
    renderFindingsExtremes(ranked, metric.unit);
    renderFindingsRanked(metricKey, metric, ranked);
    renderFindingsNotRankable(metricKey, metric, notRanked);
    renderFindingsCaveats(metricKey);
    $("#psi25-findings-evidence").hidden = true;
  }

  function initializeFindingsFilters() {
    const groups = Object.values(findingsBundle.payload.metrics).flatMap((metric) => [
      ...(metric.ranked_cohorts || []), ...(metric.not_rankable_cohorts || []),
    ]);
    findingsSetOptions("#psi25-findings-pi", [...new Set(groups.map((item) => item.cohort?.pi).filter(Boolean))].sort(), "All investigators");
    findingsSetOptions("#psi25-findings-material", [...new Set(groups.map((item) => item.cohort?.material_class).filter(Boolean))].sort(), "All material classes");
    findingsSetOptions("#psi25-findings-restrictor", [...new Set(groups.map((item) => item.cohort?.flow_restrictor_code).filter((value) => value !== null && value !== undefined).map(String))].sort((a, b) => Number(a) - Number(b)), "All codes");
  }

  function validateFindingsPayload(payload, manifestData, expectedPairedHash) {
    if (payload.schema !== "sira.psi25.findings_ranking.v1" || manifestData.schema !== "sira.psi25.findings_manifest.v1") throw new Error("Findings artifact schema is not the expected version.");
    if (payload.record_count !== records.length || payload.record_count !== 129 || manifestData.record_count !== payload.record_count) throw new Error("Findings record count does not match the canonical BASS-II bundle.");
    if (manifestData.source_artifacts?.paired_measurement_analysis?.sha256 !== expectedPairedHash) throw new Error("Findings artifact does not reference the verified paired-analysis SHA-256.");
    if (manifestData.o2_calibration_caveat_included !== true || manifestData.independent_sample_inference !== false || manifestData.inferential_statistics_produced !== false || manifestData.causal_claims_produced !== false || manifestData.cross_metric_ranking !== false) throw new Error("Findings manifest scientific safeguards are incomplete.");
    if (payload.inferential_statistics_produced !== false || payload.causal_claims_produced !== false || payload.independent_sample_inference !== false || payload.cross_metric_ranking !== false || !payload.measurement_provenance_caveats?.o2) throw new Error("Findings payload scientific safeguards are incomplete.");
    if (!payload.metrics || !["o2", "co2", "co"].every((key) => payload.metrics[key])) throw new Error("Findings metric schema is incomplete.");
    for (const key of ["o2", "co2", "co"]) {
      const metric = payload.metrics[key];
      const paired = pairedAnalysis.metrics[key];
      const ranked = metric.ranked_cohorts;
      const notRanked = metric.not_rankable_cohorts;
      if (!Array.isArray(ranked) || !Array.isArray(notRanked) || metric.cohort_count !== ranked.length + notRanked.length) throw new Error(`Findings ${key.toUpperCase()} cohort arrays are malformed.`);
      if (metric.pair_counts?.records !== records.length || metric.pair_counts.eligible_pairs !== paired.pair_counts.eligible_pairs || metric.pair_counts.excluded_pairs !== paired.pair_counts.excluded_pairs) throw new Error(`Findings ${key.toUpperCase()} pair counts disagree with paired analysis.`);
      if (ranked.length !== metric.rankable_cohort_count || notRanked.length !== metric.not_rankable_cohort_count) throw new Error(`Findings ${key.toUpperCase()} rankable cohort counts disagree.`);
      const auditByKey = new Map(paired.record_level_audit.map((row) => [row.record_key, row]));
      const seenKeys = new Set();
      let eligibleTotal = 0;
      let excludedTotal = 0;
      let lastMean = Infinity;
      let lastRank = 0;
      let lastNumericMean = null;
      for (let index = 0; index < ranked.length; index += 1) {
        const item = ranked[index];
        const mean = Number(item.statistics?.mean);
        if (!Number.isFinite(mean) || item.statistics?.n !== item.eligible_pairs || item.eligible_pairs < 1 || item.display_order !== index + 1 || item.ranked_by !== "signed_mean_paired_change_within_metric_only") throw new Error(`Findings ${key.toUpperCase()} ranked cohort metadata is invalid.`);
        if (mean > lastMean) throw new Error(`Findings ${key.toUpperCase()} ranking order is not descending.`);
        const expectedRank = index === 0 ? 1 : (mean === lastNumericMean ? lastRank : index + 1);
        if (item.rank !== expectedRank) throw new Error(`Findings ${key.toUpperCase()} competition rank/tie metadata is invalid.`);
        lastMean = mean;
        lastNumericMean = mean;
        lastRank = expectedRank;
        const eligibleRows = item.eligible_record_evidence || [];
        const excludedRows = item.excluded_record_evidence || [];
        if (eligibleRows.length !== item.eligible_pairs || excludedRows.length !== item.excluded_pairs) throw new Error(`Findings ${key.toUpperCase()} cohort evidence count mismatch.`);
        eligibleTotal += eligibleRows.length;
        excludedTotal += excludedRows.length;
        for (const row of [...eligibleRows, ...excludedRows]) {
          if (!row.record_key || seenKeys.has(row.record_key) || !byRecordKey.has(row.record_key)) throw new Error(`Findings ${key.toUpperCase()} has duplicate or unknown source record evidence.`);
          seenKeys.add(row.record_key);
          const source = auditByKey.get(row.record_key);
          const expectedEligible = eligibleRows.includes(row);
          if (!source || source.pair_eligible !== expectedEligible) throw new Error(`Findings ${key.toUpperCase()} evidence eligibility disagrees with paired analysis.`);
          if (eligibleRows.includes(row) && String(source.delta_final_minus_initial) !== String(row.delta_final_minus_initial)) throw new Error(`Findings ${key.toUpperCase()} supporting delta disagrees with paired analysis.`);
        }
      }
      for (const item of notRanked) {
        if (item.eligible_pairs !== 0 || item.not_rankable_reason !== "no_eligible_pairs") throw new Error(`Findings ${key.toUpperCase()} has an incorrectly rankable empty cohort.`);
        const excludedRows = item.excluded_record_evidence || [];
        if (excludedRows.length !== item.excluded_pairs || item.records_in_cohort !== item.excluded_pairs) throw new Error(`Findings ${key.toUpperCase()} not-rankable evidence count mismatch.`);
        excludedTotal += excludedRows.length;
        for (const row of excludedRows) {
          if (!row.record_key || seenKeys.has(row.record_key) || !byRecordKey.has(row.record_key)) throw new Error(`Findings ${key.toUpperCase()} has duplicate or unknown not-rankable evidence.`);
          seenKeys.add(row.record_key);
          const source = auditByKey.get(row.record_key);
          if (!source || source.pair_eligible !== false) throw new Error(`Findings ${key.toUpperCase()} excluded evidence disagrees with paired analysis.`);
        }
      }
      if (eligibleTotal !== metric.pair_counts.eligible_pairs || excludedTotal !== metric.pair_counts.excluded_pairs || seenKeys.size !== records.length) throw new Error(`Findings ${key.toUpperCase()} does not account for all 129 unique source records.`);
    }
  }

  let synthesisBundle = null;

  function synthesisDisplay(value) {
    if (value === null || value === undefined || value === "") return "—";
    const raw = String(value);
    const number = Number(raw);
    if (!Number.isFinite(number)) return raw;
    return number.toLocaleString(undefined, { maximumSignificantDigits: 7 });
  }

  // Presentation-only formatting: preserve source artifacts and full-precision values.
  // Long decimal tokens in narrative copy are shortened to the same 7-significant-digit
  // display convention used by the metric cards; the verified JSON is never rewritten.
  function synthesisFormatNarrative(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/(^|[^\w.])(-?\d+\.\d{8,})(?![\w.])/g, (match, prefix, raw) => {
      const numeric = Number(raw);
      return `${prefix}${Number.isFinite(numeric) ? synthesisDisplay(numeric) : raw}`;
    });
  }

  function synthesisGroupLabel(group) {
    const flow = group?.flow_restrictor_code;
    const flowText = flow === null || flow === undefined || flow === "" ? "Unspecified restrictor" : `Restrictor ${flow}`;
    return `${group?.pi || "Unknown PI"} · ${group?.material_class || "Unclassified material"} · ${flowText}`;
  }

  function synthesisFlagLabel(flag) {
    const labels = {
      small_n_descriptive_only: "Small n · descriptive only",
      sample_id_reuse_possible_dependence: "Repeated Sample ID · possible dependence",
      material_class_unclassified: "Material class unclassified",
      o2_sensor_calibration_limitation: "O₂ calibration limitation",
      mean_median_opposite_sign: "Mean and median have opposite signs",
      mean_median_gap_nonzero: "Mean–median gap present",
      mixed_positive_and_negative_record_changes: "Mixed positive and negative records",
      observed_range_includes_zero: "Observed range includes zero",
      not_rankable_no_eligible_pairs: "Not rankable · no eligible pairs",
    };
    return labels[flag] || String(flag || "Unspecified flag").replaceAll("_", " ");
  }

  function synthesisSetOptions(selector, values, firstLabel) {
    const select = $(selector);
    const current = select.value;
    const first = node("option", "", firstLabel);
    first.value = "";
    select.replaceChildren(first);
    for (const value of values) {
      const option = node("option", "", value);
      option.value = value;
      select.append(option);
    }
    if (values.includes(current)) select.value = current;
  }

  function synthesisMatches(card) {
    const group = card.cohort || {};
    const pi = $("#psi25-synthesis-pi").value;
    const material = $("#psi25-synthesis-material").value;
    const restrictor = $("#psi25-synthesis-restrictor").value;
    const flag = $("#psi25-synthesis-flag").value;
    return (!pi || group.pi === pi)
      && (!material || group.material_class === material)
      && (!restrictor || String(group.flow_restrictor_code ?? "") === restrictor)
      && (!flag || (card.flags || []).includes(flag));
  }

  function synthesisSummaryCard(label, value, note, caution = false) {
    const card = node("article", caution ? "is-caution" : "");
    card.append(node("span", "", label), node("strong", "", value), node("small", "", note));
    return card;
  }

  function synthesisRenderSummary(cards, globalQuestionCount) {
    const notRankable = cards.filter((card) => card.interpretation_status === "not_rankable").length;
    const questions = cards.reduce((sum, card) => sum + (card.research_questions || []).length, globalQuestionCount);
    const records = cards.reduce((sum, card) => sum + Number(card.records_in_cohort || 0), 0);
    const host = $("#psi25-synthesis-summary");
    host.replaceChildren(
      synthesisSummaryCard("INSIGHT CARDS", cards.length, "Filtered metric cohort cards"),
      synthesisSummaryCard("NOT RANKABLE", notRankable, "No eligible exact pairs", notRankable > 0),
      synthesisSummaryCard("RESEARCH QUESTIONS", questions, "Filtered card questions plus global gaps"),
      synthesisSummaryCard("RECORD EVIDENCE", records, "Cohort records represented", records > 0),
    );
  }

  function synthesisAppendFlags(host, flags) {
    const wrap = node("div", "psi25-synthesis-flags");
    if (!flags?.length) wrap.append(node("span", "psi25-synthesis-flag is-neutral", "No additional cohort flag"));
    for (const flag of flags || []) {
      const caution = flag !== "observed_range_includes_zero";
      wrap.append(node("span", `psi25-synthesis-flag${caution ? " is-caution" : " is-neutral"}`, synthesisFlagLabel(flag)));
    }
    host.append(wrap);
  }

  function synthesisRenderQuestions(host, questions) {
    const list = node("ul", "psi25-synthesis-question-list");
    if (!questions?.length) {
      list.append(node("li", "psi25-synthesis-empty", "No additional rule-triggered research question for this cohort."));
    } else {
      for (const question of questions) {
        const item = node("li", "psi25-synthesis-question");
        const metadata = node("div", "psi25-synthesis-question-meta");
        metadata.append(node("span", "psi25-synthesis-question-id", question.question_id || "Question"));
        metadata.append(node("span", "psi25-synthesis-question-trigger", String(question.trigger || "evidence gap").replaceAll("_", " ")));
        item.append(metadata, node("p", "", question.question || "Question text unavailable."));
        list.append(item);
      }
    }
    host.append(list);
  }

  function synthesisEvidenceRow(body, evidence, eligible) {
    const row = node("tr");
    const test = node("td", "", evidence.test_id || "—");
    row.append(test);
    const sample = node("td", evidence.sample_id_reused ? "is-caution" : "", evidence.sample_id_raw || "—");
    if (evidence.sample_id_reused) sample.title = "Exact, case-sensitive Sample ID is reused across experiment records.";
    row.append(sample);
    if (eligible) {
      const delta = node("td", "psi25-synthesis-number", synthesisDisplay(evidence.delta_final_minus_initial));
      delta.title = String(evidence.delta_final_minus_initial ?? "");
      row.append(delta);
      row.append(node("td", "", evidence.sample_id_reused ? "Reused ID · potential dependence" : "No reuse flag"));
    } else {
      const reasons = Array.isArray(evidence.exclusion_reasons) ? evidence.exclusion_reasons.join("; ") : "Exclusion reason not stated";
      const reasonCell = node("td", "is-caution", reasons);
      reasonCell.title = reasons;
      row.append(reasonCell);
    }
    const action = node("td");
    const button = node("button", "psi25-synthesis-record-button", "Open source record");
    button.type = "button";
    button.dataset.synthesisRecordKey = evidence.record_key || "";
    action.append(button);
    row.append(action);
    body.append(row);
  }

  function synthesisRenderEvidence(card, host) {
    const details = node("details", "psi25-synthesis-evidence");
    const eligible = card.supporting_record_evidence || [];
    const excluded = card.excluded_record_evidence || [];
    details.append(node("summary", "", `Inspect source evidence · ${eligible.length} eligible · ${excluded.length} excluded`));

    const eligibleHeading = node("div", "psi25-synthesis-subheading");
    eligibleHeading.append(node("h4", "", "Supporting experiment records"), node("span", "", "Eligible exact pairs"));
    details.append(eligibleHeading);
    const eligibleWrap = node("div", "table-wrap psi25-synthesis-table-wrap");
    eligibleWrap.setAttribute("role", "region");
    eligibleWrap.setAttribute("aria-label", "Supporting synthesis experiment evidence");
    eligibleWrap.tabIndex = 0;
    const eligibleTable = node("table", "record-table psi25-synthesis-table");
    const eligibleHead = node("thead");
    const eligibleHeadRow = node("tr");
    for (const label of ["Test", "Sample ID", "Paired Δ", "Sample identity", "Source"]) eligibleHeadRow.append(node("th", "", label));
    eligibleHead.append(eligibleHeadRow);
    const eligibleBody = node("tbody");
    if (!eligible.length) {
      const row = node("tr");
      const cell = node("td", "psi25-synthesis-empty", "No eligible supporting records.");
      cell.colSpan = 5;
      row.append(cell);
      eligibleBody.append(row);
    } else {
      for (const item of eligible) synthesisEvidenceRow(eligibleBody, item, true);
    }
    eligibleTable.append(eligibleHead, eligibleBody);
    eligibleWrap.append(eligibleTable);
    details.append(eligibleWrap);

    const excludedHeading = node("div", "psi25-synthesis-subheading");
    excludedHeading.append(node("h4", "", "Excluded experiment records"), node("span", "", "Reasons preserved"));
    details.append(excludedHeading);
    const excludedWrap = node("div", "table-wrap psi25-synthesis-table-wrap");
    excludedWrap.setAttribute("role", "region");
    excludedWrap.setAttribute("aria-label", "Excluded synthesis experiment evidence");
    excludedWrap.tabIndex = 0;
    const excludedTable = node("table", "record-table psi25-synthesis-table");
    const excludedHead = node("thead");
    const excludedHeadRow = node("tr");
    for (const label of ["Test", "Sample ID", "Exclusion reason(s)", "Source"]) excludedHeadRow.append(node("th", "", label));
    excludedHead.append(excludedHeadRow);
    const excludedBody = node("tbody");
    if (!excluded.length) {
      const row = node("tr");
      const cell = node("td", "psi25-synthesis-empty", "No excluded records in this cohort.");
      cell.colSpan = 4;
      row.append(cell);
      excludedBody.append(row);
    } else {
      for (const item of excluded) synthesisEvidenceRow(excludedBody, item, false);
    }
    excludedTable.append(excludedHead, excludedBody);
    excludedWrap.append(excludedTable);
    details.append(excludedWrap);
    host.append(details);
  }

  function synthesisRenderCard(card) {
    const article = node("article", `psi25-synthesis-card${card.interpretation_status === "not_rankable" ? " is-not-rankable" : ""}`);
    const heading = node("div", "psi25-synthesis-card-heading");
    const title = node("div");
    title.append(node("p", "psi25-synthesis-eyebrow", `${card.insight_id || "Insight"} · ${card.metric?.toUpperCase?.() || $("#psi25-synthesis-metric").value.toUpperCase()}`));
    title.append(node("h3", "", card.cohort_label || synthesisGroupLabel(card.cohort || {})));
    heading.append(title);
    const metricCards = synthesisBundle.payload.metrics[card.metric]?.insight_cards || [];
    // The findings engine assigns a shared rank only when signed means are exactly equal.
    const tiedMean = card.interpretation_status !== "not_rankable"
      && metricCards.filter((candidate) => candidate.rank === card.rank).length > 1;
    const rankText = card.interpretation_status === "not_rankable"
      ? "NOT RANKABLE"
      : `RANK ${card.rank ?? "—"}${tiedMean ? " · TIED MEAN" : ""}`;
    heading.append(node("span", `psi25-synthesis-rank${card.interpretation_status === "not_rankable" ? " is-caution" : ""}`, rankText));
    article.append(heading);

    const statusLine = node("p", "psi25-synthesis-card-status", `${card.summary_status || card.interpretation_status || "Descriptive"} · ${card.eligible_pairs} eligible / ${card.records_in_cohort} experiment records · ${card.excluded_pairs} excluded`);
    article.append(statusLine);
    synthesisAppendFlags(article, card.flags);

    article.append(node("p", "psi25-synthesis-observation", synthesisFormatNarrative(card.observation || "No eligible exact initial/final pair is available; no mean or direction is assigned.")));
    if (card.distribution) article.append(node("p", "psi25-synthesis-distribution", synthesisFormatNarrative(card.distribution)));

    if (card.statistics) {
      const stats = node("dl", "psi25-synthesis-statistics");
      const entries = [
        ["Mean Δ", card.statistics.mean], ["Median Δ", card.statistics.median],
        ["Observed minimum", card.statistics.minimum], ["Observed maximum", card.statistics.maximum],
        ["Positive / negative / zero", `${card.direction_counts?.positive ?? 0} / ${card.direction_counts?.negative ?? 0} / ${card.direction_counts?.zero ?? 0}`],
        ["Mean–median gap", card.absolute_mean_median_gap],
      ];
      for (const [label, value] of entries) {
        const item = node("div");
        item.append(node("dt", "", label));
        const dd = node("dd", "", label === "Positive / negative / zero" ? value : `${synthesisDisplay(value)}${label === "Positive / negative / zero" ? "" : ` ${card.unit || ""}`}`.trim());
        if (value !== null && value !== undefined) dd.title = String(value);
        item.append(dd);
        stats.append(item);
      }
      article.append(stats);
    } else {
      article.append(node("p", "psi25-synthesis-not-rankable", "No eligible exact paired observations. This cohort is not assigned a mean, direction, or rank."));
    }

    if (card.mission_research_relevance) {
      const relevance = node("p", "psi25-synthesis-relevance", card.mission_research_relevance);
      article.append(relevance);
    }
    synthesisRenderQuestions(article, card.research_questions);
    synthesisRenderEvidence(card, article);
    return article;
  }

  function synthesisRenderGlobalQuestions() {
    const questions = (synthesisBundle?.payload?.research_questions || []).filter((question) => question.metric === "all");
    const host = $("#psi25-synthesis-global-questions");
    host.replaceChildren();
    const list = node("ul", "psi25-synthesis-question-list");
    if (!questions.length) {
      list.append(node("li", "psi25-synthesis-empty", "No global research questions are present in the verified artifact."));
    } else {
      for (const question of questions) {
        const item = node("li", "psi25-synthesis-question");
        const metadata = node("div", "psi25-synthesis-question-meta");
        metadata.append(node("span", "psi25-synthesis-question-id", question.question_id || "Question"));
        metadata.append(node("span", "psi25-synthesis-question-trigger", String(question.trigger || "global").replaceAll("_", " ")));
        item.append(metadata, node("p", "", question.question || "Question text unavailable."));
        list.append(item);
      }
    }
    host.append(list);
    $("#psi25-synthesis-global-count").textContent = `${questions.length} global questions`;
  }

  function synthesisRenderLimitations(metricKey) {
    const host = $("#psi25-synthesis-limitations");
    host.replaceChildren();
    const payload = synthesisBundle.payload;
    const reuse = payload.sample_reuse_summary || {};
    host.append(node("p", "", `Sample identity: ${reuse.distinct_nonblank_exact_raw_sample_ids ?? "—"} distinct exact Sample IDs; ${reuse.reused_exact_raw_id_groups ?? "—"} reused ID groups include ${reuse.records_in_reused_exact_raw_id_groups ?? "—"} experiment records. Repeated IDs may indicate dependent records; eligible-pair n is not independent physical-sample n.`));
    if (metricKey === "o2") {
      const caveat = payload.measurement_provenance_caveats?.o2 || {};
      host.append(node("p", "is-caution", `O₂ source limitation: ${caveat.source_note || "The source ReadMe records an O₂ sensor calibration limitation."} ${caveat.interpretation_limit || "Residual measurement uncertainty is not quantified."}`));
    }
    const list = node("ul", "psi25-synthesis-constraints");
    for (const constraint of payload.scientific_use_constraints || []) list.append(node("li", "", constraint));
    host.append(list);
    host.append(node("p", "psi25-synthesis-safety-note", "These summaries identify research priorities only. They do not qualify materials, identify a universally safer fuel, or specify spacecraft firefighting procedures."));
  }

  function renderPsi25Synthesis() {
    if (!synthesisBundle) return;
    const metricKey = $("#psi25-synthesis-metric").value;
    const metric = synthesisBundle.payload.metrics[metricKey];
    if (!metric) return;
    const cards = (metric.insight_cards || []).filter(synthesisMatches);
    const globalCount = (synthesisBundle.payload.research_questions || []).filter((question) => question.metric === "all").length;
    synthesisRenderSummary(cards, globalCount);
    const host = $("#psi25-synthesis-cards");
    host.replaceChildren();
    if (!cards.length) host.append(node("p", "psi25-synthesis-empty", "No insight cards match the selected filters."));
    else for (const card of cards) host.append(synthesisRenderCard(card));
    synthesisRenderGlobalQuestions();
    synthesisRenderLimitations(metricKey);
  }

  function initializeSynthesisFilters() {
    const allCards = Object.values(synthesisBundle.payload.metrics).flatMap((metric) => metric.insight_cards || []);
    synthesisSetOptions("#psi25-synthesis-pi", [...new Set(allCards.map((card) => card.cohort?.pi).filter(Boolean))].sort(), "All investigators");
    synthesisSetOptions("#psi25-synthesis-material", [...new Set(allCards.map((card) => card.cohort?.material_class).filter(Boolean))].sort(), "All material classes");
    synthesisSetOptions("#psi25-synthesis-restrictor", [...new Set(allCards.map((card) => card.cohort?.flow_restrictor_code).filter((value) => value !== null && value !== undefined).map(String))].sort((a, b) => Number(a) - Number(b)), "All codes");
    const flags = [...new Set(allCards.flatMap((card) => card.flags || []))].sort();
    synthesisSetOptions("#psi25-synthesis-flag", flags, "All flags");
  }

  function validateSynthesisPayload(payload, manifestData) {
    if (payload.schema !== "sira.psi25.evidence_synthesis.v1" || manifestData.schema !== "sira.psi25.evidence_synthesis_manifest.v1") throw new Error("Synthesis schema is not the expected version.");
    if (payload.record_count !== records.length || payload.record_count !== 129 || manifestData.record_count !== payload.record_count) throw new Error("Synthesis record count does not match canonical BASS-II records.");
    if (payload.insight_card_count !== 54 || manifestData.insight_card_count !== 54 || manifestData.research_question_count !== 146 || payload.research_questions?.length !== 146) throw new Error("Synthesis insight/question counts do not match the verified build.");
    if (payload.generated_with_llm !== false || manifestData.llm_used !== false) throw new Error("Synthesis must remain deterministic and non-LLM-generated.");
    const safeguards = payload.safeguards || {};
    for (const flag of ["causal_claims_produced", "inferential_statistics_produced", "independent_sample_inference", "cross_metric_ranking", "operational_fire_safety_recommendations", "numeric_imputation", "llm_generated_measurements_or_claims"]) {
      if (safeguards[flag] !== false || manifestData[flag] === true) throw new Error(`Synthesis safeguard is missing or violated: ${flag}`);
    }
    if (!payload.measurement_provenance_caveats?.o2 || !payload.sample_reuse_summary) throw new Error("Synthesis measurement/sample caveats are missing.");
    const source = manifestData.source_artifacts || {};
    if (source.findings_ranking?.sha256 !== findingsBundle?.sha256 || source.paired_measurement_analysis?.sha256 !== pairedAnalysisHash) throw new Error("Synthesis source lineage does not match verified upstream artifacts.");
    const questionIds = (payload.research_questions || []).map((question) => question.question_id);
    if (questionIds.length !== 146 || questionIds.some((id) => !id) || new Set(questionIds).size !== questionIds.length) throw new Error("Research-question identities are missing or duplicated.");

    for (const key of ["o2", "co2", "co"]) {
      const metric = payload.metrics?.[key];
      if (!metric || metric.insight_cards?.length !== 18) throw new Error(`Synthesis ${key.toUpperCase()} insight-card count is invalid.`);
      const findingsMetric = findingsBundle.payload.metrics[key];
      const pairedMetric = pairedAnalysis.metrics[key];
      if (metric.pair_counts?.records !== records.length || metric.pair_counts.eligible_pairs !== findingsMetric.pair_counts.eligible_pairs || metric.pair_counts.excluded_pairs !== findingsMetric.pair_counts.excluded_pairs) throw new Error(`Synthesis ${key.toUpperCase()} pair counts disagree with findings.`);
      const findingCards = [...(findingsMetric.ranked_cohorts || []), ...(findingsMetric.not_rankable_cohorts || [])];
      const byIdentity = new Map(findingCards.map((card) => [`${card.cohort?.pi}|${card.cohort?.material_class}|${card.cohort?.flow_restrictor_code}`, card]));
      const seen = new Set();
      let eligibleCount = 0;
      let excludedCount = 0;
      let cardQuestionCount = 0;
      for (const card of metric.insight_cards) {
        const group = card.cohort || {};
        const identity = `${group.pi}|${group.material_class}|${group.flow_restrictor_code}`;
        const sourceCard = byIdentity.get(identity);
        if (!sourceCard || card.eligible_pairs !== sourceCard.eligible_pairs || card.excluded_pairs !== sourceCard.excluded_pairs) throw new Error(`Synthesis ${key.toUpperCase()} cohort identity/pair counts mismatch.`);
        if (!Array.isArray(card.research_questions) || !Array.isArray(card.supporting_record_evidence) || !Array.isArray(card.excluded_record_evidence)) throw new Error(`Synthesis ${key.toUpperCase()} evidence/question arrays are malformed.`);
        if (card.supporting_record_evidence.length !== card.eligible_pairs || card.excluded_record_evidence.length !== card.excluded_pairs || card.records_in_cohort !== card.eligible_pairs + card.excluded_pairs) throw new Error(`Synthesis ${key.toUpperCase()} evidence row accounting mismatch.`);
        eligibleCount += card.supporting_record_evidence.length;
        excludedCount += card.excluded_record_evidence.length;
        cardQuestionCount += card.research_questions.length;
        for (const row of [...card.supporting_record_evidence, ...card.excluded_record_evidence]) {
          if (!row.record_key || seen.has(row.record_key) || !byRecordKey.has(row.record_key)) throw new Error(`Synthesis ${key.toUpperCase()} contains duplicate or unknown evidence record.`);
          seen.add(row.record_key);
        }
        if (card.interpretation_status === "not_rankable") {
          if (card.eligible_pairs !== 0 || card.rank !== null || card.statistics !== undefined) throw new Error(`Synthesis ${key.toUpperCase()} incorrectly interprets a zero-pair cohort.`);
        } else if (card.interpretation_status !== "descriptive_only" || !card.statistics || card.statistics.n !== card.eligible_pairs) {
          throw new Error(`Synthesis ${key.toUpperCase()} interpretation/status fields are invalid.`);
        }
        if (key === "o2" && !(card.flags || []).includes("o2_sensor_calibration_limitation")) throw new Error("O2 calibration limitation is not attached to every O2 insight card.");
      }
      if (seen.size !== records.length || eligibleCount !== metric.pair_counts.eligible_pairs || excludedCount !== metric.pair_counts.excluded_pairs) throw new Error(`Synthesis ${key.toUpperCase()} evidence/pair totals do not cover all canonical records exactly once.`);
      const expectedKeys = new Set(pairedMetric.record_level_audit.map((row) => row.record_key));
      if (seen.size !== expectedKeys.size || [...seen].some((recordKey) => !expectedKeys.has(recordKey))) throw new Error(`Synthesis ${key.toUpperCase()} evidence keys differ from paired-analysis source.`);
      const expectedQuestions = metric.insight_cards.flatMap((card) => card.research_questions.map((question) => question.question_id));
      const allQuestionIds = new Set(payload.research_questions.map((question) => question.question_id));
      if (expectedQuestions.length !== cardQuestionCount || new Set(expectedQuestions).size !== expectedQuestions.length || expectedQuestions.some((questionId) => !allQuestionIds.has(questionId))) throw new Error(`Synthesis ${key.toUpperCase()} card research-question IDs are invalid or missing from the global index.`);
      const rankableCount = metric.insight_cards.filter((card) => card.interpretation_status === "descriptive_only").length;
      const notRankableCount = metric.insight_cards.filter((card) => card.interpretation_status === "not_rankable").length;
      if (rankableCount !== metric.rankable_cohort_count || notRankableCount !== metric.not_rankable_cohort_count) throw new Error(`Synthesis ${key.toUpperCase()} rankable/not-rankable counts mismatch.`);
    }
  }

  async function loadPsi25Synthesis() {
    const status = $("#psi25-synthesis-status");
    try {
      const responses = await Promise.all(Object.values(SYNTHESIS_FILES).map((path) => fetch(path, { cache: "no-store" })));
      if (!responses.every((response) => response.ok)) throw new Error("Synthesis artifact or manifest is unavailable.");
      const bytes = await responses[0].arrayBuffer();
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      const [payload, manifestData] = await Promise.all([Promise.resolve(JSON.parse(text)), responses[1].json()]);
      if (typeof crypto === "undefined" || !crypto.subtle?.digest) throw new Error("Web Crypto SHA-256 verification is unavailable; use the local preview on localhost.");
      const digest = bytesToHex(await crypto.subtle.digest("SHA-256", bytes));
      const output = manifestData.derived_output || {};
      if (digest !== output.sha256 || bytes.byteLength !== output.bytes) throw new Error("Synthesis SHA-256 or byte-size verification failed.");
      if (manifestData.source_artifacts?.findings_ranking?.sha256 !== findingsBundle?.sha256) throw new Error("Synthesis does not reference the verified findings artifact.");
      if (manifestData.source_artifacts?.paired_measurement_analysis?.sha256 !== pairedAnalysisHash) throw new Error("Synthesis does not reference the verified paired-analysis artifact.");
      validateSynthesisPayload(payload, manifestData);
      synthesisBundle = { payload, manifest: manifestData, sha256: digest };
      initializeSynthesisFilters();
      renderPsi25Synthesis();
      $("#psi25-synthesis-hash").textContent = `Synthesis SHA-256 verified: ${digest}`;
      $("#psi25-synthesis-builder").textContent = `Builder SHA-256: ${manifestData.builder?.sha256 || "not stated"}`;
      $("#psi25-synthesis-source").textContent = `Findings lineage verified: ${findingsBundle.sha256}`;
      status.textContent = `Verified deterministic synthesis · ${payload.insight_card_count} insight cards · ${payload.research_questions.length} research questions · ${payload.record_count} records · read-only`;
      status.classList.add("is-verified");
    } catch (error) {
      status.textContent = `Evidence synthesis unavailable: ${error instanceof Error ? error.message : "artifact validation failed"}. Verified BASS-II records, paired analysis and findings remain available.`;
      status.classList.add("is-error");
      $("#psi25-synthesis-cards").replaceChildren(node("p", "psi25-synthesis-empty", "No verified synthesis cards are available."));
    }
  }

  function synthesisOpenSourceRecord(event) {
    const button = event.target.closest("button[data-synthesis-record-key]");
    if (!button) return;
    const record = byRecordKey.get(button.dataset.synthesisRecordKey);
    if (record) {
      renderRecordDetails(record);
      $("#psi25-record-detail").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  async function loadPsi25Findings(expectedPairedHash) {
    const status = $("#psi25-findings-status");
    try {
      const responses = await Promise.all(Object.values(FINDINGS_FILES).map((path) => fetch(path, { cache: "no-store" })));
      if (!responses.every((response) => response.ok)) throw new Error("Findings artifact or manifest is unavailable.");
      const bytes = await responses[0].arrayBuffer();
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      const [payload, manifestData] = await Promise.all([Promise.resolve(JSON.parse(text)), responses[1].json()]);
      if (typeof crypto === "undefined" || !crypto.subtle?.digest) throw new Error("Web Crypto SHA-256 verification is unavailable; use the local preview on localhost.");
      const digest = bytesToHex(await crypto.subtle.digest("SHA-256", bytes));
      const output = manifestData.derived_output || {};
      if (digest !== output.sha256 || bytes.byteLength !== output.bytes) throw new Error("Findings SHA-256 or byte-size verification failed.");
      validateFindingsPayload(payload, manifestData, expectedPairedHash);
      findingsBundle = { payload, manifest: manifestData, sha256: digest };
      initializeFindingsFilters();
      renderFindings();
      $("#psi25-findings-hash").textContent = `Findings SHA-256 verified: ${digest}`;
      $("#psi25-findings-builder").textContent = `Builder SHA-256: ${manifestData.builder?.sha256 || "not stated"}`;
      status.textContent = `Verified local findings · ${payload.record_count} experiment records · study version ${payload.study_version} · read-only`;
      status.classList.add("is-verified");
      await loadPsi25Synthesis();
    } catch (error) {
      status.textContent = `Findings unavailable: ${error instanceof Error ? error.message : "artifact validation failed"}. The BASS-II record browser and paired-analysis view remain available.`;
      status.classList.add("is-error");
      $("#psi25-findings-ranked").replaceChildren();
      $("#psi25-findings-not-ranked").replaceChildren();
    }
  }

  async function loadPsi25Analysis() {
    const status = $("#psi25-analysis-status");
    try {
      const responses = await Promise.all(Object.values(ANALYSIS_FILES).map((path) => fetch(path, { cache: "no-store" })));
      if (!responses.every((response) => response.ok)) throw new Error("Paired-analysis artifact or manifest is unavailable.");
      const bytes = await responses[0].arrayBuffer();
      const analysisText = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      const [payload, manifestData] = await Promise.all([
        Promise.resolve(JSON.parse(analysisText)), responses[1].json(),
      ]);
      const derived = manifestData.derived_output || {};
      if (typeof crypto === "undefined" || !crypto.subtle?.digest) throw new Error("Web Crypto SHA-256 verification is unavailable; open the local preview on localhost.");
      const digest = bytesToHex(await crypto.subtle.digest("SHA-256", bytes));
      if (digest !== derived.sha256 || bytes.byteLength !== derived.bytes) throw new Error("Paired-analysis SHA-256 or byte-size verification failed.");
      if (payload.record_count !== 129 || payload.record_count !== records.length) throw new Error("Paired-analysis record count does not match the canonical bundle.");
      if (!payload.metrics || !["o2", "co2", "co"].every((key) => payload.metrics[key])) throw new Error("Paired-analysis metric schema is incomplete.");
      for (const key of ["o2", "co2", "co"]) {
        const metric = payload.metrics[key];
        if (metric.pair_counts?.records !== records.length || metric.record_level_audit?.length !== records.length || !Array.isArray(metric.cohort_summaries)) throw new Error(`Paired-analysis ${key.toUpperCase()} record accounting is incomplete.`);
        const eligible = metric.cohort_summaries.reduce((sum, item) => sum + item.eligible_pairs, 0);
        const excluded = metric.cohort_summaries.reduce((sum, item) => sum + item.excluded_pairs, 0);
        const auditEligible = metric.record_level_audit.filter((item) => item.pair_eligible === true).length;
        const auditExcluded = metric.record_level_audit.filter((item) => item.pair_eligible === false).length;
        if (eligible !== metric.pair_counts.eligible_pairs || excluded !== metric.pair_counts.excluded_pairs) throw new Error(`Paired-analysis ${key.toUpperCase()} cohort accounting mismatch.`);
        if (auditEligible !== eligible || auditExcluded !== excluded) throw new Error(`Paired-analysis ${key.toUpperCase()} record audit accounting mismatch.`);
      }
      if (manifestData.o2_calibration_caveat_included !== true || manifestData.independent_sample_inference !== false) throw new Error("Required scientific caveat flags are missing from the analysis manifest.");
      pairedAnalysis = payload;
      pairedAnalysisHash = digest;
      initializeAnalysisFilters();
      renderPairedAnalysis();
      $("#psi25-analysis-hash").textContent = `Analysis SHA-256 verified: ${digest}`;
      $("#psi25-analysis-builder").textContent = `Builder SHA-256: ${manifestData.builder?.sha256 || "not stated"}`;
      status.textContent = `Verified local analysis · ${payload.record_count} records · study version ${payload.study_version} · read-only`;
      status.classList.add("is-verified");
      await loadPsi25Findings(digest);
    } catch (error) {
      status.textContent = `Paired analysis unavailable: ${error instanceof Error ? error.message : "artifact validation failed"}. The canonical BASS-II record browser remains available.`;
      status.classList.add("is-error");
      $("#psi25-analysis-chart").replaceChildren(node("p", "psi25-analysis-empty", "No verified paired-analysis artifact is available."));
      const findingsStatus = $("#psi25-findings-status");
      if (findingsStatus) {
        findingsStatus.textContent = "Findings unavailable because the paired-analysis artifact did not pass verification.";
        findingsStatus.classList.add("is-error");
      }
    }
  }

  async function loadPsi25() {
    try {
      const responses = await Promise.all(Object.values(FILES).map((path) => fetch(path, { cache: "no-store" })));
      if (!responses.every((response) => response.ok)) throw new Error("One or more canonical bundle files are unavailable.");
      const [recordData, qualityData, manifestData] = await Promise.all(responses.map((response) => response.json()));
      if (!Array.isArray(recordData.records) || recordData.records.length === 0 || !qualityData.measurement_status_counts || !manifestData) {
        throw new Error("Canonical bundle schema is incomplete.");
      }
      if (recordData.record_count !== recordData.records.length || qualityData.record_count !== recordData.records.length || manifestData.record_count !== recordData.records.length) {
        throw new Error("Canonical records, quality report, and manifest have inconsistent record counts.");
      }
      for (const record of recordData.records) {
        const key = record.identity?.record_key;
        if (!key || byRecordKey.has(key) || !record.measurements || !record.source_provenance) {
          throw new Error("Canonical record identity or provenance validation failed.");
        }
        byRecordKey.set(key, record);
      }
      records = recordData.records;
      quality = qualityData;
      manifest = manifestData;
      initializeFilters();
      renderSummary();
      renderRecordTable();
      renderQuality();
      renderProvenance();
      renderConstraints();
      loadPsi25Analysis();
    } catch {
      showLoadError();
    }
  }

  for (const selector of ["#psi25-filter-pi", "#psi25-filter-material", "#psi25-filter-restrictor"]) {
    $(selector).addEventListener("change", renderRecordTable);
  }
  $("#psi25-filter-search").addEventListener("input", renderRecordTable);
  $("#psi25-filter-reset").addEventListener("click", () => {
    $("#psi25-filter-pi").value = "";
    $("#psi25-filter-material").value = "";
    $("#psi25-filter-restrictor").value = "";
    $("#psi25-filter-search").value = "";
    renderRecordTable();
  });
  $("#psi25-records-body").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-record-key]");
    if (!button) return;
    const record = byRecordKey.get(button.dataset.recordKey);
    if (record) renderRecordDetails(record);
  });
  $("#psi25-detail-close").addEventListener("click", () => { $("#psi25-record-detail").hidden = true; });

  $("#psi25-analysis-metric").addEventListener("change", renderPairedAnalysis);
  for (const selector of ["#psi25-analysis-pi", "#psi25-analysis-material", "#psi25-analysis-restrictor"]) {
    $(selector).addEventListener("change", renderPairedAnalysis);
  }
  $("#psi25-analysis-audit-search").addEventListener("input", () => {
    if (pairedAnalysis) renderAnalysisAudit(pairedAnalysis.metrics[$("#psi25-analysis-metric").value]);
  });
  $("#psi25-analysis-reset").addEventListener("click", () => {
    $("#psi25-analysis-metric").value = "o2";
    $("#psi25-analysis-pi").value = "";
    $("#psi25-analysis-material").value = "";
    $("#psi25-analysis-restrictor").value = "";
    $("#psi25-analysis-audit-search").value = "";
    renderPairedAnalysis();
  });

  for (const selector of ["#psi25-findings-metric", "#psi25-findings-pi", "#psi25-findings-material", "#psi25-findings-restrictor"]) {
    $(selector).addEventListener("change", renderFindings);
  }
  $("#psi25-findings-reset").addEventListener("click", () => {
    $("#psi25-findings-metric").value = "o2";
    $("#psi25-findings-pi").value = "";
    $("#psi25-findings-material").value = "";
    $("#psi25-findings-restrictor").value = "";
    renderFindings();
  });
  for (const selector of ["#psi25-findings-ranked", "#psi25-findings-not-ranked"]) {
    $(selector).addEventListener("click", (event) => {
      const button = event.target.closest("button[data-findings-kind]");
      if (!button) return;
      renderFindingsEvidence(button.dataset.findingsMetric, button.dataset.findingsKind, Number(button.dataset.findingsIndex));
    });
  }
  $("#psi25-findings-eligible-evidence").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-findings-record-key]");
    if (!button) return;
    const record = byRecordKey.get(button.dataset.findingsRecordKey);
    if (record) {
      renderRecordDetails(record);
      $("#psi25-record-detail").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  $("#psi25-findings-excluded-evidence").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-findings-record-key]");
    if (!button) return;
    const record = byRecordKey.get(button.dataset.findingsRecordKey);
    if (record) {
      renderRecordDetails(record);
      $("#psi25-record-detail").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  $("#psi25-findings-evidence-close").addEventListener("click", () => {
    $("#psi25-findings-evidence").hidden = true;
  });
  for (const selector of ["#psi25-synthesis-metric", "#psi25-synthesis-pi", "#psi25-synthesis-material", "#psi25-synthesis-restrictor", "#psi25-synthesis-flag"]) {
    $(selector).addEventListener("change", renderPsi25Synthesis);
  }
  $("#psi25-synthesis-reset").addEventListener("click", () => {
    $("#psi25-synthesis-metric").value = "o2";
    $("#psi25-synthesis-pi").value = "";
    $("#psi25-synthesis-material").value = "";
    $("#psi25-synthesis-restrictor").value = "";
    $("#psi25-synthesis-flag").value = "";
    renderPsi25Synthesis();
  });
  $("#psi25-synthesis-cards").addEventListener("click", synthesisOpenSourceRecord);
  loadPsi25();
})();
