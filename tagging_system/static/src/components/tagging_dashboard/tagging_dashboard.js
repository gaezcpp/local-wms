/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class TaggingDashboard extends Component {
  static template = "tagging_system.TaggingDashboard";

  setup() {
    // Services
    this.orm = useService("orm");

    // Refs (pastikan di template ada t-ref yang sama)
    this.chartSystemRef = useRef("chartSystem");
    this.chartProblemRef = useRef("chartProblem");
    this.chartTreemapRef = useRef("chartTreemap");

    // Charts holder
    this._charts = {};

    // UI Filters (yang kamu kirim ke backend)
    this.filters = useState({
      date_range: "7d",      // today | 7d | 30d | all | custom
      date_from: null,       // YYYY-MM-DD (dipakai kalau custom / today)
      date_to: null,         // YYYY-MM-DD (dipakai kalau custom / today)

      plant_code: null,
      business_unit_code: null,
      status: null,
    });

    // Options untuk dropdown
    this.options = useState({
      date_ranges: [
        { key: "today", label: "Today" },
        { key: "7d", label: "Last 7 days" },
        { key: "30d", label: "Last 30 days" },
        { key: "all", label: "All time" },
        { key: "custom", label: "Custom…" },
      ],
      plants: [],
      business_units: [],
      statuses: [
        { key: "all", label: "All" },
        { key: "open", label: "Open" },
        { key: "closed", label: "Closed" },
        { key: "not_valid", label: "Not Valid" },
      ],
    });

    // Data dashboard (yang kamu render)
    this.state = useState({
      metrics: {
        total: 0,
        closed_pct: 0,
        not_valid_pct: 0,
      },
      by_system: { labels: [], values: [] },
      by_problem: { labels: [], values: [] },
      treemap_abc_system: [],
      abc_table: [],
    });

    // Initial load
    onWillStart(async () => {
      await this.loadOptions();
      this.applyPresetToDates(this.filters.date_range);
      await this.fetchStats();
    });

    // Cleanup
    onWillUnmount(() => {
      this.destroyAllCharts();
    });
  }

  // ------------------------------------------------------------
  // Helpers: Date preset -> date_from/date_to
  // ------------------------------------------------------------
  applyPresetToDates(key) {
    const today = (window.luxon?.DateTime?.local?.() || null);

    // kalau luxon ga ada, fallback: pakai Date native (minimal)
    const toISODate = (d) => {
      const pad = (n) => `${n}`.padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    };

    const nativeToday = new Date();

    const setNativeMinusDays = (days) => {
      const d = new Date(nativeToday);
      d.setDate(d.getDate() - days);
      return d;
    };

    if (key === "today") {
      if (today) {
        this.filters.date_from = today.toISODate();
        this.filters.date_to = today.toISODate();
      } else {
        const d = toISODate(nativeToday);
        this.filters.date_from = d;
        this.filters.date_to = d;
      }
      return;
    }

    if (key === "7d") {
      // last 7 days inclusive
      if (today) {
        this.filters.date_from = today.minus({ days: 6 }).toISODate();
        this.filters.date_to = today.toISODate();
      } else {
        this.filters.date_from = toISODate(setNativeMinusDays(6));
        this.filters.date_to = toISODate(nativeToday);
      }
      return;
    }

    if (key === "30d") {
      if (today) {
        this.filters.date_from = today.minus({ days: 29 }).toISODate();
        this.filters.date_to = today.toISODate();
      } else {
        this.filters.date_from = toISODate(setNativeMinusDays(29));
        this.filters.date_to = toISODate(nativeToday);
      }
      return;
    }

    if (key === "all") {
      // backend bisa treat all sebagai no filter; set null biar jelas
      this.filters.date_from = null;
      this.filters.date_to = null;
      return;
    }

    if (key === "custom") {
      // user isi manual, jangan diubah
      // tapi kalau kosong, kasih default biar input enak
      if (!this.filters.date_from || !this.filters.date_to) {
        if (today) {
          this.filters.date_from = today.toISODate();
          this.filters.date_to = today.toISODate();
        } else {
          const d = toISODate(nativeToday);
          this.filters.date_from = d;
          this.filters.date_to = d;
        }
      }
    }
  }

  // ------------------------------------------------------------
  // Load filter options from backend (optional)
  // ------------------------------------------------------------
  async loadOptions() {
    try {
      const opt = await this.orm.call("tagging.record", "get_dashboard_filter_options", []);

      const fallbackRanges = [
        { key: "today", label: "Today" },
        { key: "7d", label: "Last 7 days" },
        { key: "30d", label: "Last 30 days" },
      ];

      const serverRanges = Array.isArray(opt?.date_ranges) ? opt.date_ranges : fallbackRanges;

      // pastikan custom selalu ada
      const hasCustom = serverRanges.some((r) => r.key === "custom");
      this.options.date_ranges = hasCustom
        ? serverRanges
        : [...serverRanges, { key: "custom", label: "Custom…" }];

      this.options.plants = opt?.plants || [];
      this.options.business_units = opt?.business_units || [];
      this.options.statuses = opt?.statuses || this.options.statuses;
    } catch (e) {
      console.warn("get_dashboard_filter_options fallback", e);
      // fallback pun tetap pastikan custom ada
      const hasCustom = this.options.date_ranges.some((r) => r.key === "custom");
      if (!hasCustom) this.options.date_ranges.push({ key: "custom", label: "Custom…" });
    }
  }


  // ------------------------------------------------------------
  // Fetch stats from backend
  // ------------------------------------------------------------
  async fetchStats() {
    const payload = { ...this.filters };

    // Kalau preset bukan custom, aman juga walaupun backend mau hitung sendiri.
    // Tapi untuk konsisten, kita selalu kirim date_from/date_to sesuai preset.
    // Untuk 'all', date_from/date_to = null.

    const res = await this.orm.call("tagging.record", "get_dashboard_stats", [payload]);

    this.state.metrics = res?.metrics || this.state.metrics;
    this.state.by_system = res?.by_system || { labels: [], values: [] };
    this.state.by_problem = res?.by_problem || { labels: [], values: [] };
    this.state.treemap_abc_system = res?.treemap_abc_system || [];
    this.state.abc_table = res?.abc_table || [];

    this.renderAll(true);
  }

  // ------------------------------------------------------------
  // Events: filters
  // ------------------------------------------------------------
  onPlantChange = async (ev) => {
    this.filters.plant_code = ev.target.value || null;
    await this.fetchStats();
  };

  onBUChange = async (ev) => {
    this.filters.business_unit_code = ev.target.value || null;
    await this.fetchStats();
  };

  onStatusChange = async (ev) => {
    const v = ev.target.value;
    this.filters.status = (!v || v === "all") ? null : v;
    await this.fetchStats();
  };

  onDateRangeChange = async (ev) => {
    const key = ev.target.value;
    this.filters.date_range = key;

    // Set date_from/to for non-custom presets
    if (key !== "custom") {
      this.applyPresetToDates(key);
      await this.fetchStats();
      return;
    }

    // custom: biarkan user pilih, jangan fetch otomatis
    this.applyPresetToDates("custom");
  };

  onFromDateChange = (ev) => {
    this.testsafeSetDate("date_from", ev.target.value);
  };

  onToDateChange = (ev) => {
    this.testsafeSetDate("date_to", ev.target.value);
  };

  // helper: set date safely
  testsafeSetDate(field, value) {
    // value expected YYYY-MM-DD
    this.filters[field] = value || null;
  }

  applyCustomRange = async () => {
    if (this.filters.date_range !== "custom") return;

    const from = this.filters.date_from;
    const to = this.filters.date_to;

    if (!from || !to) return;
    if (from > to) return;

    await this.fetchStats();
  };

  // ------------------------------------------------------------
  // Chart helpers
  // ------------------------------------------------------------
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
    if (this._charts?.[key]) {
      try {
        this._charts[key].destroy();
      } catch (e) {
        console.warn("Destroy chart failed", key, e);
      }
      delete this._charts[key];
    }
  }

  destroyAllCharts() {
    Object.keys(this._charts || {}).forEach((k) => this.destroyChart(k));
    this._charts = {};
  }

  renderAll(recreate) {
    if (!this.ensureChart()) return;

    if (recreate) {
      this.destroyChart("system");
      this.destroyChart("problem");
      this.destroyChart("treemap");
    }

    // NOTE: Pastikan canvas element ada (t-ref) sebelum render
    this.renderBar("system", this.chartSystemRef?.el, this.state.by_system);
    this.renderBar("problem", this.chartProblemRef?.el, this.state.by_problem);
    this.renderTreemap("treemap", this.chartTreemapRef?.el, this.state.treemap_abc_system);
  }

  renderBar(key, el, data) {
    if (!el) return;

    const labels = data?.labels || [];
    const values = data?.values || [];

    // Kalau ga ada data, destroy chart lama biar kosong bersih
    if (!labels.length) {
      this.destroyChart(key);
      return;
    }

    this.destroyChart(key);

    this._charts[key] = new window.Chart(el, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Total",
            data: values,
            backgroundColor: "#f59e0b",
            borderRadius: 8,
          },
        ],
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
    if (!this.ensureChart()) return;
  
    if (!this.isTreemapReady()) {
      console.warn("Treemap plugin not loaded yet");
      return;
    }
  
    const dataNodes = Array.isArray(nodes) ? nodes : [];
    if (!dataNodes.length) {
      this.destroyChart(key);
      return;
    }
  
    const getNode = (raw) => raw?._data || raw || {};
    const isLeaf = (raw) => {
      const n = getNode(raw);
      return typeof n.value !== "undefined" && !!n.label; // leaf punya label + value
    };
  
    const twoLine = (s, n = 22) => {
      const str = (s ?? "").toString().trim();
      if (!str) return ["Others"];
      if (str.length <= n) return [str];
      return [str.slice(0, n) + "…"];
    };
  
    this.destroyChart(key);
  
    this._charts[key] = new window.Chart(el, {
      type: "treemap",
      data: {
        datasets: [
          {
            tree: dataNodes,
            key: "value",
            groups: ["group", "system"],
            spacing: 2,
            borderWidth: 1,
            borderColor: "rgba(17,24,39,0.15)",
            labels: {
              display: true,
              formatter: (ctx) => {
                const item = getNode(ctx.raw);
    
                // leaf pasti punya system
                if (!item.system) return "";
    
                const sys = item.system || "Others";
                const val = item.value ?? 0;
                const sysLine = twoLine(sys, 22).join("\n");
                return `${sysLine}\n${val}`;
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
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => {
                const n = getNode(items?.[0]?.raw);
                return `ABC: ${n.group || "Others"}`;
              },
              label: (item) => {
                const n = getNode(item?.raw);
                if (!n.system) return "";
                return `System: ${n.system} • Total: ${n.value ?? 0}`;
              },
            },
          },
        },
      },
    });
    
  }
  

}

registry.category("actions").add("tagging_system.tagging_dashboard", TaggingDashboard);
