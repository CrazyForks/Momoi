import { useEffect, useState } from "react";
import "./requestMetrics.css";

const number = (v) => v == null ? "—" : Number(v).toLocaleString();
const percent = (v) => v == null ? "未报告" : `${(v * 100).toFixed(1)}%`;
const seconds = (v) => v == null ? "—" : `${(v / 1000).toFixed(2)}s`;
const date = (v) => new Date(v * 1000).toLocaleString();
const yuan = (v) => v == null ? "—" : v === 0 ? "¥0.00" : `¥${Number(v).toFixed(Math.abs(v) < 0.01 ? 6 : 4)}`;

export default function RequestMetrics({ token, refreshKey, api }) {
  const [hours, setHours] = useState("24");
  const [stage, setStage] = useState("");
  const [model, setModel] = useState("");
  const [cursor, setCursor] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [automatic, setAutomatic] = useState(true);
  useEffect(() => {
    if (!automatic || cursor) return;
    const timer = setInterval(() => { if (!document.hidden) setTick(v => v + 1); }, 30000);
    return () => clearInterval(timer);
  }, [automatic, cursor]);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setError("");
    const query = new URLSearchParams({ hours, stage, model, limit: "50" });
    if (cursor) query.set("before", cursor);
    api(`/api/metrics/requests?${query}`, { token, signal: controller.signal })
      .then(setData)
      .catch(e => { if (e.name !== "AbortError") setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [token, refreshKey, hours, stage, model, cursor, tick, api]);
  const change = (setter) => e => { setter(e.target.value); setCursor(null); };
  const totals = data?.totals || {};
  return <div className="request-metrics" aria-busy={busy}>
    <div className="metrics-toolbar">
      <label>时间范围<select value={hours} onChange={change(setHours)}><option value="1">最近 1 小时</option><option value="24">最近 24 小时</option><option value="168">最近 7 天</option></select></label>
      <label>阶段<select value={stage} onChange={change(setStage)}><option value="">全部阶段</option>{data?.filters.stages.map(s => <option key={s} value={s}>{s || "未标记"}</option>)}</select></label>
      <label>模型<select value={model} onChange={change(setModel)}><option value="">全部模型</option>{data?.filters.models.map(s => <option key={s}>{s}</option>)}</select></label>
      <label className="metrics-auto"><input type="checkbox" checked={automatic} onChange={e => setAutomatic(e.target.checked)} />30 秒自动刷新</label>
      <button className="quiet-button" disabled={busy} onClick={() => setTick(v => v + 1)}>刷新</button>
    </div>
    {error && <p role="alert">加载失败：{error}</p>}
    <div className="metrics-stats">
      {[["请求尝试", number(totals.requests)], ["缓存命中率", percent(totals.cache_hit_rate)], ["输入 / 输出 token", `${number(totals.input_tokens)} / ${number(totals.output_tokens)}`], ["平均首次工具调用", seconds(totals.first_tool_ms)], ["平均完整耗时", seconds(totals.duration_ms)], ["缓存异常线索", number(totals.alerts)]].map(([label, value]) => <article key={label}><span>{label}</span><strong>{value}</strong></article>)}
    </div>
    <p className="metrics-note">每条记录对应一次 HTTP 请求尝试，重试分别计数。首次工具调用 = turn 开始至首个工具开始执行，包含此前请求重试、取消重算和准备时间；每个 turn 仅在触发首个工具的请求上记录一次。其他请求及旧记录显示 —，不计入该均值；这不是首 token 时间。缓存命中率按已报告缓存的输入 token 加权，未报告不会算成 0%。记录保留 30 天。</p>
    <section className="metrics-panel"><h2>按小时观察</h2><div className="metrics-trend">{data?.trend.map(row => <div className="metrics-hour" key={row.bucket} title={`${date(row.bucket)} · ${row.requests} 次 · 缓存 ${percent(row.cache_hit_rate)} · 首次工具调用 ${seconds(row.first_tool_ms)}`}>
      <div className="metrics-bar-track"><div style={{height: `${(row.cache_hit_rate || 0) * 100}%`}} /></div><small>{new Date(row.bucket * 1000).getHours()}:00</small>
    </div>)}</div><p className="metrics-note">柱高为缓存命中率；悬停查看请求次数及首次工具调用耗时。</p></section>
    <section className="metrics-panel"><h2>各阶段对比</h2><div className="metrics-scroll"><table><thead><tr><th>阶段</th><th>请求</th><th>输入 token</th><th>缓存命中</th><th>平均首次工具调用</th><th>平均耗时</th><th>失败 / 取消</th><th>异常线索</th></tr></thead><tbody>{data?.stages.map(s => <tr key={s.stage}><td>{s.stage || "未标记"}</td><td>{number(s.requests)}</td><td>{number(s.input_tokens)}</td><td>{percent(s.cache_hit_rate)}</td><td>{seconds(s.first_tool_ms)}</td><td>{seconds(s.duration_ms)}</td><td>{s.errors || 0} / {s.cancelled || 0}</td><td>{s.alerts || 0}</td></tr>)}</tbody></table></div></section>
    <section className="metrics-panel"><h2>逐次请求 <small>最新在前</small></h2>
      <p className="metrics-note">异常线索：输入 ≥ 4096 token、估算共同前缀 ≥ 80%，但服务端缓存命中 &lt; 50%。前缀对比使用同路由 / 模型最近 64 次请求的分段指纹，按 tools → system → messages 的诊断顺序估算，工具按项比较；服务端实际排列未知。各部分相同不等于可独立命中缓存。</p>
      {!data?.items.length && <p>{busy ? "正在加载…" : "此范围暂无请求记录。部署后新请求会自动采集，历史 usage 不补造耗时。"}</p>}
      <div className="metrics-scroll"><table><thead><tr><th>请求 / 阶段</th><th>输入 / 输出</th><th>费用估算</th><th>缓存命中 / 未缓存</th><th>首次工具调用 / 请求耗时</th><th>结构前缀估算</th><th>结果</th></tr></thead><tbody>{data?.items.map(row => {
        const u = row.usage || {};
        const hit = u.cache_reported && u.input ? u.cache_read / u.input : null;
        return <tr key={row.id} className={row.cache_alert ? "metrics-warning" : ""}>
          <td><details><summary>{row.stage || "未标记"} · 第 {row.round || "—"} 轮<br/><small>{date(row.created_at)}</small></summary><div className="metrics-detail">{row.model}<br/>Turn: {row.turn_id || "—"}<br/>Call: {row.call_id || "—"}<br/>Request: {row.request_id}<br/>{row.first_tool_name && <>首次工具: {row.first_tool_name}<br/></>}尝试 #{row.attempt}<br/>对比记录 #{row.compared_request_id || "—"} ({row.compared_stage || "—"})<br/>HTTP {row.http_status || "—"} {row.error_type || ""}</div></details></td>
          <td>{number(u.input)} / {number(u.output)}</td><td>{yuan(row.estimated_cost)}</td><td>{percent(hit)}<br/><small>{u.cache_reported ? `${number(u.cache_read)} / ${number(u.uncached)}` : "缓存用量未报告"}</small></td>
          <td>{seconds(row.first_tool_ms)} / {seconds(row.duration_ms)}</td><td>{row.reuse_ratio_est == null ? "无基线" : percent(row.reuse_ratio_est)}<br/><small>首个结构差异：{row.changed_at}</small><br/><small>System：{row.system_unchanged == null ? "未知（旧记录）" : row.system_unchanged ? "一致" : "变化"} · 消息前段：{row.common_message_prefix_count == null ? "未知" : `${row.common_message_prefix_count} 条一致`}</small>{row.tool_comparison_granularity === "whole" && <><br/><small>工具为旧整块指纹，无法估算块内前缀</small></>}<br/><small>参数：{row.settings_changed == null ? "未知（旧记录）" : row.settings_changed ? (row.changed_settings?.join(", ") || "有变化（旧指纹未分项）") : "一致"}</small></td><td>{row.status === "success" ? "成功" : row.status === "cancelled" ? "取消" : "失败"}{row.cache_alert && <strong className="metrics-alert">高复用 / 低命中</strong>}</td>
        </tr>;
      })}</tbody></table></div>
      <div className="metrics-pagination"><button className="quiet-button" disabled={!cursor || busy} onClick={() => setCursor(null)}>回到最新</button><button className="quiet-button" disabled={!data?.next_cursor || busy} onClick={() => setCursor(data.next_cursor)}>更早请求</button></div>
    </section>
  </div>;
}
