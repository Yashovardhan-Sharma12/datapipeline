let currentJobId = null;
let latestComparisonData = [];

function updateSummary(results) {
    const complete = results.filter(r => r.status === "complete").length;
    const failed = results.filter(r => r.status === "failed").length;
    const running = results.filter(r => ["running", "pending", "retrying"].includes(r.status)).length;

    document.getElementById("metricComplete").textContent = complete;
    document.getElementById("metricFailed").textContent = failed;
    document.getElementById("metricRunning").textContent = running;
}

function updateTable(results) {
    const tbody = document.getElementById("statusTable").querySelector("tbody");
    tbody.innerHTML = "";

    if (!results || results.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="4">No query results available.</td></tr>`;
        updateSummary([]);
        return;
    }

    results.forEach((res, idx) => {
        const status = (res.status || "pending").toLowerCase();
        tbody.innerHTML += `
            <tr>
                <td>${idx + 1}</td>
                <td>${escapeHtml(res.source_label || res.query_source || "")}</td>
                <td><strong>${escapeHtml(res.filename)}</strong></td>
                <td><span class="status-pill status-${escapeHtml(status)}" title="${escapeHtml(describeQueryResult(res))}">
                    ${escapeHtml(status === "empty" ? "No rows" : status)}
                </span></td>
            </tr>`;
    });

    updateSummary(results);
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function refreshStatusLabel(status) {
    const labels = {
        running: "Running",
        success: "Successful",
        completed_with_failures: "Completed with failures",
        failed: "Failed"
    };
    return labels[status] || status || "Unknown";
}

function refreshStatusClass(status) {
    if (status === "success") return "status-complete";
    if (status === "completed_with_failures") return "status-retrying";
    if (status === "failed") return "status-failed";
    return "status-running";
}

function formatRefreshTime(value) {
    if (!value) return "Unknown time";
    const parsed = new Date(value);

    return Number.isNaN(parsed.getTime())
        ? value
        : parsed.toLocaleString("en-GB", {
            day: "2-digit",
            month: "short",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false
        });
}

const refreshHistoryState = {
    active: [],
    latest: [],
    older: [],
    nextBefore: null,
    paged: false,
    signature: null,
    details: new Map()
};

function describeQueryResult(row) {
    const error = row.error_detail;
    if (!error) return row.last_error || row.error || row.message || "";

    const labels = {
        connection: "Connection error",
        sql_error: "SQL error",
        timeout: "Query timed out"
    };
    const label = labels[error.kind];
    const details = [label ? `${label}: ${error.message}` : error.message];
    if (error.sql_error_number != null) details.push(`SQL Server error ${error.sql_error_number}`);
    if (error.line_number != null) details.push(`line ${error.line_number}`);
    if (row.fallback_output) {
        details.push(`Kept ${row.fallback_output.name} from ${formatRefreshTime(row.fallback_output.written_at)}`);
    }
    return details.join(" · ");
}

function renderRefreshHistory() {
    const container = document.getElementById("refreshHistory");
    const state = refreshHistoryState;
    const activeIds = new Set(state.active.map(refresh => refresh.job_id));
    const unique = new Map();
    for (const refresh of [...state.active, ...state.latest, ...state.older]) {
        if (!unique.has(refresh.job_id)) unique.set(refresh.job_id, refresh);
    }
    const rows = Array.from(unique.values()).slice(0, 200);
    const signature = JSON.stringify([rows, state.active.map(refresh => refresh.job_id)]);
    const olderButton = document.getElementById("refreshHistoryOlder");
    olderButton.hidden = !state.nextBefore || rows.length >= 200;
    if (signature === state.signature) return;
    state.signature = signature;

    const openIds = new Set(
        Array.from(container.querySelectorAll(".refresh-item[open]"), card => card.dataset.refreshJobId)
    );
    container.innerHTML = rows.map(refresh => {
        const id = escapeHtml(refresh.job_id);
        const progress = Math.min(100, Math.max(0, Number(refresh.progress_percent) || 0));
        const time = escapeHtml(formatRefreshTime(refresh.scheduled_for || refresh.started_at));
        const empty = Number(refresh.empty_queries) || 0;
        return `
            <details class="refresh-item" data-refresh-job-id="${id}"
                data-active="${activeIds.has(refresh.job_id)}" ${openIds.has(refresh.job_id) ? "open" : ""}>
                <summary>
                    <div>
                        <div class="refresh-title">${time}</div>
                        <div class="refresh-meta">${id}</div>
                    </div>
                    <div>
                        <div class="refresh-progress-track">
                            <div class="refresh-progress-bar" style="width:${progress}%"></div>
                        </div>
                        <div class="refresh-progress-copy">
                            ${Number(refresh.finalised_queries) || 0}/${Number(refresh.total_queries) || 0}
                            queries finalised · ${progress}%${empty ? ` · ${empty} with no rows` : ""}
                        </div>
                    </div>
                    <span class="status-pill ${refreshStatusClass(refresh.status)}">
                        ${escapeHtml(refreshStatusLabel(refresh.status))}
                    </span>
                </summary>
                <div class="refresh-details" aria-live="polite"></div>
            </details>`;
    }).join("") || '<div class="empty-row" style="padding:26px;">No scheduled refresh history recorded yet.</div>';
}

function renderRefreshDetail(refresh) {
    const quality = refresh.quality || {};
    const results = refresh.results || [];

    const failedResults = results.filter(
        row => row.status === "failed"
    );

    const sourceSummaries = ["Customer", "Colleague"]
        .map(sourceLabel => {
            const sourceRows = results.filter(row =>
                String(
                    row.source_label ||
                    row.query_source ||
                    ""
                ).toLowerCase() === sourceLabel.toLowerCase()
            );

            const sourceFinalised = sourceRows.filter(
                row => ["complete", "empty", "failed"].includes(row.status)
            ).length;

            const sourceRunning = sourceRows.filter(
                row => ["running", "retrying"].includes(row.status)
            ).length;

            const sourcePending = sourceRows.filter(
                row => row.status === "pending"
            ).length;

            const sourceFailed = sourceRows.filter(
                row => row.status === "failed"
            ).length;

            return {
                label: sourceLabel,
                total: sourceRows.length,
                finalised: sourceFinalised,
                running: sourceRunning,
                pending: sourcePending,
                failed: sourceFailed
            };
        })
        .filter(source => source.total > 0);

    const sourceProgressHtml = sourceSummaries
        .map(source => `
            <div class="source-progress-card">
                <div>
                    <span>${escapeHtml(source.label)}</span>
                    <strong>${source.finalised}/${source.total}</strong>
                </div>
                <small>
                    ${source.running} running/retrying ·
                    ${source.pending} pending ·
                    ${source.failed} failed
                </small>
            </div>
        `)
        .join("");

    const queryRows = results
        .map((row, index) => {
            const status = row.status || "pending";

            let reason = describeQueryResult(row);

            if (!reason && row.validation) {
                if (row.validation.status === "missing_data") {
                    reason =
                        `Latest Tesco week ${row.validation.week || ""} missing`;

                } else if (
                    row.validation.status === "validation_skipped"
                ) {
                    reason =
                        row.validation.message ||
                        "No year_week_number column";

                } else if (
                    row.validation.status === "error"
                ) {
                    reason =
                        row.validation.message ||
                        "Latest-week validation failed";
                }
            }

            return `
                <tr>
                    <td>${index + 1}</td>
                    <td>
                        ${escapeHtml(
                            row.source_label ||
                            row.query_source ||
                            ""
                        )}
                    </td>
                    <td>
                        <strong>
                            ${escapeHtml(row.filename || "")}
                        </strong>
                    </td>
                    <td>
                        ${escapeHtml(
                            `${row.attempts || 0}/${row.max_attempts || 3}`
                        )}
                    </td>
                    <td>
                        <span class="status-pill status-${escapeHtml(status)}">
                            ${escapeHtml(status === "empty" ? "No rows" : status)}
                        </span>
                    </td>
                    <td style="white-space:normal; min-width:260px;">
                        ${escapeHtml(reason)}
                    </td>
                </tr>`;
        })
        .join("");

    const failureMessage = refresh.error
        ? `
            <div class="refresh-error">
                ${escapeHtml(refresh.error)}
            </div>
        `
        : (
            failedResults.length
                ? `
                    <div class="refresh-error">
                        ${failedResults.length}
                        query(s) failed.
                        ContentGen is allowed to proceed using the
                        latest available outputs.
                    </div>
                `
                : ""
        );

    return `
        <div class="source-progress-grid">
            ${sourceProgressHtml}
        </div>

        <div class="quality-grid">

            <div class="quality-card">
                <span>Latest week</span>
                <strong>
                    ${escapeHtml(
                        quality.latest_year_week || "—"
                    )}
                </strong>
            </div>

            <div class="quality-card">
                <span>Week present</span>
                <strong>
                    ${quality.latest_week_present ?? "—"}
                </strong>
            </div>

            <div class="quality-card">
                <span>Missing latest week</span>
                <strong>
                    ${quality.missing_latest_week ?? "—"}
                </strong>
            </div>

            <div class="quality-card">
                <span>No year_week column</span>
                <strong>
                    ${quality.no_year_week_column ?? "—"}
                </strong>
            </div>

            <div class="quality-card">
                <span>Failed queries</span>
                <strong>
                    ${failedResults.length}
                </strong>
            </div>

        </div>

        ${failureMessage}

        <div class="table-wrap">
            <table class="refresh-query-table">

                <thead>
                    <tr>
                        <th>#</th>
                        <th>Source</th>
                        <th>Query</th>
                        <th>Attempts</th>
                        <th>Status</th>
                        <th>Reason / data quality</th>
                    </tr>
                </thead>

                <tbody>
                    ${
                        queryRows ||
                        `
                        <tr class="empty-row">
                            <td colspan="6">
                                Query details are not available yet.
                            </td>
                        </tr>
                        `
                    }
                </tbody>

            </table>
        </div>

    `;
}

async function loadRefreshDetail(card) {
    const panel = card.querySelector(".refresh-details");
    const active = card.dataset.active === "true";
    const jobId = card.dataset.refreshJobId;
    if (panel.dataset.loading || (panel.dataset.loaded && !active)) return;

    const details = refreshHistoryState.details;
    if (!active && details.has(jobId)) {
        panel.innerHTML = renderRefreshDetail(details.get(jobId));
        panel.dataset.loaded = "true";
        return;
    }

    panel.dataset.loading = "true";
    if (!panel.dataset.loaded) panel.textContent = "Loading refresh details…";
    try {
        const path = active ? "/status/" : "/refresh-history/";
        const response = await fetch(path + encodeURIComponent(jobId));
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        const refresh = active ? data : data.refresh;
        if (!active) details.set(jobId, refresh);
        if (panel.isConnected) {
            panel.innerHTML = renderRefreshDetail(refresh);
            panel.dataset.loaded = "true";
        }
    } catch {
        if (panel.isConnected) panel.textContent = "Unable to load refresh details. Close and reopen this refresh to retry.";
    } finally {
        delete panel.dataset.loading;
    }
}

async function pollRefreshHistory() {
    const state = refreshHistoryState;
    try {
        const response = await fetch("/refresh-history");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (state.paged) {
            const older = new Map([...state.latest, ...state.older].map(refresh => [refresh.job_id, refresh]));
            state.older = Array.from(older.values()).slice(0, 200);
        } else {
            state.nextBefore = data.next_before;
        }
        state.active = data.active || [];
        state.latest = data.history || [];
        renderRefreshHistory();
        document.querySelectorAll("#refreshHistory .refresh-item[open]").forEach(loadRefreshDetail);
    } catch (error) {
        console.error("Unable to load refresh history:", error);
    } finally {
        setTimeout(pollRefreshHistory, state.active.length ? 5000 : 60000);
    }
}

async function loadOlderRefreshes(event) {
    const button = event.currentTarget;
    const state = refreshHistoryState;
    if (!state.nextBefore) return;

    button.disabled = true;
    state.paged = true;
    try {
        const params = new URLSearchParams({ before: state.nextBefore });
        const response = await fetch(`/refresh-history?${params}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        state.older.push(...data.history);
        state.nextBefore = data.next_before;
        button.textContent = "Show older refreshes";
        renderRefreshHistory();
        document.querySelectorAll("#refreshHistory .refresh-item[open]").forEach(loadRefreshDetail);
    } catch (error) {
        button.textContent = "Retry loading older refreshes";
        console.error("Unable to load older refreshes:", error);
    } finally {
        button.disabled = false;
    }
}

