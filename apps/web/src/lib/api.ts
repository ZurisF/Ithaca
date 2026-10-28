import createClient from "openapi-fetch";
import type { paths } from "../generated/api";

export const api = createClient<paths>({
  baseUrl: process.env.NEXT_PUBLIC_APPLICATION_URL ?? "http://127.0.0.1:8100",
});
