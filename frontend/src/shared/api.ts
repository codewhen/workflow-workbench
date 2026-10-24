import { readRoute } from "../navigation/location";
import type { ValidationIssue } from "./types";
export class ApiError extends Error {
  constructor(
    message: string,
    public issues: ValidationIssue[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}
const token =
  document.querySelector<HTMLMetaElement>('meta[name="workbench-token"]')
    ?.content ?? "";
export async function api<T>(
  route: string,
  body?: unknown,
  workflow?: string,
  signal?: AbortSignal,
): Promise<T> {
  const params = new URLSearchParams();
  if (workflow) params.set("workflow", workflow);
  const current = readRoute(location.href);
  if (
    workflow === current.workflow &&
    current.run &&
    [
      "config",
      "state",
      "run",
      "stop",
      "pause",
      "record",
      "skip-plan",
      "skip-preview",
      "skip-confirm",
      "open-workspace",
      "draft",
    ].includes(route)
  )
    params.set("run", current.run);
  const response = await fetch(
    `/api/${route}${params.size ? "?" + params.toString() : ""}`,
    {
      signal,
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined
          ? {}
          : { "Content-Type": "application/json", "X-Workbench-Token": token },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );
  const value: unknown = await response.json();
  if (!response.ok)
    throw new ApiError(
      typeof value === "object" && value !== null && "error" in value
        ? String(value.error)
        : "Request failed.",
      typeof value === "object" &&
        value !== null &&
        "issues" in value &&
        Array.isArray(value.issues)
        ? (value.issues as ValidationIssue[])
        : [],
    );
  return value as T;
}