function normalizeMarketValue(value) {
    if (
        value === null ||
        value === undefined
    ) {
        return "";
    }

    return String(value)
        .trim()
        .toUpperCase();
}

function normalizeWeekValue(value) {
    if (
        value === null ||
        value === undefined
    ) {
        return "";
    }

    const text = String(value).trim();

    if (!text) {
        return "";
    }

    // SQL numeric values can arrive through JSON as:
    // 202634
    // 202634.0
    // "202634"
    //
    // Normalise all of them to one comparable key.

    const numericValue = Number(
        text.replace(/,/g, "")
    );

    if (Number.isFinite(numericValue)) {
        return String(
            Math.trunc(numericValue)
        );
    }

    return text.replace(
        /[.]0+$/,
        ""
    );
}

function normalizeBusinessParentValue(value) {
    if (
        value === null ||
        value === undefined
    ) {
        return "";
    }

    return String(value).trim();
}

function businessParentKey(value) {
    return normalizeBusinessParentValue(
        value
    ).toLowerCase();
}

function rebuildSelect(
    selectElement,
    values,
    allLabel,
    currentSelection
) {
    selectElement.innerHTML =
        `<option value="">${allLabel}</option>`;

    values.forEach(value => {
        const option =
            document.createElement("option");

        option.value = value;
        option.textContent = value;

        selectElement.appendChild(option);
    });

    if (
        currentSelection &&
        values.includes(currentSelection)
    ) {
        selectElement.value =
            currentSelection;

    } else {
        selectElement.value = "";
    }
}

