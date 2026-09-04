/**
 * Conductor — canonical KPI definition catalog.
 *
 * Reference data for the "KPI Definitions" table in the KPI Studio view
 * (frontend/kpi-studio.js). This is the source-of-truth wording for what each
 * KPI means, its goal, and its unit — separate from the *measured* KPI rows
 * that live in the database and come back from /api/kpis.
 *
 * Shape:
 *   [{ group: 'Catalog', kpis: [{ name, goal, type, definition }, ...] }, ...]
 *
 * `type` is the unit sigil used in the source workbook:
 *   %  percentage      #  count      @  duration (days)     $  currency
 *
 * Notes on fidelity to the source list:
 *   - KPI names are kept VERBATIM, including source typos ("Prdouct Reviews
 *     Removed", "Interal SLA", "Supressions Flagged", "Intitial SLA Missed").
 *     They match labels in the upstream workbook / Asana fields, so silently
 *     correcting them here would break that mapping.
 *   - The redundant leading unit sigil was stripped from each definition
 *     ("% The percentage of…" -> "The percentage of…") because the unit is
 *     already carried in `type`.
 *   - `group` is INFERRED from the row order of the source list, which had no
 *     explicit department column. Several KPI names repeat across groups (for
 *     example "Tasks Created Per Brand" and "Time to Close % to Goal"); the
 *     group is what disambiguates them.
 */
'use strict';

