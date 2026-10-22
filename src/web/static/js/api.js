// HTTP 客户端：所有请求都返回 JSON；失败时抛出带中文提示的 Error
const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: method === "POST" ? JSON_HEADERS : undefined,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    throw new Error((data && data.error) || `请求失败（HTTP ${res.status}）`);
  }
  return data;
}

export const api = {
  meta: () => request("GET", "/api/meta"),
  state: () => request("GET", "/api/state"),
  characters: () => request("GET", "/api/catalog/characters"),
  lightcones: () => request("GET", "/api/catalog/lightcones"),
  relicsets: () => request("GET", "/api/catalog/relicsets"),
  post: (path, body = {}) => request("POST", path, body),
};