function refreshValidationFilters() {
    const marketFilter =
        document.getElementById(
            "marketFilter"
        );

    const weekFilter =
        document.getElementById(
            "weekFilter"
        );

    const businessParentFilter =
        document.getElementById(
            "businessParentFilter"
        );

    const selectedMarket =
        normalizeMarketValue(
            marketFilter.value
        );

    const selectedWeek =
        normalizeWeekValue(
            weekFilter.value
        );

    const selectedBusinessParent =
        normalizeBusinessParentValue(
            businessParentFilter.value
        );

    // ----------------------------------------------------------
    // Market
    // Always based on the full validation dataset.

    const markets = [
        ...new Set(
            latestComparisonData
                .map(row =>
                    normalizeMarketValue(
                        row.validation_market
                    )
                )
                .filter(Boolean)
        )
    ].sort();

    rebuildSelect(
        marketFilter,
        markets,
        "All markets",
        selectedMarket
    );

    const activeMarket =
        normalizeMarketValue(
            marketFilter.value
        );

    const marketRows =
        latestComparisonData.filter(row =>
            !activeMarket ||
            normalizeMarketValue(
                row.validation_market
            ) === activeMarket
        );

    // ----------------------------------------------------------
    // Year week
    // Based on the selected market.

    const weeks = [
        ...new Set(
            marketRows
                .map(row =>
                    normalizeWeekValue(
                        row.year_week_number
                    )
                )
                .filter(Boolean)
        )
    ].sort((a, b) => {

        const aNumber = Number(a);
        const bNumber = Number(b);

        if (
            Number.isFinite(aNumber) &&
            Number.isFinite(bNumber)
        ) {
            return bNumber - aNumber;
        }

        return b.localeCompare(
            a,
            undefined,
            {numeric: true}
        );
    });

    rebuildSelect(
        weekFilter,
        weeks,
        "All weeks",
        selectedWeek
    );

    const activeWeek =
        normalizeWeekValue(
            weekFilter.value
        );

    const marketWeekRows =
        marketRows.filter(row =>
            !activeWeek ||
            normalizeWeekValue(
                row.year_week_number
            ) === activeWeek
        );

    // ----------------------------------------------------------
    // Business parent
    // Based on Market + Week.

    const businessParentsByKey =
        new Map();

    marketWeekRows.forEach(row => {

        const displayValue =
            normalizeBusinessParentValue(
                row.businessparent
            );

        if (displayValue) {
            businessParentsByKey.set(
                businessParentKey(
                    displayValue
                ),
                displayValue
            );
        }
    });

    const businessParents = [
        ...businessParentsByKey.values()
    ].sort((a, b) =>
        a.localeCompare(
            b,
            undefined,
            {sensitivity: "base"}
        )
    );

    const preservedBusinessParent =
        businessParents.find(
            value =>
                businessParentKey(value) ===
                businessParentKey(
                    selectedBusinessParent
                )
        ) || "";

    rebuildSelect(
        businessParentFilter,
        businessParents,
        "All business parents",
        preservedBusinessParent
    );
}

