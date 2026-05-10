import * as api from "./api.js";

// ---------- tiny DOM helper ----------
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function")
      el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k in el) el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

function setApp(...nodes) {
  const app = document.getElementById("app");
  clear(app);
  for (const n of nodes) app.append(n);
}

function showError(err) {
  console.error(err);
  const msg =
    err instanceof api.ApiError
      ? `Error ${err.status}: ${typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail)}`
      : err?.message || String(err);
  return h("div", { class: "error" }, msg);
}

// ---------- router ----------
const routes = [];

function route(pattern, render) {
  // pattern like "/experiments/:id" — compiled to regex with named groups
  const names = [];
  const rx = new RegExp(
    "^" +
      pattern.replace(/:[a-zA-Z]+/g, (m) => {
        names.push(m.slice(1));
        return "([^/]+)";
      }) +
      "/?$"
  );
  routes.push({ rx, names, render });
}

async function renderRoute() {
  const hash = location.hash.replace(/^#/, "") || "/experiments";
  const auth = !!api.token.get();
  if (!auth && hash !== "/login" && hash !== "/register") {
    location.hash = "#/login";
    return;
  }
  renderNav(auth);
  for (const r of routes) {
    const m = hash.match(r.rx);
    if (m) {
      const params = Object.fromEntries(r.names.map((n, i) => [n, m[i + 1]]));
      try {
        await r.render(params);
      } catch (err) {
        setApp(showError(err));
      }
      return;
    }
  }
  setApp(h("div", { class: "card" }, "Not found"));
}

window.addEventListener("hashchange", renderRoute);
window.addEventListener("DOMContentLoaded", renderRoute);

// ---------- navbar ----------
async function renderNav(authed) {
  const right = document.getElementById("nav-right");
  clear(right);
  if (!authed) {
    right.append(
      h("a", { href: "#/login" }, "Log in"),
      h("a", { href: "#/register" }, "Register")
    );
    return;
  }
  try {
    const user = await api.me();
    right.append(
      h("span", { class: "user" }, user.username),
      h(
        "button",
        {
          class: "btn btn-ghost",
          onClick: () => {
            api.logout();
            location.hash = "#/login";
          },
        },
        "Log out"
      )
    );
  } catch {
    api.logout();
    location.hash = "#/login";
  }
}

// ---------- auth pages ----------
route("/login", () => {
  const errBox = h("div");
  const form = h(
    "form",
    {
      class: "card form",
      onSubmit: async (e) => {
        e.preventDefault();
        clear(errBox);
        try {
          await api.login(form.username.value, form.password.value);
          location.hash = "#/experiments";
        } catch (err) {
          errBox.append(showError(err));
        }
      },
    },
    h("h1", {}, "Log in"),
    errBox,
    h("label", {}, "Username", h("input", { name: "username", required: true })),
    h(
      "label",
      {},
      "Password",
      h("input", { name: "password", type: "password", required: true })
    ),
    h("button", { class: "btn btn-primary", type: "submit" }, "Log in"),
    h("p", { class: "muted" }, "No account? ", h("a", { href: "#/register" }, "Register"))
  );
  setApp(form);
});

route("/register", () => {
  const errBox = h("div");
  const form = h(
    "form",
    {
      class: "card form",
      onSubmit: async (e) => {
        e.preventDefault();
        clear(errBox);
        try {
          await api.register(form.username.value, form.email.value, form.password.value);
          await api.login(form.username.value, form.password.value);
          location.hash = "#/experiments";
        } catch (err) {
          errBox.append(showError(err));
        }
      },
    },
    h("h1", {}, "Register"),
    errBox,
    h("label", {}, "Username", h("input", { name: "username", required: true, minLength: 3 })),
    h("label", {}, "Email", h("input", { name: "email", type: "email", required: true })),
    h(
      "label",
      {},
      "Password",
      h("input", { name: "password", type: "password", required: true, minLength: 6 })
    ),
    h("button", { class: "btn btn-primary", type: "submit" }, "Create account"),
    h("p", { class: "muted" }, "Have an account? ", h("a", { href: "#/login" }, "Log in"))
  );
  setApp(form);
});

// ---------- experiments list ----------
route("/experiments", async () => {
  const experiments = await api.listExperiments();
  const list = h("div", { class: "list" });

  function repaint(items) {
    clear(list);
    if (items.length === 0) {
      list.append(h("div", { class: "muted" }, "No experiments yet."));
      return;
    }
    for (const e of items) {
      list.append(
        h(
          "div",
          { class: "list-row" },
          h(
            "a",
            { href: `#/experiments/${e.experiment_id}`, class: "list-title" },
            e.title
          ),
          h("div", { class: "muted" }, e.description || "—"),
          h(
            "button",
            {
              class: "btn btn-danger",
              onClick: async () => {
                if (!confirm(`Delete experiment "${e.title}"?`)) return;
                await api.deleteExperiment(e.experiment_id);
                const rest = items.filter((x) => x.experiment_id !== e.experiment_id);
                repaint(rest);
              },
            },
            "Delete"
          )
        )
      );
    }
  }
  repaint(experiments);

  const form = h(
    "form",
    {
      class: "inline-form",
      onSubmit: async (ev) => {
        ev.preventDefault();
        const created = await api.createExperiment({
          title: form.title.value,
          description: form.description.value || null,
        });
        form.reset();
        experiments.unshift(created);
        repaint(experiments);
      },
    },
    h("input", { name: "title", placeholder: "Experiment title", required: true }),
    h("input", { name: "description", placeholder: "Description (optional)" }),
    h("button", { class: "btn btn-primary", type: "submit" }, "Add")
  );

  setApp(
    h("h1", {}, "My experiments"),
    h("div", { class: "card" }, form),
    h("div", { class: "card" }, list)
  );
});

// ---------- experiment detail ----------
route("/experiments/:id", async ({ id }) => {
  const exp = await api.getExperiment(id);
  const runs = await api.listRuns(id);

  const titleInput = h("input", { value: exp.title, required: true });
  const descInput = h("textarea", { rows: 3 }, exp.description || "");
  const meta = h("div", { class: "muted" }, `Created ${new Date(exp.created_at).toLocaleString()}`);

  const saveBtn = h(
    "button",
    {
      class: "btn btn-primary",
      onClick: async () => {
        await api.updateExperiment(id, {
          title: titleInput.value,
          description: descInput.value || null,
        });
      },
    },
    "Save"
  );
  const deleteBtn = h(
    "button",
    {
      class: "btn btn-danger",
      onClick: async () => {
        if (!confirm("Delete this experiment and all runs?")) return;
        await api.deleteExperiment(id);
        location.hash = "#/experiments";
      },
    },
    "Delete experiment"
  );

  const runsList = h("div", { class: "list" });
  function paintRuns(items) {
    clear(runsList);
    if (items.length === 0) {
      runsList.append(h("div", { class: "muted" }, "No runs yet."));
      return;
    }
    for (const r of items) {
      runsList.append(
        h(
          "div",
          { class: "list-row" },
          h(
            "a",
            { href: `#/runs/${r.run_id}`, class: "list-title" },
            `#${r.run_number} — ${r.name}`
          ),
          h("div", { class: "muted" }, r.description || "—"),
          h(
            "button",
            {
              class: "btn btn-danger",
              onClick: async () => {
                if (!confirm(`Delete run "${r.name}"?`)) return;
                await api.deleteRun(r.run_id);
                paintRuns(items.filter((x) => x.run_id !== r.run_id));
              },
            },
            "Delete"
          )
        )
      );
    }
  }
  paintRuns(runs);

  const runForm = h(
    "form",
    {
      class: "inline-form",
      onSubmit: async (ev) => {
        ev.preventDefault();
        const created = await api.createRun(id, {
          name: runForm.name.value,
          description: runForm.description.value || null,
        });
        runForm.reset();
        runs.push(created);
        paintRuns(runs);
      },
    },
    h("input", { name: "name", placeholder: "Run name", required: true }),
    h("input", { name: "description", placeholder: "Description (optional)" }),
    h("button", { class: "btn btn-primary", type: "submit" }, "Add run")
  );

  setApp(
    h(
      "div",
      { class: "crumbs" },
      h("a", { href: "#/experiments" }, "← Experiments")
    ),
    h(
      "div",
      { class: "card form" },
      h("h1", {}, "Experiment"),
      meta,
      h("label", {}, "Title", titleInput),
      h("label", {}, "Description", descInput),
      h("div", { class: "row-gap" }, saveBtn, deleteBtn)
    ),
    h("h2", {}, "Runs"),
    h("div", { class: "card" }, runForm),
    h("div", { class: "card" }, runsList)
  );
});

// ---------- run detail ----------
route("/runs/:id", async ({ id }) => {
  const run = await api.getRun(id);
  const [series, images, reports] = await Promise.all([
    api.listSeries(id),
    api.listRunImages(id),
    api.listReports(id),
  ]);

  const nameInput = h("input", { value: run.name, required: true });
  const descInput = h("textarea", { rows: 3 }, run.description || "");

  const saveBtn = h(
    "button",
    {
      class: "btn btn-primary",
      onClick: async () => {
        await api.updateRun(id, {
          name: nameInput.value,
          description: descInput.value || null,
        });
      },
    },
    "Save"
  );
  const deleteBtn = h(
    "button",
    {
      class: "btn btn-danger",
      onClick: async () => {
        if (!confirm("Delete this run?")) return;
        await api.deleteRun(id);
        location.hash = `#/experiments/${run.experiment_id}`;
      },
    },
    "Delete run"
  );

  // Series section
  const seriesList = h("div", { class: "list" });
  function paintSeries(items) {
    clear(seriesList);
    if (items.length === 0) {
      seriesList.append(h("div", { class: "muted" }, "No series yet."));
      return;
    }
    for (const s of items) {
      seriesList.append(
        h(
          "div",
          { class: "list-row" },
          h("a", { href: `#/series/${s.series_id}`, class: "list-title" }, s.series_name),
          h(
            "div",
            { class: "muted" },
            [s.unit_x && `x: ${s.unit_x}`, s.unit_y && `y: ${s.unit_y}`]
              .filter(Boolean)
              .join(" · ") || "—"
          ),
          h(
            "button",
            {
              class: "btn btn-danger",
              onClick: async () => {
                if (!confirm(`Delete series "${s.series_name}"?`)) return;
                await api.deleteSeries(s.series_id);
                paintSeries(items.filter((x) => x.series_id !== s.series_id));
              },
            },
            "Delete"
          )
        )
      );
    }
  }
  paintSeries(series);

  const seriesForm = h(
    "form",
    {
      class: "inline-form",
      onSubmit: async (ev) => {
        ev.preventDefault();
        const created = await api.createSeries(id, {
          series_name: seriesForm.series_name.value,
          unit_x: seriesForm.unit_x.value || null,
          unit_y: seriesForm.unit_y.value || null,
          description: null,
        });
        seriesForm.reset();
        series.push(created);
        paintSeries(series);
      },
    },
    h("input", { name: "series_name", placeholder: "Series name", required: true }),
    h("input", { name: "unit_x", placeholder: "x unit" }),
    h("input", { name: "unit_y", placeholder: "y unit" }),
    h("button", { class: "btn btn-primary", type: "submit" }, "Add series")
  );

  // Images section
  const imageGrid = h("div", { class: "image-grid" });
  function paintImages(items) {
    clear(imageGrid);
    if (items.length === 0) {
      imageGrid.append(h("div", { class: "muted" }, "No images yet."));
      return;
    }
    for (const img of items) {
      imageGrid.append(
        h(
          "div",
          { class: "image-tile" },
          h("a", { href: img.url, target: "_blank" }, h("img", { src: img.url, alt: "" })),
          h(
            "button",
            {
              class: "btn btn-danger btn-sm",
              onClick: async () => {
                if (!confirm("Delete image?")) return;
                await api.deleteRunImage(id, img.file_id);
                paintImages(items.filter((x) => x.file_id !== img.file_id));
              },
            },
            "Delete"
          )
        )
      );
    }
  }
  paintImages(images);

  const fileInput = h("input", { type: "file", accept: "image/*" });
  const uploadBtn = h(
    "button",
    {
      class: "btn btn-primary",
      onClick: async () => {
        if (!fileInput.files[0]) return;
        await api.uploadRunImage(id, fileInput.files[0]);
        const refreshed = await api.listRunImages(id);
        paintImages(refreshed);
        fileInput.value = "";
      },
    },
    "Upload image"
  );

  // Reports section
  const reportsList = h("div", { class: "list" });
  function paintReports(items) {
    clear(reportsList);
    if (items.length === 0) {
      reportsList.append(h("div", { class: "muted" }, "No reports yet."));
      return;
    }
    for (const r of items) {
      reportsList.append(
        h(
          "div",
          { class: "list-row" },
          h("a", { href: `#/reports/${r.report_id}`, class: "list-title" }, r.title),
          h("div", { class: "muted" }, new Date(r.created_at).toLocaleString()),
          h(
            "button",
            {
              class: "btn btn-danger",
              onClick: async () => {
                if (!confirm(`Delete report "${r.title}"?`)) return;
                await api.deleteReport(r.report_id);
                paintReports(items.filter((x) => x.report_id !== r.report_id));
              },
            },
            "Delete"
          )
        )
      );
    }
  }
  paintReports(reports);

  const reportForm = h(
    "form",
    {
      class: "inline-form",
      onSubmit: async (ev) => {
        ev.preventDefault();
        const created = await api.createReport(id, { title: reportForm.title.value });
        reportForm.reset();
        reports.unshift(created);
        paintReports(reports);
      },
    },
    h("input", { name: "title", placeholder: "Report title", required: true }),
    h("button", { class: "btn btn-primary", type: "submit" }, "Add report")
  );

  setApp(
    h(
      "div",
      { class: "crumbs" },
      h("a", { href: `#/experiments/${run.experiment_id}` }, "← Experiment")
    ),
    h(
      "div",
      { class: "card form" },
      h("h1", {}, `Run #${run.run_number}`),
      h("label", {}, "Name", nameInput),
      h("label", {}, "Description", descInput),
      h("div", { class: "row-gap" }, saveBtn, deleteBtn)
    ),
    h("h2", {}, "Data series"),
    h("div", { class: "card" }, seriesForm),
    h("div", { class: "card" }, seriesList),
    h("h2", {}, "Images"),
    h("div", { class: "card" }, h("div", { class: "row-gap" }, fileInput, uploadBtn)),
    h("div", { class: "card" }, imageGrid),
    h("h2", {}, "Reports"),
    h("div", { class: "card" }, reportForm),
    h("div", { class: "card" }, reportsList)
  );
});

// ---------- series detail ----------
route("/series/:id", async ({ id }) => {
  const series = await api.getSeries(id);
  const [points, plot] = await Promise.all([
    api.listPoints(id),
    api.getSeriesPlot(id),
  ]);

  const nameInput = h("input", { value: series.series_name, required: true });
  const unitXInput = h("input", { value: series.unit_x || "" });
  const unitYInput = h("input", { value: series.unit_y || "" });
  const descInput = h("textarea", { rows: 2 }, series.description || "");

  const saveBtn = h(
    "button",
    {
      class: "btn btn-primary",
      onClick: async () => {
        await api.updateSeries(id, {
          series_name: nameInput.value,
          unit_x: unitXInput.value || null,
          unit_y: unitYInput.value || null,
          description: descInput.value || null,
        });
      },
    },
    "Save"
  );
  const deleteBtn = h(
    "button",
    {
      class: "btn btn-danger",
      onClick: async () => {
        if (!confirm("Delete this series?")) return;
        await api.deleteSeries(id);
        location.hash = `#/runs/${series.run_id}`;
      },
    },
    "Delete series"
  );

  // Plot section
  const plotBox = h("div", { class: "plot-box" });
  function paintPlot(file) {
    clear(plotBox);
    if (file) {
      plotBox.append(h("img", { src: file.url, alt: "plot" }));
    } else {
      plotBox.append(
        h("div", { class: "muted" }, "No plot yet. Add points and click Generate plot.")
      );
    }
  }
  paintPlot(plot);

  const plotBtn = h(
    "button",
    {
      class: "btn btn-primary",
      onClick: async () => {
        try {
          await api.generatePlot(id);
          const fresh = await api.getSeriesPlot(id);
          paintPlot(fresh);
        } catch (err) {
          alert(err.message);
        }
      },
    },
    "Generate / refresh plot"
  );

  // Points table
  const pointsTable = h("table", { class: "points-table" });
  function paintPoints(items) {
    clear(pointsTable);
    pointsTable.append(
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", {}, "#"),
          h("th", {}, `x${series.unit_x ? ` (${series.unit_x})` : ""}`),
          h("th", {}, `y${series.unit_y ? ` (${series.unit_y})` : ""}`),
          h("th", {}, "σx"),
          h("th", {}, "σy"),
          h("th", {}, "")
        )
      )
    );
    const tbody = h("tbody");
    for (const p of items) {
      tbody.append(
        h(
          "tr",
          {},
          h("td", {}, p.measurement_order),
          h("td", {}, p.x_value),
          h("td", {}, p.y_value),
          h("td", {}, p.x_uncertainty ?? ""),
          h("td", {}, p.y_uncertainty ?? ""),
          h(
            "td",
            {},
            h(
              "button",
              {
                class: "btn btn-danger btn-sm",
                onClick: async () => {
                  await api.deletePoint(p.point_id);
                  paintPoints(items.filter((x) => x.point_id !== p.point_id));
                },
              },
              "×"
            )
          )
        )
      );
    }
    pointsTable.append(tbody);
  }
  paintPoints(points);

  const nextOrder = () => (points.length ? Math.max(...points.map((p) => p.measurement_order)) + 1 : 1);
  const orderInput = h("input", { type: "number", min: 1, value: nextOrder(), required: true });
  const xInput = h("input", { type: "number", step: "any", required: true });
  const yInput = h("input", { type: "number", step: "any", required: true });
  const xeInput = h("input", { type: "number", step: "any", min: 0 });
  const yeInput = h("input", { type: "number", step: "any", min: 0 });

  const pointForm = h(
    "form",
    {
      class: "point-form",
      onSubmit: async (ev) => {
        ev.preventDefault();
        const data = {
          measurement_order: Number(orderInput.value),
          x_value: Number(xInput.value),
          y_value: Number(yInput.value),
          x_uncertainty: xeInput.value === "" ? null : Number(xeInput.value),
          y_uncertainty: yeInput.value === "" ? null : Number(yeInput.value),
        };
        try {
          const created = await api.addPoint(id, data);
          points.push(created);
          points.sort((a, b) => a.measurement_order - b.measurement_order);
          paintPoints(points);
          pointForm.reset();
          orderInput.value = nextOrder();
        } catch (err) {
          alert(err.message);
        }
      },
    },
    h("label", {}, "order", orderInput),
    h("label", {}, "x", xInput),
    h("label", {}, "y", yInput),
    h("label", {}, "σx", xeInput),
    h("label", {}, "σy", yeInput),
    h("button", { class: "btn btn-primary", type: "submit" }, "Add point")
  );

  setApp(
    h(
      "div",
      { class: "crumbs" },
      h("a", { href: `#/runs/${series.run_id}` }, "← Run")
    ),
    h(
      "div",
      { class: "card form" },
      h("h1", {}, "Series"),
      h("label", {}, "Name", nameInput),
      h(
        "div",
        { class: "grid-2" },
        h("label", {}, "x unit", unitXInput),
        h("label", {}, "y unit", unitYInput)
      ),
      h("label", {}, "Description", descInput),
      h("div", { class: "row-gap" }, saveBtn, deleteBtn)
    ),
    h("h2", {}, "Plot"),
    h("div", { class: "card" }, h("div", { class: "row-gap" }, plotBtn), plotBox),
    h("h2", {}, "Data points"),
    h("div", { class: "card" }, pointForm),
    h("div", { class: "card" }, pointsTable)
  );
});

