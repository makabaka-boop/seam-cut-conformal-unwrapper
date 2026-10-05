const BASE = "/api";

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const message = payload?.detail || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

export const api = {
  samples: () => request("/samples"),
  sample: (name) => request(`/samples/${name}`),
  prepare: (mesh) =>
    request("/prepare", {
      method: "POST",
      body: JSON.stringify(mesh),
    }),
  solve: (mesh, anchors) =>
    request("/solve", {
      method: "POST",
      body: JSON.stringify({ mesh, anchors }),
    }),
};