function applyFilters() {
    const comparisonBody =
        document
            .getElementById(
                "comparisonTable"
            )
            .querySelector("tbody");

    // Rebuild dependent dropdowns without
    // clearing valid selections.
    refreshValidationFilters();

    const selectedMarket =
        normalizeMarketValue(
            document
                .getElementById(
                    "marketFilter"
                )
                .value
        );

    const selectedWeek =
        normalizeWeekValue(
            document
                .getElementById(
                    "weekFilter"
                )
                .value
        );

    const selectedBusinessParent =
        businessParentKey(
            document
                .getElementById(
                    "businessParentFilter"
                )
                .value
        );

    comparisonBody.innerHTML = "";

    const filteredRows =
        latestComparisonData.filter(row => {

            const matchesMarket =
                !selectedMarket ||
                normalizeMarketValue(
                    row.validation_market
                ) === selectedMarket;

            const matchesWeek =
                !selectedWeek ||
                normalizeWeekValue(
                    row.year_week_number
                ) === selectedWeek;

            const matchesBusinessParent =
                !selectedBusinessParent ||
                businessParentKey(
                    row.businessparent
                ) === selectedBusinessParent;

            return (
                matchesMarket &&
                matchesWeek &&
                matchesBusinessParent
            );
        });

    if (filteredRows.length === 0) {

        comparisonBody.innerHTML = `
            <tr class="empty-row">
                <td colspan="26">
                    No validation rows match the selected filters.
                </td>
            </tr>
        `;

        return;
    }

    filteredRows.forEach(row => {

        const isMatch =
            String(
                row.match_status || ""
            ).toUpperCase() === "MATCH";

        const matchClass =
            isMatch
                ? "match-ok"
                : "match-diff";

        const matchText =
            row.match_status ?? "";

        comparisonBody.innerHTML += `
            <tr>
                <td>
                    <strong>
                        ${normalizeMarketValue(
                            row.validation_market
                        )}
                    </strong>
                </td>

                <td>
                    ${normalizeWeekValue(
                        row.year_week_number
                    )}
                </td>

                <td>
                    ${row.country ?? ""}
                </td>

                <td>
                    ${row.sub_country ?? ""}
                </td>

                <td>
                    ${row.channel ?? ""}
                </td>

                <td>
                    <strong>
                        ${row.businessparent ?? ""}
                    </strong>
                </td>

                <td>
                    ${row.handled_volume_difference ?? ""}
                </td>

                <td>
                    ${row.offered_volume_difference ?? ""}
                </td>

                <td>
                    ${row.repeat_contact_24hr_difference ?? ""}
                </td>

                <td>
                    ${row.abandoned_difference ?? ""}
                </td>

                <td>
                    ${row.average_handling_time_difference ?? ""}
                </td>

                <td>
                    ${row.average_speed_of_answer_difference ?? ""}
                </td>

                <td>
                    ${row.gogw_volume_difference ?? ""}
                </td>

                <td>
                    ${row.gogw_total_value_difference ?? ""}
                </td>

                <td>
                    ${row.gogw_average_value_difference ?? ""}
                </td>

                <td>
                    ${row.csat_difference ?? ""}
                </td>

                <td>
                    ${row.service_level_difference ?? ""}
                </td>

                <td>
                    ${row.opened_conversations_difference ?? ""}
                </td>

                <td>
                    ${row.journey_volume_difference ?? ""}
                </td>

                <td>
                    ${row.closed_conversations_difference ?? ""}
                </td>

                <td>
                    ${row.avg_eht_difference ?? ""}
                </td>

                <td>
                    ${row.repeat_contact_rate_difference ?? ""}
                </td>

                <td>
                    ${row.fcst_offered_volume_tw_difference ?? ""}
                </td>

                <td>
                    ${row.fcst_handled_time_tw_difference ?? ""}
                </td>

                <td>
                    ${row.fcst_journey_volume_tw_difference ?? ""}
                </td>

                <td>
                    <span
                        class="match-pill ${matchClass}"
                    >
                        ${matchText}
                    </span>
                </td>
            </tr>
        `;
    });
}

