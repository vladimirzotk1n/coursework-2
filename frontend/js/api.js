export const API_URL = window.__API_URL__ || "http://localhost:8000";
const TOKEN_KEY = "auth_token";

export const token = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (v) => localStorage.setItem(TOKEN_KEY, v),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, { body, form, file } = {}) {
  const headers = {};
  const t = token.get();
  if (t) headers["Authorization"] = `Bearer ${t}`;

  let payload;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  } else if (form !== undefined) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form).toString();
  } else if (file !== undefined) {
    const fd = new FormData();
    fd.append("upload", file);
    payload = fd;
  }

  const res = await fetch(`${API_URL}${path}`, { method, headers, body: payload });
  if (res.status === 204) return undefined;
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    const detail = data?.detail ?? res.statusText;
    throw new ApiError(res.status, detail);
  }
  return data;
}

// --- auth / users ---
export const register = (username, email, password) =>
  request("POST", "/auth/register", { body: { username, email, password } });

export const login = async (username, password) => {
  const res = await request("POST", "/auth/login", { form: { username, password } });
  token.set(res.access_token);
  return res;
};

export const logout = () => token.clear();

export const me = () => request("GET", "/users/me");

// --- experiments ---
export const listExperiments = () => request("GET", "/experiments");
export const createExperiment = (data) => request("POST", "/experiments", { body: data });
export const getExperiment = (id) => request("GET", `/experiments/${id}`);
export const updateExperiment = (id, data) =>
  request("PATCH", `/experiments/${id}`, { body: data });
export const deleteExperiment = (id) => request("DELETE", `/experiments/${id}`);

// --- runs ---
export const listRuns = (experimentId) =>
  request("GET", `/experiments/${experimentId}/runs`);
export const createRun = (experimentId, data) =>
  request("POST", `/experiments/${experimentId}/runs`, { body: data });
export const getRun = (id) => request("GET", `/runs/${id}`);
export const updateRun = (id, data) => request("PATCH", `/runs/${id}`, { body: data });
export const deleteRun = (id) => request("DELETE", `/runs/${id}`);

// --- series ---
export const listSeries = (runId) => request("GET", `/runs/${runId}/series`);
export const createSeries = (runId, data) =>
  request("POST", `/runs/${runId}/series`, { body: data });
export const getSeries = (id) => request("GET", `/series/${id}`);
export const updateSeries = (id, data) =>
  request("PATCH", `/series/${id}`, { body: data });
export const deleteSeries = (id) => request("DELETE", `/series/${id}`);

// --- points ---
export const listPoints = (seriesId) => request("GET", `/series/${seriesId}/points`);
export const addPoint = (seriesId, data) =>
  request("POST", `/series/${seriesId}/points`, { body: data });
export const replacePoints = (seriesId, points) =>
  request("PUT", `/series/${seriesId}/points`, { body: { points } });
export const deletePoint = (id) => request("DELETE", `/points/${id}`);
export const generatePlot = (seriesId) =>
  request("POST", `/series/${seriesId}/plot`);
export const getSeriesPlot = (seriesId) => request("GET", `/series/${seriesId}/plot`);

// --- run images ---
export const listRunImages = (runId) => request("GET", `/runs/${runId}/images`);
export const uploadRunImage = (runId, file) =>
  request("POST", `/runs/${runId}/images`, { file });
export const deleteRunImage = (runId, fileId) =>
  request("DELETE", `/runs/${runId}/images/${fileId}`);

// --- reports ---
export const listReports = (runId) => request("GET", `/runs/${runId}/reports`);
export const createReport = (runId, data) =>
  request("POST", `/runs/${runId}/reports`, { body: data });
export const getReport = (id) => request("GET", `/reports/${id}`);
export const updateReport = (id, data) =>
  request("PATCH", `/reports/${id}`, { body: data });
export const deleteReport = (id) => request("DELETE", `/reports/${id}`);

export const uploadReportSource = (reportId, file) =>
  request("PUT", `/reports/${reportId}/source`, { file });
export const uploadReportPdf = (reportId, file) =>
  request("PUT", `/reports/${reportId}/pdf`, { file });
export const getReportSource = (reportId) =>
  request("GET", `/reports/${reportId}/source`);
export const getReportPdf = (reportId) => request("GET", `/reports/${reportId}/pdf`);

export const listAttachments = (reportId) =>
  request("GET", `/reports/${reportId}/attachments`);
export const addAttachment = (reportId, file) =>
  request("POST", `/reports/${reportId}/attachments`, { file });
export const deleteAttachment = (reportId, fileId) =>
  request("DELETE", `/reports/${reportId}/attachments/${fileId}`);
