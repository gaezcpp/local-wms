/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class TaggingDashboard extends Component {
  static template = "tagging_system.TaggingDashboard";

  setup() {
    this.orm = useService("orm");

    // Filters
    this.filters = useState({
      plant_code: "",
      business_unit_code: "",
      status: "",
      date_range: "7d",
    });

    // Options
    this.options = useState({
      plants: [],
      business_units: [],
      date_ranges: [],
      statuses: [],
    });

    // Canvas refs
    this.chartSystemRef = useRef("chartSystem");
    this.chartProblemRef = useRef("chartProblem");
    this.chartTreemapRef = useRef("chartTreemap");

    // State
    this.state = useState({
      metrics: { total: 0, pct_closed: 0, pct_not_valid: 0 },
      by_system: { labels: [], values: [] },
      by_problem: { labels: [], values: [] },
      treemap_abc_system: [],
      abc_table: [],
    });

    // Chart instances
    this._charts = {}; // { system: Chart, problem: Chart, treemap: Chart }

    onWillStart(async () => {
      await this.loadOptions();
      await this.fetchStats(); // render happens after data comes
    });

    onWillUnmount(() => {
      this.destroyAllCharts();
    });
  }

  // -------------------------
  // Load filter options
  // -------------------------
  async loadOptions() {
    try {
      const opt = await this.orm.call("tagging.record", "get_dashboard_filter_options", []);
      this.options.date_ranges = opt.date_ranges || this.options.date_ranges;
      this.options.plants = opt.plants || [];
      this.options.business_units = opt.business_units || [];
      this.options.statuses = opt.statuses || this.options.statuses;
    } catch (e) {
      console.warn("get_dashboard_filter_options fallback", e);
    }
  }

  // -------------------------
  // Fetch stats
  // -------------------------
  async fetchStats() {
    const payload = { ...this.filters };
    const res = await this.orm.call("tagging.record", "get_dashboard_stats", [payload]);

    this.state.metrics = res.metrics || this.state.metrics;
    this.state.by_system = res.by_system || { labels: [], values: [] };
    this.state.by_problem = res.by_problem || { labels: [], values: [] };
    this.state.treemap_abc_system = res.treemap_abc_system || [];
    this.state.abc_table = res.abc_table || [];

    this.renderAll(true);
  }

  // -------------------------
  // Events
  // -------------------------
  onPlantChange = async (ev) => {
    this.filters.plant_code = ev.target.value;
    await this.fetchStats();
  };

  onBUChange = async (ev) => {
    this.filters.business_unit_code = ev.target.value;
    await this.fetchStats();
  };

  onStatusChange = async (ev) => {
    this.filters.status = ev.target.value;
    await this.fetchStats();
  };

  onDateRangeChange = async (ev) => {
    this.filters.date_range = ev.target.value;
    await this.fetchStats();
  };

  // -------------------------
  // Chart helpers
  // -------------------------
  ensureChart() {
    if (!window.Chart) {
      console.error("Chart.js not loaded");
      return false;
    }
    return true;
  }

  isTreemapReady() {
    try {
      return !!window.Chart?.registry?.controllers?.get("treemap");
    } catch (e) {
      return false;
    }
  }

  destroyChart(key) {
    if (this._charts[key]) {
      try {
        this._charts[key].destroy();
      } catch (e) {
        console.warn("Destroy chart failed", key, e);
      }
      delete this._charts[key];
    }
  }

  destroyAllCharts() {
    Object.keys(this._charts).forEach((k) => this.destroyChart(k));
    this._charts = {};
  }

  renderAll(recreate) {
    if (!this.ensureChart()) return;

    if (recreate) {
      this.destroyChart("system");
      this.destroyChart("problem");
      this.destroyChart("treemap");
    }

    this.renderBar("system", this.chartSystemRef.el, this.state.by_system);
    this.renderBar("problem", this.chartProblemRef.el, this.state.by_problem);
    this.renderTreemap("treemap", this.chartTreemapRef.el, this.state.treemap_abc_system);
  }

  renderBar(key, el, data) {
    if (!el) return;

    const labels = data?.labels || [];
    const values = data?.values || [];

    // Skip if no data (biar gak grid kosong doang)
    if (!labels.length) return;

    this._charts[key] = new window.Chart(el, {
      type: "bar",
      data: {
        labels,
        datasets: [{ label: "Total", data: values }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            ticks: { color: "#374151", maxRotation: 0, autoSkip: true },
            grid: { color: "rgba(0,0,0,0.06)" },
          },
          y: {
            beginAtZero: true,
            ticks: { color: "#374151" },
            grid: { color: "rgba(0,0,0,0.06)" },
          },
        },
      },
    });
  }

  renderTreemap(key, el, nodes) {
    if (!el) return;

    // Skip if plugin not ready
    if (!this.isTreemapReady()) {
      console.warn("Treemap plugin not loaded yet");
      return;
    }

    // Skip if no data
    if (!(nodes || []).length) return;

    this._charts[key] = new window.Chart(el, {
      type: "treemap",
      data: {
        datasets: [
          {
            tree: nodes,
            key: "value",
            groups: ["group"],
            spacing: 1,
            borderWidth: 1,
            label: {
              display: true,
              formatter: (ctx) => {
                const item = ctx.raw?._data || ctx.raw;
                const lbl = item?.label || "";
                const val = item?.value ?? "";
                return `${lbl}\n${val}`;
              },
              color: "#111",
              font: { size: 11, weight: "600" },
            },
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
      },
    });
  }
}

registry.category("actions").add("tagging_system.tagging_dashboard", TaggingDashboard);