function renderComparison(results) {
    const comparisonBody =
        document
            .getElementById(
                "comparisonTable"
            )
            .querySelector("tbody");

    // IMPORTANT:
    // Do NOT reset filter dropdowns here.
    //
    // renderComparison is called every two seconds
    // while a job is being polled. Resetting them
    // caused user-selected filters to jump back to All.

    latestComparisonData = [];

    const validationResults =
        (results || []).filter(
            result =>
                result.filename &&
                result.filename
                    .toLowerCase()
                    .startsWith(
                        "validation_"
                    ) &&
                result.filename
                    .toLowerCase()
                    .endsWith(".sql") &&
                Array.isArray(
                    result.comparison_data
                ) &&
                result.comparison_data.length > 0
        );

    if (
        validationResults.length === 0
    ) {
        comparisonBody.innerHTML = `
            <tr class="empty-row">
                <td colspan="26">
                    Run a validation_&lt;market&gt;.sql query
                    to populate this table.
                </td>
            </tr>
        `;

        return;
    }

    validationResults.forEach(result => {

        const fallbackMarket =
            result.filename
                .toLowerCase()
                .replace(
                    "validation_",
                    ""
                )
                .replace(
                    ".sql",
                    ""
                )
                .toUpperCase();

        result.comparison_data.forEach(
            row => {

                latestComparisonData.push({
                    ...row,

                    validation_market:
                        row.validation_market ||
                        result.validation_market ||
                        fallbackMarket
                });
            }
        );
    });

    applyFilters();
}