// ---------- report detail ----------
route("/reports/:id", async ({ id }) => {
  const report = await api.getReport(id);
  const [source, pdf, attachments] = await Promise.all([
    api.getReportSource(id),
    api.getReportPdf(id),
    api.listAttachments(id),
  ]);

  const titleInput = h("input", { value: report.title, required: true });
  const saveBtn = h(
    "button",
    {
      class: "btn btn-primary",
      onClick: async () => {
        await api.updateReport(id, { title: titleInput.value });
      },
    },
    "Save"
  );
  const deleteBtn = h(
    "button",
    {
      class: "btn btn-danger",
      onClick: async () => {
        if (!confirm("Delete this report?")) return;
        await api.deleteReport(id);
        location.hash = `#/runs/${report.run_id}`;
      },
    },
    "Delete report"
  );

  function fileCard(label, currentFile, acceptExt, uploader, linkLabel) {
    const box = h("div");
    const fileInput = h("input", { type: "file", accept: acceptExt });
    function paint(file) {
      clear(box);
      if (file) {
        box.append(h("a", { href: file.url, target: "_blank" }, `${linkLabel} (${file.size_bytes} bytes)`));
      } else {
        box.append(h("span", { class: "muted" }, "Not uploaded."));
      }
    }
    paint(currentFile);
    const btn = h(
      "button",
      {
        class: "btn btn-primary",
        onClick: async () => {
          if (!fileInput.files[0]) return;
          const res = await uploader(id, fileInput.files[0]);
          paint(res);
          fileInput.value = "";
        },
      },
      "Upload"
    );
    return h(
      "div",
      { class: "card" },
      h("h3", {}, label),
      box,
      h("div", { class: "row-gap" }, fileInput, btn)
    );
  }

  const attachmentsList = h("div", { class: "list" });
  function paintAttachments(items) {
    clear(attachmentsList);
    if (items.length === 0) {
      attachmentsList.append(h("div", { class: "muted" }, "No attachments."));
      return;
    }
    for (const a of items) {
      attachmentsList.append(
        h(
          "div",
          { class: "list-row" },
          h(
            "a",
            { href: a.url, target: "_blank", class: "list-title" },
            `${a.mime_type} — ${a.size_bytes} bytes`
          ),
          h("div", {}, ""),
          h(
            "button",
            {
              class: "btn btn-danger",
              onClick: async () => {
                await api.deleteAttachment(id, a.file_id);
                paintAttachments(items.filter((x) => x.file_id !== a.file_id));
              },
            },
            "Delete"
          )
        )
      );
    }
  }
  paintAttachments(attachments);

  const attachInput = h("input", { type: "file" });
  const attachBtn = h(
    "button",
    {
      class: "btn btn-primary",
      onClick: async () => {
        if (!attachInput.files[0]) return;
        const added = await api.addAttachment(id, attachInput.files[0]);
        attachments.push(added);
        paintAttachments(attachments);
        attachInput.value = "";
      },
    },
    "Upload attachment"
  );

  setApp(
    h(
      "div",
      { class: "crumbs" },
      h("a", { href: `#/runs/${report.run_id}` }, "← Run")
    ),
    h(
      "div",
      { class: "card form" },
      h("h1", {}, "Report"),
      h("label", {}, "Title", titleInput),
      h("div", { class: "row-gap" }, saveBtn, deleteBtn)
    ),
    fileCard("LaTeX source (.tex)", source, ".tex,application/x-tex,text/x-tex", api.uploadReportSource, "Download source"),
    fileCard("PDF", pdf, ".pdf,application/pdf", api.uploadReportPdf, "Open PDF"),
    h("h2", {}, "Attachments"),
    h("div", { class: "card" }, h("div", { class: "row-gap" }, attachInput, attachBtn)),
    h("div", { class: "card" }, attachmentsList)
  );
});