window.ConductorKpiCatalog = Object.freeze([
  {
    group: 'Catalog',
    kpis: [
      { name: 'On Time Completion Rate', goal: '100', type: '%', definition: 'Percentage of all teams meeting their Time to Close.' },
      { name: 'Internal SLA', goal: '', type: '%', definition: 'The count of completed tasks where the field "Intitial SLA Missed" = "Yes".' },
      { name: 'Overdue Tasks % of total', goal: '', type: '%', definition: 'The percentage difference in average time to close (representing actual average time, not a predefined target or goal).' },
      { name: 'Tasks Created Per Brand', goal: '', type: '#', definition: 'The average count of created tasks calculated per active brand.' },
      { name: 'Task Completion Rate', goal: '', type: '%', definition: 'The percentage of tasks completed relative to tasks created.' },
      { name: 'Backlog', goal: '', type: '#', definition: 'The count of open tasks.' },
      { name: 'Listings Created', goal: '', type: '#', definition: 'The count of listings created.' },
      { name: 'Catalog TTC', goal: '', type: '@', definition: 'The average task completion time calculated as completed_at minus created_at.' },
      { name: 'Team % to Goal', goal: '', type: '%', definition: 'The percentage of tasks completed relative to the goal.' },
    ],
  },
  {
    group: 'Cases',
    kpis: [
      { name: 'Cases Created Per Brand', goal: '', type: '#', definition: 'Cases created / active_brands.' },
      { name: 'Cases Closed', goal: '', type: '#', definition: 'The count of completed tasks with Case IDs.' },
      { name: 'Case Time to Close (Days), Created T-3M', goal: '', type: '@', definition: 'The average task completion time calculated as completed_at minus created_at.' },
      { name: 'Time to Close % to Goal', goal: '', type: '%', definition: 'Count of tasks that are passed the SLA (3 days).' },
      { name: 'Overdue Tasks % of total', goal: '', type: '%', definition: 'The percentage difference in average time to close (representing actual average time, not a predefined target or goal).' },
      { name: 'Over Due Tasks', goal: '', type: '#', definition: 'Tasks created within a given time frame.' },
      { name: 'Tasks Created', goal: '', type: '#', definition: 'Tasks created within a given time frame.' },
      { name: '# Open Cases With Initial SLA Missed', goal: '', type: '#', definition: 'The count of completed tasks where the field "Intitial SLA Missed" = "Yes".' },
      { name: 'Cases Won', goal: '', type: '#', definition: 'The total sum of tasks that have at least one case ID.' },
      { name: 'Cases Lost', goal: '', type: '#', definition: 'The count of completed tasks matching the regex search (length 11 characters, starting with 1).' },
    ],
  },
  {
    group: 'Omni-Channel',
    kpis: [
      { name: 'Live Suggestions %', goal: '', type: '%', definition: 'The percentage of live revenue relative to total revenue (calculated as live_revenue / live_revenue + suggested_revenue).' },
      { name: 'Omni Listings Time to Close', goal: '', type: '@', definition: 'The average task completion time calculated as completed_at minus created_at.' },
      { name: 'Time to Close % to Goal', goal: '', type: '%', definition: 'Percentage of tasks that were closed within the time to close goal (2 days for Omni-channel).' },
      { name: 'Tasks Created Per Brand', goal: '', type: '#', definition: 'The average count of created tasks calculated per active brand.' },
      { name: 'Overdue Tasks % of total', goal: '', type: '%', definition: 'The percentage difference in average time to close (representing actual average time, not a predefined target or goal).' },
      { name: 'Over Due Tasks', goal: '', type: '#', definition: 'Count of tasks that were closed past SLA (3 days).' },
      { name: 'Tasks Created', goal: '', type: '#', definition: 'Tasks created.' },
      { name: 'Tasks Completed', goal: '', type: '#', definition: 'The count of completed tasks where the category is listing management.' },
    ],
  },
  {
    group: 'Listing Management',
    kpis: [
      { name: 'Branded Content Created %', goal: '', type: '%', definition: 'The percentage of branded content submitted versus tasks requested (images, A+, brand store, brand story).' },
      { name: 'Branded Content Created #', goal: '', type: '#', definition: 'The count of completed tasks where the task type is branded content submission (images, A+, brand store, brand story).' },
      { name: 'Listing Time to Close', goal: '', type: '@', definition: 'The average task completion time calculated as completed_at minus created_at.' },
      { name: 'Time to Close % to Goal', goal: '', type: '%', definition: 'Percentage of tasks that were closed within the time to close goal (2 days for listing management).' },
      { name: 'Tasks Created Per Brand', goal: '', type: '#', definition: 'The average count of created tasks calculated per active brand.' },
      { name: 'Overdue Tasks % of total', goal: '', type: '%', definition: 'The percentage difference in average time to close (representing actual average time, not a predefined target or goal).' },
      { name: 'Over Due Tasks', goal: '', type: '#', definition: 'Tasks currently overdue.' },
      { name: 'Tasks Created', goal: '', type: '#', definition: 'Tasks created.' },
      { name: 'Tasks Completed', goal: '', type: '#', definition: 'The count of completed tasks where the category is listing management.' },
      { name: 'Branded Content Created', goal: '', type: '%', definition: 'The percentage of branded content submitted versus tasks requested (images, A+, brand store, brand story).' },
    ],
  },
  {
    group: 'FBA & Reimbursements',
    kpis: [
      { name: 'Unfulfillable Units', goal: '', type: '#', definition: 'The count of inventory units dispositioned as unfulfillable at the time of the snapshot report (e.g., Mondays).' },
      { name: 'Unfulfillable Removed units', goal: '', type: '#', definition: 'The count of inventory units dispositioned as unfulfillable that were subsequently removed by Amazon.' },
      { name: 'Unfulfillable Disposed Units', goal: '', type: '#', definition: 'The count of inventory units dispositioned as unfulfillable that were subsequently disposed of by Amazon.' },
      { name: 'Unfulfillable Lost', goal: '', type: '#', definition: 'The count of inventory units previously dispositioned as unfulfillable that currently hold no disposition status.' },
      { name: 'Recovered Units', goal: '', type: '#', definition: 'The count of inventory units that transitioned from a negative disposition (lost, damaged, unfulfillable, etc.) to sellable.' },
      { name: '$ Actual Lost Inbound', goal: '', type: '$', definition: 'The total value of inventory units dispositioned as inbound lost or inbound damaged.' },
      { name: '$ Amount Submitted', goal: '', type: '$', definition: 'The total amount of claims submitted calculated from within each case ID.' },
      { name: '$ Amount Received', goal: '', type: '$', definition: 'The total amount of funds received as detailed in the full report.' },
      { name: 'Inbound Lost Reimbursed Settlement Report', goal: '', type: '$', definition: 'The total amount of funds reimbursed where the unit disposition was inbound lost or inbound damaged.' },
      { name: 'BOLs Missing (1 BOL = Shipment ID)', goal: '', type: '#', definition: 'The count of Bills of Lading (BOLs) originating from DFW that are pending submission.' },
    ],
  },
  {
    group: 'Customer Service',
    kpis: [
      { name: 'On time completetion rate', goal: '', type: '%', definition: 'The percentage of tasks completed on time.' },
      { name: '# Refunds Submitted', goal: '', type: '#', definition: 'The count of refunds submitted originating from brand requests and buyer-seller messages.' },
      { name: '$ Total Refund Amount', goal: '', type: '$', definition: 'The total sum of refunds alongside the average time to close.' },
      { name: 'Time to close', goal: '', type: '#', definition: 'The count of customer reviews that have been successfully removed.' },
      { name: 'Time to Close % to Goal', goal: '', type: '%', definition: 'Percentage of tasks that met the time to close.' },
      { name: 'Prdouct Reviews Removed', goal: '', type: '#', definition: 'The buyer reviews that have been removed from the detail page.' },
      { name: 'Seller Feedback Removed', goal: '', type: '#', definition: 'Total count of seller feedback removed from feedback manager.' },
      { name: 'Overall BM Feedback', goal: '', type: '#', definition: 'The average BM feedback score.' },
    ],
  },
  {
    group: 'EPM & Operations',
    kpis: [
      { name: 'Asana Readiness', goal: '', type: '%', definition: 'The percentage of Asana readiness.' },
      { name: 'Interal SLA', goal: '', type: '%', definition: 'The percentage of tasks completed within the SLA.' },
      { name: 'Task Completed on Time', goal: '', type: '%', definition: 'The percentage of tasks completed on time.' },
      { name: '# of brands per EPM', goal: '', type: '#', definition: 'The average count of active brands calculated per EPM.' },
      { name: '# of created tasks per FTE', goal: '', type: '#', definition: 'The average count of created tasks calculated per FTE.' },
      { name: 'Measuring Effiency', goal: '', type: '#', definition: 'The measurement of efficiency.' },
      { name: 'Supressions Flagged', goal: '', type: '#', definition: 'The count of suppressions flagged.' },
      { name: 'Supressions Resolved', goal: '', type: '#', definition: 'The count of suppressions resolved.' },
    ],
  },
  {
    group: 'Onboarding & Offboarding',
    kpis: [
      { name: 'Pre-Roadmap Deliverable Timeliness', goal: '', type: '%', definition: 'The percentage of pre-roadmap deliverables completed on time.' },
      { name: 'Internal Sync Scheduling Timeliness', goal: '', type: '%', definition: 'The percentage of internal syncs scheduled on time.' },
      { name: 'Meeting-to-Action Conversion Timeliness', goal: '', type: '%', definition: 'The percentage of meeting action items completed on time.' },
      { name: 'System Setup Accuracy & Timeliness', goal: '', type: '%', definition: 'The percentage of system setups completed accurately and on time.' },
      { name: 'Onboarding Graduation Timing Accuracy', goal: '', type: '%', definition: 'The percentage of onboarding graduations completed on time.' },
      { name: 'Tracker & Status Update Compliance', goal: '', type: '%', definition: 'The percentage of tracker and status updates kept in full compliance.' },
      { name: 'Inventory Monitoring Coverage', goal: '', type: '%', definition: 'The percentage of active brand inventory coverage maintained during offboarding.' },
      { name: 'SNS Transfer Completion Timeliness', goal: '', type: '%', definition: 'The percentage of SNS transfers completed on time.' },
      { name: 'Board Closeout Accuracy', goal: '', type: '%', definition: 'The percentage of offboarding boards closed out accurately.' },
      { name: 'SNS Data Pull Timeliness', goal: '', type: '%', definition: 'The percentage of SNS data pulls completed on time.' },
    ],
  },
  {
    group: 'People & Recruiting',
    kpis: [
      { name: '# of Hires YTD', goal: '', type: '#', definition: 'The total count of new hires year-to-date.' },
      { name: '# of Hires MTD', goal: '', type: '#', definition: 'The count of hires month-to-date.' },
      { name: 'Retention Rate YTD', goal: '', type: '%', definition: 'The percentage of employees retained year-to-date.' },
      { name: 'Retention Rate MTD', goal: '', type: '%', definition: 'The percentage of employees retained month-to-date.' },
      { name: 'Time to Close', goal: '', type: '@', definition: 'The average number of days required to fill or close an open role.' },
      { name: '# of Candidates Added to Pipeline', goal: '', type: '#', definition: 'The count of candidates added to the recruitment pipeline.' },
      { name: '# of Hiring Manager Interviews', goal: '', type: '#', definition: 'The total count of interviews conducted by hiring managers.' },
      { name: '# of Open Roles', goal: '', type: '#', definition: 'The count of open job requisitions.' },
      { name: '# of Open Headcount', goal: '', type: '#', definition: 'The count of open headcount.' },
      { name: 'YTD Voluntary turnover', goal: '', type: '%', definition: 'The percentage of voluntary employee turnover year-to-date.' },
      { name: 'MTD Voluntary turnover', goal: '', type: '%', definition: 'The percentage of voluntary employee turnover month-to-date.' },
      { name: 'YTD Non-voluntary turnover', goal: '', type: '%', definition: 'The percentage of non-voluntary turnover year-to-date.' },
      { name: 'MTD Non-voluntary turnover', goal: '', type: '%', definition: 'The percentage of non-voluntary turnover month-to-date.' },
    ],
  },
]);

/** Flattened rows: [{ group, name, goal, type, definition }, ...] */
window.ConductorKpiCatalogRows = Object.freeze(
  window.ConductorKpiCatalog.reduce((rows, section) => rows.concat(
    section.kpis.map((kpi) => Object.freeze(Object.assign({ group: section.group }, kpi)))
  ), [])
);

/** Human labels for the unit sigils used in the `type` column. */
window.ConductorKpiTypeLabels = Object.freeze({
  '%': 'Percentage',
  '#': 'Count',
  '@': 'Duration (days)',
  $: 'Currency',
});