function pollStatus() {
    if (!currentJobId) {
        return;
    }

    fetch(
        `/status/${currentJobId}`
    )
        .then(
            response =>
                response.json()
        )
        .then(data => {

            if (data.results) {

                updateTable(
                    data.results
                );

                renderComparison(
                    data.results
                );
            }

            if (
                data.status !== "completed" &&
                data.status !== "failed"
            ) {
                setTimeout(
                    pollStatus,
                    2000
                );
            }
        })
        .catch(error =>
            console.error(
                "Error polling status:",
                error
            )
        );
}

function loadQueryCatalog() {
    const select =
        document.getElementById(
            "singleQuery"
        );

    const summary =
        document.getElementById(
            "queryCatalogSummary"
        );

    if (!select) {
        return;
    }

    const previousSelection =
        select.value;

    fetch(
        "/query-catalog",
        {
            cache: "no-store"
        }
    )
        .then(
            async response => {

                const data =
                    await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.message ||
                        "Unable to load query catalogue"
                    );
                }

                return data;
            }
        )
        .then(data => {

            const sources =
                Array.isArray(data.sources)
                    ? data.sources
                    : [];

            select.innerHTML = "";

            let total = 0;
            const sourceSummary = [];

            sources.forEach(source => {

                const files =
                    Array.isArray(source.files)
                        ? source.files
                        : [];

                const count =
                    Number.isFinite(
                        Number(source.count)
                    )
                        ? Number(source.count)
                        : files.length;

                total += count;

                sourceSummary.push(
                    `${source.label}: ${count}`
                );

                if (files.length === 0) {
                    return;
                }

                const group =
                    document.createElement(
                        "optgroup"
                    );

                group.label =
                    `${source.label} (${count})`;

                files.forEach(filename => {

                    const option =
                        document.createElement(
                            "option"
                        );

                    option.value =
                        `${source.key}::${filename}`;

                    option.textContent =
                        filename;

                    group.appendChild(
                        option
                    );
                });

                select.appendChild(
                    group
                );
            });

            if (
                select.options.length === 0
            ) {
                const option =
                    document.createElement(
                        "option"
                    );

                option.value = "";

                option.textContent =
                    "No SQL queries discovered";

                select.appendChild(
                    option
                );
            }

            if (previousSelection) {

                const previousOption =
                    [...select.options].find(
                        option =>
                            option.value ===
                            previousSelection
                    );

                if (previousOption) {
                    select.value =
                        previousSelection;
                }
            }

            const totalMetric =
                document.getElementById(
                    "metricTotal"
                );

            if (totalMetric) {
                totalMetric.textContent =
                    total;
            }

            if (summary) {
                summary.textContent =
                    `${total} queries discovered · ${sourceSummary.join(" · ")}`;
            }

            const colleague =
                sources.find(
                    source =>
                        source.key ===
                        "colleague"
                );

            if (
                !colleague ||
                Number(
                    colleague.count || 0
                ) === 0
            ) {
                console.warn(
                    "No Colleague queries discovered by the running API.",
                    colleague
                        ? colleague.folder
                        : "Colleague source missing"
                );
            }
        })
        .catch(error => {

            console.error(
                "Unable to load query catalogue:",
                error
            );

            if (summary) {
                summary.textContent =
                    `Unable to load query catalogue: ${error.message}`;
            }
        });
}

