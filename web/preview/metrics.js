// Synthetic preview data only; never included in production monitoring responses.
export function previewRequestMetrics() {
  const now = Date.now() / 1000;
  const stages = ["owner", "heartbeat", "plan_step", "current_state_maintenance", "goal"].map((stage, i) => ({ stage, requests: 24 - i * 3, input_tokens: 1600000 - i * 170000, output_tokens: 12000, cache_hit_rate: [.91, .76, .94, .87, .85][i], first_response_ms: 3400 + i * 430, duration_ms: 3800 + i * 450, errors: i === 1 ? 1 : 0, cancelled: 0, alerts: i === 1 ? 1 : 0 }));
  return {
    totals: { requests: 90, input_tokens: 6300000, output_tokens: 60000, cache_hit_rate: .878, first_response_ms: 4260, duration_ms: 4700, alerts: 1 },
    stages, filters: { stages: stages.map(s => s.stage), models: ["deepseek-flash"] },
    trend: Array.from({ length: 12 }, (_, i) => ({ bucket: now - (11-i)*3600, requests: 5+i, cache_hit_rate: i === 7 ? .43 : .80 + (i % 4)*.04, first_response_ms: 4000 })),
    items: stages.map((s, i) => ({ id: 100-i, ...s, created_at: now-i*120, round: i+1, model: "deepseek-flash", turn_id: `preview-${s.stage}`, call_id: `preview-call-${i}`, request_id: `preview-request-${i}`, attempt: 1, status: "success", http_status: 200, usage: { input: 76000, output: 360, cache_read: i===1 ? 2816 : 70000, uncached: i===1 ? 73184 : 6000, cache_reported: true }, reuse_ratio_est: .977, changed_at: "transcript[318]", compared_request_id: 90-i, compared_stage: "owner", cache_alert: i===1 })), next_cursor: null,
  };
}