function startJob(payload) {

    fetch(
        "/run-sql",
        {
            method: "POST",
            headers: {
                "Content-Type":
                    "application/json"
            },
            body: JSON.stringify(
                payload
            )
        }
    )
        .then(async response => {

            const data =
                await response.json();

            if (!response.ok) {
                throw new Error(
                    data.message ||
                    "Unable to start query job"
                );
            }

            return data;
        })
        .then(data => {

            currentJobId =
                data.job_id;

            document
                .getElementById(
                    "jobIdLabel"
                )
                .textContent =
                    `Job: ${currentJobId}`;

            document
                .getElementById(
                    "metricComplete"
                )
                .textContent = "0";

            document
                .getElementById(
                    "metricFailed"
                )
                .textContent = "0";

            pollStatus();
        })
        .catch(error => {

            console.error(
                "Error starting SQL job:",
                error
            );

            alert(
                error.message
            );
        });
}

function openContentGenModal() {

    document
        .getElementById(
            "stepDiagnostics"
        )
        .checked = false;

    const message =
        document.getElementById(
            "contentGenMessage"
        );

    message.className =
        "modal-message info";

    message.textContent =
        "Select diagnostics for the full workflow, or leave it off to run ContentGen + Database Upload.";

    message.classList.add(
        "show"
    );

    document
        .getElementById(
            "contentGenRunButton"
        )
        .disabled = false;

    document
        .getElementById(
            "contentGenRunButton"
        )
        .textContent =
            "Run workflow";

    document
        .getElementById(
            "contentGenModal"
        )
        .classList.add(
            "open"
        );
}

function closeContentGenModal() {

    document
        .getElementById(
            "contentGenModal"
        )
        .classList.remove(
            "open"
        );
}

function handleModalBackdrop(event) {

    if (
        event.target.id ===
        "contentGenModal"
    ) {
        closeContentGenModal();
    }
}

function triggerContentGen() {

    const includeDiagnostics =
        document
            .getElementById(
                "stepDiagnostics"
            )
            .checked;

    const button =
        document.getElementById(
            "contentGenRunButton"
        );

    const message =
        document.getElementById(
            "contentGenMessage"
        );

    button.disabled = true;

    button.textContent =
        "Starting...";

    message.className =
        "modal-message info show";

    message.textContent =
        includeDiagnostics
            ? "Starting Diagnostics → ContentGen → Database Upload..."
            : "Starting ContentGen → Database Upload...";

    fetch(
        "/run-contentgen",
        {
            method: "POST",

            headers: {
                "Content-Type":
                    "application/json"
            },

            body: JSON.stringify({
                include_diagnostics:
                    includeDiagnostics
            })
        }
    )
        .then(
            async response => {

                const data =
                    await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.message ||
                        "Unable to start ContentGen workflow"
                    );
                }

                return data;
            }
        )
        .then(data => {

            message.className =
                "modal-message success show";

            message.textContent =
                data.message ||
                "ContentGen workflow accepted.";

            button.textContent =
                "Started";

            setTimeout(
                () => {

                    closeContentGenModal();

                    button.disabled =
                        false;

                    button.textContent =
                        "Run workflow";
                },
                1600
            );
        })
        .catch(error => {

            console.error(
                "Error starting ContentGen workflow:",
                error
            );

            message.className =
                "modal-message error show";

            message.textContent =
                error.message;

            button.disabled = false;

            button.textContent =
                "Run workflow";
        });
}

document.addEventListener(
    "keydown",
    event => {

        if (
            event.key === "Escape"
        ) {
            closeContentGenModal();
        }
    }
);

function runAll() {

    // Explicitly tell the backend that a manual
    // "Run all" means every configured source:
    // Customer + Colleague.

    startJob({
        source: "all"
    });
}

function runOne() {

    const selection =
        document
            .getElementById(
                "singleQuery"
            )
            .value;

    if (!selection) {
        return;
    }

    const separatorIndex =
        selection.indexOf("::");

    if (
        separatorIndex === -1
    ) {
        alert(
            "Unable to determine the query source."
        );

        return;
    }

    const source =
        selection.slice(
            0,
            separatorIndex
        );

    const filename =
        selection.slice(
            separatorIndex + 2
        );

    startJob({
        source: source,
        filename: filename
    });
}

document.addEventListener(
    "DOMContentLoaded",
    () => {

        // Build the single-query dropdown from the
        // running API rather than relying on stale HTML.

        loadQueryCatalog();

        // Start refresh-history polling.
        document.getElementById("refreshHistory").addEventListener("toggle", event => {
            if (event.target.matches(".refresh-item[open]")) loadRefreshDetail(event.target);
        }, true);
        document.getElementById("refreshHistoryOlder").addEventListener("click", loadOlderRefreshes);
        pollRefreshHistory();

        // Refresh the live query catalogue every minute.
        // This also allows newly git-pulled SQL files to
        // appear without restarting/hard-refreshing the browser.

        setInterval(
            loadQueryCatalog,
            60000
        );
    }
);
